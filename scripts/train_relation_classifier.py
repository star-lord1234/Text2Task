#!/usr/bin/env python3
"""Train the Phase 3 relation classifier (provisional SILVER). Selection uses validation only; test is never read."""
from __future__ import annotations

import argparse, hashlib, json, sys, time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import torch  # noqa: E402
from torch import nn  # noqa: E402
from transformers import get_linear_schedule_with_warmup  # noqa: E402

from src.model_data.token_classification import read_jsonl  # noqa: E402
from src.model_training.relation_classifier import (  # noqa: E402
    LABELS, RelationClassifier, build_tokenizer, collate, detect_device, encode_rows,
    predict_probs, prf, save_model, seed_everything)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=ROOT / "configs/relation_training.json")
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--pooling")
    ap.add_argument("--class-weight", choices=["none", "sqrt", "balanced"])
    ap.add_argument("--train-file")
    ap.add_argument("--epochs", type=int)
    ap.add_argument("--lr", type=float)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--limit", type=int, help="memorisation/smoke: train and eval on first N train rows")
    a = ap.parse_args()
    cfg = json.loads(a.config.read_text())
    for k, v in (("pooling", a.pooling), ("class_weight", a.class_weight), ("train_file", a.train_file),
                 ("epochs", a.epochs), ("learning_rate", a.lr), ("seed", a.seed)):
        if v is not None:
            cfg[k] = v
    seed_everything(cfg["seed"])
    device = detect_device()
    data = ROOT / cfg["data_dir"]
    tok = build_tokenizer(cfg["base_model"])
    train_rows = read_jsonl(data / cfg["train_file"])
    val_rows = read_jsonl(data / "validation.jsonl")
    if a.limit:
        train_rows = train_rows[: a.limit]
        val_rows = train_rows
    train = encode_rows(train_rows, tok, cfg["max_length"])
    val = encode_rows(val_rows, tok, cfg["max_length"])
    unrep = sum(not x["representable"] for x in train + val)
    print(f"device={device} train={len(train)} val={len(val)} unrepresentable={unrep}")
    assert unrep == 0, "pair markers lost to truncation"

    model = RelationClassifier(cfg["base_model"], tok, cfg["pooling"]).to(device)
    counts = Counter(x["label"] for x in train)
    if cfg["class_weight"] == "none":
        w = [1.0] * len(LABELS)
    else:
        total = sum(counts.values())
        w = [(total / (len(LABELS) * max(counts.get(i, 1), 1))) for i in range(len(LABELS))]
        if cfg["class_weight"] == "sqrt":
            w = [x ** 0.5 for x in w]
    loss_fn = nn.CrossEntropyLoss(weight=torch.tensor(w, device=device))
    opt = torch.optim.AdamW(model.parameters(), lr=cfg["learning_rate"], weight_decay=cfg["weight_decay"])
    bs, acc = cfg["train_batch_size"], cfg["grad_accum"]
    steps = cfg["epochs"] * ((len(train) + bs * acc - 1) // (bs * acc))
    sched = get_linear_schedule_with_warmup(opt, int(cfg["warmup_ratio"] * steps), steps)
    pad = tok.pad_token_id
    gen = torch.Generator().manual_seed(cfg["seed"])

    out_dir = ROOT / cfg["model_dir"] / "provisional_silver" / a.run_name
    res_dir = ROOT / cfg["results_dir"] / "runs" / a.run_name
    res_dir.mkdir(parents=True, exist_ok=True)
    best, history, t0 = (-1.0, None), [], time.time()
    for epoch in range(1, cfg["epochs"] + 1):
        model.train()
        order = torch.randperm(len(train), generator=gen).tolist()
        total_loss = 0.0
        opt.zero_grad()
        for step, i in enumerate(range(0, len(order), bs), 1):
            ids, att, mask, y = collate([train[j] for j in order[i:i + bs]], pad, device)
            loss = loss_fn(model(ids, att, mask), y)
            (loss / acc).backward()
            total_loss += loss.item()
            if step % 20 == 0:
                print(f"  epoch {epoch} batch {step} loss {loss.item():.3f} t={time.time()-t0:.0f}s", flush=True)
            if step % acc == 0 or i + bs >= len(order):
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step(); sched.step(); opt.zero_grad()
        probs = predict_probs(model, val, pad, device)
        pred = [LABELS[max(range(len(LABELS)), key=lambda k: p[k])] for p in probs]
        gold = [LABELS[x["label"]] for x in val]
        m = prf(gold, pred)
        rec = {"epoch": epoch, "train_loss": total_loss / max(1, (len(order) + bs - 1) // bs),
               "macro_positive_f1": m["macro_positive_f1"], "micro_positive_f1": m["micro_positive"]["f1"],
               "per_label_f1": {l: m[l]["f1"] for l in LABELS[1:]}, "none_fpr": m["NONE"]["false_positive_rate"]}
        history.append(rec)
        print(json.dumps(rec))
        if m["macro_positive_f1"] > best[0]:
            best = (m["macro_positive_f1"], epoch)
            save_model(model, tok, out_dir, {
                "version": f"relations-{a.run_name}", "base_model": cfg["base_model"], "pooling": cfg["pooling"],
                "labels": LABELS, "best_epoch": epoch, "best_val_macro_positive_f1": best[0], "config": cfg,
                "class_weights": w, "train_label_counts": dict(counts), "seed": cfg["seed"], "device": device,
                "data_hashes": {s: hashlib.sha256((data / f).read_bytes()).hexdigest() for s, f in
                                (("train", cfg["train_file"]), ("validation", "validation.jsonl"))},
                "provenance": {"tier": "SILVER", "is_final_research_model": False, "human_verified": False},
                "memorisation_run": bool(a.limit)})
    summary = {"run": a.run_name, "best_epoch": best[1], "best_val_macro_positive_f1": best[0],
               "history": history, "seconds": time.time() - t0, "config": cfg}
    (res_dir / "training_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"best epoch {best[1]} macro_positive_f1={best[0]:.4f} -> {out_dir}")


if __name__ == "__main__":
    main()
