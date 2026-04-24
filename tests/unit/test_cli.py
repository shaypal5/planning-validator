from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from planning_validator.cli import app
from planning_validator.models import DetectionResult, RepoSnapshot

runner = CliRunner()


class MetadataStub:
    repo = "acme/widgets"
    default_branch = "main"
    head_sha = "abc123"


def test_detect_writes_detection_result_and_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / ".github/planning-validator.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        (
            "schema_version: v1alpha1\n"
            "planning_files:\n"
            "  - docs/roadmap.md\n"
            "patching:\n"
            "  provider: openai\n"
            "  model: gpt-5.4-thinking\n"
            "  allowed_update_globs:\n"
            "    - docs/**/*.md\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/roadmap.md").write_text("# Roadmap\n", encoding="utf-8")

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(
        "planning_validator.cli.collect_repo_metadata",
        lambda _repo_root: MetadataStub(),
    )
    monkeypatch.setattr("planning_validator.cli.GitHubEvidenceClient", FakeClient)
    monkeypatch.setattr(
        "planning_validator.cli.collect_recent_pr_snapshot",
        lambda *args, **kwargs: RepoSnapshot.model_validate(
            {
                "repo": "acme/widgets",
                "default_branch": "main",
                "head_sha": "abc123",
                "planning_files": [
                    {"path": "docs/roadmap.md", "content": "# Roadmap\n", "sha": "1"}
                ],
                "tracking_files": [],
                "recent_prs": [],
                "recent_issues": [],
            }
        ),
    )
    monkeypatch.setattr(
        "planning_validator.cli.run_detector",
        lambda resolved, snapshot: DetectionResult.model_validate(
            {
                "is_stale": False,
                "summary": "No stale documentation signals detected.",
                "signals": [],
                "target_files": [],
                "ignored_prs": [],
            }
        ),
    )

    json_out = tmp_path / "artifacts/detection.json"
    result = runner.invoke(
        app,
        [
            "detect",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--json-out",
            str(json_out),
        ],
    )

    assert result.exit_code == 0
    assert "No stale documentation signals detected." in result.stdout
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["is_stale"] is False


def test_detect_surfaces_failures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / ".github/planning-validator.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("schema_version: bad\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "detect",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--json-out",
            str(tmp_path / "detection.json"),
        ],
    )

    assert result.exit_code == 1
    assert "Detection failed:" in result.stderr


def test_detect_requires_github_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / ".github/planning-validator.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        (
            "schema_version: v1alpha1\n"
            "planning_files:\n"
            "  - docs/roadmap.md\n"
            "patching:\n"
            "  provider: openai\n"
            "  model: gpt-5.4-thinking\n"
            "  allowed_update_globs:\n"
            "    - docs/**/*.md\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/roadmap.md").write_text("# Roadmap\n", encoding="utf-8")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(
        "planning_validator.cli.collect_repo_metadata",
        lambda _repo_root: MetadataStub(),
    )

    result = runner.invoke(
        app,
        [
            "detect",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--json-out",
            str(tmp_path / "detection.json"),
        ],
    )

    assert result.exit_code == 1
    assert "GITHUB_TOKEN environment variable is required" in result.stderr


def test_patch_command_is_reserved() -> None:
    result = runner.invoke(app, ["patch"])

    assert result.exit_code == 1
    assert "'patch' is reserved for a later milestone." in result.stderr


def test_run_command_is_reserved() -> None:
    result = runner.invoke(app, ["run"])

    assert result.exit_code == 1
    assert "'run' is reserved for a later milestone." in result.stderr
