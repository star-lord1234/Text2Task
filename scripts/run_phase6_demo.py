#!/usr/bin/env python3
"""Demo (SCRIPTED data): a three-person chain, completion unblocking, a held cycle. Prints JSON + Mermaid + DOT."""
from __future__ import annotations

import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.graph.graph_builder import WorkflowGraph  # noqa: E402
from src.graph.scenario_runner import WS, run_graph_scenario  # noqa: E402
from src.graph.serialize import to_dot, to_frontend, to_mermaid  # noqa: E402

DEMO = {"name": "demo_chain", "tasks": [
    {"owner": "bianca", "title": "draft the report", "due": "2026-11-12"}, {"owner": "dev", "title": "review the draft", "due": "2026-11-13"},
    {"owner": "riya", "title": "send to the client", "due": "2026-11-16"}],
    "steps": [{"add": ["T-1", "T-2"]}, {"add": ["T-2", "T-3"]}, {"add": ["T-3", "T-1"], "expect": {"status": "rejected", "code": "CYCLE"}},
              {"status": ["T-1", "completed"], "expect_diff": {"became_ready": ["T-2"]}}]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, help="directory to write demo_chain.json / .mmd / .dot")
    a = ap.parse_args()
    r = run_graph_scenario(DEMO)
    g = WorkflowGraph.from_store(r["store"], WS)
    payload = {"mode": "SCRIPTED demo data", "passed": r["passed"], "graph": to_frontend(g)}
    print(json.dumps(payload["graph"]["meta"], indent=1)); print(to_mermaid(g))
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "demo_chain.json").write_text(json.dumps(payload, indent=2))
        (a.out / "demo_chain.mmd").write_text(to_mermaid(g)); (a.out / "demo_chain.dot").write_text(to_dot(g))


if __name__ == "__main__":
    main()
