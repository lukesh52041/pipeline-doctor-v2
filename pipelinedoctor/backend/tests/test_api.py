import hashlib
import hmac
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.samples import get_sample  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health_and_index(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert "PipelineDoctor" in client.get("/").text


def test_diagnose_roundtrip(client):
    s = get_sample("python-missing-module")
    r = client.post("/api/diagnose", json={"log": s["log"], **s["meta"], "use_llm": False})
    assert r.status_code == 200
    body = r.json()
    assert body["category"] == "dependency" and body["id"]
    assert client.get(f"/api/diagnoses/{body['id']}").json()["title"] == body["title"]
    assert client.get("/api/diagnoses", params={"repo": s["meta"]["repo"]}).json()


def test_empty_log_rejected(client):
    assert client.post("/api/diagnose", json={"log": ""}).status_code == 422


def test_oversized_log_rejected(client, monkeypatch):
    monkeypatch.setenv("MAX_LOG_BYTES", "10")
    assert client.post("/api/diagnose", json={"log": "x" * 50}).status_code == 413


def test_risk_endpoint(client):
    r = client.post("/api/risk", json={"files": ["src/a.py"], "additions": 30})
    assert r.status_code == 200 and r.json()["level"] in {"low", "medium", "high"}


def test_roles_are_enforced(client, monkeypatch):
    monkeypatch.setenv("API_KEYS", "dev-key:developer,boss-key:admin")
    assert client.get("/api/admin/stats").status_code == 401
    assert client.get("/api/admin/stats", headers={"X-API-Key": "nope"}).status_code == 401
    denied = client.get("/api/admin/stats", headers={"X-API-Key": "dev-key"})
    assert denied.status_code == 403 and "Access denied" in denied.json()["detail"]
    assert client.get("/api/admin/stats", headers={"X-API-Key": "boss-key"}).status_code == 200


def test_webhook_signature(client, monkeypatch):
    assert client.post("/webhooks/github", content=b"{}").status_code == 503
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    body = json.dumps({"action": "requested"}).encode()
    assert client.post("/webhooks/github", content=body,
                       headers={"X-Hub-Signature-256": "sha256=bad", "X-GitHub-Event": "workflow_run"}).status_code == 401
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    ok = client.post("/webhooks/github", content=body,
                     headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": "workflow_run"})
    assert ok.status_code == 200 and ok.json() == {"ignored": "run not completed"}
