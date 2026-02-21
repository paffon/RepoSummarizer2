"""Async GitHub REST API client."""

import asyncio
import base64
import logging
import re
from typing import Any

import httpx

from src import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------


class InvalidGitHubURL(Exception):
    pass


class RepoNotFound(Exception):
    pass


class RepoPrivate(Exception):
    pass


class RateLimited(Exception):
    pass


class EmptyRepo(Exception):
    pass


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

_GITHUB_URL_RE = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+?)(?:\.git)?/?$"
)


def parse_github_url(url: str) -> tuple[str, str]:
    """Return (owner, repo) or raise InvalidGitHubURL."""
    m = _GITHUB_URL_RE.match(url.strip())
    if not m:
        raise InvalidGitHubURL(
            f"Invalid GitHub URL: expected https://github.com/<owner>/<repo>, got: {url}"
        )
    return m.group(1), m.group(2)


# ---------------------------------------------------------------------------
# Promising subdirectory names for truncated-tree fallback
# ---------------------------------------------------------------------------

_PROMISING_DIRS = {
    "src", "lib", "app", "pkg", "packages", "core", "api", "server",
    "client", "cmd", "internal", "main", "source", "sources",
}

_TEST_DIRS = {
    "test", "tests", "__tests__", "spec", "specs", "fixtures",
    "mocks", "e2e", "integration", "functional",
}


# ---------------------------------------------------------------------------
# GitHub client
# ---------------------------------------------------------------------------


class GitHubClient:
    """Async context manager wrapping httpx.AsyncClient for GitHub API calls."""

    BASE = "https://api.github.com"

    def __init__(self) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = config.settings.github_token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        else:
            logger.warning("No GITHUB_TOKEN set — using unauthenticated API (60 req/hour limit)")

        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=config.GITHUB_TIMEOUT_SECONDS,
            follow_redirects=True,
        )

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_error(self, resp: httpx.Response, owner: str = "", repo: str = "") -> None:
        if resp.status_code == 404:
            raise RepoNotFound(f"Repository {owner}/{repo} not found.")
        if resp.status_code == 403:
            if "x-ratelimit-remaining" in resp.headers and resp.headers["x-ratelimit-remaining"] == "0":
                raise RateLimited("GitHub API rate limit exceeded. Try again later.")
            # Generic 403 — treat as rate limit for safety
            raise RateLimited("GitHub API access denied (possibly rate limited).")
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Step 2: metadata
    # ------------------------------------------------------------------

    async def fetch_metadata(self, owner: str, repo: str) -> dict[str, Any]:
        """
        Fetch repo metadata. Returns a dict with:
          default_branch, description, language, topics, size,
          license_name, fork, commit_sha
        Raises RepoNotFound, RepoPrivate, RateLimited.
        """
        url = f"{self.BASE}/repos/{owner}/{repo}"
        resp = await self._client.get(url)
        self._check_error(resp, owner, repo)

        data = resp.json()

        if data.get("private"):
            raise RepoPrivate("Repository not found or is private.")

        # Resolve the latest commit SHA for the default branch
        branch = data.get("default_branch", "main")
        sha = await self._fetch_branch_sha(owner, repo, branch)

        license_info = data.get("license") or {}
        return {
            "owner": owner,
            "repo": repo,
            "full_name": data.get("full_name", f"{owner}/{repo}"),
            "default_branch": branch,
            "commit_sha": sha,
            "description": data.get("description") or "",
            "language": data.get("language") or "",
            "topics": data.get("topics") or [],
            "size_kb": data.get("size", 0),
            "license_name": license_info.get("name", ""),
            "fork": data.get("fork", False),
        }

    async def _fetch_branch_sha(self, owner: str, repo: str, branch: str) -> str:
        url = f"{self.BASE}/repos/{owner}/{repo}/git/refs/heads/{branch}"
        resp = await self._client.get(url)
        if resp.status_code != 200:
            # Fallback — try commits endpoint
            url2 = f"{self.BASE}/repos/{owner}/{repo}/commits/{branch}"
            resp2 = await self._client.get(url2)
            if resp2.status_code == 200:
                return resp2.json().get("sha", "unknown")
            return "unknown"
        return resp.json().get("object", {}).get("sha", "unknown")

    # ------------------------------------------------------------------
    # Step 3: file tree
    # ------------------------------------------------------------------

    async def fetch_tree(self, owner: str, repo: str, branch: str) -> list[dict[str, Any]]:
        """
        Fetch the full recursive file tree. Returns list of {path, type, size}.
        Falls back to selective subtree expansion if the tree is truncated.
        """
        url = f"{self.BASE}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        resp = await self._client.get(url)
        self._check_error(resp, owner, repo)
        data = resp.json()

        items = data.get("tree", [])
        if not data.get("truncated", False):
            return self._clean_tree(items)

        # --- Truncated fallback ---
        logger.info(f"[{owner}/{repo}] Tree truncated — expanding top-level + promising subdirs")
        return await self._expand_truncated_tree(owner, repo, branch)

    def _clean_tree(self, items: list[dict]) -> list[dict]:
        return [
            {"path": i["path"], "type": i["type"], "size": i.get("size", 0)}
            for i in items
        ]

    async def _expand_truncated_tree(
        self, owner: str, repo: str, branch: str
    ) -> list[dict[str, Any]]:
        # Fetch non-recursive top-level tree
        url = f"{self.BASE}/repos/{owner}/{repo}/git/trees/{branch}"
        resp = await self._client.get(url)
        self._check_error(resp, owner, repo)
        top_items = resp.json().get("tree", [])

        result = self._clean_tree([i for i in top_items if i["type"] == "blob"])

        # Identify promising subdirs (not blocklisted, not test dirs)
        subdirs = [
            i for i in top_items
            if i["type"] == "tree"
            and i["path"].lower() not in _TEST_DIRS
            and (
                i["path"].lower() in _PROMISING_DIRS
                or not i["path"].startswith(".")
            )
        ]

        # Limit expansions
        subdirs = subdirs[: config.MAX_SUBTREE_EXPANSIONS]

        async def expand_one(item: dict) -> list[dict]:
            try:
                r = await self._client.get(
                    f"{self.BASE}/repos/{owner}/{repo}/git/trees/{item['sha']}"
                )
                if r.status_code != 200:
                    return []
                subtree = r.json().get("tree", [])
                return self._clean_tree([
                    {**i, "path": f"{item['path']}/{i['path']}"}
                    for i in subtree
                    if i["type"] == "blob"
                ])
            except Exception:
                return []

        nested = await asyncio.gather(*[expand_one(d) for d in subdirs])
        for chunk in nested:
            result.extend(chunk)

        return result

    # ------------------------------------------------------------------
    # Step 3: file content
    # ------------------------------------------------------------------

    async def fetch_file(self, owner: str, repo: str, path: str) -> str:
        """Fetch a single file's text content (base64-decoded)."""
        url = f"{self.BASE}/repos/{owner}/{repo}/contents/{path}"
        resp = await self._client.get(url)
        if resp.status_code != 200:
            return ""
        data = resp.json()
        if isinstance(data, list):
            # It's a directory — skip
            return ""
        raw = data.get("content", "")
        encoding = data.get("encoding", "base64")
        if encoding == "base64":
            try:
                return base64.b64decode(raw.replace("\n", "")).decode("utf-8", errors="replace")
            except Exception:
                return ""
        return raw

    async def fetch_files_parallel(
        self, owner: str, repo: str, paths: list[str]
    ) -> dict[str, str]:
        """Fetch multiple files concurrently. Returns {path: content}."""
        tasks = [self.fetch_file(owner, repo, p) for p in paths]
        contents = await asyncio.gather(*tasks, return_exceptions=True)
        result = {}
        for path, content in zip(paths, contents):
            if isinstance(content, str) and content:
                result[path] = content
            else:
                logger.debug(f"Skipped {path}: {content!r}")
        return result
