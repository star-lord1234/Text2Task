# Text2Task

Action-item extraction from team chat: neural entity and relation models, rule-based dates/owners, task reconciliation in review mode, a dependency graph, and a local app.
All model results are agreement with **provisional SILVER labels** (MailEx-derived); there is no human-verified GOLD evaluation.

## Recommended team workflow: Docker

The published Docker image contains the website, API, Python dependencies and
the selected entity/relation checkpoints. Model files, MailEx data, optimizer
state and training checkpoints are **not** stored in Git.

Prerequisite: install and start Docker Desktop (or Docker Engine with Compose).
If a newly installed Docker Desktop is running but `docker` is not found, open
a new Terminal window or run `export PATH="$HOME/.docker/bin:$PATH"` first.

### First run

```sh
git clone <REPOSITORY_URL>
cd ML_Project
cp .env.example .env
```

Edit `.env` and replace `REPLACE_WITH_OWNER` with the GitHub user or organization
that owns the published package:

```dotenv
T2T_IMAGE=ghcr.io/<OWNER>/text2task:0.1.0-silver
T2T_PORT=8000
T2T_TZ=UTC
```

For a private GHCR package, authenticate once using a GitHub personal access
token with `read:packages`. Do not put the token in `.env` or commit it.

```sh
export CR_PAT=<YOUR_READ_PACKAGES_TOKEN>
echo "$CR_PAT" | docker login ghcr.io -u <YOUR_GITHUB_USERNAME> --password-stdin
unset CR_PAT
```

Pull and start the complete application:

```sh
docker compose pull
docker compose up -d
docker compose ps
```

Open **http://localhost:8000**. The initial pull is large because it includes
PyTorch and both model checkpoints; later starts reuse Docker's local cache.
Application state is kept in the `text2task-state` Docker volume.

Useful commands:

```sh
docker compose logs -f text2task       # startup/model-loading logs
docker compose down                    # stop, preserving app state
docker compose pull && docker compose up -d  # update to a newer image
docker compose down -v                 # stop AND delete local app state
```

The API health endpoint is
http://localhost:8000/api/system/health. Model availability and honest SILVER
provenance are exposed at http://localhost:8000/api/system/capabilities.

Docker Desktop runs a Linux VM on macOS, so Apple MPS is not available inside
the container; inference uses CPU. The image is built for both `linux/arm64`
(Apple Silicon) and `linux/amd64` (Intel/AMD machines).

### Publishing a model image (maintainer only)

The repository intentionally cannot build the real-model image from a fresh
clone because model weights are excluded from Git. A maintainer with the trained
models in their local workspace publishes the image once; teammates only pull it.

1. Install/start Docker Desktop.
2. Authenticate to GHCR with a token that has `write:packages`.
3. Publish from the project root:

```sh
export CR_PAT=<YOUR_WRITE_PACKAGES_TOKEN>
echo "$CR_PAT" | docker login ghcr.io -u <YOUR_GITHUB_USERNAME> --password-stdin
unset CR_PAT

export T2T_IMAGE=ghcr.io/<OWNER>/text2task
scripts/publish_container.sh 0.1.0-silver
```

`scripts/prepare_docker_models.py` creates an ignored, minimal release bundle
before the build. It includes approximately 530 MB of selected model artifacts
and a SHA-256 manifest. It excludes the raw dataset, email content, `.venv`, all
optimizer files and all intermediate checkpoints. The publish script then builds
and pushes `arm64` and `amd64` images tagged `0.1.0-silver` and `latest`.

For a one-machine Docker smoke test without publishing:

```sh
python3 scripts/prepare_docker_models.py
docker build -t text2task:local .
T2T_IMAGE=text2task:local docker compose up
```

After publishing, give the package read permission to the repository/team in
GitHub Packages and replace the placeholder in `.env.example` with the real
image name.

## Local development without Docker

```sh
scripts/run_app.sh                    # real models, http://127.0.0.1:8000 (builds the frontend the first time)
T2T_NO_MODELS=1 scripts/run_app.sh    # scripted demo only; Live mode reports "model unavailable"
scripts/dev.sh                        # API + Vite dev server with hot reload
```
Needs the project venv (`.venv`), Node with pnpm, and for Live mode the trained checkpoints under `models/`.

* **Scripted** mode replays scenarios A to F. Scenario F is the full 17-message presenter demo; see `docs/demo_walkthrough.md` for the click-by-click script. Extraction is pre-written by the scenario and labelled `scripted`; reconciliation, review, history and the graph are the real code.
* **Live** mode runs the real entity and relation models (`neural`), optional rule refinement of their output (`refined` / `rule`, see below), rule date/owner resolution (`rule`) and cue-based reconciliation (`rule (cue-based)`). If a model is unavailable the failure is stored and shown; it is never replaced by scripted output. The rule fallback is opt-in and off by default.
* Everything the model proposes is a **suggestion** until a person accepts, edits or dismisses it (review mode). Human edits are labelled `human`.
  Only the person a suggestion lands on may accept it (`reviewer_ids` in `/api/suggestions`, enforced by the API with `403 NOT_YOUR_REVIEW`): the assignee accepts a new task, the owner accepts status changes and new prerequisites of their task, the people whose agreement a date change needs confirm it. Unassigned suggestions can be decided by anyone; the author of a message may also dismiss a misread of it.
  The reconciler is written so automatic application could be added later; it currently refuses to start in that mode.

## Pipeline configurations (Live mode)
The **Pipeline** selector in Settings (sidebar) (or `PUT /api/settings {"pipeline_preset": ...}`) chooses how much rule refinement surrounds the neural models: `neural_only` (raw checkpoints), `neural_plus_linker`, `refined` (span and date repair), `hybrid` (default: adds action-phrase recovery, clause-level dependencies and lifecycle handling without a task span) and `rule_only` (no neural model). Each stage can also be switched individually with `refine_overrides`. The AI Inspector shows the raw neural spans next to the refined ones, labels every span `neural`, `refined` or `rule`, and lists what each rule did. See `results/phase7_5/REPORT.md`.

## Tests
```sh
.venv/bin/python -m unittest discover -s tests      # backend
cd frontend && pnpm test                            # Vitest + axe
cd frontend && pnpm exec playwright test            # end to end (starts a scripted server and a live-models server); writes results/phase7/screenshots
```
After changing the API: `.venv/bin/python scripts/export_openapi.py` (a test fails if `docs/openapi.json` is stale). Frontend API types live in `frontend/src/api/types.ts` and are maintained by hand (`pnpm gen:types` currently fails with TypeScript 7 and nothing imports its output).
Compare pipeline configurations on the live fixtures: `.venv/bin/python scripts/run_live_battery.py` then `scripts/summarize_phase7_5.py`.

## Layout
`src/api` FastAPI app · `src/reconciliation` task reconciliation · `src/pipeline`, `src/temporal` fields · `src/graph` dependency graph · `frontend/` React app · `results/` saved experiment outputs and reports (Phases 3 to 7).
