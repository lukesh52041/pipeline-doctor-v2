"""Pull request risk score with a per-factor breakdown. Every point is explained."""
import re

CODE_EXT = (".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".rb", ".rs", ".c", ".cpp", ".h",
            ".cs", ".php", ".kt", ".swift")
CI_MARKERS = (".github/workflows/", "dockerfile", "docker-compose", "jenkinsfile", ".gitlab-ci")
DEP_MARKERS = ("requirements", "pyproject.toml", "poetry.lock", "pipfile", "package.json", "package-lock.json",
               "yarn.lock", "pnpm-lock.yaml", "go.mod", "go.sum", "cargo.toml", "cargo.lock", "pom.xml",
               "build.gradle")
_TEST_RE = re.compile(r"(^|/)(tests?|__tests__|specs?)/|(^|/)test_|_test\.|\.test\.|\.spec\.")


def is_test(path: str) -> bool:
    return bool(_TEST_RE.search(path.lower()))


def is_source(path: str) -> bool:
    return path.lower().endswith(CODE_EXT) and not is_test(path)


def _factor(name, points, maximum, detail):
    return {"name": name, "points": round(points, 1), "max": maximum, "detail": detail}


def score_risk(files: list, additions: int = 0, deletions: int = 0, recent_failure_rate: float = 0.0) -> dict:
    lower = [f.lower() for f in files]
    changed_lines = max(0, additions) + max(0, deletions)
    sources = [f for f in files if is_source(f)]
    tests = [f for f in files if is_test(f)]
    ci = [f for f, low in zip(files, lower) if any(m in low for m in CI_MARKERS)]
    deps = [f for f, low in zip(files, lower) if any(m in low.rsplit("/", 1)[-1] for m in DEP_MARKERS)]
    rate = min(max(recent_failure_rate, 0.0), 1.0)

    factors = [
        _factor("Change size", min(25, changed_lines / 20), 25, f"{changed_lines} lines changed"),
        _factor("Files touched", min(15, len(files) * 1.5), 15, f"{len(files)} files"),
        _factor("CI or Docker config", 15 if ci else 0, 15,
                ", ".join(ci[:3]) if ci else "No pipeline config changed"),
        _factor("Dependencies", 15 if deps else 0, 15,
                ", ".join(deps[:3]) if deps else "No dependency files changed"),
        _factor("Tests", 15 if sources and not tests else 0, 15,
                "Source changed with no test changes" if sources and not tests else "Tests updated or no source changed"),
        _factor("Recent failures", min(15, rate * 30), 15, f"{round(rate * 100)}% of recent runs failed"),
    ]
    total = round(min(100, sum(f["points"] for f in factors)))
    level = "low" if total < 30 else "medium" if total < 60 else "high"

    advice = []
    if ci:
        advice.append("Test the pipeline change on a branch before merging.")
    if deps:
        advice.append("Check the lockfile diff and run a clean install.")
    if sources and not tests:
        advice.append("Add or update a test for the changed code.")
    if changed_lines > 400:
        advice.append("Consider splitting this change into smaller pull requests.")
    return {"score": total, "level": level, "factors": factors, "advice": advice}
