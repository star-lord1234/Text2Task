import copy
import unittest

from scripts.select_candidates import (
    analyze_record,
    dependency_matches,
    select_candidates,
    verify_no_cross_split_duplicates,
)


def make_record(record_id, split, text, thread_id=None, duplicate_info=None, event_type="O"):
    thread_id = thread_id or record_id.replace(":", "_")
    tokens = text.split()
    labels = ["O"] * len(tokens)
    payload = {"labels": [labels], "triggers": [""], "extras": [""]}
    return {
        "id": record_id,
        "source": "mailex",
        "source_split": split,
        "source_filename": f"{thread_id}.json",
        "thread_id": thread_id,
        "turn_index": 0,
        "text": text,
        "text_raw": text,
        "tokens": tokens,
        "token_offsets": [[0, 0] for _ in tokens],
        "original_events": {event_type: payload},
        "thread_context": {"turn_count": 1},
        "duplicate_info": duplicate_info,
    }


class DependencyPatternTests(unittest.TestCase):
    def test_after_alone_is_not_a_dependency(self):
        self.assertFalse(dependency_matches("We will have drinks after work."))
        self.assertFalse(dependency_matches("Lunch is after the meeting."))
        self.assertFalse(dependency_matches("I will travel when air fares are cheaper."))

    def test_as_soon_as_possible_is_a_deadline_not_a_dependency(self):
        self.assertFalse(dependency_matches("Please send the report as soon as possible."))

    def test_action_conditioned_connectors_are_candidates(self):
        first = dependency_matches("We need to review the draft before we send the final report.")
        second = dependency_matches("Once you approve the draft, we will send the final version.")
        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(first[0]["pattern"], "action_conditioned_temporal_connector")

    def test_strong_dependency_needs_nearby_action_evidence(self):
        self.assertTrue(dependency_matches("Pending approval, we will send the signed agreement."))
        self.assertFalse(dependency_matches("The two variables are dependent on each other."))
        self.assertFalse(
            dependency_matches(
                "To unsubscribe, send an email. Your use of Yahoo Groups is subject to the Terms of Service."
            )
        )


class CoverageFlagTests(unittest.TestCase):
    def test_deadline_request_and_temporal_flags_are_provisional(self):
        record = make_record(
            "mailex:train:a:turn_0000",
            "train",
            "Please send the report by Friday at 5 PM.",
            event_type="Request_Action",
        )
        analysis = analyze_record(record)
        self.assertTrue(analysis["flags"]["explicit_actionable_request"])
        self.assertTrue(analysis["flags"]["explicit_deadline"])
        self.assertTrue(analysis["flags"]["temporal_expression"])
        self.assertFalse(analysis["flags"]["no_actionable_tasks"])

    def test_no_action_email_is_retained_as_a_coverage_category(self):
        record = make_record("mailex:dev:b:turn_0000", "dev", "Thanks for the information.")
        analysis = analyze_record(record)
        self.assertTrue(analysis["flags"]["no_actionable_tasks"])


class DeterministicSelectionTests(unittest.TestCase):
    def _fixture(self):
        records = {"train": [], "dev": [], "test": []}
        duplicate = {"exact_group_id": "exact:shared", "exact_group_size": 3}
        for split in records:
            records[split].append(
                make_record(
                    f"mailex:{split}:shared:turn_0000",
                    split,
                    "Please send the report by Friday.",
                    duplicate_info=duplicate,
                    event_type="Request_Action",
                )
            )
            records[split].append(
                make_record(
                    f"mailex:{split}:unique:turn_0000",
                    split,
                    f"The {split} status information is available.",
                )
            )
        analyses = {
            record["id"]: analyze_record(record)
            for split_records in records.values()
            for record in split_records
        }
        return records, analyses

    def test_selection_is_deterministic_and_preserves_splits(self):
        records, analyses = self._fixture()
        first, _ = select_candidates(copy.deepcopy(records), copy.deepcopy(analyses), {"train": 2, "dev": 2, "test": 2}, 123)
        second, _ = select_candidates(copy.deepcopy(records), copy.deepcopy(analyses), {"train": 2, "dev": 2, "test": 2}, 123)
        self.assertEqual(
            {split: [record["id"] for record in values] for split, values in first.items()},
            {split: [record["id"] for record in values] for split, values in second.items()},
        )
        for split, values in first.items():
            self.assertTrue(all(record["source_split"] == split for record in values))

    def test_duplicate_group_never_crosses_selected_splits(self):
        records, analyses = self._fixture()
        selected, _ = select_candidates(records, analyses, {"train": 2, "dev": 2, "test": 2}, 123)
        verify_no_cross_split_duplicates(selected)
        owners = {
            record["source_split"]
            for values in selected.values()
            for record in values
            if (record.get("duplicate_info") or {}).get("exact_group_id") == "exact:shared"
        }
        self.assertLessEqual(len(owners), 1)


if __name__ == "__main__":
    unittest.main()
