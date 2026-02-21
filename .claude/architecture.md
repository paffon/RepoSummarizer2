# RepoSummarizer2 — Architecture

## Project Layout

```text
RepoSummarizer2/
├── src/                       # Core application code
│   ├── main.py                   # FastAPI app, /summarize endpoint, exception handlers, request ID middleware
│   ├── config.py                 # pydantic-settings — crashes on startup if NEBIUS_API_KEY or GITHUB_TOKEN missing
│   ├── models.py                 # Pydantic schemas: SummarizeRequest, SummarizeResponse, ErrorResponse
│   ├── prompts_service.py        # Module-level system prompt constants + user message builder functions
│   ├── repo/
│   │   ├── github_api.py         # Async GitHub client: metadata, tree, file fetching, domain exceptions
│   │   └── file_filter.py        # Scoring function, blocklist, content normalization, token budgeting
│   └── llm/
│       ├── base.py               # BaseLLMClient abstract class + LLMError exception
│       ├── deepseek_v3.py        # Worker model (single-pass + reduce)
│       └── llama_8b.py           # Planner model (map chunks)
├── tests/                     # Automated test suite
└── runners/                   # Interactive developer scripts — not part of the app, never imported
    ├── github_runner.py          # Explore raw GitHub API responses
    └── llm_runner.py             # Test LLM prompts interactively
```

## Prompts Service (`src/prompts_service.py`)

All LLM message content lives here. Nothing else in the codebase contains raw prompt strings.

The module uses plain module-level constants and functions — no class wrapper, no instantiation.

### System prompt constants

| Name | Used by | Purpose |
| --- | --- | --- |
| `SUMMARIZE_SYSTEM` | DeepSeek V3, single-pass | Instructs the model to return `{"summary", "technologies", "structure"}` JSON |
| `MAP_SYSTEM` | Llama 8B, map phase | Extracts `{"purpose", "technologies", "structure"}` notes from one chunk |
| `REDUCE_SYSTEM` | DeepSeek V3, reduce phase | Merges all map notes into the final three-key JSON |
| `JSON_REPAIR_SYSTEM` | Either model, retry | Fixes malformed JSON while preserving content |

### User message builder functions

| Function | Arguments | Returns |
| --- | --- | --- |
| `summarize_user` | `repo_context: str` | User message string for the single-pass call |
| `map_user` | `chunk: str` | User message string for one map-phase file |
| `reduce_user` | `notes: list[str]` | User message string for the reduce call |
| `json_repair_user` | `bad_json: str, error: str` | User message string for the repair retry |

### Usage pattern

```python
import src.prompts_service as prompts

messages = [
    {"role": "system", "content": prompts.SUMMARIZE_SYSTEM},
    {"role": "user",   "content": prompts.summarize_user(repo_context)},
]
```

## Domain Exceptions (`src/repo/github_api.py`)

Use distinct exception types for distinct failure modes — do not reuse one class for structurally different cases:

| Exception | Raised when | HTTP response |
| --- | --- | --- |
| `InvalidGitHubURL` | URL fails regex validation | 422 |
| `RepoNotFound` | GitHub returns 404 | 404 |
| `RepoPrivate` | GitHub 200 + `private: true` | 404 (message only, no metadata leak) |
| `RateLimited` | GitHub 403 + rate-limit header | 429 |
| `LLMError` | LLM call fails after retries | 502 |

## Chunk Definition (map phase)

A **chunk** is one fetched file's normalized, capped content. Each file that passes filtering and is fetched becomes exactly one chunk — no further splitting of individual files. The per-file 10,000-char cap ensures every chunk fits within the Planner model's context window.

## Large Repo Threshold

A repo is **large** when the assembled context token estimate exceeds **50,000 tokens** after filtering, normalizing, and applying the per-file cap. Below this: single-pass (DeepSeek V3 only). At or above: two-pass map/reduce.

## Caching

- **Write always:** every successfully processed repo is stored in SQLite, keyed by `(owner/repo, commit_sha)`. A new commit SHA produces a new row via `INSERT OR REPLACE`, overriding the old entry. Degraded responses (built from metadata only) are **not** cached.
- **Cache bypass:** expose as an optional query parameter `?bypass_cache=true` on `POST /summarize`. Default: cache is used. This keeps the request body contract (`{"github_url": "..."}`) clean.

## Runners

Runners live in `runners/` and are standalone Python scripts — no server required. Each exercises one core component with full console output so the developer can observe every intermediate value without adding debug prints to production code.

### `runners/github_runner.py`

Accepts `<owner> <repo>` args. Fires the metadata and recursive tree API calls via `httpx`, prints raw JSON responses. Useful for checking what the GitHub API returns before the production client post-processes it.

### `runners/llm_runner.py`

Interactive REPL: choose a model, paste repo context, see the exact payload sent, the raw API response, and the parsed result. Loops so the developer can test multiple prompts or switch models mid-session.
