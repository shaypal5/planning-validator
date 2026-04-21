"""Helpers for applying .gitignore rules to repo-relative paths."""

from __future__ import annotations

from pathlib import Path

from pathspec import PathSpec


class GitIgnoreFilter:
    """Evaluate repo-relative paths against collected .gitignore rules."""

    def __init__(self, *, repo_root: Path, spec: PathSpec | None) -> None:
        self.repo_root = repo_root
        self._spec = spec

    def ignores(self, path: str) -> bool:
        if self._spec is None:
            return False
        return self._spec.match_file(path)


def load_gitignore_filter(repo_root: Path) -> GitIgnoreFilter:
    patterns: list[str] = []
    for gitignore_path in sorted(repo_root.rglob(".gitignore")):
        if not gitignore_path.is_file():
            continue

        base_dir = gitignore_path.parent.relative_to(repo_root).as_posix()
        raw_lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        patterns.extend(_prefix_gitignore_patterns(raw_lines, base_dir=base_dir))

    spec = PathSpec.from_lines("gitwildmatch", patterns) if patterns else None
    return GitIgnoreFilter(repo_root=repo_root, spec=spec)


def _prefix_gitignore_patterns(lines: list[str], *, base_dir: str) -> list[str]:
    prefixed_patterns: list[str] = []
    for line in lines:
        if not line or line.isspace():
            continue

        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue

        is_negated = stripped.startswith("!")
        body = stripped[1:] if is_negated else stripped
        if not body:
            continue

        if base_dir in {"", "."}:
            prefixed_patterns.append(stripped)
            continue

        normalized_body = body.lstrip("/") if body.startswith("/") else body
        prefix = f"{base_dir}/"
        candidate = f"{prefix}{normalized_body}"
        prefixed_patterns.append(f"!{candidate}" if is_negated else candidate)

    return prefixed_patterns
