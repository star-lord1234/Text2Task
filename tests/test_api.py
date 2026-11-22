"""API tests (Phase 7). Real reconciler/graph; model predictors are fakes so no torch is needed. Live-mode honesty is tested explicitly."""
import json
import re
import unittest
import warnings

warnings.filterwarnings("ignore")
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.config import Settings
from src.api.services.model_registry import ModelRegistry


class FakeEntity:
    device = "fake"

    def predict(self, text):
        out = []
        for i, (typ, pat) in enumerate((("PERSON", r"^[A-Z][a-z]+(?=,)"), ("TASK", r"(?<=please )[a-z ]+?(?= by| once|\.)"), ("TEMPORAL", r"by \w+"))):
            m = re.search(pat, text)
            if m:
                out.append({"id": f"fe{i}", "type": typ, "start": m.start(), "end": m.end(), "text": m.group(0), "confidence": 0.9})
        return out


class FakeRelation:
    version = "fake-relations"
    device = "fake"

    def predict(self, text, entities):
        by = {e["type"]: e for e in entities}
        rels = []
        if "TASK" in by and "PERSON" in by:
            rels.append({"source_id": by["TASK"]["id"], "target_id": by["PERSON"]["id"], "label": "ASSIGNED_TO", "score": 0.97, "provenance": "neural", "model_version": self.version})
        if "TASK" in by and "TEMPORAL" in by:
            rels.append({"source_id": by["TASK"]["id"], "target_id": by["TEMPORAL"]["id"], "label": "DUE_ON", "score": 0.95, "provenance": "neural", "model_version": self.version})
        return {"relations": rels, "no_link": [], "unrepresentable": []}


def make_client(models=None, **kw):
    settings = Settings(db_path=":memory:", load_models=False, **kw)
    registry = None
    if models == "fake":
        registry = ModelRegistry(settings, entity_factory=lambda p: FakeEntity(), relation_factory=lambda p: FakeRelation())
    app = create_app(settings, registry)
    return TestClient(app)


def reviewer(s, fallback="riya"):
    """The person a suggestion lands on (only they may accept it); anyone when nobody in particular is affected."""
    return s["reviewer_ids"][0] if s.get("reviewer_ids") else fallback


def accept_all(c, actor=None, skip_no_action=True):
    out = []
    for s in c.get("/api/suggestions").json():
        if skip_no_action and s["operation"] == "NO_ACTION":
            continue
        r = c.post(f"/api/suggestions/{s['id']}/accept", json={"actor_id": actor or reviewer(s)})
        out.append(r)
    return out


def logical_state(c):
    """Everything a user can see, minus nothing: tasks, suggestions, graph, messages, history."""
    w = c.get("/api/workspace").json()
    hist = {t["id"]: c.get(f"/api/tasks/{t['id']}/history").json() for t in w["tasks"]}
    return json.dumps({"tasks": w["tasks"], "sugg": w["suggestions"], "msgs": w["messages"], "graph": c.get("/api/dependencies").json(), "hist": hist,
                       "scenario": w["scenario"]}, sort_keys=True, default=str)


class CapabilitiesTests(unittest.TestCase):
    def test_models_disabled_is_reported_honestly(self):
        with make_client() as c:
            cap = c.get("/api/system/capabilities").json()
            self.assertEqual(cap["entity_model"]["status"], "disabled")
            self.assertFalse(cap["entity_model"]["available"])
            self.assertFalse(cap["modes"]["live"])
            self.assertTrue(cap["modes"]["scripted"])
            self.assertFalse(cap["rule_fallback"]["enabled"])           # off by default
            self.assertTrue(cap["entity_model"]["provisional"])
            self.assertIn("SILVER", cap["entity_model"]["provenance"])

    def test_fake_models_loaded_is_reported(self):
        with make_client("fake") as c:
            cap = c.get("/api/system/capabilities").json()
            self.assertTrue(cap["modes"]["live"])
            self.assertEqual(cap["relation_model"]["version"], "fake-relations")

    def test_missing_checkpoint_is_a_failed_status_not_a_crash(self):
        settings = Settings(db_path=":memory:", load_models=True, entity_model_dir=Settings().entity_model_dir.parent / "nope", relation_model_dir=Settings().relation_model_dir.parent / "nope")
        with TestClient(create_app(settings)) as c:
            cap = c.get("/api/system/capabilities").json()
            self.assertEqual(cap["entity_model"]["status"], "failed")
            self.assertIn("checkpoint not found", cap["entity_model"]["error"])
            self.assertFalse(cap["modes"]["live"])


class LiveModeHonestyTests(unittest.TestCase):
    MSG = {"sender_id": "riya", "recipient_ids": ["bianca"], "text": "Bianca, please prepare the report by Friday.", "mode": "live", "created_at": "2026-11-11T09:30:00-06:00"}

    def test_live_with_unavailable_models_fails_visibly_and_creates_nothing(self):
        with make_client() as c:
            r = c.post("/api/messages", json=self.MSG)
            self.assertEqual(r.status_code, 201)
            a = r.json()
            self.assertEqual(a["message"]["status"], "analysis_failed")
            self.assertIn("Model unavailable", a["error"])
            self.assertEqual(a["proposals"], [])
            self.assertIsNone(a["entities"])
            w = c.get("/api/workspace").json()
            self.assertEqual((w["tasks"], w["suggestions"]), ([], []))
            self.assertEqual(len(w["messages"]), 1)                      # the message itself is kept

    def test_scripted_output_never_substitutes_for_failed_live(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load")                              # scripted fixtures exist and are loaded...
            a = c.post("/api/messages", json={**self.MSG, "text": "Anushree, please prepare the cleaned dataset by Thursday."}).json()
            self.assertEqual(a["message"]["status"], "analysis_failed")  # ...but are never used to answer a live message
            self.assertEqual(a["proposals"], [])
            self.assertNotIn("scripted", json.dumps(a["provenance"]))

    def test_retry_after_models_become_available_does_not_duplicate(self):
        with make_client() as c:
            mid = c.post("/api/messages", json=self.MSG).json()["message"]["id"]
            rt = c.app.state.rt
            rt.registry = ModelRegistry(rt.settings, entity_factory=lambda p: FakeEntity(), relation_factory=lambda p: FakeRelation())
            rt.registry.load()
            first = c.post(f"/api/messages/{mid}/retry").json()
            self.assertEqual(first["message"]["status"], "analysed")
            second = c.post(f"/api/messages/{mid}/retry").json()         # idempotent: no new proposals
            self.assertEqual([p["id"] for p in first["proposals"]], [p["id"] for p in second["proposals"]])
            accept_all(c)
            self.assertEqual(len(c.get("/api/tasks").json()), 1)

    def test_live_with_fake_neural_models_has_neural_provenance_and_labelled_rules(self):
        with make_client("fake") as c:
            a = c.post("/api/messages", json=self.MSG).json()
            self.assertEqual(a["message"]["status"], "analysed")
            self.assertEqual(a["provenance"]["entities"], "neural")
            self.assertEqual(a["provenance"]["relations"], "neural")
            self.assertEqual(a["provenance"]["reconciliation"], "rule (cue-based)")   # never claimed as neural
            self.assertTrue(all(r["provenance"] == "neural" for r in a["relations"]))
            self.assertEqual(a["model_versions"]["relations"], "fake-relations")
            create = [p for p in a["proposals"] if p["operation"] == "CREATE_TASK"][0]
            self.assertEqual(create["source_kind"], "neural")
            self.assertEqual(create["provenance"]["reconciliation"], "rule (cue-based)")
            self.assertEqual(a["classes_not_produced"], ["GROUP", "EVENT", "ARTIFACT"])
            accept_all(c)
            (t,) = c.get("/api/tasks?assignee_id=bianca").json()
            self.assertEqual((t["title"], t["due"]["value"]), ("prepare the report", "2026-11-13"))

    def test_rule_fallback_is_opt_in_and_labelled(self):
        with make_client() as c:
            r = c.put("/api/settings", json={"allow_rule_fallback": True}).json()
            self.assertTrue(r["allow_rule_fallback"])
            a = c.post("/api/messages", json=self.MSG).json()
            self.assertEqual(a["message"]["status"], "analysed")
            self.assertEqual(a["provenance"]["entities"], "rule")
            self.assertEqual(a["provenance"]["relations"], "rule")
            self.assertIn("opt-in fallback", a["model_versions"]["entities"])
            self.assertTrue(c.get("/api/system/capabilities").json()["rule_fallback"]["enabled"])

    def test_scripted_free_text_has_no_extraction_and_is_not_invented(self):
        with make_client() as c:
            a = c.post("/api/messages", json={**self.MSG, "mode": "scripted"}).json()
            self.assertEqual(a["message"]["status"], "no_extraction")
            self.assertEqual(a["proposals"], [])
            self.assertEqual(c.get("/api/tasks").json(), [])

    def test_naive_message_time_means_workspace_local_time(self):
        with make_client("fake") as c:
            c.put("/api/settings", json={"timezone": "America/Chicago"})
            a = c.post("/api/messages", json={**self.MSG, "created_at": "2026-11-11T09:30"}).json()
            self.assertEqual(a["message"]["created_at"], "2026-11-11T09:30:00-06:00")
            self.assertEqual(c.post("/api/messages", json={**self.MSG, "created_at": "yesterday"}).status_code, 422)

    def test_unknown_participant_is_rejected(self):
        with make_client() as c:
            r = c.post("/api/messages", json={**self.MSG, "sender_id": "nobody"})
            self.assertEqual(r.status_code, 404)
            self.assertEqual(r.json()["code"], "NOT_FOUND")


class ScenarioAFlowTests(unittest.TestCase):
    def run_a(self, c):
        c.post("/api/scenarios/A/load")
        for _ in range(5):
            c.post("/api/scenarios/step")
            accept_all(c)

    def test_scenario_a_matches_its_expectations_and_ends_in_the_right_state(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load")
            for k in range(1, 6):
                c.post("/api/scenarios/step")
                m = c.get("/api/workspace").json()["messages"][-1]
                self.assertTrue(m["matches_expectation"], (k, [p["operation"] for p in m["proposals"]], m["expected"]))
                self.assertEqual(m["mode"], "scripted")
                accept_all(c)
            tasks = {t["id"]: t for t in c.get("/api/tasks").json()}
            self.assertEqual(set(tasks), {"T-1", "T-2"})                  # the acknowledgement created NO duplicate
            self.assertEqual((tasks["T-1"]["owner_id"], tasks["T-1"]["ui_status"], tasks["T-1"]["due"]["value"]), ("anushree", "done", "2026-11-12"))
            self.assertEqual((tasks["T-2"]["owner_id"], tasks["T-2"]["ui_status"]), ("bianca", "in_progress"))
            g = c.get("/api/dependencies").json()
            self.assertEqual([(e["source"], e["target"], e["kind"]) for e in g["edges"]], [("T-1", "T-2", "accepted")])   # prerequisite -> dependent

    def test_dependent_is_blocked_until_the_prerequisite_is_done(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load")
            for _ in range(3):
                c.post("/api/scenarios/step")
                accept_all(c)
            t = {x["id"]: x for x in c.get("/api/tasks").json()}
            self.assertEqual(t["T-2"]["ui_status"], "blocked")
            self.assertEqual(t["T-2"]["blocked_by"], ["T-1"])
            self.assertEqual(c.get("/api/impact?task_id=T-1&status=completed").json()["became_ready"], ["T-2"])
            c.post("/api/scenarios/step")
            accept_all(c)
            self.assertEqual({x["id"]: x["ui_status"] for x in c.get("/api/tasks").json()}["T-2"], "todo")

    def test_review_mode_nothing_changes_until_accepted(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load")
            c.post("/api/scenarios/step")
            self.assertEqual(c.get("/api/tasks").json(), [])
            (s,) = c.get("/api/suggestions").json()
            self.assertEqual((s["kind"], s["status"]), ("create_task", "pending"))
            self.assertIn("Anushree", s["summary"])
            self.assertEqual(s["provenance"]["extraction"], "scripted")
            self.assertEqual(s["provenance"]["reconciliation"], "rule (cue-based)")
            self.assertTrue(s["evidence"]["sentence"].startswith("Anushree, please"))

    def test_accept_dependency_before_its_task_is_refused_with_409(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load")
            for _ in range(2):
                c.post("/api/scenarios/step")
                accept_all(c)
            c.post("/api/scenarios/step")
            dep = [s for s in c.get("/api/suggestions").json() if s["operation"] == "ADD_DEPENDENCY"][0]
            self.assertTrue(dep["must_accept_first"])
            r = c.post(f"/api/suggestions/{dep['id']}/accept", json={"actor_id": reviewer(dep)})
            self.assertEqual((r.status_code, r.json()["code"]), (409, "PREREQUISITE_PENDING"))

    def test_persona_switching_is_client_state_only(self):
        with make_client() as c:
            self.run_a(c)
            before = logical_state(c)
            for who in ("riya", "anushree", "bianca"):
                c.get(f"/api/tasks?assignee_id={who}")
                c.get("/api/workspace")
            self.assertEqual(before, logical_state(c))
            self.assertEqual([t["id"] for t in c.get("/api/tasks?assignee_id=bianca").json()], ["T-2"])
            self.assertEqual([t["id"] for t in c.get("/api/tasks?assignee_id=anushree").json()], ["T-1"])


class ScenarioControlTests(unittest.TestCase):
    def test_previous_step_rebuilds_the_exact_earlier_state(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load")
            states = {}
            for k in range(1, 6):
                c.post("/api/scenarios/step")
                accept_all(c)
                states[k] = logical_state(c)
            for k in (4, 3, 2, 1):
                c.post("/api/scenarios/previous")
                self.assertEqual(logical_state(c), states[k], f"state after previous -> step {k} differs")
            c.post("/api/scenarios/previous")
            self.assertEqual(c.get("/api/workspace").json()["scenario"]["step"], 0)
            self.assertEqual(c.get("/api/tasks").json(), [])

    def test_replay_after_previous_is_identical(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load")
            for _ in range(5):
                c.post("/api/scenarios/step"); accept_all(c)
            final = logical_state(c)
            c.post("/api/scenarios/reset")
            for _ in range(5):
                c.post("/api/scenarios/step"); accept_all(c)
            self.assertEqual(final, logical_state(c))                   # deterministic ids, timestamps and history

    def test_play_all_uses_a_labelled_simulated_reviewer(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load")
            st = c.post("/api/scenarios/play").json()
            self.assertEqual((st["step"], st["total"]), (5, 5))
            hist = c.get("/api/tasks/T-1/history").json()
            self.assertEqual({h["actor"] for h in hist}, {"simulated-reviewer"})
            self.assertEqual([t["ui_status"] for t in c.get("/api/tasks").json()], ["done", "in_progress"])

    def test_previous_keeps_recorded_review_decisions(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load")
            c.post("/api/scenarios/step")
            (s,) = c.get("/api/suggestions").json()
            c.post(f"/api/suggestions/{s['id']}/dismiss", json={"actor_id": "riya", "reason": "not needed"})
            c.post("/api/scenarios/step")
            before = logical_state(c)
            c.post("/api/scenarios/step")
            c.post("/api/scenarios/previous")
            self.assertEqual(logical_state(c), before)
            self.assertEqual(c.get("/api/suggestions?status=dismissed").json()[0]["resolution_note"], "not needed")

    def test_graph_snapshot_by_step(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load")
            for _ in range(4):
                c.post("/api/scenarios/step"); accept_all(c)
            self.assertEqual(len(c.get("/api/dependencies?step=2").json()["edges"]), 0)
            self.assertEqual(len(c.get("/api/dependencies?step=3").json()["edges"]), 1)
            self.assertEqual(c.get("/api/dependencies?step=3").json()["nodes"][1]["derived_state"], "blocked")
            self.assertEqual(c.get("/api/dependencies?step=4").json()["nodes"][1]["derived_state"], "ready")

    def test_workspace_reset_wipes_state_but_keeps_participants_and_history_stays_append_only(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load")
            for _ in range(3):
                c.post("/api/scenarios/step"); accept_all(c)
            c.put("/api/participants", json={"id": "riya", "name": "Riya S.", "role": "Lead", "color": "#6c5ce7"})
            w = c.post("/api/workspace/reset").json()
            self.assertEqual((w["tasks"], w["messages"], w["suggestions"]), ([], [], []))
            self.assertEqual([p["name"] for p in w["participants"]], ["Riya S.", "Anushree", "Bianca"])
            self.assertIsNone(w["scenario"]["scenario_id"])
            import sqlite3
            rt = c.app.state.rt
            with rt.store.transaction():
                rt.store.insert_task(__import__("src.reconciliation.models", fromlist=["Task"]).Task("T-9", "default", "t", "x"))
                rt.store.append_history("default", "T-9", operation="X", field="status", before=None, after="open", actor="a", source_kind="human")
            with self.assertRaises(sqlite3.DatabaseError):
                rt.store.conn.execute("DELETE FROM history")             # immutability is back in force after the reset


class ReviewAndEditTests(unittest.TestCase):
    def setUp(self):
        self.cm = make_client()
        self.c = self.cm.__enter__()
        self.c.post("/api/scenarios/B/load")
        self.c.post("/api/scenarios/step")
        accept_all(self.c)

    def tearDown(self):
        self.cm.__exit__(None, None, None)

    def test_proposed_deadline_change_does_not_change_the_due_date_until_confirmed(self):
        c = self.c
        c.post("/api/scenarios/step")
        accept_all(c)
        t = c.get("/api/tasks/T-1").json()
        self.assertEqual(t["due"]["value"], "2026-11-12")                 # Thursday still active
        self.assertEqual(t["pending_changes"]["due"]["value"]["value"], "2026-11-13")
        c.post("/api/scenarios/step")
        accept_all(c, actor="riya")
        t = c.get("/api/tasks/T-1").json()
        self.assertEqual((t["due"]["value"], t["pending_changes"], t["version"]), ("2026-11-13", {}, 3))   # confirm = one version bump, two history events
        ops = [h["operation"] for h in t["history"]]
        self.assertEqual(ops, ["CREATE_TASK", "PROPOSE_DUE_DATE_CHANGE", "CONFIRM_DUE_DATE_CHANGE", "CONFIRM_DUE_DATE_CHANGE"])

    def test_manual_edit_is_a_human_edit_and_version_checked(self):
        c = self.c
        t = c.get("/api/tasks/T-1").json()
        r = c.patch("/api/tasks/T-1", json={"actor_id": "riya", "expected_version": t["version"], "changes": {"title": "send the Q4 model report", "due_text": "next Monday"}})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["title"], "send the Q4 model report")
        self.assertEqual(body["due"]["value"], "2026-11-16")
        self.assertEqual([(h["source_kind"], h["operation"]) for h in body["history"][-2:]], [("human", "MANUAL_EDIT")] * 2)
        stale = c.patch("/api/tasks/T-1", json={"actor_id": "riya", "expected_version": t["version"], "changes": {"title": "x"}})
        self.assertEqual((stale.status_code, stale.json()["code"]), (409, "STALE_VERSION"))
        self.assertEqual(c.get("/api/tasks/T-1").json()["title"], "send the Q4 model report")      # nothing written

    def test_error_shape_and_unknown_ids(self):
        c = self.c
        r = c.post("/api/suggestions/P-nope/accept", json={"actor_id": "riya"})
        self.assertEqual((r.status_code, set(r.json())), (404, {"code", "message", "details"}))
        self.assertEqual(c.get("/api/tasks/T-99").status_code, 404)
        self.assertEqual(c.patch("/api/tasks/T-1", json={"actor_id": "riya", "expected_version": 1, "changes": {"owner_id": "nobody"}}).status_code, 404)

    def test_accept_twice_is_idempotent_and_dismissed_cannot_be_accepted(self):
        c = self.c
        c.post("/api/scenarios/step")
        (s,) = c.get("/api/suggestions").json()
        a = c.post(f"/api/suggestions/{s['id']}/accept", json={"actor_id": reviewer(s), "idempotency_key": "k"}).json()
        b = c.post(f"/api/suggestions/{s['id']}/accept", json={"actor_id": reviewer(s), "idempotency_key": "k"}).json()
        self.assertTrue(b["result"].get("replayed"))
        self.assertEqual(a["result"]["version"], b["result"]["version"])
        c.post("/api/scenarios/step")
        (s2,) = c.get("/api/suggestions").json()
        c.post(f"/api/suggestions/{s2['id']}/dismiss", json={"actor_id": reviewer(s2)})
        r = c.post(f"/api/suggestions/{s2['id']}/accept", json={"actor_id": reviewer(s2)})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "ALREADY_RESOLVED"))

    def test_edit_before_accept_resolves_an_unresolved_owner(self):
        with make_client("fake") as c:
            a = c.post("/api/messages", json={"sender_id": "riya", "recipient_ids": ["bianca", "anushree"], "text": "Hey all, please prepare the plan by Friday.", "mode": "live",
                                              "created_at": "2026-11-11T09:30:00-06:00"}).json()
            (s,) = [p for p in a["proposals"] if p["operation"] == "CREATE_TASK"]
            self.assertIn("assignee", s["unresolved"])
            r = c.post(f"/api/suggestions/{s['id']}/accept", json={"actor_id": "riya", "edits": {"owner_id": "anushree"}})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(c.get("/api/tasks/T-1").json()["owner_id"], "anushree")
            self.assertEqual(c.get("/api/tasks/T-1/history").json()[0]["source_kind"], "human")      # edited -> human provenance


class DependencyApiTests(unittest.TestCase):
    def test_manual_edges_cycle_held_and_history(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load")
            for _ in range(3):
                c.post("/api/scenarios/step"); accept_all(c)
            add = c.post("/api/dependencies", json={"actor_id": "riya", "prerequisite_task_id": "T-2", "dependent_task_id": "T-1"}).json()
            self.assertEqual((add["decision"]["status"], add["decision"]["code"]), ("rejected", "CYCLE"))
            self.assertEqual(add["decision"]["cycle_path"], ["T-2", "T-1", "T-2"])
            g = add["graph"]
            self.assertTrue(g["meta"]["acyclic"])
            self.assertEqual([e["kind"] for e in g["edges"]], ["accepted", "held"])          # held edge stays visible, never dropped
            eid = [e["id"] for e in g["edges"] if e["kind"] == "accepted"][0]
            rm = c.delete(f"/api/dependencies/{eid}?actor_id=riya&reason=wrong").json()
            self.assertEqual(rm["graph"]["meta"]["accepted_edges"], 0)
            re_ = c.post(f"/api/dependencies/{[e['id'] for e in rm['graph']['edges'] if 'CYCLE' in e['reason']][0]}/reconsider", json={"actor_id": "riya"}).json()
            self.assertEqual(re_["decision"]["status"], "accepted")                          # the cycle is gone, so the held edge can now be accepted

    def test_message_order_creates_no_edge(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load")
            for _ in range(2):
                c.post("/api/scenarios/step"); accept_all(c)
            self.assertEqual(c.get("/api/dependencies").json()["edges"], [])

    def test_impact_validates_input(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load")
            c.post("/api/scenarios/step"); accept_all(c)
            self.assertEqual(c.get("/api/impact?task_id=T-1&status=bogus").status_code, 422)
            self.assertEqual(c.get("/api/impact?task_id=T-9&status=completed").status_code, 404)


class EmptyStateTests(unittest.TestCase):
    def test_empty_workspace_and_graph(self):
        with make_client() as c:
            w = c.get("/api/workspace").json()
            self.assertEqual((w["tasks"], w["messages"], w["suggestions"]), ([], [], []))
            g = c.get("/api/dependencies").json()
            self.assertEqual((g["nodes"], g["edges"], g["meta"]["acyclic"]), ([], [], True))
            self.assertEqual(len(w["participants"]), 3)

    def test_single_node_graph(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load"); c.post("/api/scenarios/step"); accept_all(c)
            g = c.get("/api/dependencies").json()
            self.assertEqual((len(g["nodes"]), len(g["edges"])), (1, 0))


if __name__ == "__main__":
    unittest.main()


class ScenarioLibraryTests(unittest.TestCase):
    def play_steps(self, c, sid, steps, accept=True):
        c.post(f"/api/scenarios/{sid}/load")
        out = []
        for k in range(1, steps + 1):
            c.post("/api/scenarios/step")
            m = c.get("/api/workspace").json()["messages"][-1]
            self.assertTrue(m["matches_expectation"], (sid, k, [p["operation"] for p in m["proposals"]], m["expected"]))
            out.append(m)
            if accept:
                for sug in c.get("/api/suggestions").json():
                    if sug["operation"] != "NO_ACTION" and not sug["requires_referent"] and not sug["unresolved"]:
                        c.post(f"/api/suggestions/{sug['id']}/accept", json={"actor_id": reviewer(sug)})
        return out

    def test_listing(self):
        with make_client() as c:
            ids = [s["id"] for s in c.get("/api/scenarios").json()["scenarios"]]
            self.assertEqual(ids, ["A", "B", "C", "D", "E", "F"])

    def test_scenario_b_to_e_match_their_scripted_expectations(self):
        with make_client() as c:
            self.play_steps(c, "B", 3)
            self.play_steps(c, "D", 3)
            self.play_steps(c, "E", 4)

    def test_scenario_d_historical_and_status_messages_create_nothing(self):
        with make_client() as c:
            msgs = self.play_steps(c, "D", 3)
            self.assertEqual([m["proposals"][0]["operation"] for m in msgs[:2]], ["NO_ACTION", "NO_ACTION"])
            self.assertEqual([t["title"] for t in c.get("/api/tasks").json()], ["investigate why the server went down"])
            self.assertEqual(c.get("/api/tasks").json()[0]["owner_id"], "anushree")

    def test_scenario_e_reverse_dependency_is_held_and_the_accepted_graph_stays_valid(self):
        with make_client() as c:
            self.play_steps(c, "E", 3)
            c.post("/api/scenarios/step")
            (s,) = [x for x in c.get("/api/suggestions").json() if x["operation"] == "ADD_DEPENDENCY"]
            r = c.post(f"/api/suggestions/{s['id']}/accept", json={"actor_id": reviewer(s)}).json()
            self.assertEqual(r["result"]["edge_status"], "rejected")            # surfaced to the UI as 'held for review'
            self.assertTrue(r["result"]["reason"].startswith("CYCLE:"))
            g = c.get("/api/dependencies").json()
            self.assertTrue(g["meta"]["acyclic"])
            self.assertEqual(sorted((e["source"], e["target"], e["kind"]) for e in g["edges"]), [("T-1", "T-2", "accepted"), ("T-2", "T-1", "held")])
            self.assertEqual({n["id"]: n["derived_state"] for n in g["nodes"]}, {"T-1": "ready", "T-2": "blocked"})   # held edge blocks nothing

    def test_scenario_c_ambiguity_shows_options_and_changes_nothing_until_chosen(self):
        with make_client() as c:
            c.post("/api/scenarios/C/load")
            for _ in range(2):
                c.post("/api/scenarios/step")
                (s,) = c.get("/api/suggestions").json()
                self.assertIn("assignee", s["unresolved"])                         # nobody is named: not invented
                r = c.post(f"/api/suggestions/{s['id']}/accept", json={"actor_id": "riya", "edits": {"owner_id": None}})
                self.assertEqual(r.status_code, 200)
            c.post("/api/scenarios/step")
            (s,) = c.get("/api/suggestions").json()
            self.assertEqual((s["kind"], s["requires_referent"], s["unresolved"]), ("clarification", True, ["task"]))
            self.assertEqual({r["task_id"] for r in s["match"]["ranked"]}, {"T-1", "T-2"})
            self.assertTrue(all(t["owner_id"] is None for t in c.get("/api/tasks").json()))   # nothing guessed
            no = c.post(f"/api/suggestions/{s['id']}/accept", json={"actor_id": reviewer(s)})
            self.assertEqual((no.status_code, no.json()["code"]), (422, "REFERENT_REQUIRED"))
            ok = c.post(f"/api/suggestions/{s['id']}/accept", json={"actor_id": "anushree", "edits": {"task_id": "T-1"}})
            self.assertEqual(ok.status_code, 200)
            owners = {t["id"]: t["owner_id"] for t in c.get("/api/tasks").json()}
            self.assertEqual(owners, {"T-1": "anushree", "T-2": None})


class EvaluationEndpointTests(unittest.TestCase):
    def test_reports_saved_results_unchanged_and_with_limitations(self):
        import json as _json
        from src.api.config import ROOT
        with make_client() as c:
            d = c.get("/api/evaluation").json()
        saved = _json.loads((ROOT / "results/relation_extraction/evaluation/validation_markers_sqrt.json").read_text())
        self.assertEqual(d["relations"]["mode_a"]["neural"]["micro_f1"], saved["mode_A_reference_spans"]["neural"]["micro_positive"]["f1"])
        self.assertIn("SILVER", d["provenance"])
        saved_e = _json.loads((ROOT / "results/entity_extraction/entity_v2_three_class/epoch3_sqrt_weighted/metrics.json").read_text())
        self.assertEqual(d["entities"]["per_type"]["PERSON"]["f1"], saved_e["silver_v2_provisional_per_entity"]["PERSON"]["f1-score"])
        self.assertEqual(d["entities"]["overall"]["f1"], saved_e["silver_v2_provisional_overall"]["f1"])
        self.assertTrue(d["relations"]["limitations"])
        self.assertEqual([p["id"] for p in d["phases"]], ["phase4", "phase5", "phase6"])
        self.assertTrue(all(p["limitations"] for p in d["phases"]))

    def test_missing_results_are_reported_missing_not_invented(self):
        import tempfile
        from pathlib import Path
        from src.api.services.evaluation import build_evaluation
        d = build_evaluation(Path(tempfile.mkdtemp()))
        self.assertFalse(d["entities"]["available"])
        self.assertFalse(d["relations"]["available"])
        self.assertEqual(len(d["missing"]), 5)
        self.assertTrue(all(not p["available"] for p in d["phases"]))


class CannedEntity:
    """Stub entity model returning fixed (type, substring) spans per text: fragmented on purpose, like the real checkpoint."""
    device = "fake"

    def __init__(self, canned):
        self.canned = canned

    def predict(self, text):
        out = []
        for i, (typ, sub) in enumerate(self.canned.get(text, [])):
            a = text.index(sub)
            out.append({"id": f"pred-e{i}", "type": typ, "start": a, "end": a + len(sub), "text": sub, "confidence": 0.9})
        return out


CANNED = {
    "Bianca, please prepare the report by Friday.": [("PERSON", "Bianca"), ("TASK", "prepare the"), ("TEMPORAL", "by"), ("TEMPORAL", "Friday")],
    "After you clean the dataset, write a report.": [("TASK", "After you"), ("TASK", "write a report")],
    "The server went down yesterday.": [("TEMPORAL", "yesterday")],
}


def refinement_client(preset):
    settings = Settings(db_path=":memory:", load_models=False)
    reg = ModelRegistry(settings, entity_factory=lambda p: CannedEntity(CANNED), relation_factory=lambda p: FakeRelation())
    c = TestClient(create_app(settings, reg))
    c.put("/api/settings", json={"timezone": "America/Chicago", "pipeline_preset": preset})
    return c


def post_live(c, sender, rec, text):
    return c.post("/api/messages", json={"sender_id": sender, "recipient_ids": rec, "text": text, "mode": "live", "created_at": "2026-11-11T09:30:00-06:00"}).json()


class HybridPipelineApiTests(unittest.TestCase):
    def client(self, preset):
        c = refinement_client(preset)
        c.__enter__()                                  # run the app's startup (loads the stub models)
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def test_settings_validate_preset_and_stage_names(self):
        with make_client() as c:
            self.assertEqual(c.put("/api/settings", json={"pipeline_preset": "nope"}).status_code, 422)
            self.assertEqual(c.put("/api/settings", json={"refine_overrides": {"warp_drive": True}}).status_code, 422)
            ok = c.put("/api/settings", json={"pipeline_preset": "refined", "refine_overrides": {"temporal_merge": False}})
            self.assertEqual(ok.status_code, 200)
            pipe = c.get("/api/system/capabilities").json()["pipeline"]
            self.assertEqual(pipe["preset"], "refined+custom")
            self.assertFalse(pipe["config"]["temporal_merge"])
            self.assertEqual({p["name"] for p in pipe["presets"]}, {"neural_only", "neural_plus_linker", "refined", "hybrid", "rule_only"})

    def test_hybrid_keeps_raw_neural_output_next_to_the_refined_output(self):
        c = self.client("hybrid")
        a = post_live(c, "riya", ["bianca"], "Bianca, please prepare the report by Friday.")
        ref = a["refinement"]
        self.assertEqual([e["text"] for e in ref["raw_entities"]], ["Bianca", "prepare the", "by", "Friday"])
        refined = {e["text"]: e["origin"] for e in a["entities"]}
        self.assertEqual(refined, {"Bianca": "neural", "prepare the report": "refined", "by Friday": "refined"})
        self.assertEqual(a["provenance"]["entities"], "neural")
        self.assertEqual(a["provenance"]["entity_refinement"], "rule")
        task = next(e for e in a["entities"] if e["type"] == "TASK")
        self.assertEqual(task["neural_ids"], ["pred-e1"])
        self.assertEqual(task["refinement"][0]["op"], "extend_to_action_phrase")
        (prop,) = [p for p in a["proposals"] if p["operation"] == "CREATE_TASK"]
        self.assertIn("prepare the report", prop["summary"])
        self.assertIn("2026-11-13", prop["summary"] + str(prop))                      # 'by Friday' became a resolved due date
        self.assertEqual(c.get(f"/api/messages/{a['message']['id']}/analysis").json()["refinement"]["raw_entities"], ref["raw_entities"])   # persisted

    def test_neural_only_gives_the_raw_fragments_to_the_reconciler(self):
        c = self.client("neural_only")
        a = post_live(c, "riya", ["bianca"], "Bianca, please prepare the report by Friday.")
        self.assertEqual([e["text"] for e in a["entities"]], ["Bianca", "prepare the", "by", "Friday"])
        self.assertTrue(all(e["origin"] == "neural" for e in a["entities"]))
        (prop,) = [p for p in a["proposals"] if p["operation"] == "CREATE_TASK"]
        self.assertNotIn("report", prop["summary"])                                    # the truncated title the refinement stage repairs

    def test_clause_dependency_is_proposed_and_accepted_through_review(self):
        c = self.client("hybrid")
        a = post_live(c, "riya", ["anushree", "bianca"], "After you clean the dataset, write a report.")
        ops = sorted(p["operation"] for p in a["proposals"])
        self.assertEqual(ops, ["ADD_DEPENDENCY", "CREATE_TASK", "CREATE_TASK"])
        self.assertTrue(all(p["status"] == "pending" for p in a["proposals"]))          # review mode: nothing applied yet
        self.assertEqual(c.get("/api/tasks").json(), [])
        dep = next(p for p in a["proposals"] if p["operation"] == "ADD_DEPENDENCY")
        self.assertEqual(c.post(f"/api/suggestions/{dep['id']}/accept", json={"actor_id": "riya"}).status_code, 409)      # needs its tasks first
        for p in a["proposals"]:
            if p["operation"] == "CREATE_TASK":
                self.assertEqual(c.post(f"/api/suggestions/{p['id']}/accept", json={"actor_id": "riya", "edits": {"owner_id": None}}).status_code, 200)
        self.assertEqual(c.post(f"/api/suggestions/{dep['id']}/accept", json={"actor_id": "riya"}).status_code, 200)
        g = c.get("/api/dependencies").json()
        titles = {t["id"]: t["title"] for t in c.get("/api/tasks").json()}
        (edge,) = g["edges"]
        self.assertEqual((titles[edge["source"]], titles[edge["target"]], edge["kind"]), ("clean the dataset", "write a report", "accepted"))
        rel = [r for r in a["relations"] if r["label"] == "DEPENDS_ON"]
        self.assertEqual([(r["provenance"], r["rule"]) for r in rel], [("rule", "clause:cue_first")])

    def test_neural_only_cannot_build_that_dependency_and_gate_blocks_the_bare_imperative(self):
        c = self.client("neural_only")
        a = post_live(c, "riya", ["anushree", "bianca"], "After you clean the dataset, write a report.")
        self.assertEqual([p["operation"] for p in a["proposals"] if p["operation"] != "NO_ACTION"], [])
        self.assertEqual(c.get("/api/dependencies").json()["edges"], [])

    def test_statements_create_nothing_in_any_preset(self):
        for preset in ("neural_only", "refined", "hybrid"):
            c = self.client(preset)
            a = post_live(c, "riya", ["anushree"], "The server went down yesterday.")
            self.assertEqual([p["operation"] for p in a["proposals"] if p["operation"] != "NO_ACTION"], [], preset)

    def test_rule_only_preset_needs_no_model_and_is_labelled_rule(self):
        c = make_client()                                   # no models at all
        c.put("/api/settings", json={"timezone": "America/Chicago", "pipeline_preset": "rule_only"})
        caps = c.get("/api/system/capabilities").json()
        self.assertTrue(caps["modes"]["live"])
        a = post_live(c, "riya", ["bianca"], "Bianca, please prepare the report by Friday.")
        self.assertIsNone(a["error"])
        self.assertEqual((a["provenance"]["entities"], a["provenance"]["relations"]), ("rule", "rule"))
        self.assertTrue(a["entities"])
        c.put("/api/settings", json={"pipeline_preset": "hybrid"})
        a2 = post_live(c, "riya", ["bianca"], "Bianca, please prepare the report by Friday. ")
        self.assertIn("Model unavailable", a2["error"])      # a neural preset with no model still fails honestly, and never falls back silently

    def test_scripted_mode_is_untouched_by_refinement(self):
        c = make_client()
        c.post("/api/scenarios/A/load")
        c.post("/api/scenarios/step")
        mid = c.get("/api/workspace").json()["messages"][-1]["id"]
        a = c.get(f"/api/messages/{mid}/analysis").json()
        self.assertIsNone(a["refinement"])
        self.assertTrue(all(e.get("origin") is None for e in a["entities"]))


class OpenApiSyncTests(unittest.TestCase):
    def test_docs_openapi_json_matches_the_app(self):
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root / "scripts"))
        import export_openapi
        on_disk = json.loads((root / "docs" / "openapi.json").read_text())
        self.assertEqual(json.loads(json.dumps(export_openapi.schema(), sort_keys=True)), on_disk,
                         "docs/openapi.json is stale: run scripts/export_openapi.py and `pnpm gen:types` in frontend/")


class ReviewerRightsTests(unittest.TestCase):
    """A suggestion is decided by the person it lands on: the assignee accepts their own new task, not the project lead."""

    def test_only_the_assignee_can_accept_their_new_task(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load"); c.post("/api/scenarios/step")          # Riya: "Anushree, please prepare the cleaned dataset"
            (s,) = c.get("/api/suggestions").json()
            self.assertEqual(s["reviewer_ids"], ["anushree"])
            for actor in ("riya", "bianca"):
                r = c.post(f"/api/suggestions/{s['id']}/accept", json={"actor_id": actor})
                self.assertEqual((r.status_code, r.json()["code"]), (403, "NOT_YOUR_REVIEW"))
            self.assertEqual(c.get("/api/workspace").json()["tasks"], [])           # nothing changed
            self.assertEqual(c.post(f"/api/suggestions/{s['id']}/accept", json={"actor_id": "anushree"}).status_code, 200)

    def test_the_author_may_dismiss_a_misread_but_a_bystander_may_not(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load"); c.post("/api/scenarios/step")
            (s,) = c.get("/api/suggestions").json()
            self.assertEqual(c.post(f"/api/suggestions/{s['id']}/dismiss", json={"actor_id": "bianca"}).status_code, 403)
            self.assertEqual(c.post(f"/api/suggestions/{s['id']}/dismiss", json={"actor_id": "riya"}).status_code, 200)

    def test_a_dependency_is_accepted_by_the_owner_of_the_waiting_task(self):
        with make_client() as c:
            c.post("/api/scenarios/A/load")
            for _ in range(3):
                c.post("/api/scenarios/step"); accept_all(c)
            edges = c.get("/api/dependencies").json()["edges"]
            self.assertEqual([(e["source"], e["target"], e["kind"]) for e in edges], [("T-1", "T-2", "accepted")])
            hist = c.get("/api/tasks/T-2/history").json()
            self.assertIn("bianca", {h["actor"] for h in hist})                       # Bianca's task waits, so Bianca accepted it


class ScenarioFTests(unittest.TestCase):
    """The 17-message presenter demo: every step matches its expectation and the final graph shows every dependency shape."""

    def test_full_demo_story(self):
        with make_client() as c:
            c.post("/api/scenarios/F/load")
            for k in range(1, 18):
                c.post("/api/scenarios/step")
                m = c.get("/api/workspace").json()["messages"][-1]
                self.assertTrue(m["matches_expectation"], (k, [p["operation"] for p in m["proposals"]], m["expected"]))
                for _ in range(2):          # a dependency waits for its task, so accept in two passes
                    for s in c.get("/api/suggestions").json():
                        if s["operation"] == "NO_ACTION" or s["requires_referent"] or [u for u in s["unresolved"] if not (u == "assignee" and s["operation"] == "CREATE_TASK")]:
                            continue
                        c.post(f"/api/suggestions/{s['id']}/accept", json={"actor_id": reviewer(s)})   # the open call (step 6) is left open
            tasks = {t["id"]: (t["owner_id"], t["lifecycle"], t["derived_state"]) for t in c.get("/api/workspace").json()["tasks"]}
            self.assertEqual(tasks, {
                "T-1": ("anushree", "completed", "done"), "T-2": ("anushree", "in_progress", "ready"), "T-3": ("bianca", "open", "blocked"),
                "T-4": ("bianca", "cancelled", "cancelled"), "T-5": ("anushree", "open", "ready"), "T-6": ("bianca", "open", "blocked"),
                "T-7": ("bianca", "open", "blocked_cancelled_prereq")})
            g = c.get("/api/dependencies").json()
            edges = sorted((e["source"], e["target"], e["kind"]) for e in g["edges"])
            self.assertEqual(edges, [("T-1", "T-2", "accepted"), ("T-2", "T-3", "accepted"), ("T-3", "T-6", "accepted"), ("T-4", "T-6", "accepted"),
                                     ("T-4", "T-7", "accepted"), ("T-5", "T-6", "accepted"), ("T-6", "T-3", "held")])
            self.assertTrue(g["meta"]["acyclic"])
            self.assertEqual(c.get("/api/tasks/T-4").json()["due"]["value"], "2026-11-13")      # moved Thu -> Fri after confirmation
