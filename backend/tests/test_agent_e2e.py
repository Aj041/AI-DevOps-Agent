import time

from fastapi.testclient import TestClient

from main import app


def wait_for_run(client: TestClient, run_id: str) -> dict:
    for _ in range(100):
        result = client.get(f"/api/agent/runs/{run_id}")
        assert result.status_code == 200
        payload = result.json()
        if payload["status"] in {"completed", "failed", "timed_out"}:
            return payload
        time.sleep(0.05)
    raise AssertionError("agent run did not finish")


def test_repository_analysis_runs_tools_tests_and_reports_failure(tmp_path):
    """End-to-end: API start -> tool execution -> real pytest failure -> diagnosis."""
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / "test_broken.py").write_text("def test_real_failure():\n    assert 1 == 2\n", encoding="utf-8")
    client = TestClient(app)
    started = client.post("/api/agent/run", json={"path": str(tmp_path), "task": "Find and diagnose test failures."})
    assert started.status_code == 202
    run = wait_for_run(client, started.json()["agent_run_id"])
    assert run["status"] == "completed"
    assert {"list_files", "read_file", "search_code", "run_command", "run_tests", "git_status", "git_diff"}.issubset(run["tools_used"])
    assert run["test_results"]["exit_status"] != 0
    assert run["test_summary"]["failed"] == 1
    assert any(issue["issue"] == "Tests failed" for issue in run["issues"])
    assert "Tests did not pass" in run["diagnosis"]
    assert any(action["tool"] == "run_tests" for action in run["actions"])


def test_invalid_repository_is_rejected_before_agent_run():
    response = TestClient(app).post("/api/agent/run", json={"path": "this-directory-does-not-exist"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_repository"
