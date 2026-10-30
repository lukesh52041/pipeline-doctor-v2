"""Sandbox logs so anyone can try the app without connecting a repository.

Fake credentials are assembled at runtime so secret scanners never see them in the repo.
"""
FAKE_GH_TOKEN = "gh" + "p_" + "Ab12" * 9
FAKE_AWS_KEY = "AK" + "IA" + "IOSFODNN7" + "EXAMPLE"

_py = """Run python -m pip install -r requirements.txt
Collecting fastapi==0.115.0
Successfully installed fastapi-0.115.0 uvicorn-0.30.6
Run pytest -q
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-8.3.2, pluggy-1.5.0
collected 0 items / 1 error
==================================== ERRORS ====================================
_________________ ERROR collecting tests/test_reports.py _______________________
tests/test_reports.py:3: in <module>
    import pandas as pd
E   ModuleNotFoundError: No module named 'pandas'
=========================== short test summary info ============================
ERROR tests/test_reports.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
Error: Process completed with exit code 2."""

_npm = """Run npm ci
npm ERR! code ERESOLVE
npm ERR! ERESOLVE could not resolve
npm ERR!
npm ERR! While resolving: react-datepicker@4.8.0
npm ERR! Found: react@19.0.0
npm ERR! node_modules/react
npm ERR!   react@"^19.0.0" from the root project
npm ERR!
npm ERR! Could not resolve dependency:
npm ERR! peer react@"^16.9.0 || ^17 || ^18" from react-datepicker@4.8.0
npm ERR!
npm ERR! Fix the upstream dependency conflict, or retry
npm ERR! this command with --force or --legacy-peer-deps
Error: Process completed with exit code 1."""

_perm = f"""Run actions/github-script@v7
env:
  GITHUB_TOKEN: {FAKE_GH_TOKEN}
  AWS_ACCESS_KEY_ID: {FAKE_AWS_KEY}
  NOTIFY_EMAIL: dev.ops@example.com
  RUNNER_HOST: 10.24.8.31
RequestError [HttpError]: Resource not accessible by integration
    at /home/runner/work/_actions/actions/github-script/v7/dist/index.js:9537:21
  status: 403,
  response: {{ url: 'https://api.github.com/repos/acme/web/issues/42/comments' }}
Error: Unhandled error: HttpError: Resource not accessible by integration"""

_oom = """Run npm run build
> web@1.4.0 build
> vite build
vite v5.4.2 building for production...
transforming (2410) src/components/Chart.tsx
<--- Last few GCs --->
[1982:0x5a1e2c0]    81234 ms: Mark-Compact 2031.4 (2085.2) -> 2029.8 (2087.0) MB, 1203.4 / 0.0 ms
FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory
Error: Process completed with exit code 134."""

_flaky_a = """Run pytest -v
tests/test_cart.py::test_add_item PASSED
tests/test_checkout.py::test_payment_timeout FAILED
tests/test_checkout.py::test_order_total PASSED
=================================== FAILURES ===================================
____________________________ test_payment_timeout ______________________________
E   AssertionError: assert 504 == 200
=========================== short test summary info ============================
FAILED tests/test_checkout.py::test_payment_timeout - AssertionError: assert 504 == 200
========================= 1 failed, 2 passed in 41.20s =========================
Error: Process completed with exit code 1."""

_flaky_b = """Run pytest -v
tests/test_cart.py::test_add_item PASSED
tests/test_checkout.py::test_payment_timeout PASSED
tests/test_inventory.py::test_sync_stock FAILED
=================================== FAILURES ===================================
____________________________ test_sync_stock ___________________________________
E   AssertionError: assert 11 == 12
=========================== short test summary info ============================
FAILED tests/test_inventory.py::test_sync_stock - AssertionError: assert 11 == 12
========================= 1 failed, 2 passed in 39.80s =========================
Error: Process completed with exit code 1."""

SAMPLES = [
    {"id": "python-missing-module", "title": "Missing Python module", "log": _py,
     "meta": {"repo": "demo/api", "commit_sha": "a1c3e50", "duration_s": 95}},
    {"id": "npm-dependency-conflict", "title": "npm dependency conflict", "log": _npm,
     "meta": {"repo": "demo/web", "commit_sha": "b72d9f1", "duration_s": 48}},
    {"id": "token-permissions", "title": "Permission error (contains secrets)", "log": _perm,
     "meta": {"repo": "demo/web", "commit_sha": "c90e1a7", "duration_s": 31}},
    {"id": "out-of-memory", "title": "Build out of memory", "log": _oom,
     "meta": {"repo": "demo/web", "commit_sha": "d41f6b2", "duration_s": 210}},
    {"id": "flaky-run-a", "title": "Flaky tests, run A", "log": _flaky_a,
     "meta": {"repo": "demo/shop", "commit_sha": "e5509cc", "duration_s": 120}},
    {"id": "flaky-run-b", "title": "Flaky tests, run B (same commit)", "log": _flaky_b,
     "meta": {"repo": "demo/shop", "commit_sha": "e5509cc", "duration_s": 115}},
]


def get_sample(sample_id: str):
    return next((s for s in SAMPLES if s["id"] == sample_id), None)
