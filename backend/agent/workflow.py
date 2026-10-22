from __future__ import annotations

import json
import re
import secrets
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.llm import LLMPlanner
from repository.analyzer import analyze_repository
from tools.core import RepositoryTools

CI_CD_TASK = "Analyze this repository and prepare it for CI/CD."
TEST_FAILURE_TASK = "Find and diagnose test failures."
ALL_TOOLS = ["list_files", "read_file", "search_code", "run_command", "run_tests", "git_status", "git_diff"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def detect_issues(report: dict[str, Any], tools: RepositoryTools | None = None) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    important = report["important_files"]
    if not important["Dockerfile"]:
        issues.append({"issue": "Missing Dockerfile", "severity": "medium", "file": "Dockerfile", "explanation": "No container build definition was found.", "suggested_fix": "Generate and review a Dockerfile for the detected stack."})
    if not report["workflows"]:
        issues.append({"issue": "Missing CI workflow", "severity": "medium", "file": ".github/workflows/ci.yml", "explanation": "Changes are not automatically tested in GitHub Actions.", "suggested_fix": "Generate a workflow using the detected package manager and test command."})
    if important[".env"] and not important[".env.example"]:
        issues.append({"issue": "Missing environment template", "severity": "high", "file": ".env.example", "explanation": "A local environment file exists without a safe template for collaborators.", "suggested_fix": "Add .env.example containing variable names only."})
    if report["language"] == "Unknown":
        issues.append({"issue": "Unknown project stack", "severity": "low", "file": "", "explanation": "No recognized manifest was found.", "suggested_fix": "Add a standard dependency manifest or configure the project manually."})
    return issues


def test_command(report: dict[str, Any], package_contents: str = "") -> list[str] | None:
    """Return a supported command only when the repository advertises one."""
    if report["language"] == "Python":
        # The API process may run inside a virtual environment whose Scripts
        # directory is not on PATH. Use that interpreter so this is a real,
        # reproducible pytest invocation rather than a simulated test result.
        return [sys.executable, "-m", "pytest"]
    if report["language"] == "JavaScript/TypeScript":
        try:
            if "test" not in json.loads(package_contents).get("scripts", {}):
                return None
        except (TypeError, ValueError):
            return None
        return ["npm", "test"]
    if report["language"] == "Java": return ["mvn", "test"]
    if report["language"] == "Go": return ["go", "test", "./..."]
    if report["language"] == "Rust": return ["cargo", "test"]
    return None


def generate_ci(report: dict[str, Any]) -> str:
    command = "python -m pytest" if report["language"] == "Python" else " ".join(test_command(report, '{"scripts":{"test":"test"}}') or ["echo", "No test command detected"])
    setup = {"Python": "python-version: '3.12'\n          cache: pip", "JavaScript/TypeScript": "node-version: '20'", "Java": "java-version: '21'", "Go": "go-version: '1.22'", "Rust": "toolchain: stable"}.get(report["language"], "")
    install = {"Python": "python -m pip install -r requirements.txt", "JavaScript/TypeScript": "npm ci", "Java": "mvn -B dependency:go-offline", "Go": "go mod download", "Rust": "cargo fetch"}.get(report["language"], "echo 'No dependency install command detected'")
    build = {"Python": "python -m compileall .", "JavaScript/TypeScript": "npm run build --if-present", "Java": "mvn -B package -DskipTests", "Go": "go build ./...", "Rust": "cargo build"}.get(report["language"], "echo 'No build command detected'")
    setup_action = {"JavaScript/TypeScript": "node", "Python": "python", "Java": "java", "Go": "go", "Rust": "rust"}.get(report["language"], "python")
    return f"""name: CI
on:
  push:
  pull_request:
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-{setup_action}@v5
        with:
          {setup or "python-version: '3.12'"}
      - name: Install dependencies
        run: {install}
      - name: Run tests
        run: {command}
      - name: Build
        run: {build}
"""


def generate_dockerfile(report: dict[str, Any]) -> str:
    templates = {
        "Python": "FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\nCMD [\"python\", \"-m\", \"pytest\"]\n",
        "JavaScript/TypeScript": "FROM node:20-alpine\nWORKDIR /app\nCOPY package*.json ./\nRUN npm ci\nCOPY . .\nRUN npm run build --if-present\nCMD [\"npm\", \"start\"]\n",
        "Java": "FROM maven:3.9-eclipse-temurin-21\nWORKDIR /app\nCOPY pom.xml .\nRUN mvn dependency:go-offline\nCOPY . .\nRUN mvn package -DskipTests\nCMD [\"java\", \"-jar\", \"target/app.jar\"]\n",
        "Go": "FROM golang:1.22-alpine AS build\nWORKDIR /src\nCOPY . .\nRUN go build -o /app ./...\nFROM alpine:3.20\nCOPY --from=build /app /app\nCMD [\"/app\"]\n",
        "Rust": "FROM rust:1.82 AS build\nWORKDIR /app\nCOPY . .\nRUN cargo build --release\nCMD [\"./target/release/app\"]\n",
    }
    return templates.get(report["language"], "FROM alpine:3.20\nWORKDIR /app\nCOPY . .\nCMD [\"sh\"]\n")


def _test_summary(result: dict[str, Any]) -> dict[str, int | bool]:
    text = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
    return {"passed": sum(int(v) for v in re.findall(r"(\d+) passed", text)), "failed": sum(int(v) for v in re.findall(r"(\d+) failed", text)), "success": result.get("exit_status") == 0}


def _failure_files(output: str, files: list[str]) -> list[str]:
    mentioned = [name for name in files if name in output]
    return (mentioned or [name for name in files if "test" in Path(name).name.lower()])[:3]


class AgentExecutor:
    """Executes only RepositoryTools operations and streams their factual results."""

    def __init__(self, path: str, task: str, emit: Callable[..., None]) -> None:
        self.path, self.task, self.emit = path, task, emit
        self.tools = RepositoryTools(path)
        self.used: list[str] = []

    def _tool(self, name: str, message: str, call: Callable[[], Any], optional: bool = False) -> Any:
        self.emit("running", message, tool=name)
        try:
            value = call()
            self.used.append(name)
            status = value.get("exit_status") if isinstance(value, dict) else None
            if status not in (None, 0): self.emit("warning", f"{name} completed with exit code {status}", tool=name)
            else: self.emit("success", message.replace("Running", "Completed").replace("Reading", "Read"), tool=name)
            return value
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            self.used.append(name)
            self.emit("warning" if optional else "error", f"{name} failed: {error}", tool=name)
            if optional: return {"error": str(error)}
            raise

    def execute(self) -> dict[str, Any]:
        self.emit("success", "Repository loaded")
        files = self._tool("list_files", "Listing repository files", self.tools.list_files)
        # Tool planning happens after the factual inventory is available and
        # before any remaining inspection/execution calls are made.
        selection = LLMPlanner().choose_tools_with_status(self.task, files)
        suffix = " (local fallback)" if selection["error"] else ""
        self.emit("warning" if selection["error"] else "success", f"Selected tools: {', '.join(selection['tools'])}{suffix}")
        report = analyze_repository(self.path)
        self.emit("success", f"Detected {report['framework']} ({report['language']})")
        manifest_names = {"package.json", "requirements.txt", "pyproject.toml", "pom.xml", "go.mod", "Cargo.toml", "Dockerfile"}
        config_contents: dict[str, str] = {}
        for file in [f for f in files if f in manifest_names][:8]:
            config_contents[file] = self._tool("read_file", f"Reading {file}", lambda file=file: self.tools.read_file(file))
        if not config_contents: self.emit("warning", "No recognized dependency manifest was found")
        test_matches = self._tool("search_code", "Searching code for test references", lambda: self.tools.search_code("test"))
        self._tool("run_command", "Checking Git command availability", lambda: self.tools.run_command(["git", "--version"]), optional=True)
        self._tool("git_status", "Reading Git status", self.tools.git_status, optional=True)
        self._tool("git_diff", "Reading Git diff", self.tools.git_diff, optional=True)
        command = test_command(report, config_contents.get("package.json", ""))
        test_results: dict[str, Any] | None = None
        test_summary: dict[str, int | bool] = {"passed": 0, "failed": 0, "success": False}
        issues = detect_issues(report, self.tools)
        if command:
            test_results = self._tool("run_tests", f"Running tests: {' '.join(command)}", lambda: self.tools.run_tests(command), optional=True)
            if "error" in test_results:
                issues.append({"issue": "Test command failure", "severity": "high", "file": "", "explanation": test_results["error"], "suggested_fix": "Install the required test runner and retry the run."})
                self.emit("error", "Test command could not be executed")
            else:
                test_summary = _test_summary(test_results)
                if test_summary["success"]:
                    self.emit("success", f"Tests passed ({test_summary['passed']} reported)", tool="run_tests")
                else:
                    affected = _failure_files(test_results.get("stdout", "") + test_results.get("stderr", ""), files)
                    for file in affected:
                        if file not in config_contents: self._tool("read_file", f"Inspecting failure context in {file}", lambda file=file: self.tools.read_file(file), optional=True)
                    cause = (test_results.get("stderr") or test_results.get("stdout") or "The test runner returned a non-zero exit status.").strip()[-1200:]
                    issues.append({"issue": "Tests failed", "severity": "high", "file": affected[0] if affected else "", "explanation": cause, "suggested_fix": "Review the failing assertion and inspected source context before applying a targeted change."})
                    self.emit("error", f"Tests failed ({test_summary['failed']} reported); analyzing affected files", tool="run_tests")
        else:
            issues.append({"issue": "No test command detected", "severity": "medium", "file": "", "explanation": "The repository did not advertise a supported test command.", "suggested_fix": "Add a test script or document the test command."})
            self.emit("warning", "No supported test command detected")
        proposed_files: list[dict[str, str]] = []
        if not report["important_files"]["Dockerfile"]:
            proposed_files.append({"proposal_id": secrets.token_urlsafe(12), "reason": "Container build definition is missing", **self.tools.proposed_file("Dockerfile", generate_dockerfile(report))})
        if not report["workflows"]:
            proposed_files.append({"proposal_id": secrets.token_urlsafe(12), "reason": "GitHub Actions workflow is missing", **self.tools.proposed_file(".github/workflows/ci.yml", generate_ci(report))})
        if proposed_files:
            self.emit("success", f"Generated {len(proposed_files)} reviewable CI/CD proposal(s)")
            self.emit("waiting", "Waiting for approval before modifying files")
        diagnosis = f"{report['name']} is a {report['framework']} repository. {'Tests passed' if test_summary['success'] else 'Tests did not pass or no test command was available'}. Findings: {', '.join(issue['issue'] for issue in issues) or 'no issues in the inspected surface'}."
        return {"report": report, "issues": issues, "test_results": test_results, "test_summary": test_summary, "proposed_files": proposed_files, "ci_workflow": next((item["content"] for item in proposed_files if item["path"].endswith("ci.yml")), None), "diagnosis": diagnosis, "tools_used": list(dict.fromkeys(self.used)), "test_matches": len(test_matches), "planner": selection}


class AgentRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self, path: str, task: str) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        run = {"agent_run_id": run_id, "repository": path, "task": task, "status": "queued", "started_at": utc_now(), "completed_at": None, "duration_seconds": 0, "actions": [], "tools_used": [], "issues": [], "test_summary": {"passed": 0, "failed": 0, "success": False}, "proposed_files": [], "error": None}
        with self._lock: self._runs[run_id] = run
        threading.Thread(target=self._execute, args=(run_id,), daemon=True).start()
        return self.get(run_id)

    def get(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            if run_id not in self._runs: raise KeyError(run_id)
            return dict(self._runs[run_id])

    def _update(self, run_id: str, **values: Any) -> None:
        with self._lock: self._runs[run_id].update(values)

    def _emit(self, run_id: str, state: str, message: str, tool: str | None = None) -> None:
        with self._lock: self._runs[run_id]["actions"].append({"at": utc_now(), "state": state, "message": message, "tool": tool})

    def _execute(self, run_id: str) -> None:
        run, started = self.get(run_id), time.monotonic()
        self._update(run_id, status="running")
        try:
            result = AgentExecutor(run["repository"], run["task"], lambda state, message, tool=None: self._emit(run_id, state, message, tool)).execute()
            self._update(run_id, **result, status="completed", completed_at=utc_now(), duration_seconds=round(time.monotonic() - started, 2))
        except subprocess.TimeoutExpired as error:
            self._emit(run_id, "error", f"Run timed out: {error}")
            self._update(run_id, status="timed_out", error={"code": "timeout", "message": str(error)}, completed_at=utc_now(), duration_seconds=round(time.monotonic() - started, 2))
        except (ValueError, OSError, RuntimeError) as error:
            self._emit(run_id, "error", f"Agent run failed: {error}")
            self._update(run_id, status="failed", error={"code": "tool_failure", "message": str(error)}, completed_at=utc_now(), duration_seconds=round(time.monotonic() - started, 2))
        except Exception as error:
            self._emit(run_id, "error", f"Agent run failed: {error}")
            self._update(run_id, status="failed", error={"code": "agent_failure", "message": str(error)}, completed_at=utc_now(), duration_seconds=round(time.monotonic() - started, 2))

    def apply_proposal(self, run_id: str, proposal_id: str, approved: bool) -> dict[str, Any]:
        if not approved:
            raise PermissionError("Explicit approval is required")
        with self._lock:
            if run_id not in self._runs:
                raise KeyError(run_id)
            run = self._runs[run_id]
            proposal = next((item for item in run.get("proposed_files", []) if item["proposal_id"] == proposal_id), None)
            if proposal is None:
                raise KeyError(proposal_id)
            if proposal.get("applied_at"):
                raise ValueError("This proposal has already been applied")
            tools = RepositoryTools(run["repository"])
            result = tools.apply_proposal(proposal, approved=True)
            proposal["applied_at"] = utc_now()
            self._runs[run_id]["actions"].append({"at": proposal["applied_at"], "state": "success", "message": f"Applied approved change to {proposal['path']}", "tool": "apply_proposal"})
            return result


RUNS = AgentRunStore()


def run_agent(path: str, task: str = CI_CD_TASK) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    result = AgentExecutor(path, task, lambda state, message, tool=None: events.append({"state": state, "message": message, "tool": tool})).execute()
    result.update({"agent_run_id": str(uuid.uuid4()), "repository": path, "task": task, "status": "completed", "actions": events, "activity": [event["message"] for event in events], "duration_seconds": 0})
    return result
