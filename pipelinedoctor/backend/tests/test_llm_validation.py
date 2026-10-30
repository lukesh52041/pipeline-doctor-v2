from app.diagnose import _merge, _validate_llm

LINES = ["a", "b", "c"]


def test_invalid_line_numbers_are_dropped_and_confidence_capped():
    d = _validate_llm({"category": "test", "title": "x", "root_cause": "y", "confidence": 0.99,
                       "evidence_lines": [99, "x", -1]}, LINES)
    assert d["evidence"] == [] and d["confidence"] <= 0.4


def test_evidence_text_comes_from_log_not_model():
    d = _validate_llm({"category": "build", "confidence": 0.8, "evidence_lines": [2],
                       "title": "t", "root_cause": "r"}, LINES)
    assert d["evidence"] == [{"line": 2, "text": "b"}] and d["confidence"] == 0.8


def test_unknown_category_and_bad_confidence():
    assert _validate_llm({"category": "made-up", "confidence": 0.5, "evidence_lines": [1]}, LINES)["category"] == "unknown"
    assert _validate_llm({"confidence": "high"}, LINES) is None
    assert _validate_llm("not a dict", LINES) is None


def test_merge_prefers_higher_confidence_when_categories_differ():
    rule = {"category": "test", "title": "R", "confidence": 0.6, "evidence": [], "fix_steps": [],
            "suggested_diff": "", "source": "rules"}
    llm = {"category": "infra", "title": "L", "confidence": 0.85, "evidence": [], "fix_steps": [],
           "suggested_diff": "", "source": "llm", "other_candidates": []}
    assert _merge(rule, llm)["title"] == "L"
