from app.risk import score_risk


def test_small_safe_change_is_low():
    r = score_risk(["src/a.py", "tests/test_a.py"], additions=10, deletions=2)
    assert r["level"] == "low" and r["score"] < 30


def test_risky_change_is_high_and_explained():
    files = [".github/workflows/ci.yml", "requirements.txt", "src/a.py", "src/b.py"]
    r = score_risk(files, additions=500, deletions=200, recent_failure_rate=0.5)
    assert r["level"] == "high" and r["score"] <= 100
    assert any("test" in a.lower() for a in r["advice"])
    assert sum(f["points"] for f in r["factors"]) >= r["score"] - 1


def test_missing_tests_only_penalized_when_source_changed():
    assert score_risk(["README.md"])["factors"][4]["points"] == 0
    assert score_risk(["src/a.py"])["factors"][4]["points"] == 15
