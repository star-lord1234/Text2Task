#!/usr/bin/env python3
"""Write docs/openapi.json from the FastAPI app (frontend types are generated from it; a test keeps it in sync)."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.api.app import create_app  # noqa: E402
from src.api.config import Settings  # noqa: E402


def schema() -> dict:
    return create_app(Settings(db_path=":memory:", load_models=False)).openapi()


if __name__ == "__main__":
    out = ROOT / "docs" / "openapi.json"
    out.write_text(json.dumps(schema(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {out} ({len(schema()['paths'])} paths)")
