import os
import unittest
from pathlib import Path
from unittest.mock import patch

from src.api.config import Settings


class DockerRuntimeTests(unittest.TestCase):
    def test_runtime_paths_are_configurable_from_environment(self):
        values = {
            "T2T_DB": "/app/state/test.db",
            "T2T_ENTITY_MODEL": "/app/models/entity",
            "T2T_RELATION_MODEL": "/app/models/relation",
            "T2T_FRONTEND_DIST": "/app/frontend/dist",
            "T2T_RESULTS_DIR": "/app/results",
            "T2T_TZ": "Asia/Kolkata",
        }
        with patch.dict(os.environ, values, clear=False):
            settings = Settings.from_env()
        self.assertEqual("/app/state/test.db", settings.db_path)
        self.assertEqual(Path("/app/models/entity"), settings.entity_model_dir)
        self.assertEqual(Path("/app/models/relation"), settings.relation_model_dir)
        self.assertEqual(Path("/app/frontend/dist"), settings.frontend_dist)
        self.assertEqual(Path("/app/results"), settings.results_dir)
        self.assertEqual("Asia/Kolkata", settings.default_timezone)

    def test_container_files_do_not_embed_a_registry_credential(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("compose.yaml", ".env.example", "Dockerfile"):
            text = (root / name).read_text(encoding="utf-8")
            self.assertNotIn("ghp_", text)
            self.assertNotIn("github_pat_", text)

    def test_generated_bundle_excludes_training_state_and_private_data(self):
        root = Path(__file__).resolve().parents[1]
        bundle = root / "docker/model_bundle"
        if not bundle.is_dir():
            self.skipTest("model bundle is generated only in release workspaces")
        names = {path.name for path in bundle.rglob("*") if path.is_file()}
        self.assertIn("model.safetensors", names)
        self.assertIn("model.pt", names)
        self.assertNotIn("optimizer.pt", names)
        self.assertFalse(any(path.suffix in {".jsonl", ".db"} for path in bundle.rglob("*")))


if __name__ == "__main__":
    unittest.main()
