# Submission Notes (for Examiners)

This repository implements the Nebius Academy assignment: a FastAPI service that summarizes a public GitHub repository via `POST /summarize`.

## What this project demonstrates

- Async API pipeline with clear separation of concerns (`src/main.py`, `src/repo`, `src/llm`, `src/prompts_service.py`).
- Nebius Token Factory integration through OpenAI-compatible clients (`AsyncOpenAI`) using `NEBIUS_API_KEY`.
- Practical repository preprocessing strategy: score-based file selection, blocklist filtering, normalization, and prompt budgeting.
- Large-repo handling via two-pass map/reduce (Planner: Llama 3.1 8B, Worker: DeepSeek V3).
- Deterministic response contract with structured JSON output and standardized JSON errors.

## Design choices that improve robustness

- **Cache by commit SHA**: avoids stale summaries for moving default branches and cuts repeated LLM cost.
- **Graceful degradation**: if JSON repair still fails, returns metadata-based summary instead of crashing.
- **Parallel I/O**: selected files are fetched concurrently, reducing wall-clock latency.
- **Prompt centralization**: all model prompt content lives in a single module for easy tuning and auditability.

## How constraints are handled

- Large repositories are bounded by:
  - per-file size cap,
  - per-file character cap,
  - max file count,
  - aggregate context threshold.
- Non-informative files are excluded (binary, lock, generated/build artifacts, virtualenvs, test directories).

## Error handling highlights

- URL validation, repository not found/private, rate limiting, upstream LLM failures, and timeouts are mapped to explicit HTTP statuses.
- Request validation errors are normalized into the same JSON error envelope expected by the assignment checker.

## Test coverage

- Unit and API tests validate filtering, URL parsing, model client behavior, caching, error mappings, and endpoint contract.
- Live Nebius tests are present and automatically skipped when no real API key is configured.

## Additional doc

- Detailed request lifecycle diagrams and branch behavior are documented in [docs/flow.md](flow.md).
