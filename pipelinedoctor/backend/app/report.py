"""Weekly reliability report for one repo."""
from collections import Counter, defaultdict

from . import db
from .flaky import detect_flaky


def weekly_report(repo: str, days: int = 7) -> dict:
    rows = db.failed_runs_with_titles(repo, days)
    total_runs, failed_runs = db.run_counts(repo, days)
    groups = defaultdict(lambda: {"count": 0, "seconds": 0, "category": ""})
    for r in rows:
        g = groups[r["title"]]
        g["count"] += 1
        g["seconds"] += r["duration_s"] or 0
        g["category"] = r["category"]

    ranked = sorted(groups.items(), key=lambda kv: (kv[1]["seconds"], kv[1]["count"]), reverse=True)
    fix_list = [
        {"title": t, "category": g["category"], "occurrences": g["count"], "minutes_lost": round(g["seconds"] / 60, 1)}
        for t, g in ranked
    ]
    return {
        "repo": repo,
        "days": days,
        "runs": total_runs,
        "failed_runs": failed_runs,
        "failure_rate": round(failed_runs / total_runs, 2) if total_runs else 0.0,
        "by_category": dict(Counter(r["category"] for r in rows)),
        "fix_list": fix_list[:8],
        "minutes_avoidable_if_top3_fixed": round(sum(f["minutes_lost"] for f in fix_list[:3]), 1),
        "flaky_tests": detect_flaky(repo)[:5],
    }
