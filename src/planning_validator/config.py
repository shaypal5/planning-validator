"""Configuration loading and validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from planning_validator.file_io import resolve_repo_relative_globs
from planning_validator.models import ValidatorConfig


class ConfigError(ValueError):
    """Raised when the repository config is invalid."""


@dataclass(frozen=True)
class ResolvedConfig:
    config: ValidatorConfig
    config_path: Path
    repo_root: Path
    planning_paths: tuple[str, ...]
    tracking_paths: tuple[str, ...]
    patchable_paths: tuple[str, ...]

    @property
    def all_document_paths(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.planning_paths, *self.tracking_paths)))


def load_config(config_path: str | Path, repo_root: str | Path | None = None) -> ResolvedConfig:
    path = Path(config_path).expanduser().resolve()
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")

    root = Path(repo_root).expanduser().resolve() if repo_root else Path.cwd().resolve()
    if not root.exists():
        raise ConfigError(f"Repository root not found: {root}")
    if not root.is_dir():
        raise ConfigError(f"Repository root is not a directory: {root}")

    try:
        raw_data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse YAML: {exc}") from exc

    if not isinstance(raw_data, dict):
        raise ConfigError("Config root must be a YAML mapping")

    try:
        config = ValidatorConfig.model_validate(raw_data)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc

    planning_paths = _resolve_globs(root, config.planning_files, field_name="planning_files")
    tracking_paths = _resolve_globs(root, config.tracking_files, field_name="tracking_files")
    patchable_paths = _validate_semantics(
        repo_root=root,
        config=config,
        planning_paths=planning_paths,
        tracking_paths=tracking_paths,
    )

    return ResolvedConfig(
        config=config,
        config_path=path,
        repo_root=root,
        planning_paths=tuple(sorted(planning_paths)),
        tracking_paths=tuple(sorted(tracking_paths)),
        patchable_paths=tuple(sorted(patchable_paths)),
    )


def _resolve_globs(repo_root: Path, patterns: list[str], *, field_name: str) -> set[str]:
    matches: set[str] = set()
    for pattern in patterns:
        try:
            file_matches = resolve_repo_relative_globs(repo_root, [pattern])
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        if not file_matches:
            raise ConfigError(f"{field_name} pattern matched no files: {pattern}")
        matches.update(file_matches)
    _reject_non_markdown(matches, field_name=field_name)
    return matches


def _reject_non_markdown(paths: set[str], *, field_name: str) -> None:
    non_markdown = sorted(
        path for path in paths if Path(path).suffix.lower() not in {".md", ".markdown"}
    )
    if non_markdown:
        joined = ", ".join(non_markdown)
        raise ConfigError(f"{field_name} matched non-markdown files: {joined}")


def _validate_semantics(
    *,
    repo_root: Path,
    config: ValidatorConfig,
    planning_paths: set[str],
    tracking_paths: set[str],
) -> set[str]:
    if any(pattern.strip() == "**/*" for pattern in config.patching.allowed_update_globs):
        raise ConfigError(
            "patching.allowed_update_globs must not contain the unbounded pattern '**/*'"
        )

    all_docs = planning_paths | tracking_paths
    allowed_paths = _resolve_optional_globs(repo_root, config.patching.allowed_update_globs)
    forbidden_paths = _resolve_optional_globs(repo_root, config.patching.forbidden_update_globs)
    patchable_docs = (all_docs & allowed_paths) - forbidden_paths
    if not patchable_docs:
        raise ConfigError(
            "At least one planning/tracking file must match patching.allowed_update_globs "
            "without also matching patching.forbidden_update_globs",
        )
    return patchable_docs


def _resolve_optional_globs(repo_root: Path, patterns: list[str]) -> set[str]:
    try:
        return set(resolve_repo_relative_globs(repo_root, patterns))
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
