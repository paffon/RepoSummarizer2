"""
Live integration tests against the real Nebius TokenFactory API.

These tests verify that:
  1. The configured model names actually exist on Nebius.
  2. A minimal completion round-trip succeeds.

Run them with:
    pytest tests/test_live_nebius.py -v

They are skipped automatically when NEBIUS_API_KEY is not a real key
(i.e. equals the dummy value set in conftest.py).
"""

import os

import pytest

from src import config
from src.llm.base import LLMError
from src.llm.deepseek_v3 import NebiusDeepSeekV3Client
from src.llm.llama_8b import NebiusLlama8BClient

_REAL_KEY = os.environ.get("NEBIUS_API_KEY", "")
_HAS_REAL_KEY = bool(_REAL_KEY) and _REAL_KEY != "test-dummy-key"

pytestmark = pytest.mark.skipif(
    not _HAS_REAL_KEY,
    reason="NEBIUS_API_KEY is not set to a real key — skipping live tests",
)

_PING_MESSAGES = [{"role": "user", "content": 'Reply with exactly: {"summary":"ok","technologies":[],"structure":"ok"}'}]


class TestLiveDeepSeekV3:
    async def test_model_exists_and_responds(self):
        """Verify deepseek-ai/DeepSeek-V3 (or whatever WORKER_MODEL is) resolves on Nebius."""
        client = NebiusDeepSeekV3Client()
        try:
            result = await client.complete(_PING_MESSAGES)
            assert isinstance(result, str)
            assert len(result) > 0, "Model returned empty content"
        except LLMError as exc:
            pytest.fail(
                f"Live DeepSeek call failed — model may not exist on Nebius.\n"
                f"WORKER_MODEL = {config.WORKER_MODEL!r}\n"
                f"Error: {exc}"
            )
        finally:
            await client.close()

    async def test_worker_model_name_configured(self):
        """Sanity-check: WORKER_MODEL is a non-empty string."""
        assert config.WORKER_MODEL, "WORKER_MODEL is empty in config"
        assert "/" in config.WORKER_MODEL, (
            f"WORKER_MODEL {config.WORKER_MODEL!r} looks wrong — expected 'org/model' format"
        )


class TestLiveLlama8B:
    async def test_model_exists_and_responds(self):
        """Verify meta-llama/Meta-Llama-3.1-8B-Instruct (or PLANNER_MODEL) resolves on Nebius."""
        client = NebiusLlama8BClient()
        messages = [{"role": "user", "content": "Say: hello"}]
        try:
            result = await client.complete(messages)
            assert isinstance(result, str)
            assert len(result) > 0, "Model returned empty content"
        except LLMError as exc:
            pytest.fail(
                f"Live Llama call failed — model may not exist on Nebius.\n"
                f"PLANNER_MODEL = {config.PLANNER_MODEL!r}\n"
                f"Error: {exc}"
            )
        finally:
            await client.close()

    async def test_planner_model_name_configured(self):
        """Sanity-check: PLANNER_MODEL is a non-empty string."""
        assert config.PLANNER_MODEL, "PLANNER_MODEL is empty in config"
        assert "/" in config.PLANNER_MODEL, (
            f"PLANNER_MODEL {config.PLANNER_MODEL!r} looks wrong — expected 'org/model' format"
        )
