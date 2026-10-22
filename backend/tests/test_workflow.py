from agent.workflow import detect_issues, generate_ci, generate_dockerfile

def test_issue_detection_and_ci(tmp_path):
    report = {"important_files": {"Dockerfile": False, ".env": False, ".env.example": False}, "workflows": [], "language": "Python"}
    issues = detect_issues(report, None)
    assert {issue["issue"] for issue in issues} == {"Missing Dockerfile", "Missing CI workflow"}
    assert "pytest" in generate_ci(report)
    assert "python:3.12-slim" in generate_dockerfile(report)