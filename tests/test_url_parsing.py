"""Tests for parse_github_url in src/repo/github_api.py."""

import pytest

from src.repo.github_api import InvalidGitHubURL, parse_github_url


class TestParseGitHubURL:
    def test_simple_url(self):
        owner, repo = parse_github_url("https://github.com/torvalds/linux")
        assert owner == "torvalds"
        assert repo == "linux"

    def test_url_with_git_suffix(self):
        owner, repo = parse_github_url("https://github.com/torvalds/linux.git")
        assert owner == "torvalds"
        assert repo == "linux"

    def test_url_with_trailing_slash(self):
        owner, repo = parse_github_url("https://github.com/torvalds/linux/")
        assert owner == "torvalds"
        assert repo == "linux"

    def test_url_with_dashes(self):
        owner, repo = parse_github_url("https://github.com/my-org/my-repo")
        assert owner == "my-org"
        assert repo == "my-repo"

    def test_url_with_underscores(self):
        owner, repo = parse_github_url("https://github.com/my_org/my_repo")
        assert owner == "my_org"
        assert repo == "my_repo"

    def test_url_with_dots(self):
        owner, repo = parse_github_url("https://github.com/owner/repo.name")
        assert owner == "owner"
        assert repo == "repo.name"

    def test_url_strips_whitespace(self):
        owner, repo = parse_github_url("  https://github.com/owner/repo  ")
        assert owner == "owner"
        assert repo == "repo"

    def test_http_is_rejected(self):
        with pytest.raises(InvalidGitHubURL):
            parse_github_url("http://github.com/owner/repo")

    def test_wrong_host_rejected(self):
        with pytest.raises(InvalidGitHubURL):
            parse_github_url("https://gitlab.com/owner/repo")

    def test_missing_repo_rejected(self):
        with pytest.raises(InvalidGitHubURL):
            parse_github_url("https://github.com/owner")

    def test_empty_string_rejected(self):
        with pytest.raises(InvalidGitHubURL):
            parse_github_url("")

    def test_plain_string_rejected(self):
        with pytest.raises(InvalidGitHubURL):
            parse_github_url("not-a-url")

    def test_url_with_path_suffix_rejected(self):
        with pytest.raises(InvalidGitHubURL):
            parse_github_url("https://github.com/owner/repo/tree/main")

    def test_mixed_case_preserved(self):
        owner, repo = parse_github_url("https://github.com/MyOrg/MyRepo")
        assert owner == "MyOrg"
        assert repo == "MyRepo"
