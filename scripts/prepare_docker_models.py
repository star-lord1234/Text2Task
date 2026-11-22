#!/usr/bin/env python3
"""Create the minimal, ignored model bundle used by the inference container."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTITY_SOURCE = ROOT / "models/text2task-distilbert/entity_v2_three_class/epoch3_sqrt_weighted"
RELATION_SOURCE = ROOT / "models/text2task-relations/ACTIVE"
OUTPUT = ROOT / "docker/model_bundle"
ENTITY_FILES = (
    "model.safetensors", "config.json", "tokenizer.json", "tokenizer_config.json",
    "label_mappings.json", "training_metadata.json",
)
RELATION_FILES = ("model.pt", "tokenizer.json", "tokenizer_config.json", "relation_config.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_required(source: Path, destination: Path, names: tuple[str, ...]) -> None:
    for name in names:
        path = source / name
        if not path.is_file():
            raise SystemExit(f"Required release artifact is missing: {path}")
        shutil.copy2(path, destination / name)


def main() -> None:
    relation_source = RELATION_SOURCE.resolve()
    if not ENTITY_SOURCE.is_dir() or not relation_source.is_dir():
        raise SystemExit("The selected entity or relation model directory does not exist")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="text2task-model-bundle-", dir=OUTPUT.parent) as temporary:
        staging = Path(temporary)
        entity_out, relation_out = staging / "entity", staging / "relation"
        entity_out.mkdir()
        relation_out.mkdir()
        copy_required(ENTITY_SOURCE, entity_out, ENTITY_FILES)
        copy_required(relation_source, relation_out, RELATION_FILES)

        # Relation weights contain the complete encoder, but construction still
        # needs the DistilBERT architecture. Reuse the local entity architecture
        # and let RelationClassifier resize embeddings for its marker tokenizer.
        shutil.copy2(ENTITY_SOURCE / "config.json", relation_out / "config.json")

        files = []
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                files.append({
                    "path": str(path.relative_to(staging)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                })
        manifest = {
            "bundle_version": "0.1.0-silver",
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "annotation_tier": "SILVER",
            "human_verified": False,
            "final_research_model": False,
            "entity_source": str(ENTITY_SOURCE.relative_to(ROOT)),
            "relation_source": str(relation_source.relative_to(ROOT)),
            "excluded": ["training checkpoints", "optimizer state", "datasets", "raw email text"],
            "files": files,
            "total_bytes": sum(item["bytes"] for item in files),
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        if OUTPUT.exists():
            shutil.rmtree(OUTPUT)
        Path(temporary).replace(OUTPUT)

    print(f"Prepared {OUTPUT.relative_to(ROOT)} ({manifest['total_bytes'] / 1024 / 1024:.1f} MiB)")
    print(f"Files: {len(manifest['files'])}; annotation tier: SILVER; human verified: false")


if __name__ == "__main__":
    main()
