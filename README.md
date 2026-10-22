# AI DevOps Agent

AI DevOps Agent is a local-first developer tool that inspects a repository, detects configuration and delivery issues, runs its supported tests, and produces reviewable CI/CD and fix proposals. It uses FastAPI, React, and an optional OpenAI-compatible LLM planner.

## Architecture

```text
React dashboard -> FastAPI routes -> agent workflow -> repository analyzer
                                      |             -> secure repository tools
                                      |             -> issue detector / CI generator
                                      -> optional LLM planner (tool selection only)
```

The backend is split into `repository/` (source resolution and analysis), `tools/` (bounded file, command, and Git operations), `agent/` (planning and orchestration), and `api/` (REST contracts).

The frontend presents the repository overview, activity, issues, tests, CI proposal, and Git read state.

## Features

- Analyze a local directory or a GitHub HTTPS repository URL.
- Search and select public GitHub repositories in the dashboard. Set `GITHUB_TOKEN` on the backend to list and clone private repositories.
- Detect Python, JavaScript/TypeScript, Java, Go, and Rust manifests and frameworks.
- Inspect important files, workflows, environment templates, and repository structure.
- Run allowlisted test commands: `pytest`, `npm test`, `mvn test`, `go test ./...`, or `cargo test`.
- Generate issue records with severity, file, explanation, and suggested fix.
- Generate Dockerfile and GitHub Actions proposals without silently writing them.
- Review unified diffs for proposed files and explicitly approve each write. Proposals are rejected if the underlying file changed since review.
- Provide unified diffs before approved file writes.
- Read Git status, diff, and branch. Branch creation and commits require `approved: true`.
- Never push automatically.

## Setup

### Requirements

- Python 3.12+
- Node.js 20+
- Git

### Install dependencies

From the project root:

```powershell
python -m pip install -r backend/requirements.txt
cd frontend
npm install
```

### Environment configuration

Copy `.env.example` to `.env` if using an LLM provider.

- `LLM_API_KEY` and `LLM_MODEL` enable the OpenAI-compatible planner.
- `LLM_ENDPOINT` optionally selects another compatible endpoint.
- Without credentials, a deterministic local planner selects the safe inspection tools.
- Set `GITHUB_TOKEN` on the backend to list private repositories and clone repositories the token can access.
- Public repositories can be searched without a token.

**Never put your GitHub token or LLM API key in frontend configuration or commit real secrets to GitHub.**

## Run locally

### Start the backend

From the project root:

```powershell
$env:PYTHONPATH = "backend"
python -m uvicorn backend.main:app --reload --port 8000
```

### Start the frontend

In another terminal:

```powershell
cd frontend
npm run dev
```

Open the dashboard at:

[http://localhost:5173](http://localhost:5173)

Enter an absolute repository path and select **Analyze repository**.

The API documentation is available at:

[http://localhost:8000/docs](http://localhost:8000/docs)

## How the agent works

1. The workflow analyzes the repository first.
2. The optional LLM receives a bounded file inventory and an allowlisted tool catalog.
3. The agent executes selected safe tools.
4. The detected test command is run.
5. Issues are classified and a CI workflow proposal is generated.
6. Proposed file changes are presented as diffs and require explicit approval before being applied.

The LLM chooses tools; it never receives `.env` values and cannot execute arbitrary shell text.

## API highlights

| Endpoint | Purpose |
|---|---|
| `POST /api/repository/analyze` | Analyze a repository using `{ "path": "..." }` |
| `POST /api/agent/run` | Run an agent task using `{ "path": "...", "task": "..." }` |
| `GET /api/github/repositories?query=...` | Search GitHub repositories |
| `POST /api/agent/runs/{run_id}/proposals/{proposal_id}/apply` | Apply a proposal using `{ "approved": true }` |
| `POST /api/tests/run` | Run supported repository tests |
| `POST /api/ci/generate` | Generate a CI workflow proposal |
| `POST /api/fixes/propose` | Propose fixes |
| `POST /api/fixes/apply` | Apply approved fixes |
| `GET /api/git/status?path=...` | Read Git status |
| `GET /api/git/diff` | Read Git diff |
| `GET /api/git/branch` | Read the current Git branch |
| `POST /api/git/branch` | Create a branch with explicit approval |
| `POST /api/git/commit` | Create a commit with explicit approval |

## Testing and CI

Run backend tests from the project root:

```powershell
$env:PYTHONPATH = "backend"
pytest backend/tests -q
```

The root GitHub Actions workflow tests the FastAPI backend and builds the Vite frontend on pushes and pull requests.

## Security

- Commands run with `shell=False`, inside the selected repository, with a restricted environment, a 120-second maximum, and command-specific argument limits.
- The agent allows test commands and read-only Git inspection.
- Branch creation and commits require explicit approval.
- Paths cannot escape the repository.
- `.env` is never returned, and secret-looking values are redacted from readable files.
- Proposed file changes show a diff and are applied only after an explicit user action.
- Stale proposals are rejected if the file changed after analysis.
- Remote pushes are intentionally not implemented.

These controls constrain tool calls but do not provide an operating-system sandbox. Only analyze repositories whose test code you trust.

## Docker

The backend and frontend each have a Dockerfile, and `docker-compose.yml` mounts the workspace for local development.

Build the containers:

```powershell
docker compose build
```

Run the application:

```powershell
docker compose up
```
