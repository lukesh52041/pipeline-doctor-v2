"""Deterministic, rule-based failure detection. Fast, free, and easy to audit."""
import re
from dataclasses import dataclass

CATEGORIES = {
    "dependency", "config", "test", "build", "permissions", "infra", "timeout", "lint", "unknown",
}


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    title: str
    patterns: tuple
    cause: str
    fixes: tuple
    checks: tuple
    confidence: float
    diff: str = ""
    default_x: str = "the missing item"


@dataclass
class Finding:
    rule: Rule
    lines: list
    x: str
    confidence: float


def _r(*patterns):
    return tuple(re.compile(p, re.I) for p in patterns)


PERMISSIONS_DIFF = """--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@
+permissions:
+  contents: read
+  pull-requests: write   # add only the scopes the failing step needs"""

TIMEOUT_DIFF = """--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@
 jobs:
   build:
+    timeout-minutes: 30"""

ERESOLVE_DIFF = """--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@
-      - run: npm ci
+      - run: npm ci --legacy-peer-deps   # workaround, not a fix"""

RULES = (
    Rule(
        "git-auth", "permissions", "Git authentication failed",
        _r(r"Authentication failed", r"could not read Username", r"fatal: repository .* not found",
           r"Permission denied \(publickey\)"),
        "git couldn't authenticate to the remote repository.",
        ("Use actions/checkout with a token that can read the repository.",
         "Private submodules and private dependencies need a personal access token, a deploy key, or a GitHub App token.",
         "Check that the token hasn't expired."),
        ("Is the repository private or in another organization?",
         "Does the workflow run on a pull request from a fork? Forks don't receive secrets."),
        0.9,
    ),
    Rule(
        "py-missing-module", "dependency", "Missing Python module",
        _r(r"ModuleNotFoundError: No module named ['\"](?P<x>[^'\"]+)['\"]",
           r"ImportError: No module named (?P<x>\S+)"),
        "The code imports `{x}`, but it isn't installed in the CI environment.",
        ("Add the package that provides `{x}` to requirements.txt (or pyproject.toml).",
         "Make sure the install step runs before the failing step.",
         "If dependencies are cached, change the cache key so they reinstall."),
        ("The import name and the pip package name can differ (for example, `yaml` comes from PyYAML).",
         "Check that it works in a clean virtualenv on your machine."),
        0.92,
        "--- a/requirements.txt\n+++ b/requirements.txt\n@@\n+{x}",
        "the module",
    ),
    Rule(
        "py-version", "dependency", "No matching Python package version",
        _r(r"Could not find a version that satisfies the requirement (?P<x>\S+)",
           r"requires a different Python"),
        "pip couldn't find a release of `{x}` that works with this Python version.",
        ("Check which Python versions the package supports and match `python-version` in the workflow.",
         "Loosen or correct the version pin in requirements.txt."),
        ("Is the package published on the index you're using?",),
        0.88,
        "",
        "the package",
    ),
    Rule(
        "npm-eresolve", "dependency", "npm dependency conflict",
        _r(r"npm (?:ERR!|error) code ERESOLVE", r"ERESOLVE (?:unable to resolve|could not resolve)"),
        "Two packages need incompatible versions of the same dependency, so npm refuses to install.",
        ("Read the 'Found:' and 'Could not resolve dependency' lines to see which packages clash.",
         "Upgrade or pin one side so the version ranges overlap.",
         "Short-term workaround: install with --legacy-peer-deps. This hides the conflict; it doesn't fix it."),
        ("Did a recent dependency or Node version upgrade introduce this?",),
        0.93,
        ERESOLVE_DIFF,
    ),
    Rule(
        "node-missing-module", "dependency", "Missing Node module",
        _r(r"Cannot find module ['\"](?P<x>[^'\"]+)['\"]", r"Module not found: Error: Can't resolve ['\"](?P<x>[^'\"]+)['\"]"),
        "The build imports `{x}`, but it can't be found.",
        ("Run `npm install {x}` (use --save-dev for build tools) and commit package.json and the lockfile.",
         "If `{x}` is a relative path, check the file name's letter case. CI runs on Linux, which is case-sensitive."),
        ("Is the package listed in dependencies, or only installed on your machine?",),
        0.88,
        "",
        "a module",
    ),
    Rule(
        "npm-missing-script", "config", "Missing npm script",
        _r(r"Missing script: ['\"]?(?P<x>[\w:.-]+)['\"]?"),
        "package.json has no `{x}` script, but the workflow runs it.",
        ("Add a `{x}` entry under \"scripts\" in package.json, or change the workflow to call an existing script.",),
        ("Does the workflow run from the right working-directory?",),
        0.93,
        "",
        "the requested",
    ),
    Rule(
        "workflow-yaml", "config", "Invalid workflow file",
        _r(r"Invalid workflow file", r"yaml: line \d+", r"Unexpected value '[^']+'"),
        "GitHub couldn't parse the workflow file.",
        ("Check indentation and key names near the line the error points to.",
         "Validate the file with actionlint before pushing."),
        ("Did you copy the workflow from a different CI system?",),
        0.9,
    ),
    Rule(
        "missing-secret", "config", "Missing input or secret",
        _r(r"Input required and not supplied: (?P<x>\S+)",
           r"(?P<x>\b[A-Z][A-Z0-9_]{3,}) (?:is|are) (?:not set|undefined|missing)"),
        "`{x}` was empty when the step ran. It's usually a secret or variable that isn't defined or isn't available to this workflow.",
        ("Define it under Settings > Secrets and variables > Actions.",
         "Check that the name in the workflow matches the secret's name exactly.",
         "Secrets aren't passed to workflows triggered by pull requests from forks."),
        ("Is the workflow running on a fork or on Dependabot's branch?",),
        0.86,
        "",
        "a required value",
    ),
    Rule(
        "port-in-use", "infra", "Port already in use",
        _r(r"EADDRINUSE.*?:(?P<x>\d{2,5})", r"address already in use"),
        "Another process is already listening on port {x}.",
        ("Stop the duplicate service. A service container or an earlier background step may already own that port.",
         "Use a different port, or port 0 so the OS picks a free one."),
        ("Do two jobs or steps start the same server?",),
        0.9,
        "",
        "the required port",
    ),
    Rule(
        "oom", "infra", "Out of memory",
        _r(r"exit code 137", r"JavaScript heap out of memory", r"\bMemoryError\b", r"\bOOMKilled\b",
           r"(?:^|\s)Killed\s*$"),
        "The process was stopped for using more memory than the runner has.",
        ("Lower parallelism (for example, `pytest -n 2` or `jest --maxWorkers=2`).",
         "For Node builds, raise the heap limit with NODE_OPTIONS=--max-old-space-size=4096.",
         "Move the job to a larger runner if it genuinely needs the memory."),
        ("Did memory use grow after a recent dependency or data-size change?",),
        0.88,
    ),
    Rule(
        "docker-build", "build", "Docker build failed",
        _r(r"failed to solve", r"executor failed running", r"returned a non-zero code: \d+"),
        "A step in the Dockerfile failed, so the image couldn't be built.",
        ("Find the first failing RUN line and run that command locally in the same base image.",
         "Pin the base image tag so it doesn't change under you.",
         "Check that COPY paths exist and aren't excluded by .dockerignore."),
        ("Did the base image tag change recently?",),
        0.8,
    ),
    Rule(
        "permissions", "permissions", "Permission denied",
        _r(r"Resource not accessible by integration", r"Permission denied", r"\bEACCES\b",
           r"HTTP 403", r"403 Forbidden"),
        "The job tried to do something its token or user isn't allowed to do.",
        ("If the error says 'Resource not accessible by integration', grant the scope the step needs in a `permissions:` block.",
         "For a script that isn't executable, run `chmod +x` on it before the step.",
         "Pull requests from forks get a read-only token by design."),
        ("Which API call or file does the failing step touch?",
         "Does this only fail on pull requests from forks?"),
        0.82,
        PERMISSIONS_DIFF,
    ),
    Rule(
        "timeout", "timeout", "Step or job timed out",
        _r(r"exceeded the maximum execution time", r"Timeout of \d+\s*ms exceeded", r"timed out after",
           r"\bETIMEDOUT\b", r"The operation was canceled"),
        "Something ran past its time limit, or a network call never answered.",
        ("Find which step is slow. Compare its duration with earlier successful runs.",
         "Add `timeout-minutes` so a hang fails fast instead of burning minutes.",
         "Retry only network steps, not the whole job."),
        ("Is the step hanging, or just slower than before?",
         "'The operation was canceled' can also mean someone cancelled the run by hand."),
        0.72,
        TIMEOUT_DIFF,
    ),
    Rule(
        "lint", "lint", "Lint or type check failed",
        _r(r"✖ \d+ problems?", r"Found \d+ errors? in \d+ files?", r"error TS\d+:"),
        "The linter or type checker reported errors, which fail the job.",
        ("Run the same lint command locally and fix the reported lines.",
         "Add a pre-commit hook so this is caught before pushing."),
        ("Did a linter or TypeScript version bump add new rules?",),
        0.8,
    ),
    Rule(
        "pytest-failure", "test", "Test failure",
        _r(r"^(?:\S+Z\s+)?FAILED\s+(?P<x>\S+)", r"\b\d+ failed\b", r"AssertionError"),
        "Tests failed: {x}. This points to a code or test problem rather than the environment.",
        ("Read the assertion message under the first failing test.",
         "Re-run just that test locally with `pytest -x -k <name>`.",
         "If it passes on a re-run with no code change, it may be flaky. See the flaky test report."),
        ("Did the failing test touch time, randomness, network, or shared state?",),
        0.78,
        "",
        "see the evidence lines",
    ),
    Rule(
        "jest-failure", "test", "JavaScript test failure",
        _r(r"Tests:\s+\d+ failed", r"^\s*●\s+.+›", r"FAIL\s+(?P<x>\S+\.(?:test|spec)\.\S+)"),
        "Tests failed: {x}. This points to a code or test problem rather than the environment.",
        ("Read the expected/received diff under the first failing test.",
         "Re-run that file locally with `npx jest <file>`."),
        ("Did snapshot files change?",),
        0.78,
        "",
        "see the evidence lines",
    ),
)

_MAX_EVIDENCE = 6


def match_rules(lines: list) -> list:
    """Return findings sorted by confidence (highest first)."""
    findings = []
    for order, rule in enumerate(RULES):
        hits, x = [], ""
        for number, line in enumerate(lines, 1):
            for pattern in rule.patterns:
                m = pattern.search(line)
                if m:
                    hits.append(number)
                    if not x:
                        x = m.groupdict().get("x") or ""
                    break
        if not hits:
            continue
        if rule.id == "py-missing-module":
            x = x.split(".")[0]
        confidence = min(0.97, rule.confidence + 0.03 * min(len(hits) - 1, 3))
        findings.append((confidence, -order, Finding(rule, hits[:_MAX_EVIDENCE], x or rule.default_x, confidence)))
    findings.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [f for _, _, f in findings]


def render(template: str, x: str) -> str:
    return template.replace("{x}", x)
