from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from planning_validator.config import load_config
from planning_validator.file_io import read_local_document_inventory, resolve_repo_relative_globs


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def create_repo_with_config(tmp_path: Path) -> Path:
    write_file(tmp_path / "README.md", "# Example repo\n")
    write_file(tmp_path / "docs/roadmap.md", "# Roadmap\n")
    write_file(tmp_path / "docs/tasks.md", "# Tasks\n")
    write_file(
        tmp_path / ".github/planning-validator.yml",
        """
        schema_version: v1alpha1
        planning_files:
          - README.md
          - docs/roadmap.md
        tracking_files:
          - docs/tasks.md
        patching:
          provider: openai
          model: gpt-5.4-thinking
          allowed_update_globs:
            - README.md
            - docs/**/*.md
        """,
    )
    return tmp_path / ".github/planning-validator.yml"


def test_resolve_repo_relative_globs_returns_sorted_deduped_matches(tmp_path: Path) -> None:
    write_file(tmp_path / "docs/b.md", "# B\n")
    write_file(tmp_path / "docs/a.md", "# A\n")
    (tmp_path / "docs/subdir").mkdir(parents=True)

    matches = resolve_repo_relative_globs(tmp_path, ["docs/*.md", "docs/a.md"])

    assert matches == ("docs/a.md", "docs/b.md")


def test_resolve_repo_relative_globs_rejects_root_escape_patterns(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must not traverse outside the repository root"):
        resolve_repo_relative_globs(tmp_path, ["../outside.md"])


def test_resolve_repo_relative_globs_rejects_matches_that_escape_repo_root(tmp_path: Path) -> None:
    outside_file = tmp_path.parent / "outside.md"
    outside_file.write_text("outside\n", encoding="utf-8")
    os.symlink(outside_file, tmp_path / "docs-link.md")

    with pytest.raises(ValueError, match="escaped the repository root"):
        resolve_repo_relative_globs(tmp_path, ["docs-link.md"])


def test_read_local_document_inventory_loads_and_dedupes_documents(tmp_path: Path) -> None:
    config_path = create_repo_with_config(tmp_path)
    write_file(
        tmp_path / ".github/planning-validator.yml",
        """
        schema_version: v1alpha1
        planning_files:
          - README.md
          - docs/shared.md
        tracking_files:
          - docs/shared.md
          - docs/tasks.md
        patching:
          provider: openai
          model: gpt-5.4-thinking
          allowed_update_globs:
            - README.md
            - docs/**/*.md
        """,
    )
    write_file(tmp_path / "docs/shared.md", "# Shared\n")

    resolved = load_config(config_path, repo_root=tmp_path)
    inventory = read_local_document_inventory(resolved)

    assert inventory.planning_paths == ["README.md", "docs/shared.md"]
    assert inventory.tracking_paths == ["docs/shared.md", "docs/tasks.md"]
    assert [document.path for document in inventory.all_documents] == [
        "README.md",
        "docs/shared.md",
        "docs/tasks.md",
    ]
    assert inventory.planning_documents[1] is inventory.tracking_documents[0]


def test_read_local_document_inventory_excludes_gitignored_documents(tmp_path: Path) -> None:
    config_path = create_repo_with_config(tmp_path)
    write_file(tmp_path / ".gitignore", "docs/tasks.md\n")

    resolved = load_config(config_path, repo_root=tmp_path)
    inventory = read_local_document_inventory(resolved)

    assert inventory.planning_paths == ["README.md", "docs/roadmap.md"]
    assert inventory.tracking_paths == []
    assert [document.path for document in inventory.all_documents] == [
        "README.md",
        "docs/roadmap.md",
    ]


def test_read_local_document_inventory_is_deterministic(tmp_path: Path) -> None:
    config_path = create_repo_with_config(tmp_path)
    resolved = load_config(config_path, repo_root=tmp_path)

    first_inventory = read_local_document_inventory(resolved)
    second_inventory = read_local_document_inventory(resolved)

    assert first_inventory.model_dump() == second_inventory.model_dump()
