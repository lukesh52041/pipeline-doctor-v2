"""Diagnosis engine: redact -> rules -> (optional) AI -> validate -> merge.

Every claim carries evidence lines taken from the real log. If nothing is convincing,
the result is labelled "uncertain" instead of guessing.
"""
import asyncio
import logging
import os
import time

from .config import get_settings
from .flaky import parse_test_results
from .llm import ERROR_RE, llm_diagnose
from .parsers import CATEGORIES, Finding, match_rules, render
from .redact import redact
from .tinyfish_service import generate_search_query, perform_research

log = logging.getLogger("pipelinedoctor.diagnose")

CONFIDENT = 0.8
UNCERTAIN_BELOW = 0.5
LLM_CONFIDENCE_CAP = 0.9


def _evidence(lines: list, numbers: list) -> list:
    return [{"line": n, "text": lines[n - 1][:300]} for n in numbers if 1 <= n <= len(lines)]


def _from_rule(best: Finding, lines: list, findings: list) -> dict:
    rule, x = best.rule, best.x
    return {
        "category": rule.category,
        "title": rule.title,
        "root_cause": render(rule.cause, x),
        "confidence": round(best.confidence, 2),
        "source": "rules",
        "evidence": _evidence(lines, best.lines),
        "fix_steps": [render(s, x) for s in rule.fixes],
        "suggested_diff": render(rule.diff, x),
        "next_checks": list(rule.checks),
        "other_candidates": [
            {"title": f.rule.title, "category": f.rule.category, "confidence": round(f.confidence, 2)}
            for f in findings[1:4]
        ],
    }


def _unknown(lines: list) -> dict:
    hits = [i + 1 for i, line in enumerate(lines) if ERROR_RE.search(line)][-5:]
    if not hits:
        hits = [i + 1 for i, line in enumerate(lines) if line.strip()][-3:]
    return {
        "category": "unknown",
        "title": "Couldn't determine the cause",
        "root_cause": "No known failure pattern matched, and no AI analysis was available for this log.",
        "confidence": 0.2,
        "source": "uncertain",
        "evidence": _evidence(lines, hits),
        "fix_steps": ["Find the first error in the log, not the last. Later errors are often side effects.",
                      "Re-run with debug logging (set the ACTIONS_STEP_DEBUG secret to true)."],
        "suggested_diff": "",
        "next_checks": [],
        "other_candidates": [],
    }


def _validate_llm(data, lines: list):
    """Never trust the model's text for evidence. Keep only real line numbers and read the text from the log."""
    if not isinstance(data, dict):
        return None
    try:
        confidence = max(0.0, min(float(data.get("confidence", 0)), LLM_CONFIDENCE_CAP))
    except (TypeError, ValueError):
        return None
    numbers = []
    for n in data.get("evidence_lines", []) if isinstance(data.get("evidence_lines"), list) else []:
        if isinstance(n, int) and 1 <= n <= len(lines) and n not in numbers:
            numbers.append(n)
    if not numbers:  # an answer with no verifiable evidence is capped low
        confidence = min(confidence, 0.4)
    category = data.get("category") if data.get("category") in CATEGORIES else "unknown"

    def strings(key):
        v = data.get(key)
        return [str(s)[:400] for s in v][:8] if isinstance(v, list) else []

    return {
        "category": category,
        "title": str(data.get("title") or "AI diagnosis")[:120],
        "root_cause": str(data.get("root_cause") or "")[:600],
        "confidence": round(confidence, 2),
        "source": "llm",
        "evidence": _evidence(lines, numbers[:6]),
        "fix_steps": strings("fix_steps"),
        "suggested_diff": str(data.get("suggested_diff") or "")[:2000],
        "next_checks": strings("next_checks"),
        "other_candidates": [],
    }


def _merge(rule_result, llm_result):
    if rule_result and llm_result:
        if llm_result["category"] == rule_result["category"]:
            rule_result["source"] = "rules+llm"
            rule_result["confidence"] = max(rule_result["confidence"], llm_result["confidence"])
            seen = {e["line"] for e in rule_result["evidence"]}
            rule_result["evidence"] += [e for e in llm_result["evidence"] if e["line"] not in seen]
            rule_result["evidence"].sort(key=lambda e: e["line"])
            rule_result["fix_steps"] += [s for s in llm_result["fix_steps"] if s not in rule_result["fix_steps"]]
            rule_result["suggested_diff"] = rule_result["suggested_diff"] or llm_result["suggested_diff"]
            return rule_result
        if llm_result["confidence"] > rule_result["confidence"]:
            llm_result["other_candidates"] = [
                {"title": rule_result["title"], "category": rule_result["category"],
                 "confidence": rule_result["confidence"]}]
            return llm_result
        return rule_result
    return llm_result or rule_result


async def diagnose(raw_log: str, use_llm: bool = True, force_llm: bool = False, use_research: bool = True) -> dict:
    started = time.perf_counter()
    redacted, counts = redact(raw_log)
    lines = redacted.split("\n")
    findings = match_rules(lines)
    best = findings[0] if findings else None
    rule_result = _from_rule(best, lines, findings) if best else None

    llm_result = None
    if use_llm and (force_llm or best is None or best.confidence < CONFIDENT):
        llm_result = _validate_llm(await llm_diagnose(lines, findings), lines)

    result = _merge(rule_result, llm_result) or _unknown(lines)
    result["status"] = "uncertain" if result["confidence"] < UNCERTAIN_BELOW else "ok"
    if result["status"] == "uncertain":
        result["source"] = "uncertain" if result["source"] == "rules" else result["source"]
        result["next_checks"] = result["next_checks"] + [
            "Share the full log from the first failing step, not just the tail, so the cause can be located."]
    result["redaction"] = {"total": sum(counts.values()), "by_type": counts}
    result["line_count"] = len(lines)
    result["took_ms"] = round((time.perf_counter() - started) * 1000)
    result["tests"] = parse_test_results(lines)

    settings = get_settings()
    api_key = os.getenv("TINYFISH_API_KEY") or settings.tinyfish_api_key
    meaningful_category = bool(result.get("category") and result["category"] != "unknown")

    if use_research and settings.tinyfish_enabled and api_key and meaningful_category:
        query = generate_search_query(result)
        try:
            res_data = await asyncio.to_thread(
                perform_research,
                query,
                location=settings.tinyfish_location,
                language=settings.tinyfish_language,
                api_key=api_key,
            )
            result["research"] = res_data
        except Exception as exc:
            log.warning("TinyFish research execution failed: %s", exc)
            result["research"] = {
                "success": False,
                "query": query,
                "results": [],
                "error": "External research is temporarily unavailable. Your PipelineDoctor diagnosis is still available.",
            }
    elif use_research and settings.tinyfish_enabled and not api_key:
        result["research"] = {
            "success": False,
            "query": generate_search_query(result) if meaningful_category else "",
            "results": [],
            "error": "TinyFish API key is not configured.",
        }
    else:
        result["research"] = None

    return result
