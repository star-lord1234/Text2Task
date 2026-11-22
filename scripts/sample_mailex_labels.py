#!/usr/bin/env python3
"""Write a random sample of mapped records with inline entity markup for manual inspection."""
import argparse, json, random, sys
from pathlib import Path

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--records", type=Path, default=Path("data/mailex_v1/records/train.jsonl"))
    p.add_argument("--out", type=Path, default=Path("data/reports/mailex_v1_sample40.md"))
    p.add_argument("--n", type=int, default=40)
    p.add_argument("--seed", type=int, default=20261103)
    p.add_argument("--max-chars", type=int, default=1000)
    a = p.parse_args()
    rows = [json.loads(l) for l in a.records.read_text(encoding="utf-8").splitlines() if l.strip()]
    pool = [r for r in rows if len(r["text"]) <= a.max_chars]
    random.Random(a.seed).shuffle(pool)
    out = [f"# MailEx-derived label sample ({a.n} of {len(pool)} records with <= {a.max_chars} chars; seed {a.seed})\n",
           "Markup: `[[TYPE| text ]]`.\n"]
    for i, r in enumerate(pool[: a.n], 1):
        text, ents = r["text"], sorted(r["text2task_annotations"]["entities"], key=lambda e: e["start"])
        pieces, pos = [], 0
        for e in ents:
            pieces += [text[pos:e["start"]], f"[[{e['type']}|{text[e['start']:e['end']]}]]"]
            pos = e["end"]
        pieces.append(text[pos:])
        out.append(f"## {i}. `{r['id']}`\n\n" + "".join(pieces).replace("\n", " ") + "\n")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("\n".join(out), encoding="utf-8")
    print(a.out)
main()
