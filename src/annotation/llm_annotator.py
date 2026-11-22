"""Reusable, resumable LLM annotation pipeline for Text2Task.

The module has no third-party runtime dependency.  Providers implement a small
interface and return JSON text plus optional usage metadata.  The runner never
trusts provider output: every result is parsed strictly and validated against
the v1 schema and semantic graph constraints before it reaches silver output.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from src.annotation.validators import ValidationIssue, load_schema, validate_record


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPT_PATH = PROJECT_ROOT / "configs" / "annotation_prompt.md"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "data" / "reports" / "llm_annotation_report.json"
PROMPT_VERSION_RE = re.compile(r"prompt_version:\s*([^\s]+)")
PLACEHOLDER_RE = re.compile(r"{{([A-Z0-9_]+)}}")

SPAN_ISSUE_CODES = {"span_bounds", "span_text", "duplicate_entity"}
RELATION_ISSUE_CODES = {
    "source_type",
    "target_type",
    "unknown_entity",
    "self_relation",
    "duplicate_relation",
    "non_edge_label",
    "none_candidate_metadata",
    "positive_candidate_metadata",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    cost_source: str | None = None

    def add(self, other: "Usage") -> None:
        for name in ("input_tokens", "output_tokens", "total_tokens"):
            current, incoming = getattr(self, name), getattr(other, name)
            if incoming is not None:
                setattr(self, name, (current or 0) + incoming)
        if other.cost_usd is not None:
            self.cost_usd = (self.cost_usd or 0.0) + other.cost_usd
            self.cost_source = other.cost_source


@dataclass
class ProviderResponse:
    content: str
    model: str
    usage: Usage = field(default_factory=Usage)
    request_id: str | None = None
    finish_reason: str | None = None


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        retry_after: float | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after
        self.status_code = status_code


class AnnotationProvider:
    """Provider protocol implemented without importing vendor SDKs."""

    name = "base"
    external = False
    supports_structured_output = False
    structured_output_mode = "none"

    def __init__(self, model: str) -> None:
        self.model = model

    def generate(self, prompt: str, output_schema: Mapping[str, Any]) -> ProviderResponse:
        raise NotImplementedError


def _post_json(url: str, payload: Mapping[str, Any], headers: Mapping[str, str], timeout: float) -> tuple[dict[str, Any], Mapping[str, str]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            return body, response.headers
    except urllib.error.HTTPError as error:
        retry_after = None
        header = error.headers.get("Retry-After") if error.headers else None
        if header:
            try:
                retry_after = float(header)
            except ValueError:
                retry_after = None
        try:
            error_body = json.loads(error.read().decode("utf-8"))
            message = error_body.get("error", {}).get("message") or str(error)
        except (json.JSONDecodeError, UnicodeDecodeError):
            message = str(error)
        retryable = error.code in {408, 409, 429, 500, 502, 503, 504}
        raise ProviderError(
            f"HTTP {error.code}: {message}",
            retryable=retryable,
            retry_after=retry_after,
            status_code=error.code,
        ) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise ProviderError(f"Provider connection failed: {error}", retryable=True) from error


class OllamaProvider(AnnotationProvider):
    """Local Ollama chat provider using JSON or JSON-schema format enforcement."""

    name = "ollama"
    external = False
    supports_structured_output = True

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 300.0,
        format_mode: str = "json",
        max_output_tokens: int = 1536,
        context_window: int = 8192,
    ) -> None:
        super().__init__(model)
        if format_mode not in {"json", "schema"}:
            raise ValueError("Ollama format_mode must be 'json' or 'schema'")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.format_mode = format_mode
        self.max_output_tokens = max_output_tokens
        self.context_window = context_window
        self.structured_output_mode = "json_schema" if format_mode == "schema" else "json_object"

    def generate(self, prompt: str, output_schema: Mapping[str, Any]) -> ProviderResponse:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            # Some local grammar engines become impractically slow on the full
            # Text2Task schema. JSON mode still constrains syntax; the complete
            # schema and semantic validator remain mandatory after generation.
            "format": output_schema if self.format_mode == "schema" else "json",
            "options": {
                "temperature": 0,
                "num_predict": self.max_output_tokens,
                "num_ctx": self.context_window,
            },
        }
        body, _ = _post_json(f"{self.base_url}/api/chat", payload, {}, self.timeout)
        content = body.get("message", {}).get("content")
        if not isinstance(content, str):
            raise ProviderError("Ollama response did not contain message.content")
        input_tokens = body.get("prompt_eval_count")
        output_tokens = body.get("eval_count")
        usage = Usage(
            input_tokens=input_tokens if isinstance(input_tokens, int) else None,
            output_tokens=output_tokens if isinstance(output_tokens, int) else None,
            total_tokens=(input_tokens + output_tokens) if isinstance(input_tokens, int) and isinstance(output_tokens, int) else None,
            cost_usd=0.0,
            cost_source="local_provider",
        )
        return ProviderResponse(
            content=content,
            model=body.get("model", self.model),
            usage=usage,
            finish_reason=body.get("done_reason"),
        )


class OpenAIResponsesProvider(AnnotationProvider):
    """OpenAI Responses API provider with strict structured output."""

    name = "openai"
    external = True
    supports_structured_output = True
    structured_output_mode = "json_schema"

    def __init__(
        self,
        model: str,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 180.0,
        input_cost_per_million: float | None = None,
        output_cost_per_million: float | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required; provide it through the configured environment variable")
        super().__init__(model)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.input_cost_per_million = input_cost_per_million
        self.output_cost_per_million = output_cost_per_million

    @staticmethod
    def _extract_text(body: Mapping[str, Any]) -> str:
        if isinstance(body.get("output_text"), str):
            return body["output_text"]
        chunks: list[str] = []
        for item in body.get("output", []):
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    chunks.append(content["text"])
        if not chunks:
            raise ProviderError("OpenAI response did not contain output text")
        return "".join(chunks)

    def generate(self, prompt: str, output_schema: Mapping[str, Any]) -> ProviderResponse:
        payload = {
            "model": self.model,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "text2task_annotation_v1",
                    "strict": True,
                    "schema": output_schema,
                }
            },
        }
        body, headers = _post_json(
            f"{self.base_url}/responses",
            payload,
            {"Authorization": f"Bearer {self.api_key}"},
            self.timeout,
        )
        raw_usage = body.get("usage", {})
        input_tokens = raw_usage.get("input_tokens")
        output_tokens = raw_usage.get("output_tokens")
        total_tokens = raw_usage.get("total_tokens")
        estimated_cost = None
        if isinstance(input_tokens, int) and isinstance(output_tokens, int) and self.input_cost_per_million is not None and self.output_cost_per_million is not None:
            estimated_cost = (
                input_tokens * self.input_cost_per_million / 1_000_000
                + output_tokens * self.output_cost_per_million / 1_000_000
            )
        usage = Usage(
            input_tokens=input_tokens if isinstance(input_tokens, int) else None,
            output_tokens=output_tokens if isinstance(output_tokens, int) else None,
            total_tokens=total_tokens if isinstance(total_tokens, int) else None,
            cost_usd=estimated_cost,
            cost_source="cli_price_estimate" if estimated_cost is not None else None,
        )
        return ProviderResponse(
            content=self._extract_text(body),
            model=body.get("model", self.model),
            usage=usage,
            request_id=headers.get("x-request-id") or body.get("id"),
            finish_reason=body.get("status"),
        )


def annotation_output_schema(record_schema: Mapping[str, Any]) -> dict[str, Any]:
    """Extract a standalone schema for the provider's annotation-set output."""

    definitions = copy.deepcopy(record_schema["$defs"])
    root = copy.deepcopy(definitions["annotation_set"])
    root["$defs"] = definitions
    root["title"] = "Text2Task annotation set v1"
    return root


def prompt_schema_contract() -> str:
    """Concise instance contract that models are less likely to copy verbatim."""

    return """Return one object with exactly these fields:
- schema_version: \"1.0.0\"
- annotation_status: \"DRAFT\"
- annotator_id: the exact instructed string
- entities: array of {id: \"e1\"..., type: TASK|PERSON|GROUP|TEMPORAL|EVENT|ARTIFACT,
  start: integer, end: integer, text: exact substring, task_attributes: null for non-TASK;
  for TASK use {operation: CREATE|UPDATE|COMPLETE|CANCEL|UNKNOWN,
  status: PENDING|COMPLETED|CANCELED|UNKNOWN, negated: boolean, ambiguous: boolean,
  missing_fields: array using ASSIGNEE|TEMPORAL, unresolved_fields: array using
  ASSIGNEE|TEMPORAL|DEPENDENCY|CROSS_EMAIL_IDENTITY|OPERATION|STATUS,
  thread_task_id: null or \"thread-task:...\", identity_status: LOCAL_ONLY|RESOLVED|UNRESOLVED}}
- relations: array of {id: \"r1\"..., type: ASSIGNED_TO|DUE_ON|SCHEDULED_ON|DEPENDS_ON,
  source_entity_id, target_entity_id, relation_evidence: {start,end,text},
  explicit_vs_inferred: EXPLICIT|INFERRED, ambiguous: boolean}
- relation_candidates: array of {id: \"rc1\"..., source_entity_id, target_entity_id,
  label: ASSIGNED_TO|DUE_ON|SCHEDULED_ON|DEPENDS_ON|NONE, relation_evidence: object or null,
  explicit_vs_inferred: EXPLICIT|INFERRED or null}; normally return [] unless requested
- reference_resolution: {\"status\":\"DEFERRED_NO_REFERENCE_SPANS\",\"mentions\":[]}
- notes: array of strings
No other fields are allowed inside the annotation object, entities, relations, or attributes."""


@dataclass(frozen=True)
class RedactionSpan:
    start: int
    end: int
    kind: str


@dataclass(frozen=True)
class RedactionResult:
    text: str
    spans: tuple[RedactionSpan, ...]


SENSITIVE_PATTERNS = (
    ("email_address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("phone_number", re.compile(r"(?<!\w)(?:\+?\d[\d() .-]{7,}\d)(?!\w)")),
    ("long_numeric_identifier", re.compile(r"(?<!\w)\d{8,}(?!\w)")),
)


def redact_sensitive_text(text: str) -> RedactionResult:
    """Mask selected non-target PII while preserving every character offset."""

    candidates: list[RedactionSpan] = []
    for kind, pattern in SENSITIVE_PATTERNS:
        candidates.extend(RedactionSpan(match.start(), match.end(), kind) for match in pattern.finditer(text))
    chosen: list[RedactionSpan] = []
    for candidate in sorted(candidates, key=lambda item: (item.start, -(item.end - item.start), item.kind)):
        if any(candidate.start < existing.end and existing.start < candidate.end for existing in chosen):
            continue
        chosen.append(candidate)
    characters = list(text)
    for span in chosen:
        for index in range(span.start, span.end):
            if characters[index].isalnum():
                characters[index] = "x"
    redacted = "".join(characters)
    assert len(redacted) == len(text)
    return RedactionResult(redacted, tuple(sorted(chosen, key=lambda item: item.start)))


class ThreadContextIndex:
    """In-memory index of email turns used only to construct prompt context."""

    def __init__(self, records: Iterable[Mapping[str, Any]]) -> None:
        self.by_thread: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        for record in records:
            key = (str(record.get("source_split", "")), str(record.get("thread_id", "")))
            self.by_thread.setdefault(key, []).append(record)
        for members in self.by_thread.values():
            members.sort(key=lambda record: (record.get("turn_index", 0), record.get("id", "")))

    @classmethod
    def from_jsonl(cls, paths: Sequence[Path | str]) -> "ThreadContextIndex":
        records = []
        for path in paths:
            with Path(path).open(encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        records.append(json.loads(line))
        return cls(records)

    def surrounding(self, record: Mapping[str, Any], turns: int = 2) -> list[Mapping[str, Any]]:
        key = (str(record.get("source_split", "")), str(record.get("thread_id", "")))
        members = [item for item in self.by_thread.get(key, []) if item.get("id") != record.get("id")]
        target_turn = int(record.get("turn_index", 0))
        closest = sorted(
            members,
            key=lambda item: (abs(int(item.get("turn_index", 0)) - target_turn), int(item.get("turn_index", 0))),
        )[: max(0, turns * 2)]
        return sorted(closest, key=lambda item: (int(item.get("turn_index", 0)), str(item.get("id", ""))))


class PromptBuilder:
    def __init__(
        self,
        template_path: Path | str = DEFAULT_PROMPT_PATH,
        schema: Mapping[str, Any] | None = None,
    ) -> None:
        self.template_path = Path(template_path)
        self.template = self.template_path.read_text(encoding="utf-8")
        match = PROMPT_VERSION_RE.search(self.template)
        if not match:
            raise ValueError(f"Prompt version marker missing from {self.template_path}")
        self.version = match.group(1)
        self.schema = schema or load_schema()
        self.output_schema = annotation_output_schema(self.schema)

    @staticmethod
    def render_context(records: Sequence[Mapping[str, Any]], redact: bool) -> str:
        if not records:
            return "[No additional thread turns available]"
        blocks = []
        for record in records:
            context_text = str(record.get("text", ""))
            if redact:
                context_text = redact_sensitive_text(context_text).text
            blocks.append(
                f"[CONTEXT record_id={record.get('id')} turn_index={record.get('turn_index')}]\n"
                f"{context_text}\n[/CONTEXT]"
            )
        return "\n\n".join(blocks)

    @staticmethod
    def offset_guide(text: str) -> str:
        if not text:
            return "[empty target text]"
        return " ".join(
            f"[{match.start()},{match.end()})={json.dumps(match.group(0), ensure_ascii=False)}"
            for match in re.finditer(r"\w+(?:['’]\w+)*|[^\w\s]", text, re.UNICODE)
        )

    def build(
        self,
        record: Mapping[str, Any],
        context: Sequence[Mapping[str, Any]],
        *,
        annotator_id: str,
        redact: bool = False,
    ) -> tuple[str, RedactionResult]:
        original_text = str(record.get("text", ""))
        redaction = redact_sensitive_text(original_text) if redact else RedactionResult(original_text, ())
        values = {
            "ANNOTATION_SCHEMA": prompt_schema_contract(),
            "ANNOTATOR_ID": annotator_id,
            "RECORD_ID": str(record.get("id", "")),
            "SOURCE_SPLIT": str(record.get("source_split", "")),
            "THREAD_ID": str(record.get("thread_id", "")),
            "TURN_INDEX": str(record.get("turn_index", "")),
            "THREAD_CONTEXT": self.render_context(context, redact),
            "EMAIL_TEXT": redaction.text,
            "OFFSET_GUIDE": self.offset_guide(redaction.text),
        }
        prompt = self.template
        for key, value in values.items():
            prompt = prompt.replace("{{" + key + "}}", value)
        remaining = sorted(set(PLACEHOLDER_RE.findall(prompt)))
        if remaining:
            raise ValueError(f"Unfilled prompt placeholders: {remaining}")
        return prompt, redaction


def _restore_redacted_surfaces(
    annotations: Mapping[str, Any],
    original_text: str,
    redacted_text: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Restore exact source surfaces after offset-preserving prompt redaction.

    This is a deterministic representation restoration, not a semantic repair.
    Every changed field is recorded in metadata.
    """

    restored = copy.deepcopy(annotations)
    changes: list[dict[str, Any]] = []

    def restore(span: Any, path: str) -> None:
        if not isinstance(span, dict):
            return
        start, end, surface = span.get("start"), span.get("end"), span.get("text")
        if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(original_text)):
            return
        redacted_surface = redacted_text[start:end]
        original_surface = original_text[start:end]
        if surface == redacted_surface and original_surface != redacted_surface:
            span["text"] = original_surface
            changes.append({
                "path": path + ".text",
                "type": "restore_redacted_surface",
                "start": start,
                "end": end,
            })

    for index, entity in enumerate(restored.get("entities", [])):
        restore(entity, f"entities[{index}]")
    for collection_name in ("relations", "relation_candidates"):
        for index, relation in enumerate(restored.get(collection_name, [])):
            restore(relation.get("relation_evidence") if isinstance(relation, dict) else None, f"{collection_name}[{index}].relation_evidence")
    return restored, changes


def review_reasons(record: Mapping[str, Any]) -> list[str]:
    annotations = record.get("text2task_annotations") or {}
    reasons: set[str] = set()
    tasks = [entity for entity in annotations.get("entities", []) if entity.get("type") == "TASK"]
    if not tasks:
        candidate_flags = ((record.get("candidate_selection") or {}).get("provisional_coverage_flags") or {})
        if any(candidate_flags.get(flag) for flag in ("explicit_actionable_request", "commitment_or_planned_action", "multiple_tasks")):
            reasons.add("empty_task_prediction_conflicts_with_candidate_signal")
    for task in tasks:
        attributes = task.get("task_attributes") or {}
        if attributes.get("ambiguous"):
            reasons.add("ambiguous_task")
        if attributes.get("unresolved_fields"):
            reasons.add("unresolved_task_fields")
        if attributes.get("identity_status") == "UNRESOLVED":
            reasons.add("unresolved_cross_email_identity")
    for relation in annotations.get("relations", []):
        if relation.get("ambiguous"):
            reasons.add("ambiguous_relation")
        if relation.get("explicit_vs_inferred") == "INFERRED":
            reasons.add("inferred_relation")
    return sorted(reasons)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _append_jsonl(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _load_record_ids(path: Path, key: str = "id") -> set[str]:
    if not path.is_file():
        return set()
    ids = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            identifier = value.get(key)
            if isinstance(identifier, str):
                ids.add(identifier)
    return ids


@dataclass
class RunnerConfig:
    input_path: Path
    success_path: Path
    failure_path: Path
    review_path: Path
    checkpoint_path: Path
    report_path: Path = DEFAULT_REPORT_PATH
    prompt_dump_path: Path | None = None
    limit: int | None = None
    dry_run: bool = False
    max_attempts: int = 3
    base_delay_seconds: float = 2.0
    max_delay_seconds: float = 60.0
    retry_failed: bool = False
    context_turns: int = 2
    redact_sensitive: bool = False


@dataclass
class RunStats:
    run_id: str
    started_at: str
    provider: str
    model: str
    prompt_version: str
    input_path: str
    dry_run: bool
    records_considered: int = 0
    records_skipped_success: int = 0
    records_skipped_failed: int = 0
    prompts_generated: int = 0
    successful_annotations: int = 0
    invalid_json_count: int = 0
    invalid_json_attempts: int = 0
    invalid_span_count: int = 0
    relation_validation_failures: int = 0
    other_validation_failures: int = 0
    provider_failures: int = 0
    retries: int = 0
    empty_task_predictions: int = 0
    records_requiring_review: int = 0
    usage: Usage = field(default_factory=Usage)
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["usage"] = asdict(self.usage)
        return result


class AnnotationRunner:
    def __init__(
        self,
        provider: AnnotationProvider | None,
        prompt_builder: PromptBuilder,
        context_index: ThreadContextIndex,
        config: RunnerConfig,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not config.dry_run and provider is None:
            raise ValueError("A provider is required outside dry-run mode")
        self.provider = provider
        self.prompt_builder = prompt_builder
        self.context_index = context_index
        self.config = config
        self.sleep = sleep

    def _checkpoint(self, stats: RunStats, last_record_id: str | None) -> None:
        _atomic_json(
            self.config.checkpoint_path,
            {
                "version": "1.0.0",
                "updated_at": utc_now(),
                "input_path": str(self.config.input_path),
                "success_path": str(self.config.success_path),
                "failure_path": str(self.config.failure_path),
                "last_record_id": last_record_id,
                "stats": stats.to_dict(),
            },
        )

    def _report(self, stats: RunStats) -> None:
        existing: dict[str, Any] = {"report_version": "1.0.0", "runs": []}
        if self.config.report_path.is_file():
            try:
                loaded = json.loads(self.config.report_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("runs"), list):
                    existing = loaded
            except json.JSONDecodeError:
                pass
        existing["updated_at"] = utc_now()
        existing["runs"].append(stats.to_dict())
        _atomic_json(self.config.report_path, existing)

    @staticmethod
    def _classify_validation(issues: Sequence[ValidationIssue]) -> str:
        if any(issue.code in SPAN_ISSUE_CODES for issue in issues):
            return "invalid_span"
        if any(issue.code in RELATION_ISSUE_CODES or ".relations[" in issue.path or ".relation_candidates[" in issue.path for issue in issues):
            return "relation_validation"
        return "other_validation"

    def _wait_for_retry(self, attempt: int, error: ProviderError | None = None) -> None:
        if error and error.retry_after is not None:
            delay = max(0.0, error.retry_after) + random.uniform(0.0, 0.5)
        else:
            delay = min(self.config.max_delay_seconds, self.config.base_delay_seconds * (2 ** max(0, attempt - 1)))
            delay += random.uniform(0.0, min(0.5, delay * 0.1))
        self.sleep(delay)

    def run(self) -> RunStats:
        provider_name = self.provider.name if self.provider else "dry-run"
        model = self.provider.model if self.provider else "none"
        run_id = hashlib.sha256(f"{utc_now()}:{self.config.input_path}:{provider_name}:{model}".encode()).hexdigest()[:16]
        stats = RunStats(
            run_id=run_id,
            started_at=utc_now(),
            provider=provider_name,
            model=model,
            prompt_version=self.prompt_builder.version,
            input_path=str(self.config.input_path),
            dry_run=self.config.dry_run,
        )
        successful_ids = _load_record_ids(self.config.success_path)
        failed_ids = _load_record_ids(self.config.failure_path, "source_record_id")
        selected = 0
        last_record_id: str | None = None

        # A dry-run is a reproducible snapshot of prompts for this invocation,
        # not an append-only annotation ledger.  Start it afresh so rerunning
        # the same command cannot silently duplicate prompt records.
        if self.config.dry_run and self.config.prompt_dump_path is not None:
            self.config.prompt_dump_path.parent.mkdir(parents=True, exist_ok=True)
            self.config.prompt_dump_path.write_text("", encoding="utf-8")

        with self.config.input_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                record_id = record.get("id")
                if not isinstance(record_id, str):
                    raise ValueError(f"Missing record ID at {self.config.input_path}:{line_number}")
                if record_id in successful_ids:
                    stats.records_skipped_success += 1
                    continue
                if record_id in failed_ids and not self.config.retry_failed:
                    stats.records_skipped_failed += 1
                    continue
                if self.config.limit is not None and selected >= self.config.limit:
                    break
                selected += 1
                stats.records_considered += 1
                last_record_id = record_id
                context = self.context_index.surrounding(record, self.config.context_turns)
                annotator_id = f"{provider_name}:{model}"
                prompt, redaction = self.prompt_builder.build(
                    record,
                    context,
                    annotator_id=annotator_id,
                    redact=self.config.redact_sensitive,
                )
                stats.prompts_generated += 1

                if self.config.dry_run:
                    if self.config.prompt_dump_path is not None:
                        _append_jsonl(
                            self.config.prompt_dump_path,
                            {
                                "source_record_id": record_id,
                                "source_split": record.get("source_split"),
                                "prompt_version": self.prompt_builder.version,
                                "redaction_enabled": self.config.redact_sensitive,
                                "redaction_spans": [asdict(span) for span in redaction.spans],
                                "prompt": prompt,
                            },
                        )
                    continue

                attempt_history: list[dict[str, Any]] = []
                final_failure: dict[str, Any] | None = None
                feedback = ""
                for attempt in range(1, self.config.max_attempts + 1):
                    attempt_prompt = prompt + feedback
                    try:
                        response = self.provider.generate(attempt_prompt, self.prompt_builder.output_schema)  # type: ignore[union-attr]
                        stats.usage.add(response.usage)
                    except ProviderError as error:
                        attempt_history.append({
                            "attempt": attempt,
                            "category": "provider_error",
                            "retryable": error.retryable,
                            "status_code": error.status_code,
                            "message": str(error),
                        })
                        final_failure = {
                            "category": "provider_error",
                            "message": str(error),
                            "retryable": error.retryable,
                        }
                        if error.retryable and attempt < self.config.max_attempts:
                            stats.retries += 1
                            self._wait_for_retry(attempt, error)
                            continue
                        break

                    response_hash = hashlib.sha256(response.content.encode("utf-8")).hexdigest()
                    try:
                        annotations = json.loads(response.content)
                    except json.JSONDecodeError as error:
                        stats.invalid_json_attempts += 1
                        attempt_history.append({
                            "attempt": attempt,
                            "category": "invalid_json",
                            "response_sha256": response_hash,
                            "message": str(error),
                        })
                        final_failure = {
                            "category": "invalid_json",
                            "message": str(error),
                            "raw_response": response.content,
                        }
                        if attempt < self.config.max_attempts:
                            stats.retries += 1
                            feedback = "\n\nYour previous response was not valid JSON. Return a new complete JSON object only."
                            continue
                        break

                    restored, changes = _restore_redacted_surfaces(
                        annotations if isinstance(annotations, dict) else {},
                        str(record.get("text", "")),
                        redaction.text,
                    )
                    annotated_record = copy.deepcopy(record)
                    annotated_record["text2task_annotations"] = restored
                    issues = validate_record(annotated_record, self.prompt_builder.schema, require_annotations=True)
                    if issues:
                        category = self._classify_validation(issues)
                        attempt_history.append({
                            "attempt": attempt,
                            "category": category,
                            "response_sha256": response_hash,
                            "issues": [asdict(issue) for issue in issues],
                            "recorded_changes": changes,
                        })
                        final_failure = {
                            "category": category,
                            "issues": [asdict(issue) for issue in issues],
                            "raw_response": response.content,
                            "recorded_changes": changes,
                        }
                        if attempt < self.config.max_attempts:
                            stats.retries += 1
                            issue_text = "\n".join(f"- {issue}" for issue in issues[:20])
                            feedback = (
                                "\n\nYour previous JSON failed validation. Generate a new complete annotation object; "
                                "do not patch the prior object. Validation errors:\n" + issue_text
                            )
                            continue
                        break

                    reasons = review_reasons(annotated_record)
                    tasks = [entity for entity in restored.get("entities", []) if entity.get("type") == "TASK"]
                    if not tasks:
                        stats.empty_task_predictions += 1
                    if reasons:
                        stats.records_requiring_review += 1
                    annotated_record["llm_annotation_metadata"] = {
                        "pipeline_version": "1.0.0",
                        "prompt_version": self.prompt_builder.version,
                        "provider": self.provider.name,  # type: ignore[union-attr]
                        "model": response.model,
                        "timestamp": utc_now(),
                        "source_record_id": record_id,
                        "source_split": record.get("source_split"),
                        "annotation_status": restored.get("annotation_status"),
                        "structured_output_requested": self.provider.supports_structured_output,  # type: ignore[union-attr]
                        "structured_output_mode": self.provider.structured_output_mode,  # type: ignore[union-attr]
                        "attempts": attempt,
                        "attempt_history": attempt_history,
                        "request_id": response.request_id,
                        "finish_reason": response.finish_reason,
                        "usage": asdict(response.usage),
                        "redaction": {
                            "enabled": self.config.redact_sensitive,
                            "spans": [asdict(span) for span in redaction.spans],
                            "recorded_changes": changes,
                        },
                        "requires_review": bool(reasons),
                        "review_reasons": reasons,
                    }
                    _append_jsonl(self.config.success_path, annotated_record)
                    successful_ids.add(record_id)
                    stats.successful_annotations += 1
                    if reasons:
                        _append_jsonl(
                            self.config.review_path,
                            {
                                "source_record_id": record_id,
                                "source_split": record.get("source_split"),
                                "timestamp": utc_now(),
                                "review_reasons": reasons,
                                "annotation": annotated_record,
                            },
                        )
                    final_failure = None
                    self._checkpoint(stats, record_id)
                    break

                if final_failure is not None:
                    # Every quarantined failure needs human inspection or a
                    # corrected provider retry before it can enter silver.
                    stats.records_requiring_review += 1
                    category = final_failure["category"]
                    if category == "invalid_json":
                        stats.invalid_json_count += 1
                    elif category == "invalid_span":
                        stats.invalid_span_count += 1
                    elif category == "relation_validation":
                        stats.relation_validation_failures += 1
                    elif category == "provider_error":
                        stats.provider_failures += 1
                    else:
                        stats.other_validation_failures += 1
                    failure_record = {
                        "source_record_id": record_id,
                        "source_split": record.get("source_split"),
                        "timestamp": utc_now(),
                        "provider": self.provider.name,  # type: ignore[union-attr]
                        "model": self.provider.model,  # type: ignore[union-attr]
                        "prompt_version": self.prompt_builder.version,
                        "attempt_history": attempt_history,
                        "failure": final_failure,
                    }
                    _append_jsonl(self.config.failure_path, failure_record)
                    failed_ids.add(record_id)
                    self._checkpoint(stats, record_id)

        stats.completed_at = utc_now()
        if not self.config.dry_run:
            self._checkpoint(stats, last_record_id)
        self._report(stats)
        return stats


def format_summary(stats: RunStats) -> str:
    cost = "unavailable"
    if stats.usage.cost_usd is not None:
        cost = f"${stats.usage.cost_usd:.6f} ({stats.usage.cost_source})"
    return "\n".join(
        [
            "Text2Task LLM annotation run complete",
            f"  Provider/model: {stats.provider}/{stats.model}",
            f"  Records considered: {stats.records_considered}",
            f"  Successful annotations: {stats.successful_annotations}",
            f"  Invalid JSON count: {stats.invalid_json_count} (attempts: {stats.invalid_json_attempts})",
            f"  Invalid span count: {stats.invalid_span_count}",
            f"  Relation-validation failures: {stats.relation_validation_failures}",
            f"  Other validation failures: {stats.other_validation_failures}",
            f"  Empty-task predictions: {stats.empty_task_predictions}",
            f"  Records requiring review: {stats.records_requiring_review}",
            f"  Token usage: input={stats.usage.input_tokens}, output={stats.usage.output_tokens}, total={stats.usage.total_tokens}",
            f"  API cost: {cost}",
        ]
    )
