import asyncio
from unittest.mock import MagicMock, patch

import pytest
from app.diagnose import diagnose
from app.main import app
from app.samples import get_sample
from app.tinyfish_service import (
    generate_search_query,
    normalize_result_item,
    normalize_search_results,
    perform_research,
    search_tinyfish,
)
from fastapi.testclient import TestClient
from tinyfish._utils.exceptions import (
    APIConnectionError,
    AuthenticationError,
)
from tinyfish.search.types import SearchQueryResponse, SearchResult


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_app_starts_without_tinyfish(client, monkeypatch):
    """1. Application starts without TinyFish configured."""
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    monkeypatch.setenv("TINYFISH_API_KEY", "")
    h = client.get("/api/health").json()
    assert h["status"] == "ok"
    assert h["tinyfish_enabled"] is False
    assert "PipelineDoctor" in client.get("/").text


def test_app_starts_with_valid_key(client, monkeypatch):
    """2. Application starts with a valid TinyFish API key configured."""
    monkeypatch.setenv("TINYFISH_API_KEY", "test_key_abc_123")
    monkeypatch.setenv("TINYFISH_ENABLED", "true")
    h = client.get("/api/health").json()
    assert h["status"] == "ok"
    assert h["tinyfish_enabled"] is True


def test_sdk_initializes_and_passes_parameters(monkeypatch):
    """3, 4, 5. TinyFish SDK initializes, sends query, passes location and language."""
    monkeypatch.setenv("TINYFISH_API_KEY", "test_key_123")

    mock_client_instance = MagicMock()
    mock_response = SearchQueryResponse(
        query="test query",
        results=[],
        total_results=0,
        page=0,
    )
    mock_client_instance.search.query.return_value = mock_response

    with patch("app.tinyfish_service.TinyFish", return_value=mock_client_instance) as mock_cls:
        resp = search_tinyfish("test query", location="GB", language="en")
        mock_cls.assert_called_once_with(api_key="test_key_123")
        mock_client_instance.search.query.assert_called_once_with(
            "test query",
            location="GB",
            language="en",
        )
        assert resp == mock_response


def test_search_results_normalization():
    """6. Search results are normalized correctly (handling varied field formats)."""
    # From SearchResult typed object
    sr = SearchResult(
        position=1,
        title="Official Python Docs",
        url="https://docs.python.org",
        snippet="Explanation of module imports.",
        site_name="python.org",
    )
    norm = normalize_result_item(sr)
    assert norm == {
        "title": "Official Python Docs",
        "url": "https://docs.python.org",
        "description": "Explanation of module imports.",
        "source": "python.org",
    }

    # From arbitrary dictionary
    d = {
        "title": "StackOverflow Thread",
        "url": "https://stackoverflow.com/q/123",
        "description": "Common fix for missing packages.",
        "source": "Stack Overflow",
    }
    norm_d = normalize_result_item(d)
    assert norm_d == {
        "title": "StackOverflow Thread",
        "url": "https://stackoverflow.com/q/123",
        "description": "Common fix for missing packages.",
        "source": "Stack Overflow",
    }

    # Batch normalization
    res_list = normalize_search_results([sr, d])
    assert len(res_list) == 2
    assert res_list[0]["source"] == "python.org"
    assert res_list[1]["source"] == "Stack Overflow"


def test_missing_api_key_handled(monkeypatch):
    """7. Missing API key is handled gracefully."""
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    monkeypatch.setenv("TINYFISH_API_KEY", "")

    with pytest.raises(RuntimeError, match="TinyFish API key is missing"):
        search_tinyfish("test query")

    res = perform_research("test query")
    assert res["success"] is False
    assert res["error"] == "TinyFish API key is not configured."


def test_invalid_api_key_handled(monkeypatch):
    """8. Invalid API key is handled gracefully."""
    monkeypatch.setenv("TINYFISH_API_KEY", "invalid_key")

    mock_client = MagicMock()
    # Mock httpx response for 401
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"
    mock_client.search.query.side_effect = AuthenticationError("Unauthorized", response=mock_resp)

    with patch("app.tinyfish_service.TinyFish", return_value=mock_client):
        res = perform_research("test query")
        assert res["success"] is False
        assert res["error"] == "TinyFish authentication failed. Check your API key."


def test_network_failure_does_not_break_diagnosis(monkeypatch):
    """9. TinyFish network failure does not break diagnosis."""
    monkeypatch.setenv("TINYFISH_API_KEY", "dummy_key")
    monkeypatch.setenv("TINYFISH_ENABLED", "true")

    mock_req = MagicMock()
    mock_client = MagicMock()
    mock_client.search.query.side_effect = APIConnectionError("Connection timeout", request=mock_req)

    with patch("app.tinyfish_service.TinyFish", return_value=mock_client):
        sample = get_sample("python-missing-module")
        d = asyncio.run(diagnose(sample["log"], use_llm=False, use_research=True))

        # Diagnosis is still intact
        assert d["category"] == "dependency"
        assert d["status"] == "ok"
        assert d["confidence"] >= 0.7
        assert "pandas" in d["root_cause"]
        # Research recorded the failure gracefully without crashing
        assert d["research"] is not None
        assert d["research"]["success"] is False
        assert "Unable to connect to TinyFish" in d["research"]["error"]


def test_diagnosis_workflow_with_tinyfish_success(monkeypatch):
    """Full workflow with successful TinyFish research integration."""
    monkeypatch.setenv("TINYFISH_API_KEY", "dummy_key")
    monkeypatch.setenv("TINYFISH_ENABLED", "true")

    mock_resp = SearchQueryResponse(
        query="Python ModuleNotFoundError dependency installation solution",
        results=[
            SearchResult(
                position=1,
                title="Python Modules and Packages Guide",
                url="https://docs.python.org/3/tutorial/modules.html",
                snippet="How to install and import Python modules.",
                site_name="python.org",
            ),
            SearchResult(
                position=2,
                title="Fixing ModuleNotFoundError",
                url="https://stackoverflow.com/questions/12345",
                snippet="Run pip install pandas in your workflow environment.",
                site_name="stackoverflow.com",
            ),
        ],
        total_results=2,
        page=0,
    )

    mock_client = MagicMock()
    mock_client.search.query.return_value = mock_resp

    with patch("app.tinyfish_service.TinyFish", return_value=mock_client):
        sample = get_sample("python-missing-module")
        d = asyncio.run(diagnose(sample["log"], use_llm=False, use_research=True))

        assert d["category"] == "dependency"
        assert d["research"] is not None
        assert d["research"]["success"] is True
        assert d["research"]["query"] == "Python ModuleNotFoundError dependency installation solution"
        assert len(d["research"]["results"]) == 2
        assert d["research"]["results"][0]["title"] == "Python Modules and Packages Guide"
        assert d["research"]["results"][0]["url"] == "https://docs.python.org/3/tutorial/modules.html"
        assert d["research"]["results"][0]["source"] == "python.org"


def test_research_api_endpoint(client, monkeypatch):
    """Test POST /api/research endpoint."""
    monkeypatch.setenv("TINYFISH_API_KEY", "dummy_key")

    mock_resp = SearchQueryResponse(
        query="Docker build failed troubleshooting",
        results=[
            SearchResult(
                position=1,
                title="Docker Build Reference",
                url="https://docs.docker.com/engine/reference/builder/",
                snippet="Docker build command troubleshooting guide.",
                site_name="docker.com",
            )
        ],
        total_results=1,
        page=0,
    )

    mock_client = MagicMock()
    mock_client.search.query.return_value = mock_resp

    with patch("app.tinyfish_service.TinyFish", return_value=mock_client):
        res = client.post(
            "/api/research",
            json={"query": "Docker build failed troubleshooting", "location": "US", "language": "en"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["query"] == "Docker build failed troubleshooting"
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "Docker Build Reference"
        assert data["results"][0]["source"] == "docker.com"


def test_research_api_endpoint_empty_query_rejected(client):
    """POST /api/research rejects empty query strings."""
    assert client.post("/api/research", json={"query": ""}).status_code == 422
    assert client.post("/api/research", json={"query": "   "}).status_code == 422


def test_research_endpoint_roles_enforced(client, monkeypatch):
    """POST /api/research enforces role-based authentication."""
    monkeypatch.setenv("API_KEYS", "dev-key:developer,lead-key:lead")
    # Missing key
    assert client.post("/api/research", json={"query": "test"}).status_code == 401
    # Invalid key
    assert client.post("/api/research", json={"query": "test"}, headers={"X-API-Key": "wrong"}).status_code == 401
    # Valid key
    with patch("app.main.perform_research", return_value={"success": True, "query": "test", "results": []}):
        res = client.post("/api/research", json={"query": "test"}, headers={"X-API-Key": "dev-key"})
        assert res.status_code == 200


def test_api_key_never_exposed(client, monkeypatch):
    """14. API key never appears in frontend code or API responses."""
    secret = "SUPER_SECRET_TINYFISH_KEY_999888"
    monkeypatch.setenv("TINYFISH_API_KEY", secret)
    monkeypatch.setenv("TINYFISH_ENABLED", "true")

    # Health check
    assert secret not in client.get("/api/health").text

    # Frontend HTML
    assert secret not in client.get("/").text

    # Diagnose response
    sample = get_sample("python-missing-module")
    mock_resp = SearchQueryResponse(
        query="test query",
        results=[],
        total_results=0,
        page=0,
    )
    with patch("app.tinyfish_service.TinyFish") as mock_tf:
        mock_tf.return_value.search.query.return_value = mock_resp
        d_res = client.post("/api/diagnose", json={"log": sample["log"], "use_llm": False, "use_research": True})
        assert secret not in d_res.text

    # Research response
    with patch("app.tinyfish_service.TinyFish") as mock_tf:
        mock_tf.return_value.search.query.return_value = mock_resp
        r_res = client.post("/api/research", json={"query": "test query"})
        assert secret not in r_res.text


def test_intelligent_query_generation_all_categories():
    """Verify focused queries generated for all 6 PRD failure cases."""
    # 1. ModuleNotFoundError
    q1 = generate_search_query({
        "category": "dependency",
        "title": "Missing Python module",
        "root_cause": "The code imports `pandas`, but it isn't installed.",
        "evidence": [{"line": 10, "text": "ModuleNotFoundError: No module named 'pandas'"}],
    })
    assert q1 == "Python ModuleNotFoundError dependency installation solution"

    # 2. npm dependency conflict
    q2 = generate_search_query({
        "category": "dependency",
        "title": "npm dependency conflict",
        "root_cause": "ERESOLVE unable to resolve dependency tree",
        "evidence": [{"line": 15, "text": "npm ERR! code ERESOLVE"}],
    })
    assert q2 == "npm ERESOLVE dependency conflict resolution"

    # 3. Docker build failure
    q3 = generate_search_query({
        "category": "build",
        "title": "Docker build failed",
        "root_cause": "Step 4/10 failed: COPY failed: file not found",
        "evidence": [{"line": 8, "text": "The command '/bin/sh -c ...' returned a non-zero code: 1"}],
    })
    assert q3 == "Docker build failed troubleshooting"

    # 4. Permission denied
    q4 = generate_search_query({
        "category": "permissions",
        "title": "Git authentication failed",
        "root_cause": "git couldn't authenticate to remote repository",
        "evidence": [{"line": 3, "text": "Permission denied (publickey)"}],
    })
    assert q4 == "GitHub Actions permission denied troubleshooting"

    # 5. Out of memory
    q5 = generate_search_query({
        "category": "infra",
        "title": "Out of memory",
        "root_cause": "Process was terminated by system (OOM)",
        "evidence": [{"line": 12, "text": "Killed"}],
    })
    assert q5 == "CI pipeline out of memory troubleshooting"

    # 6. Connection timeout
    q6 = generate_search_query({
        "category": "timeout",
        "title": "Command timed out",
        "root_cause": "Step exceeded maximum execution time",
        "evidence": [{"line": 20, "text": "The job running on runner exceeded maximum timeout"}],
    })
    assert q6 == "CI pipeline network connection timeout troubleshooting"


def test_empty_search_results_handling():
    """Verify empty search results message."""
    mock_resp = SearchQueryResponse(query="uncommon query", results=[], total_results=0, page=0)
    mock_client = MagicMock()
    mock_client.search.query.return_value = mock_resp

    with patch("app.tinyfish_service.TinyFish", return_value=mock_client):
        res = perform_research("uncommon query", api_key="dummy_key")
        assert res["success"] is True
        assert res["results"] == []
        assert res["message"] == "No relevant research results found."


def test_disable_research_toggle(monkeypatch):
    """Test when developer disables research toggle."""
    monkeypatch.setenv("TINYFISH_API_KEY", "dummy_key")
    monkeypatch.setenv("TINYFISH_ENABLED", "true")

    sample = get_sample("python-missing-module")
    d = asyncio.run(diagnose(sample["log"], use_llm=False, use_research=False))
    assert d["research"] is None
    assert d["category"] == "dependency"
