from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, status
import httpx
from pydantic import BaseModel, Field

from agent.workflow import CI_CD_TASK, RUNS, generate_ci, generate_dockerfile, test_command
from repository.analyzer import analyze_repository
from repository.source import RepositoryUnavailableError, resolve_source
from tools.core import RepositoryTools

router = APIRouter(prefix="/api")


class RepositoryRequest(BaseModel): path: str = Field(min_length=1)
class AgentRequest(RepositoryRequest): task: str = CI_CD_TASK
class ProposalRequest(RepositoryRequest): file: str; content: str; approved: bool = False
class GitRequest(RepositoryRequest): value: str = ""; approved: bool = False
class ApprovalRequest(BaseModel): approved: bool = False


@router.get("/github/repositories")
def github_repositories(query: str = ""):
    """Find public repositories, or the configured user's repos when token is set."""
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token: headers["Authorization"] = f"Bearer {token}"
    if query.strip():
        url = "https://api.github.com/search/repositories"
        search = query.strip()
        github_query = f"repo:{search}" if search.count("/") == 1 and " " not in search else f"{search} in:name"
        params = {"q": github_query, "sort": "stars", "order": "desc", "per_page": 10}
    elif token:
        url = "https://api.github.com/user/repos"
        params = {"sort": "updated", "per_page": 30, "affiliation": "owner,collaborator,organization_member"}
    else:
        return {"repositories": [], "message": "Search public repositories, or configure GITHUB_TOKEN to list private repositories."}
    try:
        response = httpx.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except httpx.TimeoutException as error:
        raise HTTPException(504, {"code": "github_timeout", "message": "GitHub did not respond in time. Try again."}) from error
    except httpx.HTTPStatusError as error:
        status_code = 503 if error.response.status_code >= 500 else 502
        raise HTTPException(status_code, {"code": "github_api_error", "message": f"GitHub repository lookup failed ({error.response.status_code}). Check token access and rate limits."}) from error
    except httpx.HTTPError as error:
        raise HTTPException(503, {"code": "github_unavailable", "message": f"Could not reach GitHub: {error}"}) from error
    repositories = payload.get("items", payload) if isinstance(payload, dict) else payload
    unique = {repo["full_name"]: repo for repo in repositories if repo.get("full_name") and repo.get("html_url")}
    return {"repositories": [{"name": repo["full_name"], "url": repo["html_url"], "description": (repo.get("description") or "")[:180], "private": repo.get("private", False), "default_branch": repo.get("default_branch", "main")} for repo in unique.values()]}


def checked(path: str) -> RepositoryTools:
    try: return RepositoryTools(resolve_source(path))
    except RepositoryUnavailableError as error: raise HTTPException(503, {"code": "repository_unavailable", "message": str(error)}) from error
    except ValueError as error: raise HTTPException(400, {"code": "invalid_repository", "message": str(error)}) from error


@router.post("/repository/analyze")
def repository_analyze(request: RepositoryRequest):
    try: return analyze_repository(resolve_source(request.path))
    except RepositoryUnavailableError as error: raise HTTPException(503, {"code": "repository_unavailable", "message": str(error)}) from error
    except ValueError as error: raise HTTPException(400, {"code": "invalid_repository", "message": str(error)}) from error


@router.post("/agent/run", status_code=status.HTTP_202_ACCEPTED)
def agent_run(request: AgentRequest):
    try:
        source = resolve_source(request.path)
        # Fail fast so a run never begins with an invalid/unavailable local path.
        RepositoryTools(source)
        return RUNS.start(source, request.task)
    except RepositoryUnavailableError as error:
        raise HTTPException(503, {"code": "repository_unavailable", "message": str(error)}) from error
    except ValueError as error:
        raise HTTPException(400, {"code": "invalid_repository", "message": str(error)}) from error
    except OSError as error:
        raise HTTPException(503, {"code": "repository_unavailable", "message": str(error)}) from error


@router.get("/agent/runs/{agent_run_id}")
def agent_run_status(agent_run_id: str):
    try: return RUNS.get(agent_run_id)
    except KeyError as error: raise HTTPException(404, {"code": "run_not_found", "message": "Agent run was not found"}) from error


@router.post("/agent/runs/{agent_run_id}/proposals/{proposal_id}/apply")
def agent_apply_proposal(agent_run_id: str, proposal_id: str, request: ApprovalRequest):
    try:
        return RUNS.apply_proposal(agent_run_id, proposal_id, request.approved)
    except KeyError as error:
        raise HTTPException(404, {"code": "proposal_not_found", "message": "Run or proposal was not found"}) from error
    except PermissionError as error:
        raise HTTPException(403, {"code": "approval_required", "message": str(error)}) from error
    except (ValueError, OSError) as error:
        raise HTTPException(409, {"code": "proposal_conflict", "message": str(error)}) from error


@router.post("/tests/run")
def tests_run(request: RepositoryRequest):
    tools = checked(request.path); report = analyze_repository(resolve_source(request.path)); command = test_command(report)
    if not command: raise HTTPException(400, "No supported test command detected")
    try: return tools.run_command(command)
    except Exception as error: raise HTTPException(400, str(error)) from error


@router.post("/ci/generate")
def ci_generate(request: RepositoryRequest): return {"path": ".github/workflows/ci.yml", "content": generate_ci(analyze_repository(resolve_source(request.path)))}

@router.post("/docker/generate")
def docker_generate(request: RepositoryRequest): return {"path": "Dockerfile", "content": generate_dockerfile(analyze_repository(resolve_source(request.path)))}


@router.post("/fixes/propose")
def fixes_propose(request: ProposalRequest): return checked(request.path).proposed_file(request.file, request.content)


@router.post("/fixes/apply")
def fixes_apply(request: ProposalRequest):
    try: return checked(request.path).create_file(request.file, request.content, request.approved)
    except (ValueError, PermissionError, OSError) as error: raise HTTPException(400, str(error)) from error


@router.get("/git/{operation}")
def git_operation(operation: str, path: str):
    tools = checked(path)
    try: return {"status": tools.git_status, "diff": tools.git_diff, "branch": tools.git_branch}[operation]()
    except KeyError: raise HTTPException(404, "Unknown git operation")


@router.post("/git/branch")
def git_branch(request: GitRequest):
    try: return checked(request.path).create_branch(request.value, request.approved)
    except (ValueError, PermissionError, OSError) as error: raise HTTPException(400, str(error)) from error


@router.post("/git/commit")
def git_commit(request: GitRequest):
    try: return checked(request.path).commit(request.value, request.approved)
    except (ValueError, PermissionError, OSError) as error: raise HTTPException(400, str(error)) from error
