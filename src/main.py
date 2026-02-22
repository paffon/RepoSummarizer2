import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response

from src import config, cache
import src.prompts_service as prompts
from openai.types.chat import ChatCompletionMessageParam
from src.llm.base import LLMError
from src.llm.deepseek_v3 import NebiusDeepSeekV3Client
from src.llm.llama_8b import NebiusLlama8BClient
from src.models import ErrorResponse, SummarizeRequest, SummarizeResponse
from src.repo.github_api import (
    EmptyRepo,
    GitHubClient,
    InvalidGitHubURL,
    RateLimited,
    RepoNotFound,
    RepoPrivate,
    parse_github_url,
)
from src.repo.file_filter import (
    build_repo_context,
    filter_and_score,
    select_files,
    token_estimate,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Settings singleton (src.config.settings) already validated at import time.
    await cache.init_cache()
    logger.info("RepoSummarizer2 starting up")
    yield
    await cache.close_cache()
    logger.info("RepoSummarizer2 shutting down")


app = FastAPI(title="RepoSummarizer2", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Request ID middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    req_id = uuid.uuid4().hex[:8]
    request.state.req_id = req_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = req_id
    return response


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(message=message).model_dump(),
    )


@app.exception_handler(InvalidGitHubURL)
async def handle_invalid_url(request: Request, exc: InvalidGitHubURL):
    return _error(422, str(exc))


@app.exception_handler(RepoNotFound)
async def handle_not_found(request: Request, exc: RepoNotFound):
    return _error(404, "Repository not found or is private.")


@app.exception_handler(RepoPrivate)
async def handle_private(request: Request, exc: RepoPrivate):
    return _error(404, "Repository not found or is private.")


@app.exception_handler(EmptyRepo)
async def handle_empty_repo(request: Request, exc: EmptyRepo):
    return JSONResponse(
        status_code=200,
        content=SummarizeResponse(
            summary="No source files found.",
            technologies=[],
            structure="Empty repository.",
        ).model_dump(),
    )


@app.exception_handler(RateLimited)
async def handle_rate_limit(request: Request, exc: RateLimited):
    return _error(429, "GitHub API rate limit exceeded. Please try again later.")


@app.exception_handler(LLMError)
async def handle_llm_error(request: Request, exc: LLMError):
    logger.error(f"LLM error: {exc}")
    return _error(502, "Upstream LLM failure. Please try again later.")


@app.exception_handler(asyncio.TimeoutError)
async def handle_timeout(request: Request, exc: asyncio.TimeoutError):
    return _error(504, "Request timed out.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FILE_BUDGET_CHARS = (
    config.LARGE_REPO_TOKEN_THRESHOLD * config.TOKEN_ESTIMATE_RATIO * 8 // 10
    - 4_000   # reserve for tree + system prompt
    - 8_000   # reserve for LLM output
)


def _build_degraded_response(metadata: dict[str, Any]) -> SummarizeResponse:
    lang = metadata.get("language") or "unknown"
    desc = metadata.get("description") or f"A {lang} project."
    topics = metadata.get("topics", [])
    techs = [lang] if lang and lang != "unknown" else []
    techs += [t for t in topics if t not in techs]
    return SummarizeResponse(
        summary=(
            f"{metadata['full_name']}: {desc} "
            f"(Note: full LLM summary unavailable — built from metadata.)"
        ),
        technologies=techs,
        structure="See repository for directory structure.",
    )


def _parse_llm_json(raw: str, metadata: dict[str, Any]) -> SummarizeResponse | None:
    """Parse LLM JSON output into SummarizeResponse. Returns None on failure."""
    try:
        data = json.loads(raw)
        return SummarizeResponse(
            summary=str(data.get("summary", "")),
            technologies=list(data.get("technologies", [])),
            structure=str(data.get("structure", "")),
        )
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


async def _single_pass(context: str, req_id: str, metadata: dict[str, Any]) -> SummarizeResponse:
    """Call DeepSeek V3 once; retry with repair prompt on JSON failure."""
    worker = NebiusDeepSeekV3Client()
    try:
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": prompts.SUMMARIZE_SYSTEM},
            {"role": "user", "content": prompts.summarize_user(context)},
        ]
        raw = await asyncio.wait_for(
            worker.complete(messages),
            timeout=config.LLM_TIMEOUT_SECONDS,
        )
        logger.info(f"[{req_id}] llm_raw_len={len(raw)}")

        result = _parse_llm_json(raw, metadata)
        if result:
            return result

        # Repair attempt
        logger.warning(f"[{req_id}] JSON parse failed — attempting repair")
        repair_msgs: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": prompts.JSON_REPAIR_SYSTEM},
            {"role": "user", "content": prompts.json_repair_user(raw, "Failed to parse JSON")},
        ]
        repaired = await asyncio.wait_for(
            worker.complete(repair_msgs),
            timeout=config.LLM_TIMEOUT_SECONDS,
        )
        result = _parse_llm_json(repaired, metadata)
        if result:
            return result

        logger.warning(f"[{req_id}] Repair also failed — degrading to metadata")
        return _build_degraded_response(metadata)

    finally:
        await worker.close()


async def _map_reduce(
    file_contents: dict[str, str],
    metadata: dict[str, Any],
    req_id: str,
) -> SummarizeResponse:
    """Two-pass map/reduce for large repos."""
    planner = NebiusLlama8BClient()
    worker = NebiusDeepSeekV3Client()

    async def map_one(path: str, content: str) -> str:
        chunk = content[: config.MAX_CHARS_PER_FILE]
        msgs: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": prompts.MAP_SYSTEM},
            {"role": "user", "content": prompts.map_user(chunk)},
        ]
        try:
            return await asyncio.wait_for(
                planner.complete(msgs),
                timeout=config.LLM_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.warning(f"[{req_id}] map failed for {path}: {exc}")
            return ""

    try:
        logger.info(f"[{req_id}] map phase: {len(file_contents)} chunks")
        notes_raw = await asyncio.gather(
            *[map_one(p, c) for p, c in file_contents.items()]
        )
        notes = [n for n in notes_raw if n]

        if not notes:
            logger.warning(f"[{req_id}] all map calls failed — degrading")
            return _build_degraded_response(metadata)

        logger.info(f"[{req_id}] reduce phase: {len(notes)} notes")
        reduce_msgs: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": prompts.REDUCE_SYSTEM},
            {"role": "user", "content": prompts.reduce_user(notes)},
        ]
        raw = await asyncio.wait_for(
            worker.complete(reduce_msgs),
            timeout=config.LLM_TIMEOUT_SECONDS,
        )
        result = _parse_llm_json(raw, metadata)
        if result:
            return result

        # Repair attempt
        repair_msgs: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": prompts.JSON_REPAIR_SYSTEM},
            {"role": "user", "content": prompts.json_repair_user(raw, "Failed to parse JSON")},
        ]
        repaired = await asyncio.wait_for(
            worker.complete(repair_msgs),
            timeout=config.LLM_TIMEOUT_SECONDS,
        )
        result = _parse_llm_json(repaired, metadata)
        return result or _build_degraded_response(metadata)

    except LLMError as exc:
        logger.error(f"[{req_id}] LLMError in map/reduce: {exc}")
        return _build_degraded_response(metadata)
    finally:
        await planner.close()
        await worker.close()


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(
    request: Request,
    body: SummarizeRequest,
    bypass_cache: bool = Query(default=False),
):
    req_id = request.state.req_id
    logger.info(f"[{req_id}] url={body.github_url} bypass_cache={bypass_cache}")

    owner, repo_name = parse_github_url(body.github_url)

    async with GitHubClient() as gh:
        # Always fetch metadata first (cheap; also gives us the commit SHA for cache)
        metadata = await gh.fetch_metadata(owner, repo_name)
        full_name = metadata["full_name"]
        sha = metadata["commit_sha"]
        logger.info(
            f"[{req_id}] repo={full_name} sha={sha[:7]} lang={metadata['language']}"
        )

        # Cache check — short-circuit the expensive operations
        if not bypass_cache:
            cached = await cache.get_cached(full_name, sha)
            if cached:
                logger.info(f"[{req_id}] cache hit — returning immediately")
                return SummarizeResponse(**cached)

        tree = await gh.fetch_tree(owner, repo_name, metadata["default_branch"])
        logger.info(f"[{req_id}] tree_entries={len(tree)}")

        if not tree:
            raise EmptyRepo()

        scored = filter_and_score(tree)
        if not scored:
            return _build_degraded_response(metadata)

        selected_paths = select_files(scored, budget_chars=_FILE_BUDGET_CHARS)
        omitted = [p for (_, p, _) in scored if p not in selected_paths]
        logger.info(
            f"[{req_id}] scored={len(scored)} selected={len(selected_paths)} omitted={len(omitted)}"
        )

        file_contents = await gh.fetch_files_parallel(owner, repo_name, selected_paths)

    logger.info(f"[{req_id}] fetched_files={len(file_contents)}")

    context = build_repo_context(metadata, tree, file_contents, omitted)
    est = token_estimate(context)
    logger.info(f"[{req_id}] context_chars={len(context)} token_est={est}")

    if est < config.LARGE_REPO_TOKEN_THRESHOLD:
        result = await _single_pass(context, req_id, metadata)
    else:
        result = await _map_reduce(file_contents, metadata, req_id)

    # Write to cache only for non-degraded responses
    if "(built from metadata)" not in result.summary:
        await cache.set_cached(full_name, sha, result.model_dump())

    return result
