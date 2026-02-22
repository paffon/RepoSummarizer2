"""Tests for src/cache.py — SQLite-backed async cache."""

import pytest

import src.cache as cache_module


@pytest.fixture
async def cache(tmp_path, monkeypatch):
    """Initialise the cache against a temporary SQLite file."""
    db_path = str(tmp_path / "test_cache.db")
    monkeypatch.setattr(cache_module, "_DB_PATH", db_path)
    await cache_module.init_cache()
    yield
    await cache_module.close_cache()


class TestInitAndClose:
    async def test_init_creates_connection(self, cache):
        assert cache_module._db is not None

    async def test_close_sets_db_to_none(self, cache):
        await cache_module.close_cache()
        assert cache_module._db is None
        # Re-init so fixture cleanup doesn't fail
        await cache_module.init_cache()


class TestGetCached:
    async def test_miss_returns_none(self, cache):
        result = await cache_module.get_cached("owner/repo", "abc123")
        assert result is None

    async def test_unknown_sha_returns_none(self, cache):
        result = await cache_module.get_cached("owner/repo", "unknown")
        assert result is None

    async def test_none_db_returns_none(self, monkeypatch):
        monkeypatch.setattr(cache_module, "_db", None)
        result = await cache_module.get_cached("owner/repo", "abc123")
        assert result is None

    async def test_hit_returns_stored_dict(self, cache):
        payload = {"summary": "s", "technologies": ["Python"], "structure": "t"}
        await cache_module.set_cached("owner/repo", "abc123", payload)
        result = await cache_module.get_cached("owner/repo", "abc123")
        assert result == payload


class TestSetCached:
    async def test_set_then_get_round_trip(self, cache):
        data = {"summary": "hello", "technologies": [], "structure": "flat"}
        await cache_module.set_cached("org/project", "sha1", data)
        assert await cache_module.get_cached("org/project", "sha1") == data

    async def test_skips_unknown_sha(self, cache):
        await cache_module.set_cached("org/project", "unknown", {"summary": "x", "technologies": [], "structure": "y"})
        # Nothing should be stored
        assert await cache_module.get_cached("org/project", "unknown") is None

    async def test_skips_when_db_is_none(self, monkeypatch):
        monkeypatch.setattr(cache_module, "_db", None)
        # Should not raise
        await cache_module.set_cached("org/project", "sha1", {"summary": "x", "technologies": [], "structure": "y"})

    async def test_insert_or_replace_overwrites(self, cache):
        await cache_module.set_cached("repo", "sha", {"summary": "old", "technologies": [], "structure": "s"})
        await cache_module.set_cached("repo", "sha", {"summary": "new", "technologies": [], "structure": "s"})
        result = await cache_module.get_cached("repo", "sha")
        assert result["summary"] == "new"

    async def test_different_shas_stored_independently(self, cache):
        await cache_module.set_cached("repo", "sha1", {"summary": "v1", "technologies": [], "structure": "s"})
        await cache_module.set_cached("repo", "sha2", {"summary": "v2", "technologies": [], "structure": "s"})
        assert (await cache_module.get_cached("repo", "sha1"))["summary"] == "v1"
        assert (await cache_module.get_cached("repo", "sha2"))["summary"] == "v2"

    async def test_different_repos_stored_independently(self, cache):
        await cache_module.set_cached("repo1", "sha", {"summary": "r1", "technologies": [], "structure": "s"})
        await cache_module.set_cached("repo2", "sha", {"summary": "r2", "technologies": [], "structure": "s"})
        assert (await cache_module.get_cached("repo1", "sha"))["summary"] == "r1"
        assert (await cache_module.get_cached("repo2", "sha"))["summary"] == "r2"
