from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from planning_validator.cli import app
from planning_validator.config import ConfigError, load_config

runner = CliRunner()


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def create_valid_repo(tmp_path: Path) -> Path:
    write_file(tmp_path / "README.md", "# Example repo\n")
    write_file(tmp_path / "docs/roadmap.md", "# Roadmap\n")
    write_file(
        tmp_path / ".github/planning-validator.yml",
        """
        schema_version: v1alpha1
        planning_files:
          - README.md
          - docs/roadmap.md
        tracking_files: []
        patching:
          provider: openai
          model: gpt-5.4-thinking
          allowed_update_globs:
            - README.md
            - docs/**/*.md
        """,
    )
    return tmp_path / ".github/planning-validator.yml"


def test_load_config_accepts_minimal_valid_config(tmp_path: Path) -> None:
    config_path = create_valid_repo(tmp_path)

    resolved = load_config(config_path, repo_root=tmp_path)

    assert resolved.config.schema_version == "v1alpha1"
    assert resolved.planning_paths == ("README.md", "docs/roadmap.md")
    assert resolved.tracking_paths == ()
    assert resolved.patchable_paths == ("README.md", "docs/roadmap.md")


def test_load_config_rejects_invalid_schema_version(tmp_path: Path) -> None:
    write_file(tmp_path / "README.md", "# Example repo\n")
    write_file(
        tmp_path / ".github/planning-validator.yml",
        """
        schema_version: v2
        planning_files:
          - README.md
        patching:
          provider: openai
          model: gpt-5.4-thinking
          allowed_update_globs:
            - README.md
        """,
    )

    with pytest.raises(ConfigError, match="schema_version"):
        load_config(tmp_path / ".github/planning-validator.yml", repo_root=tmp_path)


def test_load_config_rejects_missing_required_fields(tmp_path: Path) -> None:
    write_file(
        tmp_path / ".github/planning-validator.yml",
        """
        schema_version: v1alpha1
        planning_files:
          - README.md
        """,
    )

    with pytest.raises(ConfigError, match="patching"):
        load_config(tmp_path / ".github/planning-validator.yml", repo_root=tmp_path)


def test_load_config_rejects_missing_repo_root(tmp_path: Path) -> None:
    config_path = create_valid_repo(tmp_path)

    with pytest.raises(ConfigError, match="Repository root not found"):
        load_config(config_path, repo_root=tmp_path / "missing")


def test_load_config_rejects_repo_root_file_path(tmp_path: Path) -> None:
    config_path = create_valid_repo(tmp_path)

    with pytest.raises(ConfigError, match="Repository root is not a directory"):
        load_config(config_path, repo_root=config_path)


def test_load_config_rejects_bad_numeric_ranges(tmp_path: Path) -> None:
    write_file(tmp_path / "README.md", "# Example repo\n")
    write_file(
        tmp_path / ".github/planning-validator.yml",
        """
        schema_version: v1alpha1
        planning_files:
          - README.md
        staleness:
          min_signal_score: 1.4
        patching:
          provider: openai
          model: gpt-5.4-thinking
          allowed_update_globs:
            - README.md
        """,
    )

    with pytest.raises(ConfigError, match="min_signal_score"):
        load_config(tmp_path / ".github/planning-validator.yml", repo_root=tmp_path)


def test_load_config_rejects_unbounded_or_unpatchable_globs(tmp_path: Path) -> None:
    write_file(tmp_path / "README.md", "# Example repo\n")
    write_file(
        tmp_path / ".github/planning-validator.yml",
        """
        schema_version: v1alpha1
        planning_files:
          - README.md
        patching:
          provider: openai
          model: gpt-5.4-thinking
          allowed_update_globs:
            - "**/*"
        """,
    )

    with pytest.raises(ConfigError, match="unbounded pattern"):
        load_config(tmp_path / ".github/planning-validator.yml", repo_root=tmp_path)


def test_load_config_rejects_when_docs_are_outside_patch_scope(tmp_path: Path) -> None:
    write_file(tmp_path / "README.md", "# Example repo\n")
    write_file(
        tmp_path / ".github/planning-validator.yml",
        """
        schema_version: v1alpha1
        planning_files:
          - README.md
        patching:
          provider: openai
          model: gpt-5.4-thinking
          allowed_update_globs:
            - docs/**/*.md
        """,
    )

    with pytest.raises(ConfigError, match="At least one planning/tracking file"):
        load_config(tmp_path / ".github/planning-validator.yml", repo_root=tmp_path)


def test_load_config_rejects_non_markdown_matches(tmp_path: Path) -> None:
    write_file(tmp_path / "docs/roadmap.txt", "not markdown\n")
    write_file(
        tmp_path / ".github/planning-validator.yml",
        """
        schema_version: v1alpha1
        planning_files:
          - docs/roadmap.txt
        patching:
          provider: openai
          model: gpt-5.4-thinking
          allowed_update_globs:
            - docs/**
        """,
    )

    with pytest.raises(ConfigError, match="matched non-markdown files"):
        load_config(tmp_path / ".github/planning-validator.yml", repo_root=tmp_path)


def test_load_config_rejects_invalid_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / ".github/planning-validator.yml"
    write_file(config_path, "schema_version: [\n")

    with pytest.raises(ConfigError, match="Failed to parse YAML"):
        load_config(config_path, repo_root=tmp_path)


def test_load_config_rejects_non_mapping_yaml_root(tmp_path: Path) -> None:
    config_path = tmp_path / ".github/planning-validator.yml"
    write_file(config_path, "- just\n- a\n- list\n")

    with pytest.raises(ConfigError, match="Config root must be a YAML mapping"):
        load_config(config_path, repo_root=tmp_path)


def test_load_config_uses_glob_semantics_for_patchable_paths(tmp_path: Path) -> None:
    write_file(tmp_path / "docs/roadmap.md", "# Roadmap\n")
    write_file(
        tmp_path / ".github/planning-validator.yml",
        """
        schema_version: v1alpha1
        planning_files:
          - docs/roadmap.md
        patching:
          provider: openai
          model: gpt-5.4-thinking
          allowed_update_globs:
            - docs/**/*.md
        """,
    )

    resolved = load_config(tmp_path / ".github/planning-validator.yml", repo_root=tmp_path)

    assert resolved.patchable_paths == ("docs/roadmap.md",)


def test_validate_config_cli_reports_success(tmp_path: Path) -> None:
    config_path = create_valid_repo(tmp_path)

    result = runner.invoke(
        app,
        [
            "validate-config",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["patchable_files"] == ["README.md", "docs/roadmap.md"]


def test_validate_config_cli_excludes_forbidden_files_from_patchable_output(tmp_path: Path) -> None:
    write_file(tmp_path / "docs/roadmap.md", "# Roadmap\n")
    write_file(tmp_path / "docs/tasks.md", "# Tasks\n")
    write_file(
        tmp_path / ".github/planning-validator.yml",
        """
        schema_version: v1alpha1
        planning_files:
          - docs/roadmap.md
        tracking_files:
          - docs/tasks.md
        patching:
          provider: openai
          model: gpt-5.4-thinking
          allowed_update_globs:
            - docs/**/*.md
          forbidden_update_globs:
            - docs/tasks.md
        """,
    )

    result = runner.invoke(
        app,
        [
            "validate-config",
            "--config",
            str(tmp_path / ".github/planning-validator.yml"),
            "--repo-root",
            str(tmp_path),
            "--json",
        ],
    )

    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["planning_files"] == ["docs/roadmap.md"]
    assert payload["tracking_files"] == ["docs/tasks.md"]
    assert payload["patchable_files"] == ["docs/roadmap.md"]


def test_validate_config_cli_reports_config_errors_as_json(tmp_path: Path) -> None:
    write_file(
        tmp_path / ".github/planning-validator.yml",
        """
        schema_version: v1alpha1
        planning_files:
          - README.md
        """,
    )

    result = runner.invoke(
        app,
        [
            "validate-config",
            "--config",
            str(tmp_path / ".github/planning-validator.yml"),
            "--repo-root",
            str(tmp_path),
            "--json",
        ],
    )

    payload = json.loads(result.stdout)

    assert result.exit_code == 1
    assert payload["ok"] is False
    assert "patching" in payload["error"]


def test_validate_config_cli_rejects_missing_repo_root_before_loader(tmp_path: Path) -> None:
    config_path = create_valid_repo(tmp_path)

    result = runner.invoke(
        app,
        [
            "validate-config",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path / "missing"),
        ],
    )

    assert result.exit_code == 2
    assert "does not exist" in result.output
