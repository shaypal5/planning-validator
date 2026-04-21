from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from planning_validator.cli import app
from planning_validator.config import ConfigError, load_config


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


def test_validate_config_cli_reports_success(tmp_path: Path) -> None:
    config_path = create_valid_repo(tmp_path)
    runner = CliRunner()

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
    assert '"ok": true' in result.stdout
