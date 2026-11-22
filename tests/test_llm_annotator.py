import json
import tempfile
import unittest
from pathlib import Path

from src.annotation.llm_annotator import (
    AnnotationProvider,
    AnnotationRunner,
    PromptBuilder,
    ProviderResponse,
    RedactionResult,
    RunnerConfig,
    ThreadContextIndex,
    Usage,
    _restore_redacted_surfaces,
    redact_sensitive_text,
)


def source_record(record_id="mailex:dev:test:turn_0000", text="Please send the report by Friday."):
    return {
        "id": record_id,
        "source": "mailex",
        "source_split": "dev",
        "thread_id": "test",
        "turn_index": 0,
        "text": text,
        "text2task_annotations": None,
        "candidate_selection": {
            "provisional_coverage_flags": {"explicit_actionable_request": True}
        },
    }


def empty_annotation():
    return {
        "schema_version": "1.0.0",
        "annotation_status": "DRAFT",
        "annotator_id": "fake:test",
        "entities": [],
        "relations": [],
        "relation_candidates": [],
        "reference_resolution": {
            "status": "DEFERRED_NO_REFERENCE_SPANS",
            "mentions": [],
        },
        "notes": [],
    }


class FakeProvider(AnnotationProvider):
    name = "fake"
    supports_structured_output = True

    def __init__(self, responses):
        super().__init__("fake-model")
        self.responses = list(responses)
        self.calls = 0

    def generate(self, prompt, output_schema):
        self.calls += 1
        content = self.responses.pop(0)
        if not isinstance(content, str):
            content = json.dumps(content)
        return ProviderResponse(
            content=content,
            model=self.model,
            usage=Usage(input_tokens=100, output_tokens=20, total_tokens=120, cost_usd=0.0),
        )


class PromptAndRedactionTests(unittest.TestCase):
    def test_prompt_contains_schema_email_and_thread_context(self):
        record = source_record()
        context = dict(record, id="mailex:dev:test:turn_0001", turn_index=1, text="The report is attached.")
        builder = PromptBuilder()
        prompt, redaction = builder.build(record, [context], annotator_id="fake:test")
        self.assertIn("DEPENDS_ON", prompt)
        self.assertIn("Never output `$schema`", prompt)
        self.assertIn(record["text"], prompt)
        self.assertIn(context["text"], prompt)
        self.assertIn("context only; never create spans", prompt)
        self.assertEqual(redaction.text, record["text"])

    def test_redaction_preserves_offsets_and_restoration_is_recorded(self):
        text = "Email alice@example.com or call 713-555-0199."
        redaction = redact_sensitive_text(text)
        self.assertEqual(len(redaction.text), len(text))
        self.assertNotIn("alice", redaction.text)
        start = text.index("alice@example.com")
        end = start + len("alice@example.com")
        annotations = empty_annotation()
        annotations["entities"] = [
            {
                "id": "e1",
                "type": "ARTIFACT",
                "start": start,
                "end": end,
                "text": redaction.text[start:end],
                "task_attributes": None,
            }
        ]
        restored, changes = _restore_redacted_surfaces(annotations, text, redaction.text)
        self.assertEqual(restored["entities"][0]["text"], "alice@example.com")
        self.assertEqual(changes[0]["type"], "restore_redacted_surface")


class RunnerTests(unittest.TestCase):
    def make_config(self, root, input_path, max_attempts=3):
        return RunnerConfig(
            input_path=input_path,
            success_path=root / "silver.jsonl",
            failure_path=root / "failed.jsonl",
            review_path=root / "review.jsonl",
            checkpoint_path=root / "checkpoint.json",
            report_path=root / "report.json",
            limit=1,
            max_attempts=max_attempts,
            base_delay_seconds=0,
            max_delay_seconds=0,
        )

    def write_input(self, root, record=None):
        path = root / "input.jsonl"
        path.write_text(json.dumps(record or source_record()) + "\n", encoding="utf-8")
        return path

    def test_success_is_incremental_reviewable_and_resumable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = self.write_input(root)
            provider = FakeProvider([empty_annotation()])
            runner = AnnotationRunner(
                provider,
                PromptBuilder(),
                ThreadContextIndex([source_record()]),
                self.make_config(root, input_path),
                sleep=lambda _: None,
            )
            stats = runner.run()
            self.assertEqual(stats.successful_annotations, 1)
            self.assertEqual(stats.empty_task_predictions, 1)
            self.assertEqual(stats.records_requiring_review, 1)
            output = json.loads((root / "silver.jsonl").read_text())
            self.assertEqual(output["id"], source_record()["id"])
            self.assertTrue(output["llm_annotation_metadata"]["requires_review"])
            self.assertTrue((root / "checkpoint.json").is_file())
            checkpoint = json.loads((root / "checkpoint.json").read_text())
            self.assertEqual(checkpoint["last_record_id"], source_record()["id"])

            second_provider = FakeProvider([])
            second = AnnotationRunner(
                second_provider,
                PromptBuilder(),
                ThreadContextIndex([source_record()]),
                self.make_config(root, input_path),
                sleep=lambda _: None,
            ).run()
            self.assertEqual(second.records_skipped_success, 1)
            self.assertEqual(second_provider.calls, 0)

    def test_dry_run_replaces_prior_prompt_dump(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = self.write_input(root)
            config = self.make_config(root, input_path)
            config.dry_run = True
            config.prompt_dump_path = root / "prompts.jsonl"
            config.prompt_dump_path.write_text('{"stale":true}\n', encoding="utf-8")
            stats = AnnotationRunner(
                None,
                PromptBuilder(),
                ThreadContextIndex([source_record()]),
                config,
                sleep=lambda _: None,
            ).run()
            prompts = [json.loads(line) for line in config.prompt_dump_path.read_text().splitlines()]
            self.assertEqual(stats.prompts_generated, 1)
            self.assertEqual(len(prompts), 1)
            self.assertEqual(prompts[0]["source_record_id"], source_record()["id"])

    def test_invalid_json_is_retried_and_history_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = self.write_input(root)
            provider = FakeProvider(["not-json", empty_annotation()])
            stats = AnnotationRunner(
                provider,
                PromptBuilder(),
                ThreadContextIndex([source_record()]),
                self.make_config(root, input_path),
                sleep=lambda _: None,
            ).run()
            self.assertEqual(stats.successful_annotations, 1)
            self.assertEqual(stats.invalid_json_attempts, 1)
            self.assertEqual(stats.retries, 1)
            output = json.loads((root / "silver.jsonl").read_text())
            history = output["llm_annotation_metadata"]["attempt_history"]
            self.assertEqual(history[0]["category"], "invalid_json")

    def test_invalid_span_is_saved_as_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = self.write_input(root)
            annotation = empty_annotation()
            annotation["entities"] = [
                {"id": "e1", "type": "ARTIFACT", "start": 12, "end": 18, "text": "WRONG!", "task_attributes": None}
            ]
            stats = AnnotationRunner(
                FakeProvider([annotation]),
                PromptBuilder(),
                ThreadContextIndex([source_record()]),
                self.make_config(root, input_path, max_attempts=1),
                sleep=lambda _: None,
            ).run()
            self.assertEqual(stats.invalid_span_count, 1)
            self.assertEqual(stats.records_requiring_review, 1)
            failure = json.loads((root / "failed.jsonl").read_text())
            self.assertEqual(failure["failure"]["category"], "invalid_span")

    def test_relation_type_failure_is_counted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = self.write_input(root)
            annotation = empty_annotation()
            annotation["entities"] = [
                {
                    "id": "e1",
                    "type": "TASK",
                    "start": 7,
                    "end": 22,
                    "text": "send the report",
                    "task_attributes": {
                        "operation": "CREATE",
                        "status": "PENDING",
                        "negated": False,
                        "ambiguous": False,
                        "missing_fields": ["TEMPORAL"],
                        "unresolved_fields": [],
                        "thread_task_id": None,
                        "identity_status": "LOCAL_ONLY",
                    },
                },
                {"id": "e2", "type": "ARTIFACT", "start": 16, "end": 22, "text": "report", "task_attributes": None},
            ]
            annotation["relations"] = [
                {
                    "id": "r1",
                    "type": "ASSIGNED_TO",
                    "source_entity_id": "e1",
                    "target_entity_id": "e2",
                    "relation_evidence": {"start": 7, "end": 22, "text": "send the report"},
                    "explicit_vs_inferred": "EXPLICIT",
                    "ambiguous": False,
                }
            ]
            stats = AnnotationRunner(
                FakeProvider([annotation]),
                PromptBuilder(),
                ThreadContextIndex([source_record()]),
                self.make_config(root, input_path, max_attempts=1),
                sleep=lambda _: None,
            ).run()
            self.assertEqual(stats.relation_validation_failures, 1)
            self.assertEqual(stats.records_requiring_review, 1)


if __name__ == "__main__":
    unittest.main()
