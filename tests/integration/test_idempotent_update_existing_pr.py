from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from planning_validator.cli import app
from planning_validator.models import PullRequestManagerAction, PullRequestManagerResult

from .conftest import assert_patch_targets_roadmap, automation_pr, configure_offline_run


def test_idempotent_update_existing_pr(
    monkeypatch: pytest.MonkeyPatch,
    fixture_repo: Any,
    runner: CliRunner,
) -> None:
    repo_root = fixture_repo("idempotent-existing-pr")
    configure_offline_run(monkeypatch, repo_root)
    updates: list[int] = []

    def fake_manage_patch_pull_request(**kwargs: object) -> PullRequestManagerResult:
        assert_patch_targets_roadmap(kwargs["patch"])
        updates.append(77)
        return PullRequestManagerResult(
            action=PullRequestManagerAction.UPDATED,
            branch="automation/planning-validator",
            pull_request=automation_pr(77),
            committed=True,
            pushed=True,
            message="Updated planning-validator PR #77.",
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
    assert updates == [77]
    assert "Status: pr_updated" in result.stdout
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["status"] == "pr_updated"
    assert payload["pr_action"] == "updated"
    assert payload["pr_url"] == "https://github.com/acme/widgets/pull/77"
