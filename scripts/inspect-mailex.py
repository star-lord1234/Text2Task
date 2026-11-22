
import json
from pathlib import Path
from collections import Counter

ROOT = Path("data/raw/mailex")

files = list(ROOT.rglob("*.json"))

print("JSON files:", len(files))
print("Folders:", Counter(p.parent.name for p in files))

if not files:
    raise SystemExit("No JSON files found. Check your dataset path.")

sample_path = files[0]
sample = json.loads(sample_path.read_text(encoding="utf-8"))

print("\nSample file:", sample_path)
print("Top-level type:", type(sample).__name__)

if isinstance(sample, dict):
    print("Keys:", list(sample.keys()))

    sentences = sample.get("sentences")
    events = sample.get("events")

    if sentences:
        print("\nFirst sentence entry:")
        print(repr(sentences[0])[:1500])

    if events:
        print("\nEvent structure:")
        print(repr(list(events.items())[:1])[:2500])
else:
    print("First item:", repr(sample)[:2500])