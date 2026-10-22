# AI DevOps Agent

AI DevOps Agent is a local-first developer tool that inspects a repository, detects configuration and delivery issues, runs its supported tests, and produces reviewable CI/CD and fix proposals. It uses FastAPI, React, and an optional OpenAI-compatible LLM planner.

## Architecture

```text
React dashboard -> FastAPI routes -> agent workflow -> repository analyzer
                                      |              -> secure repository tools
                                      |              -> issue detector / CI generator
                                      -> optional LLM planner (tool selection only)
```

The backend is split into `repository/` (source resolution and analysis), `tools/` (bounded file, command, and Git operations), `agent/` (planning and orchestration), and `api/` (REST contracts). The frontend presents the repository overview, activity, issues, tests, CI proposal, and Git read state.

## Features

- Analyze a local directory or a GitHub HTTPS repository URL.
- Search and select public GitHub repositories in the dashboard; set `GITHUB_TOKEN` on the backend to list and clone private repositories.
- Detect Python, JavaScript/TypeScript, Java, Go, and Rust manifests/frameworks.
- Inspect important files, workflows, environment templates, and repository structure.
- Run allowlisted test commands: `pytest`, `npm test`, `mvn test`, `go test ./...`, or `cargo test`.
- Generate issue records with severity, file, explanation, and suggested fix.
- Generate Dockerfile and GitHub Actions proposals without silently writing them.
- Review unified diffs for proposed files and explicitly approve each write; proposals are rejected if the underlying file changed since review.
- Provide unified diffs before approved file writes.
- Read Git status, diff, and branch; branch creation and commits require `approved: true`.
- Never push automatically.

## Setup

Requirements: Python 3.12+, Node.js 20+, Git.

```powershell
python -m pip install -r backend/requirements.txt
cd frontend
npm install
```

Copy `.env.example` to `.env` if using an LLM provider. `LLM_API_KEY` and `LLM_MODEL` enable the OpenAI-compatible planner; `LLM_ENDPOINT` optionally selects another compatible endpoint. Without credentials, a deterministic local planner selects the safe inspection tools. Set `GITHUB_TOKEN` on the backend to list private repositories and clone repositories the token can access. Public repositories can be searched without a token. Never put this token in frontend configuration.

## Run locally

From the project root:

```powershell
$env:PYTHONPATH = "backend"
python -m uvicorn backend.main:app --reload --port 8000
```

In another terminal:

```powershell
cd frontend
npm run dev
```

Open `http://localhost:5173`, enter an absolute repository path, and select **Analyze repository**. The API is documented at `http://localhost:8000/docs`.

## How the agent works

The workflow analyzes the repository first, gives the optional LLM a bounded file inventory and an allowlisted tool catalog, executes selected safe tools, runs the detected test command, classifies issues, and generates a CI workflow proposal. The LLM chooses tools; it never receives `.env` values and it cannot execute arbitrary shell text.

## API highlights

- `POST /api/repository/analyze` with `{ "path": "..." }`
- `POST /api/agent/run` with `{ "path": "...", "task": "..." }`
- `GET /api/github/repositories?query=...`
- `POST /api/agent/runs/{run_id}/proposals/{proposal_id}/apply` with `{ "approved": true }`
- `POST /api/tests/run`
- `POST /api/ci/generate`
- `POST /api/fixes/propose` and approval-gated `/api/fixes/apply`
- `GET /api/git/status?path=...`, `/diff`, and `/branch`
- approval-gated `POST /api/git/branch` and `/api/git/commit`

## Testing and CI

Run backend tests with `PYTHONPATH=backend pytest backend/tests -q`. The root GitHub Actions workflow tests the FastAPI backend and builds the Vite frontend on pushes and pull requests.

## Security

Commands run with `shell=False`, inside the selected repository, with a restricted environment, a 120-second maximum, and command-specific argument limits. The agent allows test commands and read-only Git inspection; branch creation and commits require explicit approval. This constrains tool calls but does not provide an operating-system sandbox, so only analyze repositories whose test code you trust. Paths cannot escape the repository. `.env` is never returned, and secret-looking values are redacted from readable files. Proposed file changes show a diff and are applied only after an explicit user click; stale proposals are rejected if the file changed after analysis. Remote pushes are intentionally not implemented.

## Docker

The backend and frontend each have a Dockerfile, and `docker-compose.yml` mounts the workspace for local development. Build with `docker compose build` and run with `docker compose up`.
