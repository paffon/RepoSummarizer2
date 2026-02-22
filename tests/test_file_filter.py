"""Tests for src/repo/file_filter.py — scoring, selection, normalization, context assembly."""

import pytest

from src import config
from src.repo.file_filter import (
    build_repo_context,
    filter_and_score,
    normalize_content,
    score_file,
    select_files,
    token_estimate,
)


# ---------------------------------------------------------------------------
# score_file
# ---------------------------------------------------------------------------


class TestScoreFile:
    # Tier 1 — manifests and docs
    def test_readme_md(self):
        assert score_file("README.md", 100) == 100

    def test_readme_case_insensitive(self):
        assert score_file("readme.txt", 100) == 100

    def test_pyproject_toml(self):
        assert score_file("pyproject.toml", 100) == 100

    def test_package_json(self):
        assert score_file("package.json", 100) == 100

    def test_requirements_txt(self):
        assert score_file("requirements.txt", 100) == 100

    def test_cargo_toml(self):
        assert score_file("Cargo.toml", 100) == 100

    def test_go_mod(self):
        assert score_file("go.mod", 100) == 100

    def test_csproj_extension(self):
        assert score_file("MyProject.csproj", 100) == 100

    def test_sln_extension(self):
        assert score_file("MyProject.sln", 100) == 100

    # Tier 2 — entry points and deploy configs
    def test_main_py(self):
        assert score_file("main.py", 100) == 80

    def test_app_py(self):
        assert score_file("app.py", 100) == 80

    def test_main_go(self):
        assert score_file("main.go", 100) == 80

    def test_dockerfile(self):
        assert score_file("Dockerfile", 100) == 80

    def test_docker_compose(self):
        assert score_file("docker-compose.yml", 100) == 80

    def test_index_js(self):
        assert score_file("index.js", 100) == 80

    def test_main_rs(self):
        assert score_file("main.rs", 100) == 80

    def test_lib_rs(self):
        assert score_file("lib.rs", 100) == 80

    def test_special_tier2_path_src_main_rs(self):
        assert score_file("src/main.rs", 100) == 80

    # Tier 3 — source directories
    def test_src_dir_py(self):
        assert score_file("src/utils.py", 100) == 50

    def test_lib_dir_go(self):
        assert score_file("lib/helpers.go", 100) == 50

    def test_app_dir(self):
        assert score_file("app/routes.py", 100) == 50

    def test_api_dir(self):
        assert score_file("api/endpoints.py", 100) == 50

    def test_top_level_py(self):
        assert score_file("utils.py", 100) == 50

    def test_top_level_ts(self):
        assert score_file("helper.ts", 100) == 50

    def test_top_level_go(self):
        assert score_file("server.go", 100) == 50

    # Score 0 — blocked patterns
    def test_node_modules_blocked(self):
        assert score_file("node_modules/lodash/index.js", 100) == 0

    def test_vendor_blocked(self):
        assert score_file("vendor/gopkg.in/yaml.v2/yaml.go", 100) == 0

    def test_venv_blocked(self):
        assert score_file(".venv/lib/python3.12/site-packages/foo.py", 100) == 0

    def test_lock_file_blocked(self):
        assert score_file("package-lock.json", 100) == 0

    def test_poetry_lock_blocked(self):
        assert score_file("poetry.lock", 100) == 0

    def test_go_sum_blocked(self):
        assert score_file("go.sum", 100) == 0

    def test_png_blocked(self):
        assert score_file("assets/logo.png", 100) == 0

    def test_svg_blocked(self):
        assert score_file("public/icon.svg", 100) == 0

    def test_min_js_blocked(self):
        assert score_file("dist/bundle.min.js", 100) == 0

    def test_env_file_blocked(self):
        assert score_file(".env", 100) == 0

    def test_env_local_blocked(self):
        assert score_file(".env.local", 100) == 0

    def test_pyc_blocked(self):
        assert score_file("src/__pycache__/main.cpython-312.pyc", 100) == 0

    def test_test_dir_blocked(self):
        assert score_file("tests/test_main.py", 100) == 0

    def test_spec_dir_blocked(self):
        assert score_file("spec/routes_spec.rb", 100) == 0

    def test_pdf_blocked(self):
        assert score_file("docs/manual.pdf", 100) == 0

    # Size limit
    def test_oversized_file_blocked(self):
        assert score_file("src/big.py", config.MAX_FILE_SIZE_BYTES + 1) == 0

    def test_exactly_at_limit_passes(self):
        assert score_file("src/big.py", config.MAX_FILE_SIZE_BYTES) == 50

    # Unrecognised files score 0
    def test_unknown_extension_in_nonmatching_dir(self):
        assert score_file("data/file.xyz", 100) == 0

    def test_yaml_in_root_scores_zero(self):
        # yaml is not in the top-level source extension set
        assert score_file("config.yaml", 100) == 0


# ---------------------------------------------------------------------------
# filter_and_score
# ---------------------------------------------------------------------------


class TestFilterAndScore:
    def test_excludes_tree_type_entries(self):
        tree = [{"path": "src", "type": "tree", "size": 0}]
        assert filter_and_score(tree) == []

    def test_excludes_zero_score_blobs(self):
        tree = [{"path": "node_modules/foo.js", "type": "blob", "size": 100}]
        assert filter_and_score(tree) == []

    def test_returns_scored_blobs(self):
        tree = [{"path": "README.md", "type": "blob", "size": 200}]
        result = filter_and_score(tree)
        assert len(result) == 1
        score, path, size = result[0]
        assert score == 100
        assert path == "README.md"
        assert size == 200

    def test_sorted_by_score_descending(self):
        tree = [
            {"path": "src/helper.py", "type": "blob", "size": 100},  # 50
            {"path": "main.py", "type": "blob", "size": 100},         # 80
            {"path": "README.md", "type": "blob", "size": 100},       # 100
        ]
        result = filter_and_score(tree)
        scores = [s for s, _, _ in result]
        assert scores == sorted(scores, reverse=True)

    def test_same_score_sorted_by_size_ascending(self):
        tree = [
            {"path": "src/big.py", "type": "blob", "size": 5000},
            {"path": "src/small.py", "type": "blob", "size": 100},
        ]
        result = filter_and_score(tree)
        assert result[0][2] == 100   # smaller first
        assert result[1][2] == 5000


# ---------------------------------------------------------------------------
# select_files
# ---------------------------------------------------------------------------


class TestSelectFiles:
    def _make_scored(self, files):
        """files: list of (score, path, size)"""
        return sorted(files, key=lambda x: (-x[0], x[2]))

    def test_selects_within_budget(self):
        scored = self._make_scored([(100, "README.md", 500)])
        result = select_files(scored, budget_chars=10_000)
        assert result == ["README.md"]

    def test_excludes_files_over_budget(self):
        scored = self._make_scored([(100, "README.md", 20_000)])
        result = select_files(scored, budget_chars=5_000)
        assert result == []

    def test_respects_max_files_limit(self):
        # Create MAX_FILES_INCLUDED + 5 files each under budget
        files = [(50, f"src/f{i}.py", 10) for i in range(config.MAX_FILES_INCLUDED + 5)]
        scored = self._make_scored(files)
        result = select_files(scored, budget_chars=10_000_000)
        assert len(result) == config.MAX_FILES_INCLUDED

    def test_file_cost_capped_at_max_chars_per_file(self):
        # A file larger than MAX_CHARS_PER_FILE should cost MAX_CHARS_PER_FILE
        big_size = config.MAX_CHARS_PER_FILE * 3
        budget = config.MAX_CHARS_PER_FILE + 100
        scored = self._make_scored([
            (100, "README.md", big_size),
            (50, "src/extra.py", 50),
        ])
        result = select_files(scored, budget_chars=budget)
        # README.md costs MAX_CHARS_PER_FILE, extra.py has 50 left → both fit
        assert "README.md" in result

    def test_empty_scored_returns_empty(self):
        assert select_files([], budget_chars=10_000) == []


# ---------------------------------------------------------------------------
# normalize_content
# ---------------------------------------------------------------------------


class TestNormalizeContent:
    def test_removes_blank_lines(self):
        content = "line1\n\nline2\n\n\nline3"
        result = normalize_content(content)
        assert "\n\n" not in result
        assert "line1" in result
        assert "line2" in result
        assert "line3" in result

    def test_removes_decorator_lines(self):
        content = "def foo():\n    ###\n    pass"
        result = normalize_content(content)
        assert "###" not in result
        assert "def foo():" in result

    def test_collapses_license_header(self):
        content = (
            "# Copyright 2024 Acme Corp\n"
            "# Licensed under the MIT License\n"
            "def main(): pass"
        )
        result = normalize_content(content)
        assert "[license header omitted]" in result
        assert "Copyright" not in result
        assert "def main(): pass" in result

    def test_no_normalize_csv(self):
        content = "a,b,c\n\n1,2,3\n\n"
        result = normalize_content(content, ext=".csv")
        assert result == content

    def test_no_normalize_sql(self):
        content = "SELECT *\n\nFROM table\n\n"
        result = normalize_content(content, ext=".sql")
        assert result == content

    def test_windows_line_endings_normalized(self):
        content = "line1\r\nline2\r\nline3"
        result = normalize_content(content)
        assert "\r" not in result
        assert "line1" in result

    def test_empty_content_returns_empty(self):
        assert normalize_content("") == ""

    def test_no_license_content_unchanged_structure(self):
        content = "x = 1\ny = 2"
        result = normalize_content(content)
        assert "x = 1" in result
        assert "y = 2" in result


# ---------------------------------------------------------------------------
# token_estimate
# ---------------------------------------------------------------------------


class TestTokenEstimate:
    def test_empty_string(self):
        assert token_estimate("") == 0

    def test_uses_token_estimate_ratio(self):
        text = "a" * 400
        assert token_estimate(text) == 400 // config.TOKEN_ESTIMATE_RATIO

    def test_longer_text(self):
        text = "x" * 10_000
        assert token_estimate(text) == 10_000 // config.TOKEN_ESTIMATE_RATIO


# ---------------------------------------------------------------------------
# build_repo_context
# ---------------------------------------------------------------------------


class TestBuildRepoContext:
    def _metadata(self):
        return {
            "full_name": "owner/repo",
            "description": "A test repo",
            "language": "Python",
            "topics": ["api", "fastapi"],
            "license_name": "MIT",
            "fork": False,
        }

    def _tree(self):
        return [
            {"path": "README.md", "type": "blob", "size": 100},
            {"path": "src", "type": "tree", "size": 0},
        ]

    def test_contains_repo_name(self):
        ctx = build_repo_context(self._metadata(), self._tree(), {})
        assert "owner/repo" in ctx

    def test_contains_description(self):
        ctx = build_repo_context(self._metadata(), self._tree(), {})
        assert "A test repo" in ctx

    def test_contains_language(self):
        ctx = build_repo_context(self._metadata(), self._tree(), {})
        assert "Python" in ctx

    def test_contains_topics(self):
        ctx = build_repo_context(self._metadata(), self._tree(), {})
        assert "api" in ctx
        assert "fastapi" in ctx

    def test_contains_file_content(self):
        contents = {"README.md": "Hello world"}
        ctx = build_repo_context(self._metadata(), self._tree(), contents)
        assert "Hello world" in ctx

    def test_contains_omitted_note(self):
        ctx = build_repo_context(self._metadata(), self._tree(), {}, omitted_paths=["src/big.py"])
        assert "src/big.py" in ctx

    def test_tree_capped_at_300_entries(self):
        big_tree = [{"path": f"src/file{i}.py", "type": "blob", "size": 10} for i in range(400)]
        ctx = build_repo_context(self._metadata(), big_tree, {})
        assert "more entries omitted" in ctx

    def test_file_content_truncated_at_max_chars(self):
        long_content = "x" * (config.MAX_CHARS_PER_FILE + 1000)
        contents = {"src/big.py": long_content}
        ctx = build_repo_context(self._metadata(), self._tree(), contents)
        assert "[...truncated]" in ctx
