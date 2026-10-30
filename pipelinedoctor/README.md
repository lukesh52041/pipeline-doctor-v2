# PipelineDoctor

AI CI/CD failure explainer. Paste a failed pipeline log (or connect a GitHub repo) and get the root cause,
the exact log lines that prove it, a fix you can apply, and external research sources. No claim is shown without evidence.

## What it does

| Module | What you get |
|---|---|
| **Failure Explainer** | Category, root cause, confidence, evidence lines, fix steps, suggested diff, "check next" list |
| **Research & Solutions (TinyFish)** | External web research via TinyFish Search API: relevant docs, technical explanations, and source links |
| **Flaky Test Detector** | Tests that pass and fail on the same commit, or flip between runs, with minutes wasted |
| **Deploy Risk Scorer** | 0-100 pull request score, broken down by change size, files, CI config, dependencies, missing tests, recent failures |
| **Reliability Coach** | Weekly report: recurring causes ranked by time lost, flaky tests, failure rate |

Also included: secret and PII redaction before analysis, role-based access (developer, lead, admin),
an audit log, a sandbox with sample logs, a GitHub webhook that comments on pull requests, and a REST API.

## How a diagnosis works

1. **Redact.** Tokens, keys, passwords, emails, IPs and private keys are replaced. Line numbers don't change.
2. **Rules.** About 18 deterministic parsers recognise common failures (missing module, npm conflict, permissions,
   out of memory, timeout, Docker build, missing secret, and more). Each match records the lines it matched.
3. **AI (optional).** If no rule is confident (below 80%), the log excerpt goes to an LLM with a strict JSON schema.
   The log is treated as untrusted data. Evidence line numbers from the model are checked against the real log,
   the evidence text is always copied from the log, and an answer with no valid evidence is capped at 40% confidence.
4. **Merge.** Rules and AI are combined. Anything under 50% is labelled *uncertain* instead of presented as fact.
5. **Research (TinyFish, optional).** If external research is enabled and TinyFish is configured, PipelineDoctor
   generates a focused technical search query based on the diagnosed failure (never sending raw logs or secrets) and
   retrieves relevant technical documentation, explanations, and community solutions via the TinyFish Search API.

## Quick start

### Linux / macOS

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# Edit .env and configure TINYFISH_API_KEY (optional)
uvicorn app.main:app --app-dir backend --reload
```

### Windows (PowerShell)

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
# Edit .env and configure TINYFISH_API_KEY (optional)
uvicorn app.main:app --app-dir backend --reload
```

### Windows (Command Prompt)

```cmd
py -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements-dev.txt
copy .env.example .env
REM Edit .env and configure TINYFISH_API_KEY (optional)
uvicorn app.main:app --app-dir backend --reload
```

Open http://localhost:8000, pick a sample log, and press **Diagnose**. API docs are at `/docs`.

With Docker: `docker compose up --build`.

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `TINYFISH_API_KEY` | API key for TinyFish Search API integration. Enables external web research. |
| `TINYFISH_LOCATION` | Geographic location for TinyFish search results (default `US`). |
| `TINYFISH_LANGUAGE` | Language code for TinyFish search results (default `en`). |
| `TINYFISH_ENABLED` | Global toggle for TinyFish integration (`true` or `false`, default `true`). |
| `ANTHROPIC_API_KEY` | Enables AI analysis for unclear logs. Without it, rules only. |
| `LLM_MODEL` | Model name for the AI step (default `claude-sonnet-4-6`). |
| `API_KEYS` | `key:role,key:role`. Roles: `developer`, `lead`, `admin`. Empty means open (local dev only). |
| `GITHUB_TOKEN` | Token used to download run logs and post PR comments. |
| `GITHUB_WEBHOOK_SECRET` | Required to enable `/webhooks/github`. |
| `DB_PATH` | SQLite file (default `data/pipelinedoctor.db`). |
| `MAX_LOG_BYTES` | Largest log accepted (default 2,000,000). |

## TinyFish Web Research Integration

TinyFish Search API equips PipelineDoctor with live web research capabilities for investigating CI/CD failures.

### How it works
1. **Intelligent Query Generation:** Rather than transmitting raw logs, PipelineDoctor extracts the key failure category, error title, and redacted technical details to craft a targeted search query.
   - *Missing module:* `Python ModuleNotFoundError dependency installation solution`
   - *npm dependency clash:* `npm ERESOLVE dependency conflict resolution`
   - *Docker build failure:* `Docker build failed troubleshooting`
   - *Permission denied:* `GitHub Actions permission denied troubleshooting`
   - *Out of memory:* `CI pipeline out of memory troubleshooting`
   - *Connection timeout:* `CI pipeline network connection timeout troubleshooting`
2. **Normalized Results:** TinyFish results are parsed and normalized into a clean format (`title`, `url`, `description`, `source`).
3. **Interactive UI:**
   - Displays query used and search status.
   - Shows relevant sources with descriptions and direct `Open Source` links.
   - Provides a "Retry Search" button and an editable query input to refine searches manually.
   - User toggle: "Enable TinyFish Research" (defaults to enabled when configured).

### Complementary AI & Search
TinyFish and Anthropic serve complementary purposes:
- **Rule Engine:** Fast, deterministic failure detection.
- **Anthropic AI:** Root cause reasoning for novel or ambiguous logs.
- **TinyFish:** Real-time web search for official documentation and community fixes.

PipelineDoctor functions seamlessly with TinyFish alone, Anthropic alone, both, or neither.

## Error Handling & Graceful Degradation

External research issues never crash the application or prevent diagnosis:

| Scenario | User-Facing Message |
|---|---|
| **Missing API key** | `TinyFish API key is not configured.` |
| **Authentication failure** | `TinyFish authentication failed. Check your API key.` |
| **Network failure** | `Unable to connect to TinyFish. Try again.` |
| **No search results** | `No relevant research results found.` |
| **API rate limit or 5xx** | `External research is temporarily unavailable. Your PipelineDoctor diagnosis is still available.` |

If TinyFish is unavailable or fails, the core rule-based and AI diagnosis continue to display normally.

## Security & Privacy

- **Backend-Only Secrets:** `TINYFISH_API_KEY` is loaded on the server via `os.getenv("TINYFISH_API_KEY")` and is never exposed to the frontend, included in API responses, or logged.
- **Pre-analysis Redaction:** All sensitive data (tokens, private keys, passwords, IP addresses) are redacted before analysis or query generation. Raw logs are never transmitted to search services.
- **Untrusted Content:** All search results (titles, snippets, URLs) are treated as untrusted external content. Output is HTML-escaped and URLs are sanitized against injection attacks.
- **Human in the Loop:** Suggested fixes and code changes require human review before application; no commands from external sources are executed automatically.

## API

| Method and path | Role | Description |
|---|---|---|
| `POST /api/diagnose` | developer | Body: `log`, optional `repo`, `commit_sha`, `branch`, `duration_s`, `use_llm`, `use_research` |
| `POST /api/research` | developer | Body: `query` (min 1 char), optional `location`, `language`. Returns normalized research results. |
| `GET /api/diagnoses`, `/api/diagnoses/{id}` | developer | History and detail |
| `POST /api/risk` | developer | Body: `files`, `additions`, `deletions`, `repo` |
| `GET /api/flaky?repo=` | developer | Flaky test list |
| `GET /api/report?repo=&days=` | lead | Reliability report |
| `GET /api/admin/stats` | admin | Repos, runs, diagnoses, average confidence, top causes |
| `GET /api/samples` | none | Sandbox logs |
| `POST /webhooks/github` | signature | `workflow_run` events |

Send the key as `X-API-Key`. Wrong role returns `403 Access denied`.

```bash
# Research endpoint example
curl -s localhost:8000/api/research -H 'Content-Type: application/json' \
  -d '{"query": "Python ModuleNotFoundError troubleshooting", "location": "US", "language": "en"}'
```

## Connect GitHub

1. Set `GITHUB_TOKEN` (needs Actions read and Pull requests write on the repo) and `GITHUB_WEBHOOK_SECRET`.
2. In the repository, go to Settings > Webhooks > Add webhook.
3. Payload URL: `https://<your-host>/webhooks/github`, content type `application/json`, same secret,
   event: **Workflow runs**.
4. When a run fails, PipelineDoctor downloads the logs, diagnoses them, stores the result, and comments on the pull request (including TinyFish research links if enabled).

## Tests

Run the comprehensive automated test suite (including mocked TinyFish search tests):

```bash
pytest -v
```

## Project layout

```
backend/app/
  config.py           Environment settings (including TinyFish & Anthropic)
  db.py               SQLite persistence & audit logging
  diagnose.py         Diagnosis engine: redact -> rules -> AI -> TinyFish research -> merge
  flaky.py            Flaky test detection
  github.py           GitHub webhook, log retrieval, PR commenting
  llm.py              Optional Anthropic LLM diagnosis
  main.py             FastAPI application & REST endpoints (/api/diagnose, /api/research, etc.)
  parsers.py          Deterministic failure rules & matchers
  redact.py           Secret & PII redaction
  report.py           Weekly reliability reports
  risk.py             Pull request deployment risk scoring
  samples.py          Sample CI failure logs for testing
  tinyfish_service.py TinyFish SDK integration, query generation, & response normalization
backend/tests/        Unit, integration, and API tests
frontend/             Single-page web dashboard served by FastAPI
.github/workflows/    CI workflows: lint, test, docker build
```

## License

MIT
