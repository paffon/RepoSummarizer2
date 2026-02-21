# RepoSummarizer2 — Architecture

## Project Layout

```text
RepoSummarizer2/
├── src/                  # Core application code
│   ├── main.py              # FastAPI app, route definitions
│   ├── config.py            # Environment / settings
│   ├── prompts_service.py   # Message dataclass + all LLM prompts (see below)
│   ├── repo/
│   │   └── github_api.py    # GitHub API client & file-tree logic
│   └── llm/
│       ├── base.py          # Abstract LLM base class
│       ├── deepseek_v3.py   # Worker model (single-pass / reduce)
│       └── llama_8b.py      # Planner model (map chunks)
├── tests/                # Automated test suite
└── runners/              # Interactive developer runners (see below)
```

## Prompts Service

All LLM message construction lives in `src/prompts_service.py`. Nothing else in the codebase contains raw prompt strings.

### `Message` dataclass

```python
Message(role: str, content: str)
```

Wraps a single chat turn. `.to_dict()` returns the `{"role": ..., "content": ...}` dict expected by the OpenAI-compatible SDK.

### `PromptsService` — class attributes (system prompts)

| Attribute | Used by | Purpose |
| --- | --- | --- |
| `SUMMARIZE_SYSTEM` | DeepSeek V3, single-pass | Instructs the model to return `{"summary", "technologies", "structure"}` JSON |
| `MAP_SYSTEM` | Llama 8B, map phase | Extracts `{"purpose", "technologies", "structure"}` notes from one chunk |
| `REDUCE_SYSTEM` | DeepSeek V3, reduce phase | Merges all map notes into the final three-key JSON |
| `JSON_REPAIR_SYSTEM` | Either model, retry | Fixes malformed JSON while preserving content |

### `PromptsService` — static methods (user messages)

| Method | Arguments | Purpose |
| --- | --- | --- |
| `summarize_user` | `repo_context: str` | Wraps the assembled repo context for the single-pass call |
| `map_user` | `chunk: str` | Wraps one code chunk for the map phase |
| `reduce_user` | `notes: list[str]` | Formats the collected map notes for the reduce call |
| `json_repair_user` | `bad_json: str, error: str` | Provides the broken output and parse error for the repair retry |

### Usage pattern

```python
messages = [
    Message("system", PromptsService.SUMMARIZE_SYSTEM),
    Message("user", PromptsService.summarize_user(repo_context)),
]
```

## Caching

- **Write always:** every successfully processed repo is stored in SQLite, keyed by `(owner/repo, commit_sha)`.  A new commit SHA produces a new row via `INSERT OR REPLACE`, effectively overriding the old entry.
- **Read is opt-in:** a boolean flag (`use_cache`, default `True`) controls whether the cache lookup happens before the full pipeline runs.  Setting it to `False` forces a fresh LLM call even when a cached result exists, which is useful during development and testing.

## Runners

Runners live in `runners/` and are standalone Python scripts — no server required.  Each one exercises a single core component end-to-end with full console transparency, so the developer can observe every intermediate value without adding debug prints to production code.

### `runners/llm_runner.py` — LLM Interaction Runner

Interactive REPL for the LLM layer.

1. Prompts the developer to choose a model (DeepSeek V3 / Llama 3.1 8B / …).
2. Accepts free-form user input as the "repo context".
3. Prints the **exact payload** sent to the API (system prompt, user message, parameters).
4. Streams or prints the raw API response, then the parsed/structured result.
5. Loops — the developer can change the model mid-session or send multiple prompts.

### `runners/github_runner.py` — GitHub API Interaction Runner

Interactive explorer for the GitHub data-collection layer.

1. Accepts a GitHub URL (full `https://github.com/owner/repo`) **or** a `owner/repo` shorthand.
2. Prints each HTTP request as it fires (method, URL, headers minus secrets).
3. Displays raw API responses before post-processing.
4. Shows the filtered & scored file tree that would be handed to the LLM.
5. Optionally fetches and displays selected file contents with truncation markers.

### Adding More Runners

Each new core component (`cache`, `file_filter`, `token_budget`, …) should get its own runner following the same pattern: prompt for inputs → print all intermediate state → show final output.
