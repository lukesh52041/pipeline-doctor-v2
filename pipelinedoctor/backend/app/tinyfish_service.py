"""TinyFish Search API integration service.

Provides intelligent web research for CI/CD pipeline failure diagnosis,
normalizing external results and safely handling API errors.
"""
import logging
import os
import re

from tinyfish import TinyFish
from tinyfish._utils.exceptions import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
    RequestTimeoutError,
)

log = logging.getLogger("pipelinedoctor.tinyfish")


def search_tinyfish(query: str, location: str = "US", language: str = "en", api_key: str | None = None):
    """Execute TinyFish web search using the official TinyFish SDK.

    Reads TINYFISH_API_KEY from environment or optional api_key parameter.
    """
    if api_key is None:
        api_key = os.getenv("TINYFISH_API_KEY")

    if not api_key:
        raise RuntimeError("TinyFish API key is missing")

    client = TinyFish(api_key=api_key)

    response = client.search.query(
        query,
        location=location,
        language=language,
    )

    return response


def normalize_result_item(item) -> dict:
    """Normalize an individual search result item to standard format."""
    if isinstance(item, dict):
        title = item.get("title") or ""
        url = item.get("url") or ""
        description = item.get("snippet") or item.get("description") or ""
        source = item.get("site_name") or item.get("source") or item.get("publisher") or "Web"
    else:
        title = getattr(item, "title", "") or ""
        url = getattr(item, "url", "") or ""
        description = getattr(item, "snippet", "") or getattr(item, "description", "") or ""
        source = getattr(item, "site_name", "") or getattr(item, "source", "") or getattr(item, "publisher", "") or "Web"

    return {
        "title": str(title).strip(),
        "url": str(url).strip(),
        "description": str(description).strip(),
        "source": str(source).strip(),
    }


def normalize_search_results(response, query: str = "") -> list[dict]:
    """Normalize a TinyFish search response into a list of uniform result dictionaries."""
    if response is None:
        return []

    if isinstance(response, (list, tuple)):
        raw_results = response
    else:
        raw_results = getattr(response, "results", None)
        if raw_results is None and isinstance(response, dict):
            raw_results = response.get("results", [])
    raw_results = raw_results or []

    normalized = []
    for item in raw_results:
        norm = normalize_result_item(item)
        if norm["title"] or norm["url"]:
            normalized.append(norm)

    return normalized


def generate_search_query(diagnosis: dict) -> str:
    """Generate a focused, concise search query from a pipeline diagnosis.

    Never sends full raw pipeline logs or secret tokens.
    """
    category = str(diagnosis.get("category") or "").strip().lower()
    title = str(diagnosis.get("title") or "").strip()
    root_cause = str(diagnosis.get("root_cause") or "").strip()
    evidence_items = diagnosis.get("evidence", []) or []
    evidence_texts = [
        str(e.get("text", "")) for e in evidence_items if isinstance(e, dict)
    ]
    joined_evidence = " ".join(evidence_texts).lower()
    lowered_title = title.lower()
    lowered_cause = root_cause.lower()

    # Rule 1: Python missing module / ModuleNotFoundError
    if (
        "modulenotfounderror" in lowered_cause
        or "modulenotfounderror" in joined_evidence
        or "missing python module" in lowered_title
    ):
        return "Python ModuleNotFoundError dependency installation solution"

    # Rule 2: npm dependency conflict / ERESOLVE
    if (
        "npm" in lowered_title
        or "eresolve" in lowered_cause
        or "eresolve" in joined_evidence
    ):
        return "npm ERESOLVE dependency conflict resolution"

    # Rule 3: Docker build failure
    if (
        "docker" in lowered_title
        or "docker" in lowered_cause
        or "docker" in joined_evidence
    ):
        return "Docker build failed troubleshooting"

    # Rule 4: Permission denied
    if (
        category == "permissions"
        or "permission" in lowered_title
        or "permission denied" in joined_evidence
        or "git authentication failed" in lowered_title
    ):
        return "GitHub Actions permission denied troubleshooting"

    # Rule 5: Out of memory
    if (
        "out of memory" in lowered_title
        or "out of memory" in lowered_cause
        or "out of memory" in joined_evidence
        or "oom" in lowered_title
        or "killed" in joined_evidence
    ):
        return "CI pipeline out of memory troubleshooting"

    # Rule 6: Connection timeout / timeout
    if (
        category == "timeout"
        or "timed out" in lowered_title
        or "timeout" in lowered_title
        or "timed out" in joined_evidence
        or "connection timeout" in joined_evidence
    ):
        return "CI pipeline network connection timeout troubleshooting"

    # Fallback: focused query using title and category
    clean_title = re.sub(r"[^\w\s-]", "", title).strip()
    if clean_title and category and category != "unknown":
        return f"{clean_title} {category} troubleshooting solution"
    if clean_title:
        return f"{clean_title} troubleshooting solution"
    return "CI pipeline failure troubleshooting"


def perform_research(
    query: str,
    location: str = "US",
    language: str = "en",
    api_key: str | None = None,
) -> dict:
    """Execute research safely with full error handling and normalization.

    Returns a structured dictionary:
      - success: bool
      - query: str
      - results: list of normalized results
      - error: error message if unsuccessful
      - message: information message if no results found
    """
    cleaned_query = (query or "").strip()
    if not cleaned_query:
        return {
            "success": False,
            "query": query,
            "results": [],
            "error": "Query cannot be empty.",
        }

    effective_key = api_key or os.getenv("TINYFISH_API_KEY")
    if not effective_key:
        return {
            "success": False,
            "query": cleaned_query,
            "results": [],
            "error": "TinyFish API key is not configured.",
        }

    try:
        response = search_tinyfish(
            cleaned_query,
            location=location,
            language=language,
            api_key=effective_key,
        )
        results = normalize_search_results(response, query=cleaned_query)
        if not results:
            return {
                "success": True,
                "query": cleaned_query,
                "results": [],
                "message": "No relevant research results found.",
            }
        return {
            "success": True,
            "query": cleaned_query,
            "results": results,
        }
    except (RuntimeError, ValueError) as exc:
        msg = str(exc)
        if "missing" in msg.lower() or "no api key" in msg.lower():
            return {
                "success": False,
                "query": cleaned_query,
                "results": [],
                "error": "TinyFish API key is not configured.",
            }
        log.warning("TinyFish search error: %s", exc)
        return {
            "success": False,
            "query": cleaned_query,
            "results": [],
            "error": "External research is temporarily unavailable. Your PipelineDoctor diagnosis is still available.",
        }
    except AuthenticationError as exc:
        log.warning("TinyFish authentication failure: %s", exc)
        return {
            "success": False,
            "query": cleaned_query,
            "results": [],
            "error": "TinyFish authentication failed. Check your API key.",
        }
    except (APIConnectionError, APITimeoutError, RequestTimeoutError) as exc:
        log.warning("TinyFish network error: %s", exc)
        return {
            "success": False,
            "query": cleaned_query,
            "results": [],
            "error": "Unable to connect to TinyFish. Try again.",
        }
    except (RateLimitError, APIError, APIStatusError) as exc:
        log.warning("TinyFish API error: %s", exc)
        return {
            "success": False,
            "query": cleaned_query,
            "results": [],
            "error": "External research is temporarily unavailable. Your PipelineDoctor diagnosis is still available.",
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("Unexpected TinyFish error: %s", exc)
        return {
            "success": False,
            "query": cleaned_query,
            "results": [],
            "error": "External research is temporarily unavailable. Your PipelineDoctor diagnosis is still available.",
        }
