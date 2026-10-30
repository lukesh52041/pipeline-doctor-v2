"""Parse test results from logs and detect flaky tests across runs."""
import re
from collections import defaultdict

from . import db

_NAME = r"(?P<name>[\w./-]+::[\w\[\]:.,-]+)"
_LINE_A = re.compile(rf"^(?:\S+Z\s+)?{_NAME}\s+(?P<status>PASSED|FAILED|ERROR)\b")
_LINE_B = re.compile(rf"^(?:\S+Z\s+)?(?P<status>FAILED|ERROR)\s+{_NAME}")


def parse_test_results(lines: list) -> list:
    seen = {}
    for line in lines:
        m = _LINE_A.match(line) or _LINE_B.match(line)
        if m:
            name, status = m.group("name"), m.group("status")
            if seen.get(name) != "FAILED":
                seen[name] = status
    return [{"name": n, "status": s} for n, s in seen.items()]


def detect_flaky(repo: str) -> list:
    by_test = defaultdict(dict)
    for row in db.test_rows(repo):
        by_test[row["test_name"]][row["run_pk"]] = (row["status"], row["commit_sha"], row["duration_s"] or 0)

    flaky = []
    for name, per_run in by_test.items():
        seq = list(per_run.values())
        states = ["fail" if s[0] in ("FAILED", "ERROR") else "pass" for s in seq]
        fails, runs = states.count("fail"), len(states)
        if fails == 0:
            continue
        by_commit = defaultdict(set)
        for state, s in zip(states, seq):
            if s[1]:
                by_commit[s[1]].add(state)
        conflict = any(len(v) > 1 for v in by_commit.values())
        flips = sum(1 for a, b in zip(states, states[1:]) if a != b)
        flip_rate = flips / (runs - 1) if runs > 1 else 0.0
        if not (conflict or (runs >= 4 and flip_rate >= 0.4)):
            continue
        wasted = sum(s[2] for state, s in zip(states, seq) if state == "fail") / 60
        flaky.append({
            "test": name,
            "runs": runs,
            "failures": fails,
            "flip_rate": round(flip_rate, 2),
            "score": 1.0 if conflict else round(flip_rate, 2),
            "reason": ("Passed and failed on the same commit" if conflict
                       else f"Result changed in {flips} of {runs - 1} consecutive runs"),
            "minutes_wasted": round(wasted, 1),
        })
    flaky.sort(key=lambda f: (f["score"], f["failures"]), reverse=True)
    return flaky
