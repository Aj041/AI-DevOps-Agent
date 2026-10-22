from repository.analyzer import analyze_repository

def test_analyzer_detects_python_stack(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n")
    (tmp_path / "README.md").write_text("demo")
    report = analyze_repository(str(tmp_path))
    assert report["language"] == "Python"
    assert report["important_files"]["README.md"] is True
