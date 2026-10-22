from __future__ import annotations

import json
import os

import httpx


class LLMPlanner:
    """OpenAI-compatible planner; missing credentials falls back to local planning."""

    def __init__(self) -> None:
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.model = os.getenv("LLM_MODEL", "")
        self.endpoint = os.getenv("LLM_ENDPOINT", "https://api.openai.com/v1/chat/completions")

    def choose_tools(self, task: str, files: list[str]) -> list[str]:
        return self.choose_tools_with_status(task, files)["tools"]

    def choose_tools_with_status(self, task: str, files: list[str]) -> dict[str, object]:
        available = ["list_files", "read_file", "search_code", "run_command", "run_tests", "git_status", "git_diff"]
        if not self.api_key or not self.model:
            return {"tools": available, "error": "LLM is not configured; deterministic local planning was used."}
        try:
            response = httpx.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "temperature": 0, "messages": [
                    {"role": "system", "content": "Return JSON only: {\"tools\":[tool names]}. Select only available tools."},
                    {"role": "user", "content": json.dumps({"task": task, "files": files[:100], "available_tools": available})},
                ]},
                timeout=20,
            )
            response.raise_for_status()
            selected = json.loads(response.json()["choices"][0]["message"]["content"]).get("tools", [])
            tools = [tool for tool in selected if tool in available]
            return {"tools": tools or available, "error": None}
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            return {"tools": available, "error": f"LLM planning failed: {error}"}
