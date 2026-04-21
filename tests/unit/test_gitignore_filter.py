from __future__ import annotations

import textwrap
from pathlib import Path

from planning_validator.gitignore_filter import load_gitignore_filter


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
