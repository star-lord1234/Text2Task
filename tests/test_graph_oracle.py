"""Random edit sequences checked against independent oracles (separate DFS / Kahn / naive state code)."""
import random
import unittest

from src.graph.graph_builder import WorkflowGraph, make_edge_id
from src.graph.graph_editor import GraphEditor
from src.graph.serialize import to_frontend
from src.graph.workflow_state import compute_states
from src.reconciliation.models import Task
from src.reconciliation.store import TaskStore

WS = "w"
STATUSES = ["open", "in_progress", "completed", "cancelled"]


def clock():
    n = {"i": 0}

    def c():
        n["i"] += 1
        return f"2026-11-11T{n['i'] // 3600:02d}:{(n['i'] // 60) % 60:02d}:{n['i'] % 60:02d}+00:00"
    return c


def reaches(adj, a, b):
    seen, stack = set(), [a]
    while stack:
        x = stack.pop()
        if x == b:
            return True
        if x in seen:
            continue
        seen.add(x)
        stack.extend(adj.get(x, ()))
    return False


def kahn(nodes, edges):
    indeg = {n: 0 for n in nodes}
    for _, v in edges:
        indeg[v] += 1
    layer = {n: 0 for n in nodes}
    queue = [n for n in nodes if indeg[n] == 0]
    done = 0
    while queue:
        x = queue.pop()
        done += 1
        for u, v in edges:
            if u == x:
                layer[v] = max(layer[v], layer[x] + 1)
                indeg[v] -= 1
                if indeg[v] == 0:
                    queue.append(v)
    return done == len(nodes), layer


def oracle_states(status, edges):
    preds = {t: [u for u, v in edges if v == t] for t in status}
    out = {}
    for t, st in status.items():
        if st in ("completed", "cancelled"):
            out[t] = ("done" if st == "completed" else "cancelled", [], [])
            continue
        inc = sorted(p for p in preds[t] if status[p] in ("open", "in_progress"))
        can = sorted(p for p in preds[t] if status[p] == "cancelled")
        out[t] = ("blocked" if inc else "blocked_cancelled_prereq" if can else "ready", inc, can)
    return out


def num(t):
    return int(t.split("-")[1])


class Fuzz:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.n = self.rng.randint(3, 9)
        self.store = TaskStore(":memory:", clock=clock())
        self.status = {}
        with self.store.transaction():
            for _ in range(self.n):
                tid = self.store.next_task_id(WS)
                st = self.rng.choice(STATUSES)
                self.status[tid] = st
                self.store.insert_task(Task(tid, WS, "th", tid, status=st))
        self.editor = GraphEditor(self.store)
        self.accepted: set[tuple[str, str]] = set()      # (prerequisite, dependent), maintained by the oracle
        self.held: set[tuple[str, str]] = set()

    def step(self):
        ids = list(self.status) + ["T-99"]
        if self.accepted and self.rng.random() < 0.2:
            pre, dep = self.rng.choice(sorted(self.accepted))
            self.editor.remove_dependency(WS, make_edge_id(WS, dep, pre), "fuzz")
            self.accepted.discard((pre, dep))
            self.held.add((pre, dep))
            return
        pre, dep = self.rng.choice(ids), self.rng.choice(ids)
        adj = {}
        for u, v in self.accepted:
            adj.setdefault(u, []).append(v)
        if pre == dep:
            want = "SELF"
        elif pre not in self.status or dep not in self.status:
            want = "UNKNOWN_ENDPOINT"
        elif (pre, dep) in self.accepted:
            want = "DUPLICATE"
        elif reaches(adj, dep, pre):
            want = "CYCLE"
        else:
            want = "OK"
        r = self.editor.add_dependency(WS, pre, dep, "fuzz")
        assert r["code"] == want, f"{pre}->{dep}: got {r['code']}, oracle says {want}"
        if want == "OK":
            self.accepted.add((pre, dep)); self.held.discard((pre, dep))
        elif want != "DUPLICATE":
            self.held.add((pre, dep))

    def check(self):
        g = WorkflowGraph.from_store(self.store, WS)
        assert {(e.prerequisite, e.dependent) for e in g.accepted()} == self.accepted
        assert g.acyclic
        ok, layer = kahn(list(self.status), sorted(self.accepted))
        assert ok, "oracle says the accepted set has a cycle"
        order = g.topological_order()
        pos = {t: i for i, t in enumerate(order)}
        assert all(pos[u] < pos[v] for u, v in self.accepted), "topological order violates an edge"
        assert g.layers() == layer, "layers differ from the longest-path oracle"
        states = compute_states(g)
        for t, (d, inc, can) in oracle_states(self.status, self.accepted).items():
            s = states[t]
            assert (s.derived, s.blocked_by, s.cancelled_prereqs) == (d, inc, can), f"{t}: {(s.derived, s.blocked_by, s.cancelled_prereqs)} vs {(d, inc, can)}"
        odict = oracle_states(self.status, self.accepted)
        for t, s in states.items():
            if s.derived == "blocked":
                anc = {a for a in self.status if a != t and reaches(_adj(self.accepted), a, t)}
                assert s.root_blockers == sorted((a for a in anc if odict[a][0] in ("ready", "blocked_cancelled_prereq")), key=num)
        # rejected/held edges never block
        assert len(g.held()) >= len({e for e in self.held if e[0] in self.status and e[1] in self.status}) - 0
        d = to_frontend(g)
        assert d["meta"]["acyclic"] and d["meta"]["accepted_edges"] == len(self.accepted)


def _adj(edges):
    out = {}
    for u, v in edges:
        out.setdefault(u, []).append(v)
    return out


class OracleTests(unittest.TestCase):
    def test_random_edit_sequences_agree_with_the_oracles(self):
        steps = 0
        for seed in range(60):
            with self.subTest(seed=seed):
                f = Fuzz(seed)
                for _ in range(35):
                    f.step()
                    f.check()
                    steps += 1
        self.assertEqual(steps, 60 * 35)

    def test_oracle_is_not_vacuous(self):
        accepted = held = removed = 0
        for seed in range(60):
            f = Fuzz(seed)
            for _ in range(35):
                f.step()
            accepted += len(f.accepted)
            held += len(f.held)
        self.assertGreater(accepted, 100)
        self.assertGreater(held, 40)


if __name__ == "__main__":
    unittest.main()
