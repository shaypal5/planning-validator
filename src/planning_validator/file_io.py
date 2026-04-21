"""Repo-relative path resolution and local markdown inventory helpers."""

from __future__ import annotations

import glob
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from planning_validator.gitignore_filter import load_gitignore_filter
from planning_validator.models import LocalDocument, LocalDocumentInventory

if TYPE_CHECKING:
    from planning_validator.config import ResolvedConfig


def resolve_repo_relative_globs(repo_root: Path, patterns: Iterable[str]) -> tuple[str, ...]:
    """Resolve repository-relative glob patterns into a stable deduped file list."""

    matches: set[str] = set()
    for pattern in patterns:
        matches.update(_resolve_repo_relative_pattern(repo_root, pattern))
    return tuple(sorted(matches))


def read_local_document_inventory(resolved_config: ResolvedConfig) -> LocalDocumentInventory:
    """Load planning and tracking markdown documents from the local repository."""

    ignore_filter = load_gitignore_filter(resolved_config.repo_root)
    loaded_documents: dict[str, LocalDocument] = {}

    planning_paths = _filter_ignored_paths(
        resolved_config.planning_paths,
        ignore_filter=ignore_filter,
    )
    tracking_paths = _filter_ignored_paths(
        resolved_config.tracking_paths,
        ignore_filter=ignore_filter,
    )

    def get_document(path: str) -> LocalDocument:
        document = loaded_documents.get(path)
        if document is not None:
            return document

        content = (resolved_config.repo_root / path).read_text(encoding="utf-8")
        document = LocalDocument.from_content(path=path, content=content)
        loaded_documents[path] = document
        return document

    return LocalDocumentInventory(
        planning_documents=[get_document(path) for path in planning_paths],
        tracking_documents=[get_document(path) for path in tracking_paths],
    )


def _filter_ignored_paths(
    paths: Iterable[str],
    *,
    ignore_filter,
) -> tuple[str, ...]:
    return tuple(path for path in paths if not ignore_filter.ignores(path))


def _resolve_repo_relative_pattern(repo_root: Path, pattern: str) -> set[str]:
    pattern_path = Path(pattern)
    if pattern_path.is_absolute():
        raise ValueError(f"Glob pattern must be relative to the repository root: {pattern}")
    if ".." in pattern_path.parts:
        raise ValueError(f"Glob pattern must not traverse outside the repository root: {pattern}")

    matches: set[str] = set()
    for match in glob.glob(pattern, root_dir=repo_root, recursive=True):
        resolved_path = (repo_root / match).resolve()
        if not resolved_path.is_relative_to(repo_root):
            raise ValueError(f"Glob match escaped the repository root: {pattern}")
        if resolved_path.is_file():
            matches.add(resolved_path.relative_to(repo_root).as_posix())
    return matches
