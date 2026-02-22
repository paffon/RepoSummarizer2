"""
Shared fixtures and environment setup for the test suite.

NEBIUS_API_KEY must be set in the environment before any src.* modules are
imported (Settings() is validated at import time).  We set a dummy value here
so unit tests that don't touch the real API can run without credentials.
"""

import os

os.environ.setdefault("NEBIUS_API_KEY", "test-dummy-key")
os.environ.setdefault("GITHUB_TOKEN", "")

import pytest
