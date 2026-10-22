from __future__ import annotations

import hashlib
import base64
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse


class RepositoryUnavailableError(ValueError):
    """A syntactically valid repository source that could not be retrieved."""


def resolve_source(source: str, cache_root: str = ".dist/repos") -> str:
    source = source.strip()
    parsed = urlparse(source)
    if parsed.scheme not in {"http", "https"}:
        return str(Path(source).expanduser().resolve())
    segments = [part for part in parsed.path.strip("/").removesuffix(".git").split("/") if part]
    if parsed.netloc.lower() not in {"github.com", "www.github.com"} or len(segments) != 2 or parsed.username or parsed.password:
        raise ValueError("Only GitHub HTTPS repository URLs are supported")
    clone_url = f"https://github.com/{segments[0]}/{segments[1]}.git"
    target = Path(cache_root).expanduser().resolve() / hashlib.sha256(clone_url.encode()).hexdigest()[:16]
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            env = os.environ.copy()
            token = os.getenv("GITHUB_TOKEN", "")
            if token:
                auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
                env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader", "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {auth}"})
            completed = subprocess.run(["git", "clone", "--depth", "1", clone_url, str(target)], capture_output=True, text=True, timeout=180, shell=False, env=env)
        except subprocess.TimeoutExpired as error:
            raise RepositoryUnavailableError("Repository clone timed out") from error
        except OSError as error:
            raise RepositoryUnavailableError(f"Repository is unavailable: {error}") from error
        if completed.returncode:
            if target.exists():
                import shutil
                shutil.rmtree(target, ignore_errors=True)
            details = completed.stderr[-1000:].strip() or "GitHub did not provide an error message."
            if any(marker in details.lower() for marker in ("repository not found", "authentication failed", "could not read username")):
                details += " Check that the repository is public or configure GITHUB_TOKEN with access to it."
            raise RepositoryUnavailableError(details)
    return str(target)
