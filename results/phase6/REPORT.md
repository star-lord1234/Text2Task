# Phase 6 — Dependency graph and workflow state (FUNCTIONAL / PROVISIONAL)

**Graph validity is not semantic accuracy.** This report shows that the graph layer is correct (cycles refused, states derived properly,
history kept). It does **not** show that the system finds the right dependencies: there is no labelled dependency data, so accepted-edge
precision/recall cannot be computed. Train+validation only; the test split was never read.

## Technology actually used
NetworkX 3.7 (`DiGraph`; `has_path`, `shortest_path`, `find_cycle`, `is_directed_acyclic_graph`, `ancestors`/`descendants`, `topological_generations`,
`lexicographical_topological_sort`, `transitive_reduction`, `dag_longest_path`); the Phase 5 SQLite store as the single source of truth (the graph is a snapshot rebuilt
per request); stdlib dataclasses/unittest; SciPy `milp` only as an exact cross-check for the optional E5. **No new package was installed.**
React Flow / dagre / ELK are Phase 7 and were not used; `serialize.py` only emits JSON, DOT and Mermaid text.

## 1. Scenarios (developer-authored; regression guards, not an independent benchmark)
- **15 / 15 graph scenarios** and **3 / 3 chat-derived dependency scenarios** (Phase 5 scenarios 32-34 re-run through the real validator) pass.
- Covered: three-person chain (completing a prerequisite unblocks exactly the next task), diamond join, held cycle with its path, self/unknown/duplicate edges, redundant edge,
  timing conflict (resolved dates only), completed dependent, cancelled prerequisite, edge removal, idempotent add, cross-thread edges, reconsideration, layers and longest chain.
- A chat-derived cycle (A waits on B, B on C, C on A) is **refused by the graph validator and kept as a held edge with a `CYCLE:` reason**; the Phase 5 placeholder validator would
  have accepted it, and the snapshot then reports `acyclic = false` instead of hiding it (both are tested).

## 2. Oracle fuzz (300 seeds x 40 random edits)
Every add decision was compared with an independent DFS/Kahn oracle, and every derived state with an independent naive recomputation.
- **12000 edit decisions** and **72120 derived-state comparisons**: **0 disagreements**.
- Accepted graph acyclic after every step; topological order respects every edge; layers equal the longest-path oracle; held/removed edges never block.
- Final edge tallies: 1743 accepted, 5042 held. Held edges without a recorded reason: **0**. Reasons: {"UNKNOWN_ENDPOINT": 1643, "REMOVED": 1599, "SELF": 965, "CYCLE": 835}.
- Mutation check: a cycle-check bug injected into the editor was caught in 28 of 30 seeds (clean run: 0).

## 3. Optional E5 (consistency-aware edge selection) — SYNTHETIC ONLY
300 random graphs with a hidden true order, correct forward edges, and injected wrong edges (reversed copies and extras). It measures **constraint handling, not extraction accuracy**.

| method | cyclic result | incorrect edges removed | correct edges lost |
|---|---|---|---|
| accept everything | 278/300 instances | 0.0% | 0.0% |
| baseline: independent greedy by score | 0/300 | 73.3% | 9.8% |
| E5: max-score acyclic subset | 0/300 | 74.8% | 8.7% |

- E5 is only a small improvement over greedy (about 1.5 points more wrong edges removed,
  1.1 points fewer correct edges lost); its total score is higher in 32 of 300 instances.
- Wrong edges that are consistent with the rest of the graph cannot be detected by any acyclicity constraint (289 of 1147 stayed).
- Exactness: where every component was within the exact limit, E5 matched the MILP optimum in 227 instances (max gap 0.0).
  61 instances had a component above the limit and used the greedy fallback, which can be suboptimal (max observed gap 0.14 over 5 checked).
- E5 is **off by default** (`configs/phase6.json`) and is not wired into the pipeline.

## 4. What the real corpus shows
510 emails were replayed through Phases 3-5: **0 dependency proposals**, 7 unmatched-endpoint flags, 1 self-dependency flag.
Labelled DEPENDS_ON examples: 4 train / 0 validation / 3 test, all TASK->EVENT (not producible by the 3-class entity model). Any graph shown in a demo is **scripted** and must be labelled so; live mode will currently produce few or no edges.

## Limitations
- No semantic evaluation of dependency extraction is possible with the available data.
- Timing conflicts only compare resolved dates and only warn; nothing is inferred from date order.
- EVENT / external prerequisite nodes are unsupported; edges join tasks only.
- Rendering and layout are Phase 7. `layer` is a hint only.
- The graph is rebuilt per request, fine at hundreds of nodes and untested beyond that.
- The MILP cross-check prints harmless HiGHS solver messages to the console.
