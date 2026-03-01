# RepoSummarizer2

A FastAPI service that takes a GitHub repository URL and returns a structured summary: what the project does, which technologies it uses, and how it is organised.

---

## Quick start

```bash
# 1. Clone and enter the directory
git clone <repo-url>
cd RepoSummarizer2

# 2. Create and activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set required environment variables
#    At minimum, set NEBIUS_API_KEY in your shell.
#    GITHUB_TOKEN is optional but recommended (raises rate limit from 60 to 5000 req/hour).
# Windows PowerShell:
$env:NEBIUS_API_KEY="your_nebius_key_here"
# $env:GITHUB_TOKEN="your_github_pat_here"

# macOS / Linux:
# export NEBIUS_API_KEY=your_nebius_key_here
# export GITHUB_TOKEN=your_github_pat_here

# 5. Start the server
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

The server will crash on startup if `NEBIUS_API_KEY` is not set.

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `NEBIUS_API_KEY` | **Yes** | Nebius Token Factory API key |
| `GITHUB_TOKEN` | No | GitHub Personal Access Token (increases rate limit) |

Variables are loaded from a `.env` file in the project root, or from the shell environment.

---

## Example request

```bash
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/psf/requests"}'
```

Response:

```json
{
  "summary": "Requests is a popular Python HTTP library that makes it simple to send HTTP/1.1 requests. It abstracts away the complexity of making requests behind a simple API, supporting methods like GET, POST, PUT, DELETE, and more.",
  "technologies": ["Python", "urllib3", "certifi", "chardet"],
  "structure": "The main source lives in src/requests/. Tests are in tests/. Documentation is in docs/ with its own requirements file."
}
```

To bypass the cache (force a fresh LLM call):

```bash
curl -X POST "http://localhost:8000/summarize?bypass_cache=true" \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/psf/requests"}'
```

---

## Architecture & design decisions

### Models chosen

- **Worker — DeepSeek V3** (`deepseek-ai/DeepSeek-V3`): Used for single-pass summarisation of small/medium repos and for the reduce phase of large repos. It produces high-quality structured JSON reliably and supports native JSON mode.
- **Planner — Llama 3.1 8B** (`meta-llama/Meta-Llama-3.1-8B-Instruct`): Used in the map phase of the two-pass strategy. It is fast and cheap; all map calls fire concurrently via `asyncio.gather`, so wall-clock time is bounded by the slowest single file — not the total.

### Why the Trees API instead of cloning

`GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1` returns the entire directory structure in a single lightweight JSON call. Cloning would require gigabytes of disk I/O and network transfer for large repos. The Trees API is ~1000× faster and needs no local storage.

### File selection strategy

Files are assigned a priority score (0, 50, 80, or 100) and selected greedily within a character budget:

| Tier | Score | Examples |
|------|-------|---------|
| 1 | 100 | `README.md`, `pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml` |
| 2 | 80 | Entry points: `main.py`, `app.py`, `index.ts`, `Dockerfile` |
| 3 | 50 | Other source files in `src/`, `lib/`, top-level packages |
| 4 | 0 (skip) | Tests, binaries, lock files, node\_modules, generated files |

Within the same tier, smaller files are preferred — this maximises the number of distinct files included before the budget is exhausted.

### Large repo handling

If the assembled context exceeds **50,000 tokens** (≈ 200,000 characters), the service switches from single-pass to two-pass map/reduce:

1. **Map:** each selected file is sent individually to Llama 3.1 8B, which extracts `{purpose, technologies, structure}` notes. All map calls run concurrently.
2. **Reduce:** DeepSeek V3 merges all map notes into the final three-key response.

### Caching

Summaries are cached in SQLite keyed by `(owner/repo, commit SHA)`. A cache hit returns in milliseconds at zero LLM cost. The cache is automatically invalidated when new commits are pushed (new SHA = cache miss).

### What would be added in production

- Redis instead of SQLite (distributed cache, supports horizontal scaling)
- Auth middleware (API keys for the `/summarize` endpoint)
- Structured JSON logging with trace IDs to a log aggregator
- Rate limiting per IP
- Webhook support: pre-warm cache when GitHub push events arrive

---

## Sample repos

| Repo | Size | Language | Notes |
|------|------|----------|-------|
| `psf/requests` | Small | Python | Clean structure, README-heavy |
| `fastapi/fastapi` | Medium | Python | Multiple sub-packages |
| `torvalds/linux` | Huge | C | Triggers map/reduce; first call is slow |

```bash
# Test all three
curl -s -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/psf/requests"}' | python -m json.tool

curl -s -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/fastapi/fastapi"}' | python -m json.tool

curl -s -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/torvalds/linux"}' | python -m json.tool
```
