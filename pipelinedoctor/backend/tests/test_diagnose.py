import asyncio

import pytest

from app.diagnose import diagnose
from app.parsers import match_rules
from app.samples import SAMPLES, get_sample


def run(log, **kw):
    return asyncio.run(diagnose(log, use_llm=False, **kw))


@pytest.mark.parametrize("sample_id,category,title_part", [
    ("python-missing-module", "dependency", "Missing Python module"),
    ("npm-dependency-conflict", "dependency", "npm dependency conflict"),
    ("token-permissions", "permissions", "Permission denied"),
    ("out-of-memory", "infra", "Out of memory"),
    ("flaky-run-a", "test", "Test failure"),
])
def test_samples_are_diagnosed(sample_id, category, title_part):
    d = run(get_sample(sample_id)["log"])
    assert d["category"] == category and title_part in d["title"]
    assert d["evidence"], "every diagnosis must cite evidence"
    assert d["confidence"] >= 0.7 and d["status"] == "ok"


def test_python_module_is_named_in_cause_and_diff():
    d = run(get_sample("python-missing-module")["log"])
    assert "pandas" in d["root_cause"] and "+pandas" in d["suggested_diff"]


def test_evidence_text_matches_the_log_line():
    log = get_sample("python-missing-module")["log"]
    lines = log.split("\n")
    for e in run(log)["evidence"]:
        assert lines[e["line"] - 1][:300] == e["text"]


def test_secrets_never_appear_in_output():
    d = run(get_sample("token-permissions")["log"])
    assert d["redaction"]["total"] >= 4
    assert "ghp_" not in str(d)


def test_unknown_log_is_labelled_uncertain():
    d = run("step one\nstep two\nsomething odd happened")
    assert d["status"] == "uncertain" and d["category"] == "unknown" and d["confidence"] < 0.5


def test_ranking_prefers_specific_rule_over_generic_test_failure():
    findings = match_rules(get_sample("python-missing-module")["log"].split("\n"))
    assert findings[0].rule.id == "py-missing-module"


def test_every_sample_runs():
    for s in SAMPLES:
        assert run(s["log"])["line_count"] > 0
