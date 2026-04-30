from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from planning_validator.cli import app

from .conftest import configure_offline_run


def test_noop_when_fresh(
    monkeypatch: pytest.MonkeyPatch,
    fixture_repo: Any,
    runner: CliRunner,
) -> None:
    repo_root = fixture_repo("fresh-noop")
    configure_offline_run(monkeypatch, repo_root)

    def fail_patcher(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("patcher must not run when fixture docs are fresh")

    def fail_pr_manager(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("PR manager must not run when fixture docs are fresh")

    monkeypatch.setattr("planning_validator.cli.run_patcher", fail_patcher)
    monkeypatch.setattr("planning_validator.cli.manage_patch_pull_request", fail_pr_manager)

    summary_json = repo_root / ".planning-validator/run-summary.json"
    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(repo_root / ".github/planning-validator.yml"),
            "--repo-root",
            str(repo_root),
            "--summary-json",
            str(summary_json),
        ],
    )

    assert result.exit_code == 0
    assert "Status: clean" in result.stdout
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["status"] == "clean"
    assert payload["target_files"] == []


def test_fixture_config_validates_cleanly(fixture_repo: Any, runner: CliRunner) -> None:
    repo_root = fixture_repo("fresh-noop")

    result = runner.invoke(
        app,
        [
            "validate-config",
            "--config",
            str(repo_root / ".github/planning-validator.yml"),
            "--repo-root",
            str(repo_root),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["patchable_files"] == ["docs/roadmap.md", "docs/tasks.md"]
