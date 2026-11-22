"""Run live-message fixtures against the real app (real models) under one or more pipeline configurations and score them.

Usage: .venv/bin/python scripts/run_live_battery.py --fixtures live_battery_v1 live_scenarios_new --presets neural_only hybrid [--out results/phase7_5]
Scoring is mechanical (see score_case): expected tasks/owners/due days/statuses/edges are checked, and every task or accepted dependency that was
not expected counts as a false positive. A simulated reviewer accepts every actionable proposal (an upper bound on what lands in the task list).
Output is the raw per-case record plus a per-group summary; nothing is hand-edited.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient  # noqa: E402

from src.api.app import create_app  # noqa: E402
from src.api.config import Settings  # noqa: E402

TZ = "America/Chicago"


def _has(title: str, words: list[str]) -> bool:
    t = title.lower()
    return all(w.lower() in t for w in words)


def accept_everything(c: TestClient) -> None:
    for _ in range(6):
        progressed = False
        for s in c.get("/api/suggestions").json():
            if s["operation"] in ("NO_ACTION", "PROPOSE_DUE_DATE_CHANGE") or s.get("requires_referent"):
                continue
            r = c.post(f"/api/suggestions/{s['id']}/accept", json={"actor_id": "riya"})
            if r.status_code == 422:
                r = c.post(f"/api/suggestions/{s['id']}/accept", json={"actor_id": "riya", "edits": {"owner_id": None}})
            progressed |= r.status_code == 200
        if not progressed:
            break


def run_case(c: TestClient, case: dict) -> dict:
    c.post("/api/workspace/reset")
    props_by_msg, errors = [], []
    for sender, rec, text, hhmm in case["messages"]:
        r = c.post("/api/messages", json={"sender_id": sender, "recipient_ids": rec, "text": text, "mode": "live", "created_at": f"2026-11-11T{hhmm}:00-06:00"})
        a = r.json()
        if a.get("error"):
            errors.append(a["error"])
        msg = c.get("/api/workspace").json()["messages"][-1]
        props_by_msg.append([{"op": p["operation"], "summary": p["summary"], "flags": p["flag_codes"]} for p in msg["proposals"]])
        accept_everything(c)
    tasks = c.get("/api/tasks").json()
    graph = c.get("/api/dependencies").json()
    return {"proposals": props_by_msg, "errors": errors,
            "tasks": [{"id": t["id"], "title": t["title"], "owner": t["owner_id"], "lifecycle": t["lifecycle"],
                       "due": ((t["due"] or {}).get("value") or (t["due"] or {}).get("start") or "")[:10] if t["due"] and t["due"].get("status") == "RESOLVED" else ""} for t in tasks],
            "edges": [{"source": e["source"], "target": e["target"], "kind": e["kind"]} for e in graph["edges"]]}


def score_case(case: dict, rec: dict) -> dict:
    exp = case["expect"]
    tasks = rec["tasks"]
    claimed: set[str] = set()
    out = {"found": 0, "expected": len(exp.get("tasks", [])), "owner_ok": 0, "owner_expected": 0, "due_ok": 0, "due_expected": 0,
           "status_ok": 0, "status_expected": 0, "failures": []}
    by_expected: list = []
    for et in exp.get("tasks", []):
        m = next((t for t in tasks if t["id"] not in claimed and _has(t["title"], et["has"])), None)
        by_expected.append(m)
        if m is None:
            out["failures"].append(f"missing task {et['has']}")
            continue
        claimed.add(m["id"])
        out["found"] += 1
        if "owner" in et:
            out["owner_expected"] += 1
            if m["owner"] == et["owner"]:
                out["owner_ok"] += 1
            else:
                out["failures"].append(f"{et['has']}: owner {m['owner']} != {et['owner']}")
        if "due" in et:
            out["due_expected"] += 1
            if m["due"] == et["due"]:
                out["due_ok"] += 1
            else:
                out["failures"].append(f"{et['has']}: due {m['due'] or 'none'} != {et['due']}")
        if "status" in et:
            out["status_expected"] += 1
            if m["lifecycle"] == et["status"]:
                out["status_ok"] += 1
            else:
                out["failures"].append(f"{et['has']}: status {m['lifecycle']} != {et['status']}")
    spurious = [t for t in tasks if t["id"] not in claimed]
    out["spurious_tasks"] = [t["title"] for t in spurious]
    if spurious:
        out["failures"].append(f"spurious tasks {out['spurious_tasks']}")
    edges_exp = exp.get("edges", [])
    want = set()
    out["edges_expected"], out["edges_found"] = len(edges_exp), 0
    for dep_has, pre_has in edges_exp:
        d = next((t for t in tasks if _has(t["title"], dep_has)), None)
        p = next((t for t in tasks if _has(t["title"], pre_has) and t is not d), None)
        if d and p:
            want.add((p["id"], d["id"]))                       # graph edges run prerequisite -> dependent
        got = d and p and any(e["source"] == p["id"] and e["target"] == d["id"] and e["kind"] == "accepted" for e in rec["edges"])
        out["edges_found"] += bool(got)
        if not got:
            out["failures"].append(f"missing edge {dep_has} <- {pre_has}")
    accepted = {(e["source"], e["target"]) for e in rec["edges"] if e["kind"] == "accepted"}
    out["spurious_edges"] = sorted(f"{a}->{b}" for a, b in accepted - want)
    if out["spurious_edges"]:
        out["failures"].append(f"spurious edges {out['spurious_edges']}")
    if "last_ops" in exp and not set(exp["last_ops"]) <= {p["op"] for p in rec["proposals"][-1]}:
        out["failures"].append(f"last message ops {[p['op'] for p in rec['proposals'][-1]]} lack {exp['last_ops']}")
    if "max_creates" in exp:
        n = sum(p["op"] == "CREATE_TASK" for ps in rec["proposals"] for p in ps)
        if n > exp["max_creates"]:
            out["failures"].append(f"{n} CREATE_TASK proposals > {exp['max_creates']}")
    if rec["errors"]:
        out["failures"].append(f"errors {rec['errors']}")
    out["passed"] = not out["failures"]
    out["passed_ignoring_spurious"] = not [f for f in out["failures"] if not f.startswith("spurious")]
    return out


def summarise(cases: list[dict], scores: list[dict]) -> dict:
    groups: dict[str, list] = defaultdict(list)
    for c, s in zip(cases, scores):
        groups[c["group"]].append(s)
        groups["ALL"].append(s)
    out = {}
    for g, ss in groups.items():
        f = lambda k: sum(s[k] for s in ss)
        ratio = lambda a, b: round(f(a) / f(b), 3) if f(b) else None
        out[g] = {"cases": len(ss), "passed_strict": sum(s["passed"] for s in ss), "passed_ignoring_spurious": sum(s["passed_ignoring_spurious"] for s in ss),
                  "task_recall": ratio("found", "expected"), "owner_accuracy": ratio("owner_ok", "owner_expected"), "due_accuracy": ratio("due_ok", "due_expected"),
                  "status_accuracy": ratio("status_ok", "status_expected"), "edge_recall": ratio("edges_found", "edges_expected"),
                  "expected_edges": f("edges_expected"), "spurious_tasks": sum(len(s["spurious_tasks"]) for s in ss), "spurious_edges": sum(len(s["spurious_edges"]) for s in ss)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", nargs="+", default=["live_battery_v1", "live_scenarios_new"])
    ap.add_argument("--presets", nargs="+", default=["neural_only", "neural_plus_linker", "refined", "hybrid", "rule_only"])
    ap.add_argument("--out", default=str(ROOT / "results/phase7_5"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    fixtures = {n: json.loads((ROOT / "tests/fixtures" / f"{n}.json").read_text()) for n in a.fixtures}
    summary: dict = {}
    with TestClient(create_app(Settings(db_path=":memory:", load_models=True, default_timezone=TZ))) as c:
        c.put("/api/settings", json={"timezone": TZ})
        for preset in a.presets:
            c.put("/api/settings", json={"pipeline_preset": preset, "refine_overrides": {}})
            for fname, fx in fixtures.items():
                records, scores = [], []
                for case in fx["cases"]:
                    rec = run_case(c, case)
                    sc = score_case(case, rec)
                    records.append({"id": case["id"], "group": case["group"], "messages": case["messages"], "record": rec, "score": sc})
                    scores.append(sc)
                summary.setdefault(fname, {})[preset] = summarise(fx["cases"], scores)
                (out / f"run_{fname}_{preset}.json").write_text(json.dumps({"fixture": fname, "preset": preset, "cases": records, "summary": summary[fname][preset]}, indent=1))
                s = summary[fname][preset]["ALL"]
                print(f"{fname:20s} {preset:20s} strict {s['passed_strict']:>2}/{s['cases']}  lenient {s['passed_ignoring_spurious']:>2}  taskR {s['task_recall']}  owner {s['owner_accuracy']}  due {s['due_accuracy']}  status {s['status_accuracy']}  edgeR {s['edge_recall']}/{s['expected_edges']}  spurT {s['spurious_tasks']} spurE {s['spurious_edges']}", flush=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
