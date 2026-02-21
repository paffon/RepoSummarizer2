"""SQLite-backed summary cache keyed by (repo, commit_sha)."""

import json
import logging
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

_DB_PATH = "cache.db"
_db: aiosqlite.Connection | None = None


async def init_cache() -> None:
    global _db
    _db = await aiosqlite.connect(_DB_PATH)
    await _db.execute(
        """
        CREATE TABLE IF NOT EXISTS summaries (
            repo        TEXT NOT NULL,
            sha         TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            PRIMARY KEY (repo, sha)
        )
        """
    )
    await _db.commit()
    logger.info(f"Cache initialised at {_DB_PATH}")


async def close_cache() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


async def get_cached(repo: str, sha: str) -> dict[str, Any] | None:
    if _db is None or sha == "unknown":
        return None
    async with _db.execute(
        "SELECT summary_json FROM summaries WHERE repo = ? AND sha = ?",
        (repo, sha),
    ) as cursor:
        row = await cursor.fetchone()
    if row:
        logger.info(f"Cache hit: {repo}@{sha[:7]}")
        return json.loads(row[0])
    return None


async def set_cached(repo: str, sha: str, summary: dict[str, Any]) -> None:
    if _db is None or sha == "unknown":
        return
    await _db.execute(
        "INSERT OR REPLACE INTO summaries (repo, sha, summary_json) VALUES (?, ?, ?)",
        (repo, sha, json.dumps(summary)),
    )
    await _db.commit()
    logger.info(f"Cache write: {repo}@{sha[:7]}")
