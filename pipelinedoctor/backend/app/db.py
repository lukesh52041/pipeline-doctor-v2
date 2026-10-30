"""SQLite storage. Swap this module for Postgres/Supabase in production; the rest of the app only calls these functions."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL, run_id TEXT, commit_sha TEXT, branch TEXT,
    status TEXT NOT NULL, duration_s INTEGER DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_pk INTEGER NOT NULL REFERENCES runs(id), repo TEXT NOT NULL,
    category TEXT NOT NULL, title TEXT NOT NULL, confidence REAL NOT NULL,
    source TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS test_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_pk INTEGER NOT NULL REFERENCES runs(id), repo TEXT NOT NULL, commit_sha TEXT,
    test_name TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_repo ON runs(repo, created_at);
CREATE INDEX IF NOT EXISTS idx_diag_repo ON diagnoses(repo, created_at);
CREATE INDEX IF NOT EXISTS idx_tests_repo ON test_results(repo, test_name);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


@contextmanager
def connect():
    path = get_settings().db_path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as c:
        c.executescript(SCHEMA)


def record_run(repo, run_id, commit_sha, branch, status, duration_s=0) -> int:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO runs (repo, run_id, commit_sha, branch, status, duration_s, created_at) VALUES (?,?,?,?,?,?,?)",
            (repo, run_id, commit_sha, branch, status, int(duration_s or 0), _now()),
        )
        return cur.lastrowid


def save_diagnosis(run_pk: int, repo: str, diag: dict) -> int:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO diagnoses (run_pk, repo, category, title, confidence, source, payload, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (run_pk, repo, diag["category"], diag["title"], diag["confidence"], diag["source"], json.dumps(diag), _now()),
        )
        return cur.lastrowid


def save_tests(run_pk: int, repo: str, commit_sha, tests: list) -> None:
    if not tests:
        return
    with connect() as c:
        c.executemany(
            "INSERT INTO test_results (run_pk, repo, commit_sha, test_name, status, created_at) VALUES (?,?,?,?,?,?)",
            [(run_pk, repo, commit_sha, t["name"], t["status"], _now()) for t in tests],
        )


def list_diagnoses(repo=None, limit=50) -> list:
    sql = "SELECT id, repo, category, title, confidence, source, created_at FROM diagnoses"
    args: list = []
    if repo:
        sql += " WHERE repo = ?"
        args.append(repo)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(min(max(limit, 1), 200))
    with connect() as c:
        return [dict(r) for r in c.execute(sql, args)]


def get_diagnosis(diag_id: int):
    with connect() as c:
        row = c.execute("SELECT id, payload, created_at FROM diagnoses WHERE id = ?", (diag_id,)).fetchone()
    if not row:
        return None
    data = json.loads(row["payload"])
    data["id"], data["created_at"] = row["id"], row["created_at"]
    return data


def run_counts(repo: str, days: int = 30) -> tuple:
    with connect() as c:
        row = c.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(status = 'failed'), 0) AS failed FROM runs WHERE repo = ? AND created_at >= ?",
            (repo, _since(days)),
        ).fetchone()
    return row["total"], row["failed"]


def failed_runs_with_titles(repo: str, days: int = 7) -> list:
    with connect() as c:
        rows = c.execute(
            "SELECT d.title, d.category, d.confidence, r.duration_s FROM diagnoses d JOIN runs r ON r.id = d.run_pk "
            "WHERE d.repo = ? AND d.created_at >= ?",
            (repo, _since(days)),
        )
        return [dict(r) for r in rows]


def test_rows(repo: str) -> list:
    with connect() as c:
        rows = c.execute(
            "SELECT t.test_name, t.status, t.commit_sha, t.run_pk, r.duration_s FROM test_results t "
            "JOIN runs r ON r.id = t.run_pk WHERE t.repo = ? ORDER BY t.id",
            (repo,),
        )
        return [dict(r) for r in rows]


def audit(actor: str, action: str, detail: str = "") -> None:
    with connect() as c:
        c.execute("INSERT INTO audit_logs (actor, action, detail, created_at) VALUES (?,?,?,?)",
                  (actor, action, detail, _now()))


def admin_stats() -> dict:
    with connect() as c:
        one = lambda sql: c.execute(sql).fetchone()[0]  # noqa: E731
        cats = [dict(r) for r in c.execute(
            "SELECT category, COUNT(*) AS count FROM diagnoses GROUP BY category ORDER BY count DESC")]
        return {
            "repos": one("SELECT COUNT(DISTINCT repo) FROM runs"),
            "runs": one("SELECT COUNT(*) FROM runs"),
            "diagnoses": one("SELECT COUNT(*) FROM diagnoses"),
            "average_confidence": round(one("SELECT COALESCE(AVG(confidence), 0) FROM diagnoses"), 2),
            "top_categories": cats[:6],
        }
