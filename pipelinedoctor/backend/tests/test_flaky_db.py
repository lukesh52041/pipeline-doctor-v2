import asyncio

from app import db, flaky, report
from app.diagnose import diagnose
from app.samples import get_sample


def seed(sample_id):
    s = get_sample(sample_id)
    m = s["meta"]
    run_pk = db.record_run(m["repo"], sample_id, m["commit_sha"], "main", "failed", m["duration_s"])
    d = asyncio.run(diagnose(s["log"], use_llm=False))
    tests = d.pop("tests")
    db.save_diagnosis(run_pk, m["repo"], d)
    db.save_tests(run_pk, m["repo"], m["commit_sha"], tests)
    return m["repo"]


def test_parse_test_results():
    lines = ["tests/a.py::t1 PASSED", "FAILED tests/a.py::t2 - boom", "tests/a.py::t2 FAILED"]
    assert flaky.parse_test_results(lines) == [
        {"name": "tests/a.py::t1", "status": "PASSED"}, {"name": "tests/a.py::t2", "status": "FAILED"}]


def test_same_commit_pass_and_fail_is_flaky_and_reported():
    db.init_db()
    seed("flaky-run-a")
    repo = seed("flaky-run-b")
    found = flaky.detect_flaky(repo)
    assert [f["test"] for f in found] == ["tests/test_checkout.py::test_payment_timeout"]
    assert found[0]["reason"].startswith("Passed and failed on the same commit")
    rep = report.weekly_report(repo)
    assert rep["failed_runs"] == 2 and rep["flaky_tests"] and rep["fix_list"]


def test_stable_failure_is_not_flaky():
    db.init_db()
    for _ in range(3):
        seed("flaky-run-b")
    assert flaky.detect_flaky("demo/shop") == []
