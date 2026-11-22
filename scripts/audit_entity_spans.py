"""Phase 7.5 step 1: audit tokenizer offsets, BIO decoding and span fragmentation BEFORE any post-processing is designed.

Reads the SILVER-v2 *validation* split (never train for model behaviour, never test) and optional extra texts. Writes results/phase7_5/audit.json.
Everything is measured, nothing is tuned. Usage: .venv/bin/python scripts/audit_entity_spans.py [extra_texts.json]
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.model_training.entity_inference import EntityPredictor, decode  # noqa: E402

MODEL = ROOT / "models/text2task-distilbert/entity_v2_three_class/epoch3_sqrt_weighted"
VAL = ROOT / "data/model_ready/entities_v2_three_class/validation.jsonl"
TRAIN = ROOT / "data/model_ready/entities_v2_three_class/train.jsonl"
STOP = {"the", "a", "an", "to", "of", "and", "or", "in", "on", "at", "by", "for", "with", "is", "it", "be", "we", "you", "i", "can", "will", "please", "d", "s", "t", "ll"}
WORD = re.compile(r"\w+")


def mid_word(text: str, a: int, b: int) -> tuple[bool, bool]:
    left = a > 0 and bool(re.match(r"\w", text[a - 1])) and bool(re.match(r"\w", text[a]))
    right = b < len(text) and bool(re.match(r"\w", text[b])) and bool(re.match(r"\w", text[b - 1]))
    return left, right


def span_stats(text: str, spans: list[dict]) -> dict:
    n = len(spans)
    out = Counter()
    for s in spans:
        l, r = mid_word(text, s["start"], s["end"])
        out["starts_mid_word"] += l
        out["ends_mid_word"] += r
        out["mid_word_any"] += (l or r)
        body = text[s["start"]:s["end"]].lower()
        words = WORD.findall(body)
        out["one_or_two_chars"] += len(body.strip()) <= 2
        out["stopword_only"] += bool(words) and all(w in STOP for w in words)
        out["by_type_" + s["type"]] += 1
    out["spans"] = n
    return dict(out)


def add(a: dict, b: dict) -> dict:
    c = Counter(a)
    c.update(b)
    return dict(c)


def adjacent_same_type(text: str, spans: list[dict]) -> int:
    n = 0
    ordered = sorted(spans, key=lambda s: s["start"])
    for x, y in zip(ordered, ordered[1:]):
        if x["type"] == y["type"] and not re.search(r"[^\s]", text[x["end"]:y["start"]]):
            n += 1
    return n


def main() -> None:
    rows = [json.loads(l) for l in VAL.read_text().splitlines()]
    train = [json.loads(l) for l in TRAIN.read_text().splitlines()]
    pred = EntityPredictor(MODEL)
    tok = pred.tokenizer
    report: dict = {"model": str(MODEL.relative_to(ROOT)), "validation_rows": len(rows), "scope": "validation split read-only; test split never read"}

    # --- 1. tokenizer offset alignment
    mism, checked, special_nonempty, gaps = 0, 0, 0, 0
    for r in rows:
        enc = tok(r["text"], return_offsets_mapping=True, truncation=True, max_length=512)
        fresh = [tuple(o) for o in enc["offset_mapping"]]
        checked += 1
        if enc["input_ids"][:len(r["input_ids"])] != r["input_ids"][:len(enc["input_ids"])] and r["window_count"] == 1:
            mism += 1
        for (a, b), t in zip(fresh, tok.convert_ids_to_tokens(enc["input_ids"])):
            if t in ("[CLS]", "[SEP]") and a != b:
                special_nonempty += 1
        covered = sum(b - a for a, b in fresh)
        gaps += len(re.sub(r"\s", "", r["text"])) - covered > 0
    report["tokenizer_offsets"] = {"rows_checked": checked, "stored_ids_differ_from_fresh_tokenisation": mism, "special_tokens_with_nonempty_offsets": special_nonempty,
                                   "rows_where_offsets_do_not_cover_all_non_space_characters": gaps,
                                   "verdict": "offsets are exact char positions; pieces map back to the text without drift" if not (mism or special_nonempty or gaps) else "ISSUES FOUND"}

    # --- 2. gold span boundaries (the labels the model was trained to imitate)
    def gold_stats(data):
        tot = {}
        seen = set()
        for r in data:
            if r["source_record_id"] in seen:
                continue
            seen.add(r["source_record_id"])
            sp = [{"start": e["start"], "end": e["end"], "type": e["type"]} for e in r["entities"]]
            tot = add(tot, span_stats(r["text"], sp))
        return tot
    report["gold_boundaries_validation"] = gold_stats(rows)
    report["gold_boundaries_train"] = gold_stats(train)

    # --- 3. predictions: raw sub-token votes -> BIO decode
    texts, seen = [], set()
    for r in rows:
        if r["source_record_id"] not in seen:
            seen.add(r["source_record_id"])
            texts.append(r["text"])
    extra = json.loads(Path(sys.argv[1]).read_text()) if len(sys.argv) > 1 else []
    pred_tot, adj, orphan_i, label_flips, words_total, words_mixed, nonword_pieces = {}, 0, 0, 0, 0, 0, 0
    for text in texts + extra:
        votes = pred.votes(text)
        spans = decode(text, votes)
        pred_tot = add(pred_tot, span_stats(text, spans))
        adj += adjacent_same_type(text, spans)
        ordered = sorted(votes.items())
        prev = "O"
        for _, (lab, _) in ordered:                                   # I- after O or after a different type = orphan start
            if lab.startswith("I-") and (prev == "O" or prev.split("-")[1] != lab.split("-")[1]):
                orphan_i += 1
            prev = lab
        for m in WORD.finditer(text):                                 # within one word, do its pieces disagree about the entity type?
            labs = [lab.split("-")[-1] for (a, b), (lab, _) in ordered if a >= m.start() and b <= m.end()]
            if len(labs) > 1:
                words_total += 1
                words_mixed += len(set(labs)) > 1
    report["predicted_boundaries"] = {"texts": len(texts) + len(extra), **pred_tot, "adjacent_same_type_spans_separated_only_by_whitespace": adj,
                                      "orphan_I_tags_decoded_as_new_spans": orphan_i,
                                      "multi_piece_words": words_total, "multi_piece_words_whose_pieces_disagree_on_type": words_mixed}
    gv = report["gold_boundaries_validation"]; pv = report["predicted_boundaries"]
    rate = lambda d, k: round(d.get(k, 0) / max(1, d["spans"]), 4)
    report["rates"] = {"gold_validation_mid_word": rate(gv, "mid_word_any"), "gold_train_mid_word": rate(report["gold_boundaries_train"], "mid_word_any"),
                       "predicted_mid_word": rate(pv, "mid_word_any"), "predicted_stopword_only": rate(pv, "stopword_only"), "predicted_1_2_chars": rate(pv, "one_or_two_chars"),
                       "gold_stopword_only": rate(gv, "stopword_only")}
    out = ROOT / "results/phase7_5/audit.json"
    out.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ("tokenizer_offsets", "rates")}, indent=1))
    print("predicted:", {k: v for k, v in pv.items() if not k.startswith("by_type")})
    print("gold validation:", gv)


if __name__ == "__main__":
    main()
