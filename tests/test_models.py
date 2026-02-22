"""Tests for src/models.py — Pydantic data models."""

import pytest
from pydantic import ValidationError

from src.models import ErrorResponse, SummarizeRequest, SummarizeResponse


class TestSummarizeRequest:
    def test_valid_url(self):
        req = SummarizeRequest(github_url="https://github.com/owner/repo")
        assert req.github_url == "https://github.com/owner/repo"

    def test_missing_url_raises(self):
        with pytest.raises(ValidationError):
            SummarizeRequest()  # type: ignore[call-arg]

    def test_accepts_any_string(self):
        # Model itself does not validate URL format; that's parse_github_url's job
        req = SummarizeRequest(github_url="not-a-url")
        assert req.github_url == "not-a-url"


class TestSummarizeResponse:
    def test_valid_response(self):
        resp = SummarizeResponse(
            summary="A cool project.",
            technologies=["Python", "FastAPI"],
            structure="src/ holds the source.",
        )
        assert resp.summary == "A cool project."
        assert resp.technologies == ["Python", "FastAPI"]
        assert resp.structure == "src/ holds the source."

    def test_empty_technologies_list(self):
        resp = SummarizeResponse(summary="x", technologies=[], structure="y")
        assert resp.technologies == []

    def test_missing_summary_raises(self):
        with pytest.raises(ValidationError):
            SummarizeResponse(technologies=[], structure="y")  # type: ignore[call-arg]

    def test_model_dump(self):
        resp = SummarizeResponse(summary="s", technologies=["Go"], structure="t")
        d = resp.model_dump()
        assert d == {"summary": "s", "technologies": ["Go"], "structure": "t"}


class TestErrorResponse:
    def test_default_status_is_error(self):
        err = ErrorResponse(message="Something went wrong.")
        assert err.status == "error"

    def test_message_stored(self):
        err = ErrorResponse(message="Not found.")
        assert err.message == "Not found."

    def test_model_dump_includes_status(self):
        err = ErrorResponse(message="oops")
        d = err.model_dump()
        assert d["status"] == "error"
        assert d["message"] == "oops"
