"""File scoring, filtering, normalization, and token budgeting."""

import re
from typing import Any

from src import config

# ---------------------------------------------------------------------------
# Blocklist — patterns matched against full file path
# ---------------------------------------------------------------------------

_SKIP_PATTERNS: list[re.Pattern[str]] = [re.compile(p) for p in [
    r"node_modules/", r"vendor/", r"\.git/", r"__pycache__/", r"\.venv/", r"venv/",
    r"\.idea/", r"\.vscode/", r"dist/", r"build/", r"target/", r"\.next/", r"out/",
    r"\.lock$", r"package-lock\.json$", r"yarn\.lock$", r"poetry\.lock$", r"go\.sum$",
    r"\.(png|jpg|jpeg|gif|ico|svg|bmp|webp|woff|ttf|eot|otf|mp[34]|wav|ogg|avi|mov)$",
    r"\.(zip|tar|gz|bz2|xz|rar|7z|bin|exe|dll|so|dylib|obj|a|lib|class|pyc|pyo)$",
    r"\.(pdf|doc|docx|xls|xlsx|ppt|pptx)$",
    r"\.min\.(js|css)$",
    r"\.env$", r"\.env\.",  # never include secrets
    # Test and fixture directories (Tier 4 — skip entirely per guidelines)
    r"^tests?/", r"^__tests__/", r"^spec/", r"^specs/",
    r"^fixtures?/", r"^mocks?/", r"^e2e/",
]]

# Tier 1 — always include: manifests and docs
_TIER1_NAMES = {
    "readme.md", "readme.rst", "readme.txt", "readme",
    "pyproject.toml", "package.json", "cargo.toml", "go.mod",
    "requirements.txt", "pom.xml", "build.gradle", "build.gradle.kts",
    "cmakelists.txt", "gemfile", "pubspec.yaml", "mix.exs",
}
_TIER1_EXTENSIONS = {".csproj", ".sln"}

# Tier 2 — entry points and deploy configs
_TIER2_NAMES = {
    # Python
    "main.py", "app.py", "wsgi.py", "asgi.py", "manage.py",
    # Go
    "main.go", "app.go",
    # JS / TS
    "index.js", "index.ts", "main.js", "main.ts",
    "server.js", "server.ts", "app.js", "app.ts",
    # Java
    "main.java", "application.java", "app.java",
    # C#
    "program.cs", "startup.cs",
    # C / C++
    "main.c", "main.cpp", "main.cc",
    # Rust
    "main.rs", "lib.rs",
    # Ruby
    "app.rb", "config.ru",
    # PHP
    "index.php",
    # Swift / Kotlin / Dart
    "main.swift", "main.kt", "application.kt", "main.dart",
    # Build / deploy
    "dockerfile", "docker-compose.yml", "makefile", ".env.example",
}

# Special-cased paths for Tier 2
_TIER2_PATHS = {
    "cmd/main.go", "src/main.rs", "src/lib.rs",
}

# Tier 3 source dirs — files here get score 50
_TIER3_DIRS = {"src/", "lib/", "app/", "pkg/", "core/", "api/", "internal/", "server/"}

# Extensions that should never be normalized (binary-adjacent text)
_NO_NORMALIZE_EXT = {".csv", ".sql", ".tsv", ".jsonl", ".ndjson"}

# License header detector
_LICENSE_LINE_RE = re.compile(
    r"(copyright|license|spdx|©|apache|mit license|gnu|all rights reserved)",
    re.IGNORECASE,
)
# Decorator / visual-separator line (only punctuation chars)
_DECORATOR_RE = re.compile(r"^\s*[*\-=#/\\]{3,}\s*$")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_file(path: str, size: int) -> int:
    """
    Return priority score: 100 (Tier 1), 80 (Tier 2), 50 (Tier 3), 0 (skip).
    """
    # Blocklist check
    for pat in _SKIP_PATTERNS:
        if pat.search(path):
            return 0

    # Size check
    if size > config.MAX_FILE_SIZE_BYTES:
        return 0

    name = path.split("/")[-1].lower()
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""

    # Tier 1
    if name in _TIER1_NAMES or ext in _TIER1_EXTENSIONS:
        return 100

    # Tier 2
    if name in _TIER2_NAMES or path in _TIER2_PATHS:
        return 80

    # Tier 3: source dirs or top-level source files
    for d in _TIER3_DIRS:
        if path.startswith(d):
            return 50

    # Top-level source file (no directory separator)
    if "/" not in path and ext in {
        ".py", ".js", ".ts", ".go", ".rs", ".java", ".kt",
        ".cs", ".cpp", ".c", ".rb", ".php", ".swift", ".dart",
    }:
        return 50

    return 0


def filter_and_score(tree: list[dict[str, Any]]) -> list[tuple[int, str, int]]:
    """
    Score all blob entries. Return sorted list of (score, path, size),
    descending by score, ascending by size within the same score.
    Entries with score 0 are excluded.
    """
    scored = []
    for item in tree:
        if item.get("type") != "blob":
            continue
        path = item["path"]
        size = item.get("size", 0)
        s = score_file(path, size)
        if s > 0:
            scored.append((s, path, size))

    scored.sort(key=lambda x: (-x[0], x[2]))
    return scored


# ---------------------------------------------------------------------------
# Content normalization
# ---------------------------------------------------------------------------


def normalize_content(content: str, ext: str = "") -> str:
    """Clean file content to reduce token count without losing signal."""
    if ext in _NO_NORMALIZE_EXT:
        return content

    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    # Detect and collapse license header at the top
    header_end = 0
    in_block = False
    for i, line in enumerate(lines[:60]):  # only scan top of file
        stripped = line.strip()
        if not stripped:
            continue
        if _LICENSE_LINE_RE.search(stripped):
            header_end = i + 1
            in_block = True
        elif in_block and stripped in {"*/", "#", "*"}:
            header_end = i + 1
        elif in_block:
            break

    result = []
    if header_end > 0:
        result.append("[license header omitted]")
        lines = lines[header_end:]

    for line in lines:
        stripped = line.rstrip()
        # Skip blank lines
        if not stripped:
            continue
        # Skip pure decorator lines
        if _DECORATOR_RE.match(stripped):
            continue
        result.append(stripped)

    return "\n".join(result)


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def token_estimate(text: str) -> int:
    return len(text) // config.TOKEN_ESTIMATE_RATIO


# ---------------------------------------------------------------------------
# File selection (token budget)
# ---------------------------------------------------------------------------


def select_files(
    scored: list[tuple[int, str, int]],
    budget_chars: int,
) -> list[str]:
    """
    Greedily select files that fit within budget_chars.
    Files are pre-sorted (score desc, size asc).
    Returns list of paths to fetch.
    """
    selected = []
    used = 0
    for _score, path, size in scored:
        if len(selected) >= config.MAX_FILES_INCLUDED:
            break
        # Use size as proxy before actual fetch; actual content may vary
        cost = min(size, config.MAX_CHARS_PER_FILE)
        if used + cost <= budget_chars:
            selected.append(path)
            used += cost
    return selected


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

_TREE_MAX_ENTRIES = 300  # cap directory tree lines in the prompt


def _build_tree_block(tree: list[dict[str, Any]]) -> str:
    """Render a compact directory tree (path, type, size)."""
    lines = []
    for item in tree[:_TREE_MAX_ENTRIES]:
        t = "DIR " if item["type"] == "tree" else "    "
        size = f" ({item['size']}B)" if item.get("size") else ""
        lines.append(f"{t}{item['path']}{size}")
    if len(tree) > _TREE_MAX_ENTRIES:
        lines.append(f"... ({len(tree) - _TREE_MAX_ENTRIES} more entries omitted)")
    return "\n".join(lines)


def build_repo_context(
    metadata: dict[str, Any],
    tree: list[dict[str, Any]],
    file_contents: dict[str, str],
    omitted_paths: list[str] | None = None,
) -> str:
    """Assemble the full repo context string to send to the LLM."""
    meta_lines = [
        f"Repository: {metadata['full_name']}",
        f"Description: {metadata['description'] or 'N/A'}",
        f"Primary language: {metadata['language'] or 'Unknown'}",
        f"Topics: {', '.join(metadata.get('topics', [])) or 'none'}",
        f"License: {metadata.get('license_name') or 'not specified'}",
        f"Fork: {metadata.get('fork', False)}",
    ]

    sections = ["<repository_context>", "[REPOSITORY CONTENT START]", ""]
    sections.append("## Repository Metadata")
    sections.extend(meta_lines)
    sections.append("")
    sections.append("## Directory Structure")
    sections.append(_build_tree_block(tree))
    sections.append("")

    ext = ""
    for path, content in file_contents.items():
        if "." in path:
            ext = "." + path.rsplit(".", 1)[-1].lower()
        normalized = normalize_content(content, ext)
        truncated = normalized[: config.MAX_CHARS_PER_FILE]
        was_truncated = len(normalized) > config.MAX_CHARS_PER_FILE
        sections.append(f"## File: {path}")
        sections.append(truncated)
        if was_truncated:
            sections.append("[...truncated]")
        sections.append("")

    if omitted_paths:
        sections.append(
            f"## Note: {len(omitted_paths)} additional file(s) omitted due to token budget:"
        )
        sections.extend(f"  - {p}" for p in omitted_paths[:10])
        sections.append("")

    sections.append("[REPOSITORY CONTENT END]")
    sections.append("</repository_context>")
    return "\n".join(sections)
