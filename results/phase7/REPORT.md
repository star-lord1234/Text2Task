# Phase 7: local application (functional MVP)

Everything here is a functional check of an application, not a model result. No model was trained and no evaluation dataset was modified in this phase.
Model-quality numbers are on the in-app Evaluation page, read from the saved files in `results/` (SILVER, provisional).

## Delivered
Workspace (shared chat, personal tasks, review queue, dependency graph, scenario bar), dependency explorer (filters, snapshots, graph-as-table, what-if via the existing `impact_of`),
AI Inspector (entities, relations, resolution, reconciliation, provenance; scripted expectations shown separately from model output), deadline timeline, evaluation dashboard,
scenarios A to E, persona switching, simulated time, append-only history, honest Live-mode failure handling.
Four Phase 5 extensions (referent/anaphora, acknowledgement vs restatement, "Can someone..." requests, volunteer claim of an unowned task) with positive and negative tests.

## Test results (final run)
| Suite | Result |
|---|---|
| Backend `unittest` | 301 passed |
| Reconciliation scenarios (original + extension fixtures) | 75 / 75 |
| Frontend Vitest (incl. axe checks) | 80 passed |
| Playwright | 16 passed (13 scripted, 3 against the real models) |
| Phase 5 corpus replay / fuzz after the extensions | counts equal the original baseline; 0 invariant violations in 12000 fuzz steps |

Mutation checks show the key negative tests fail if their guard is removed (volunteer claims: owner already set, different action, closed task, joint "X and I will", ambiguity guessed).
Screenshots from the actual runs: `results/phase7/screenshots/`.

## Defects found by looking at the running app (and fixed)
Unlayered CSS overrode Tailwind utilities (selected toggles and primary buttons were illegible), a None score crash, replay exactness issues, per-type entity F1 shown blank because the saved file names it `f1-score`, a "Reassign" label for an unowned task. A computed-style e2e test guards the first.

## Known limitations
* Held (cycle-forming) edges are drawn and labelled but share the layout with the accepted edge, so a two-node cycle looks cramped.
* A task with no named owner cannot be accepted from the card; the reviewer must Edit first (deliberate: no invented owner).
* Live extraction quality is that of the provisional models: the entity model's TASK recall is very low on its SILVER validation set (see Evaluation page), so Live suggestions often need Edit or Dismiss.
* Cue-based reconciliation is brittle on formal email text (see the Phase 5 report); every proposal is review-only.
* Time zones: messages use the workspace timezone; the machine clock is only used for the default "now" of a typed message.
* No real accessibility audit beyond axe checks and keyboard e2e; no cross-browser testing (Chromium only).
* Single local user, no authentication, SQLite file, no multi-device sync.
