"""Tests for src/repo/github_api.py — GitHubClient with mocked httpx."""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.repo.github_api import (
    GitHubClient,
    RateLimited,
    RepoNotFound,
    RepoPrivate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status_code: int, json_data=None, headers=None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock()
    return resp


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


# ---------------------------------------------------------------------------
# _check_error
# ---------------------------------------------------------------------------

class TestCheckError:
    def test_404_raises_repo_not_found(self):
        gh = GitHubClient()
        resp = _mock_response(404)
        with pytest.raises(RepoNotFound):
            gh._check_error(resp, "owner", "repo")

    def test_403_with_rate_limit_header_raises_rate_limited(self):
        gh = GitHubClient()
        resp = _mock_response(403, headers={"x-ratelimit-remaining": "0"})
        with pytest.raises(RateLimited):
            gh._check_error(resp, "owner", "repo")

    def test_403_without_header_also_raises_rate_limited(self):
        gh = GitHubClient()
        resp = _mock_response(403)
        with pytest.raises(RateLimited):
            gh._check_error(resp, "owner", "repo")

    def test_200_calls_raise_for_status(self):
        gh = GitHubClient()
        resp = _mock_response(200)
        gh._check_error(resp)
        resp.raise_for_status.assert_called_once()

    def test_500_calls_raise_for_status(self):
        gh = GitHubClient()
        resp = _mock_response(500)
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server error", request=MagicMock(), response=resp
        )
        with pytest.raises(httpx.HTTPStatusError):
            gh._check_error(resp)


# ---------------------------------------------------------------------------
# fetch_metadata
# ---------------------------------------------------------------------------

class TestFetchMetadata:
    async def test_happy_path(self):
        gh = GitHubClient()
        meta_resp = _mock_response(200, {
            "full_name": "owner/repo",
            "default_branch": "main",
            "description": "A repo",
            "language": "Python",
            "topics": ["api"],
            "size": 42,
            "license": {"name": "MIT"},
            "fork": False,
            "private": False,
        })
        sha_resp = _mock_response(200, {"object": {"sha": "abc123"}})
        gh._client.get = AsyncMock(side_effect=[meta_resp, sha_resp])

        metadata = await gh.fetch_metadata("owner", "repo")

        assert metadata["full_name"] == "owner/repo"
        assert metadata["default_branch"] == "main"
        assert metadata["commit_sha"] == "abc123"
        assert metadata["description"] == "A repo"
        assert metadata["language"] == "Python"
        assert metadata["topics"] == ["api"]
        assert metadata["license_name"] == "MIT"
        assert metadata["fork"] is False
        await gh._client.aclose()

    async def test_private_repo_raises_repo_private(self):
        gh = GitHubClient()
        meta_resp = _mock_response(200, {"private": True, "default_branch": "main"})
        gh._client.get = AsyncMock(return_value=meta_resp)

        with pytest.raises(RepoPrivate):
            await gh.fetch_metadata("owner", "private-repo")
        await gh._client.aclose()

    async def test_not_found_raises_repo_not_found(self):
        gh = GitHubClient()
        resp = _mock_response(404)
        gh._client.get = AsyncMock(return_value=resp)

        with pytest.raises(RepoNotFound):
            await gh.fetch_metadata("owner", "missing")
        await gh._client.aclose()

    async def test_missing_description_defaults_to_empty_string(self):
        gh = GitHubClient()
        meta_resp = _mock_response(200, {
            "full_name": "o/r", "default_branch": "main",
            "private": False, "description": None,
            "language": None, "topics": None, "size": 0,
            "license": None, "fork": False,
        })
        sha_resp = _mock_response(200, {"object": {"sha": "abc"}})
        gh._client.get = AsyncMock(side_effect=[meta_resp, sha_resp])

        meta = await gh.fetch_metadata("o", "r")
        assert meta["description"] == ""
        assert meta["language"] == ""
        assert meta["topics"] == []
        await gh._client.aclose()


# ---------------------------------------------------------------------------
# _fetch_branch_sha
# ---------------------------------------------------------------------------

class TestFetchBranchSha:
    async def test_uses_refs_endpoint(self):
        gh = GitHubClient()
        resp = _mock_response(200, {"object": {"sha": "deadbeef"}})
        gh._client.get = AsyncMock(return_value=resp)

        sha = await gh._fetch_branch_sha("owner", "repo", "main")
        assert sha == "deadbeef"
        await gh._client.aclose()

    async def test_falls_back_to_commits_endpoint(self):
        gh = GitHubClient()
        fail_resp = _mock_response(404)
        ok_resp = _mock_response(200, {"sha": "cafebabe"})
        gh._client.get = AsyncMock(side_effect=[fail_resp, ok_resp])

        sha = await gh._fetch_branch_sha("owner", "repo", "main")
        assert sha == "cafebabe"
        await gh._client.aclose()

    async def test_returns_unknown_when_both_fail(self):
        gh = GitHubClient()
        gh._client.get = AsyncMock(return_value=_mock_response(404))

        sha = await gh._fetch_branch_sha("owner", "repo", "main")
        assert sha == "unknown"
        await gh._client.aclose()


# ---------------------------------------------------------------------------
# fetch_tree
# ---------------------------------------------------------------------------

class TestFetchTree:
    async def test_non_truncated_tree(self):
        gh = GitHubClient()
        tree_data = {
            "truncated": False,
            "tree": [
                {"path": "README.md", "type": "blob", "size": 100},
                {"path": "src", "type": "tree"},
            ],
        }
        gh._client.get = AsyncMock(return_value=_mock_response(200, tree_data))

        result = await gh.fetch_tree("owner", "repo", "main")
        assert len(result) == 2
        assert result[0]["path"] == "README.md"
        await gh._client.aclose()

    async def test_clean_tree_normalises_missing_size(self):
        gh = GitHubClient()
        tree_data = {
            "truncated": False,
            "tree": [{"path": "src/foo.py", "type": "blob"}],  # no size key
        }
        gh._client.get = AsyncMock(return_value=_mock_response(200, tree_data))

        result = await gh.fetch_tree("owner", "repo", "main")
        assert result[0]["size"] == 0
        await gh._client.aclose()


# ---------------------------------------------------------------------------
# fetch_file
# ---------------------------------------------------------------------------

class TestFetchFile:
    async def test_base64_decodes_content(self):
        gh = GitHubClient()
        encoded = _b64("print('hello')")
        resp = _mock_response(200, {"content": encoded, "encoding": "base64"})
        gh._client.get = AsyncMock(return_value=resp)

        content = await gh.fetch_file("owner", "repo", "script.py")
        assert content == "print('hello')"
        await gh._client.aclose()

    async def test_non_200_returns_empty_string(self):
        gh = GitHubClient()
        gh._client.get = AsyncMock(return_value=_mock_response(404))

        content = await gh.fetch_file("owner", "repo", "missing.py")
        assert content == ""
        await gh._client.aclose()

    async def test_directory_response_returns_empty_string(self):
        gh = GitHubClient()
        # GitHub returns a list when the path is a directory
        resp = _mock_response(200, [{"name": "file.py"}])
        gh._client.get = AsyncMock(return_value=resp)

        content = await gh.fetch_file("owner", "repo", "src")
        assert content == ""
        await gh._client.aclose()

    async def test_base64_with_newlines_decoded(self):
        gh = GitHubClient()
        raw = "hello world"
        # GitHub splits base64 with newlines every 60 chars
        encoded_with_newlines = "\n".join(
            base64.b64encode(raw.encode()).decode()[i:i+60]
            for i in range(0, len(base64.b64encode(raw.encode()).decode()), 60)
        )
        resp = _mock_response(200, {"content": encoded_with_newlines, "encoding": "base64"})
        gh._client.get = AsyncMock(return_value=resp)

        content = await gh.fetch_file("owner", "repo", "file.txt")
        assert content == "hello world"
        await gh._client.aclose()


# ---------------------------------------------------------------------------
# fetch_files_parallel
# ---------------------------------------------------------------------------

class TestFetchFilesParallel:
    async def test_returns_dict_of_path_to_content(self):
        gh = GitHubClient()
        encoded = _b64("x = 1")
        resp = _mock_response(200, {"content": encoded, "encoding": "base64"})
        gh._client.get = AsyncMock(return_value=resp)

        result = await gh.fetch_files_parallel("owner", "repo", ["src/a.py"])
        assert result == {"src/a.py": "x = 1"}
        await gh._client.aclose()

    async def test_skips_empty_content(self):
        gh = GitHubClient()
        gh._client.get = AsyncMock(return_value=_mock_response(404))

        result = await gh.fetch_files_parallel("owner", "repo", ["missing.py"])
        assert result == {}
        await gh._client.aclose()

    async def test_handles_multiple_paths(self):
        gh = GitHubClient()
        resp_a = _mock_response(200, {"content": _b64("aaa"), "encoding": "base64"})
        resp_b = _mock_response(200, {"content": _b64("bbb"), "encoding": "base64"})
        gh._client.get = AsyncMock(side_effect=[resp_a, resp_b])

        result = await gh.fetch_files_parallel("owner", "repo", ["a.py", "b.py"])
        assert result["a.py"] == "aaa"
        assert result["b.py"] == "bbb"
        await gh._client.aclose()
