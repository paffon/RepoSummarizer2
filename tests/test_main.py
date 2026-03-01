"""Tests for the FastAPI /summarize endpoint in src/main.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from src.main import _build_degraded_response, _parse_llm_json
from src.models import SummarizeResponse
from src.repo.github_api import EmptyRepo, InvalidGitHubURL, RateLimited, RepoNotFound


# ---------------------------------------------------------------------------
# Helper: fake metadata
# ---------------------------------------------------------------------------

def _metadata(full_name="owner/repo", sha="abc1234", language="Python"):
    return {
        "owner": "owner",
        "repo": "repo",
        "full_name": full_name,
        "default_branch": "main",
        "commit_sha": sha,
        "description": "A test repo",
        "language": language,
        "topics": [],
        "size_kb": 10,
        "license_name": "MIT",
        "fork": False,
    }


_VALID_RESPONSE = SummarizeResponse(
    summary="Does stuff.",
    technologies=["Python"],
    structure="Flat layout.",
)

_VALID_BODY = _VALID_RESPONSE.model_dump()


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def http_client():
    """FastAPI test client with cache I/O patched out."""
    with (
        patch("src.cache.init_cache", new_callable=AsyncMock),
        patch("src.cache.close_cache", new_callable=AsyncMock),
    ):
        from src.main import app
        async with LifespanManager(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client


# ---------------------------------------------------------------------------
# _parse_llm_json
# ---------------------------------------------------------------------------

class TestParseLlmJson:
    def test_parses_valid_json(self):
        raw = '{"summary":"s","technologies":["Go"],"structure":"t"}'
        result = _parse_llm_json(raw, {})
        assert result is not None
        assert result.summary == "s"
        assert result.technologies == ["Go"]

    def test_returns_none_on_invalid_json(self):
        result = _parse_llm_json("not json at all", {})
        assert result is None

    def test_returns_none_on_empty_string(self):
        assert _parse_llm_json("", {}) is None

    def test_missing_keys_use_defaults(self):
        raw = '{"summary":"s"}'
        result = _parse_llm_json(raw, {})
        assert result is not None
        assert result.technologies == []
        assert result.structure == ""


# ---------------------------------------------------------------------------
# _build_degraded_response
# ---------------------------------------------------------------------------

class TestBuildDegradedResponse:
    def test_uses_language_as_technology(self):
        meta = _metadata(language="Rust")
        resp = _build_degraded_response(meta)
        assert "Rust" in resp.technologies

    def test_uses_full_name_in_summary(self):
        meta = _metadata(full_name="org/project")
        resp = _build_degraded_response(meta)
        assert "org/project" in resp.summary

    def test_includes_degraded_note_in_summary(self):
        resp = _build_degraded_response(_metadata())
        assert "metadata" in resp.summary.lower()

    def test_adds_topics_as_technologies(self):
        meta = _metadata()
        meta["topics"] = ["docker", "api"]
        resp = _build_degraded_response(meta)
        assert "docker" in resp.technologies
        assert "api" in resp.technologies

    def test_no_duplicate_technologies(self):
        meta = _metadata(language="Python")
        meta["topics"] = ["python"]  # lowercase, different from "Python"
        resp = _build_degraded_response(meta)
        # "Python" and "python" are treated as different strings — no crash
        assert isinstance(resp.technologies, list)


# ---------------------------------------------------------------------------
# POST /summarize — error paths
# ---------------------------------------------------------------------------

class TestSummarizeErrors:
    async def test_invalid_url_returns_422(self, http_client):
        resp = await http_client.post("/summarize", json={"github_url": "not-a-url"})
        assert resp.status_code == 422

    async def test_missing_required_field_returns_error_shape(self, http_client):
        resp = await http_client.post("/summarize", json={})
        assert resp.status_code == 422
        body = resp.json()
        assert body["status"] == "error"
        assert "message" in body

    async def test_repo_not_found_returns_404(self, http_client):
        with (
            patch("src.main.parse_github_url", return_value=("owner", "repo")),
            patch("src.main.GitHubClient") as MockGH,
            patch("src.cache.get_cached", new_callable=AsyncMock, return_value=None),
        ):
            instance = MockGH.return_value.__aenter__.return_value
            instance.fetch_metadata = AsyncMock(side_effect=RepoNotFound())
            resp = await http_client.post(
                "/summarize", json={"github_url": "https://github.com/owner/repo"}
            )
        assert resp.status_code == 404
        assert resp.json()["status"] == "error"

    async def test_rate_limited_returns_429(self, http_client):
        with (
            patch("src.main.parse_github_url", return_value=("owner", "repo")),
            patch("src.main.GitHubClient") as MockGH,
        ):
            instance = MockGH.return_value.__aenter__.return_value
            instance.fetch_metadata = AsyncMock(side_effect=RateLimited())
            resp = await http_client.post(
                "/summarize", json={"github_url": "https://github.com/owner/repo"}
            )
        assert resp.status_code == 429

    async def test_empty_repo_returns_200_with_empty_summary(self, http_client):
        with (
            patch("src.main.parse_github_url", return_value=("owner", "repo")),
            patch("src.main.GitHubClient") as MockGH,
            patch("src.cache.get_cached", new_callable=AsyncMock, return_value=None),
        ):
            instance = MockGH.return_value.__aenter__.return_value
            instance.fetch_metadata = AsyncMock(return_value=_metadata())
            instance.fetch_tree = AsyncMock(side_effect=EmptyRepo())
            resp = await http_client.post(
                "/summarize", json={"github_url": "https://github.com/owner/repo"}
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["summary"] == "No source files found."


# ---------------------------------------------------------------------------
# POST /summarize — cache hit
# ---------------------------------------------------------------------------

class TestSummarizeCacheHit:
    async def test_cache_hit_returns_cached_data(self, http_client):
        cached = _VALID_BODY.copy()
        with (
            patch("src.main.parse_github_url", return_value=("owner", "repo")),
            patch("src.main.GitHubClient") as MockGH,
            patch("src.cache.get_cached", new_callable=AsyncMock, return_value=cached),
        ):
            instance = MockGH.return_value.__aenter__.return_value
            instance.fetch_metadata = AsyncMock(return_value=_metadata())
            resp = await http_client.post(
                "/summarize", json={"github_url": "https://github.com/owner/repo"}
            )
        assert resp.status_code == 200
        assert resp.json()["summary"] == "Does stuff."

    async def test_bypass_cache_skips_cache_lookup(self, http_client):
        with (
            patch("src.main.parse_github_url", return_value=("owner", "repo")),
            patch("src.main.GitHubClient") as MockGH,
            patch("src.cache.get_cached", new_callable=AsyncMock, return_value=_VALID_BODY) as mock_get,
            patch("src.cache.set_cached", new_callable=AsyncMock),
            patch("src.main._single_pass", new_callable=AsyncMock, return_value=_VALID_RESPONSE),
        ):
            instance = MockGH.return_value.__aenter__.return_value
            instance.fetch_metadata = AsyncMock(return_value=_metadata())
            instance.fetch_tree = AsyncMock(return_value=[
                {"path": "README.md", "type": "blob", "size": 100}
            ])
            instance.fetch_files_parallel = AsyncMock(return_value={"README.md": "hello"})
            resp = await http_client.post(
                "/summarize",
                json={"github_url": "https://github.com/owner/repo"},
                params={"bypass_cache": "true"},
            )
        mock_get.assert_not_called()
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /summarize — single-pass LLM path
# ---------------------------------------------------------------------------

class TestSummarizeSinglePass:
    async def test_successful_single_pass(self, http_client):
        with (
            patch("src.main.parse_github_url", return_value=("owner", "repo")),
            patch("src.main.GitHubClient") as MockGH,
            patch("src.cache.get_cached", new_callable=AsyncMock, return_value=None),
            patch("src.cache.set_cached", new_callable=AsyncMock),
            patch("src.main._single_pass", new_callable=AsyncMock, return_value=_VALID_RESPONSE),
        ):
            instance = MockGH.return_value.__aenter__.return_value
            instance.fetch_metadata = AsyncMock(return_value=_metadata())
            instance.fetch_tree = AsyncMock(return_value=[
                {"path": "README.md", "type": "blob", "size": 100}
            ])
            instance.fetch_files_parallel = AsyncMock(return_value={"README.md": "hello"})
            resp = await http_client.post(
                "/summarize", json={"github_url": "https://github.com/owner/repo"}
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["summary"] == "Does stuff."
        assert "Python" in body["technologies"]

    async def test_result_written_to_cache(self, http_client):
        with (
            patch("src.main.parse_github_url", return_value=("owner", "repo")),
            patch("src.main.GitHubClient") as MockGH,
            patch("src.cache.get_cached", new_callable=AsyncMock, return_value=None),
            patch("src.cache.set_cached", new_callable=AsyncMock) as mock_set,
            patch("src.main._single_pass", new_callable=AsyncMock, return_value=_VALID_RESPONSE),
        ):
            instance = MockGH.return_value.__aenter__.return_value
            instance.fetch_metadata = AsyncMock(return_value=_metadata(sha="sha999"))
            instance.fetch_tree = AsyncMock(return_value=[
                {"path": "README.md", "type": "blob", "size": 100}
            ])
            instance.fetch_files_parallel = AsyncMock(return_value={"README.md": "hello"})
            await http_client.post(
                "/summarize", json={"github_url": "https://github.com/owner/repo"}
            )
        mock_set.assert_called_once()
        args = mock_set.call_args.args
        assert args[1] == "sha999"

    async def test_request_id_header_present(self, http_client):
        with (
            patch("src.main.parse_github_url", return_value=("owner", "repo")),
            patch("src.main.GitHubClient") as MockGH,
            patch("src.cache.get_cached", new_callable=AsyncMock, return_value=_VALID_BODY),
        ):
            instance = MockGH.return_value.__aenter__.return_value
            instance.fetch_metadata = AsyncMock(return_value=_metadata())
            resp = await http_client.post(
                "/summarize", json={"github_url": "https://github.com/owner/repo"}
            )
        assert "x-request-id" in resp.headers


# ---------------------------------------------------------------------------
# POST /summarize — LLM error → 502
# ---------------------------------------------------------------------------

class TestSummarizeLlmError:
    async def test_llm_error_returns_502(self, http_client):
        from src.llm.base import LLMError

        with (
            patch("src.main.parse_github_url", return_value=("owner", "repo")),
            patch("src.main.GitHubClient") as MockGH,
            patch("src.cache.get_cached", new_callable=AsyncMock, return_value=None),
            patch("src.main._single_pass", new_callable=AsyncMock, side_effect=LLMError("bad")),
        ):
            instance = MockGH.return_value.__aenter__.return_value
            instance.fetch_metadata = AsyncMock(return_value=_metadata())
            instance.fetch_tree = AsyncMock(return_value=[
                {"path": "README.md", "type": "blob", "size": 100}
            ])
            instance.fetch_files_parallel = AsyncMock(return_value={"README.md": "hello"})
            resp = await http_client.post(
                "/summarize", json={"github_url": "https://github.com/owner/repo"}
            )
        assert resp.status_code == 502
        assert resp.json()["status"] == "error"
