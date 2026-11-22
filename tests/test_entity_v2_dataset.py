import unittest

from scripts.build_entity_dataset_v2 import resolve_single_layer


class EntityV2DatasetTests(unittest.TestCase):
    def test_shorter_person_span_wins_overlap(self):
        entities = [
            {"id": "t", "type": "TASK", "start": 0, "end": 20, "text": "Alice send the report"},
            {"id": "p", "type": "PERSON", "start": 0, "end": 5, "text": "Alice"},
        ]
        kept, dropped = resolve_single_layer(entities)
        self.assertEqual(["PERSON"], [entity["type"] for entity in kept])
        self.assertEqual(1, len(dropped))

    def test_tie_priority_is_person_temporal_task(self):
        entities = [
            {"id": "t", "type": "TASK", "start": 0, "end": 5, "text": "Alice"},
            {"id": "p", "type": "PERSON", "start": 0, "end": 5, "text": "Alice"},
        ]
        kept, _ = resolve_single_layer(entities)
        self.assertEqual("PERSON", kept[0]["type"])


if __name__ == "__main__":
    unittest.main()
