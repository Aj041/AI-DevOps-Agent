from fastapi.testclient import TestClient
from main import app

def test_health(): assert TestClient(app).get("/health").json()["status"] == "ok"

def test_analyze_endpoint(tmp_path):
	(tmp_path / "requirements.txt").write_text("pytest\n")
	response = TestClient(app).post("/api/repository/analyze", json={"path": str(tmp_path)})
	assert response.status_code == 200
	assert response.json()["language"] == "Python"
