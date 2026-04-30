from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from planning_validator.cli import app
from planning_validator.models import PullRequestManagerAction, PullRequestManagerResult

from .conftest import assert_patch_targets_roadmap, automation_pr, configure_offline_run


def test_end_to_end_simple_creates_pr_with_one_bounded_patch(
    monkeypatch: pytest.MonkeyPatch,
    fixture_repo: Any,
    runner: CliRunner,
) -> None:
    repo_root = fixture_repo("stale-one-patch")
    configure_offline_run(monkeypatch, repo_root)
    pr_calls = 0

    def fake_manage_patch_pull_request(**kwargs: object) -> PullRequestManagerResult:
        nonlocal pr_calls
        pr_calls += 1
        assert kwargs["repo"] == "acme/widgets"
        assert_patch_targets_roadmap(kwargs["patch"])
        return PullRequestManagerResult(
            action=PullRequestManagerAction.CREATED,
            branch="automation/planning-validator",
            pull_request=automation_pr(77),
            committed=True,
            pushed=True,
            message="Created planning-validator PR #77.",
        )

    monkeypatch.setattr(
        "planning_validator.cli.manage_patch_pull_request",
        fake_manage_patch_pull_request,
    )

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
    assert pr_calls == 1
    assert "Status: pr_created" in result.stdout
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["status"] == "pr_created"
    assert payload["edited_files"] == ["docs/roadmap.md"]
    assert payload["pr_url"] == "https://github.com/acme/widgets/pull/77"


def test_invalid_model_output_fails_before_pr_management(
    monkeypatch: pytest.MonkeyPatch,
    fixture_repo: Any,
    runner: CliRunner,
) -> None:
    repo_root = fixture_repo("invalid-model-output")
    configure_offline_run(monkeypatch, repo_root, model_content="TBD")

    def fail_pr_manager(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("PR manager must not run after invalid model output")

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

    assert result.exit_code == 1
    assert "Run failed: empty_or_placeholder_content" in result.stderr
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["patch_status"] == "failed"
    assert payload["pr_action"] is None
