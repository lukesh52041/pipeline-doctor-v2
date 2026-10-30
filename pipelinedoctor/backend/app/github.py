"""GitHub helpers: webhook signature check, log download, PR comments."""
import hashlib
import hmac
import io
import zipfile

import httpx

API = "https://api.github.com"
MAX_ZIP_BYTES = 50_000_000


def verify_signature(secret: str, body: bytes, header) -> bool:
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def fetch_run_logs(full_name: str, run_id, token: str, max_bytes: int = 2_000_000) -> str:
    """Download a run's logs zip and join the files. Keeps the tail if it is too large."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        resp = await client.get(f"{API}/repos/{full_name}/actions/runs/{run_id}/logs", headers=_headers(token))
        resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        if sum(i.file_size for i in zf.infolist()) > MAX_ZIP_BYTES:
            raise ValueError("Log archive is too large to analyze")
        parts = [f"##[group]{n}\n" + zf.read(n).decode("utf-8", "replace")
                 for n in sorted(zf.namelist()) if not n.endswith("/")]
    text = "\n".join(parts)
    return text[-max_bytes:] if len(text) > max_bytes else text


async def post_pr_comment(full_name: str, pr_number: int, body: str, token: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{API}/repos/{full_name}/issues/{pr_number}/comments",
                                 headers=_headers(token), json={"body": body})
        resp.raise_for_status()


def format_comment(diag: dict) -> str:
    lines = [
        f"### PipelineDoctor: {diag['title']}",
        f"**Category:** {diag['category']} | **Confidence:** {round(diag['confidence'] * 100)}%",
        "",
        diag["root_cause"],
        "",
        "**Evidence**",
    ]
    lines += [f"- line {e['line']}: `{e['text'][:160]}`" for e in diag["evidence"]] or ["- none found"]
    if diag["fix_steps"]:
        lines += ["", "**Suggested fix**"] + [f"{i}. {s}" for i, s in enumerate(diag["fix_steps"], 1)]
    if diag.get("suggested_diff"):
        lines += ["", "```diff", diag["suggested_diff"], "```"]
    if diag.get("research") and diag["research"].get("results"):
        lines += ["", "**Research & Solutions (TinyFish)**"]
        for r in diag["research"]["results"][:3]:
            lines.append(f"- [{r['title']}]({r['url']}) - {r['source']}")
    return "\n".join(lines)
