from __future__ import annotations

import os
import textwrap
from pathlib import Path

from planning_validator.gitignore_filter import _prefix_gitignore_patterns, load_gitignore_filter


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def test_gitignore_filter_ignores_root_and_nested_paths(tmp_path: Path) -> None:
    write_file(
        tmp_path / ".gitignore",
        """
        ignored.md
        docs/generated/
        """,
    )
    write_file(tmp_path / "docs/generated/.gitignore", "kept.md\n")

    ignore_filter = load_gitignore_filter(tmp_path)

    assert ignore_filter.ignores("ignored.md") is True
    assert ignore_filter.ignores("docs/generated/file.md") is True
    assert ignore_filter.ignores("docs/kept.md") is False


def test_gitignore_filter_honors_negated_rules(tmp_path: Path) -> None:
    write_file(
        tmp_path / ".gitignore",
        """
        docs/*.md
        !docs/keep.md
        """,
    )

    ignore_filter = load_gitignore_filter(tmp_path)

    assert ignore_filter.ignores("docs/drop.md") is True
    assert ignore_filter.ignores("docs/keep.md") is False


def test_gitignore_filter_prefixes_nested_gitignore_rules(tmp_path: Path) -> None:
    write_file(tmp_path / "docs/.gitignore", "drafts/\n!drafts/keep.md\n")

    ignore_filter = load_gitignore_filter(tmp_path)

    assert ignore_filter.ignores("docs/drafts/item.md") is True
    assert ignore_filter.ignores("docs/drafts/keep.md") is False


def test_prefix_gitignore_patterns_preserves_leading_spaces_and_skips_non_patterns() -> None:
    patterns = _prefix_gitignore_patterns(
        [" ", "# comment", " #not-a-comment", "!"],
        base_dir="",
    )

    assert patterns == [" #not-a-comment"]


def test_prefix_gitignore_patterns_skips_empty_anchored_nested_pattern() -> None:
    patterns = _prefix_gitignore_patterns(
        ["/"],
        base_dir="docs",
    )

    assert patterns == []


def test_gitignore_filter_matches_nested_slashless_patterns_in_descendants(tmp_path: Path) -> None:
    write_file(tmp_path / "docs/.gitignore", "*.md\n")

    ignore_filter = load_gitignore_filter(tmp_path)

    assert ignore_filter.ignores("docs/file.md") is True
    assert ignore_filter.ignores("docs/sub/file.md") is True
    assert ignore_filter.ignores("notes/file.md") is False


def test_gitignore_filter_skips_non_file_gitignore_entries(tmp_path: Path) -> None:
    os.mkdir(tmp_path / ".gitignore")
    write_file(tmp_path / "docs/.gitignore", "drafts/\n")

    ignore_filter = load_gitignore_filter(tmp_path)

    assert ignore_filter.ignores("docs/drafts/item.md") is True
