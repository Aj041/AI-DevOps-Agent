from __future__ import annotations

import difflib
import os
import re
import subprocess
import sys
import hashlib
from pathlib import Path
from typing import Any

COMMANDS = {"npm", "pytest", "python", "python3", "mvn", "gradle", "go", "cargo", "git", "node"}
SECRET = re.compile(r"(?i)(password|secret|token|api[_-]?key|private[_-]?key)")
MAX_COMMAND_TIMEOUT = 120


class RepositoryTools:
    def __init__(self, root: str):
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir(): raise ValueError("Repository root must be a directory")

    def _path(self, relative: str) -> Path:
        target = (self.root / relative).resolve()
        if target != self.root and self.root not in target.parents: raise ValueError("Path escapes repository")
        return target

    def list_files(self, limit: int = 500) -> list[str]:
        ignored = {".git", "node_modules", ".venv", "__pycache__"}
        result: list[str] = []
        for path in self.root.rglob("*"):
            if path.is_file() and not any(part in ignored for part in path.parts):
                result.append(str(path.relative_to(self.root)).replace("\\", "/"))
        return sorted(result)[:limit]

    def read_file(self, relative: str) -> str:
        path = self._path(relative)
        if path.name == ".env": return "[redacted: .env is never exposed]"
        text = path.read_text(encoding="utf-8")
        return "\n".join("[redacted]" if SECRET.search(line.split("=", 1)[0]) else line for line in text.splitlines())

    def search_code(self, query: str) -> list[dict[str, Any]]:
        matches = []
        for relative in self.list_files():
            path = self._path(relative)
            try: lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError): continue
            for number, line in enumerate(lines, 1):
                if query.lower() in line.lower(): matches.append({"file": relative, "line": number, "text": line[:240]})
        return matches[:100]

    def run_command(self, command: list[str], timeout: int = 120) -> dict[str, Any]:
        executable = Path(command[0]).stem.lower() if command else ""
        allowed = {Path(item).stem.lower() for item in COMMANDS}
        if not command or executable not in allowed: raise ValueError("Command is not allowlisted")
        if timeout < 1 or timeout > MAX_COMMAND_TIMEOUT:
            raise ValueError(f"Command timeout must be between 1 and {MAX_COMMAND_TIMEOUT} seconds")
        args = command[1:]
        # Keep the tool surface narrow: no arbitrary Git operations or language
        # interpreter snippets. The only scripts run are repository test scripts.
        if executable == "git" and args not in (["--version"], ["status", "--short"], ["diff"], ["branch", "--show-current"]):
            if not (args[:2] == ["switch", "-c"] and len(args) == 3) and not (args[:1] == ["commit"] and len(args) == 3 and args[1] == "-am"):
                raise ValueError("Only read-only Git inspection and approval-gated branch/commit commands are allowed")
        if executable in {"python", "python3"} and args != ["-m", "pytest"]:
            # Agent test commands may use the active interpreter's absolute path.
            if not (Path(command[0]).resolve() == Path(sys.executable).resolve() and args == ["-m", "pytest"]):
                raise ValueError("Python tool execution is restricted to python -m pytest")
        if executable == "pytest" and any(arg.startswith("-") and arg not in {"-q", "-v", "-x"} for arg in args):
            raise ValueError("Unsupported pytest option")
        if executable == "npm" and args != ["test"]:
            raise ValueError("NPM tool execution is restricted to npm test")
        if executable in {"mvn", "gradle"} and args not in (["test"], ["-B", "test"]):
            raise ValueError("Build tool execution is restricted to its test task")
        if executable == "go" and args != ["test", "./..."]:
            raise ValueError("Go tool execution is restricted to go test ./...")
        if executable == "cargo" and args != ["test"]:
            raise ValueError("Cargo tool execution is restricted to cargo test")
        if executable == "node":
            raise ValueError("Direct Node.js execution is disabled; use the detected npm test script")
        safe_env = {key: value for key, value in os.environ.items() if key in {"PATH", "SystemRoot", "WINDIR", "TEMP", "TMP"}}
        safe_env.update({"CI": "true", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
        completed = subprocess.run(command, cwd=self.root, env=safe_env, capture_output=True, text=True, timeout=timeout, shell=False)
        return {"command": " ".join(command), "exit_status": completed.returncode, "stdout": completed.stdout[-12000:], "stderr": completed.stderr[-12000:]}

    def run_tests(self, command: list[str], timeout: int = 120) -> dict[str, Any]:
        return self.run_command(command, timeout)

    def git_status(self) -> dict[str, Any]: return self.run_command(["git", "status", "--short"])
    def git_diff(self) -> dict[str, Any]: return self.run_command(["git", "diff"])
    def git_branch(self) -> dict[str, Any]: return self.run_command(["git", "branch", "--show-current"])

    def create_branch(self, name: str, approved: bool = False) -> dict[str, Any]:
        if not approved: raise PermissionError("Explicit approval is required")
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,80}", name) or name.startswith(("-", ".")):
            raise ValueError("Invalid branch name")
        return self.run_command(["git", "switch", "-c", name])

    def commit(self, message: str, approved: bool = False) -> dict[str, Any]:
        if not approved: raise PermissionError("Explicit approval is required")
        if not message.strip() or len(message) > 200: raise ValueError("Commit message is required and must be short")
        return self.run_command(["git", "commit", "-am", message])

    def proposed_file(self, relative: str, content: str) -> dict[str, Any]:
        path = self._path(relative)
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        diff = "".join(difflib.unified_diff(old.splitlines(True), content.splitlines(True), fromfile=relative, tofile=relative))
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        return {"path": relative, "content": content, "diff": diff, "is_new": not path.exists(), "base_sha256": digest}

    def apply_proposal(self, proposal: dict[str, Any], approved: bool = False) -> dict[str, Any]:
        if not approved: raise PermissionError("Explicit approval is required")
        path = self._path(proposal["path"])
        exists = path.exists()
        if proposal["base_sha256"] is None and exists:
            raise ValueError("The proposed new file now exists; review a fresh diff before applying")
        if proposal["base_sha256"] is not None:
            if not exists or hashlib.sha256(path.read_bytes()).hexdigest() != proposal["base_sha256"]:
                raise ValueError("The file changed since this proposal was created; review a fresh diff before applying")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(proposal["content"], encoding="utf-8")
        return {"path": proposal["path"], "written": True}

    def create_file(self, relative: str, content: str, approved: bool = False) -> dict[str, Any]:
        if not approved: raise PermissionError("Explicit approval is required")
        path = self._path(relative); path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8")
        return {"path": relative, "written": True}

    def modify_file(self, relative: str, content: str, approved: bool = False) -> dict[str, Any]:
        if not self._path(relative).exists(): raise FileNotFoundError(relative)
        return self.create_file(relative, content, approved)
