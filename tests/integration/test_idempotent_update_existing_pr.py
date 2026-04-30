from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from planning_validator.cli import app
from planning_validator.models import AutomationPullRequest, ValidatedPatch

from .conftest import automation_pr, configure_offline_run


class FakeExistingPullRequestClient:
    def __init__(self, **_kwargs: object) -> None:
        self.created: list[dict[str, object]] = []
        self.updated: list[dict[str, object]] = []
        self.labels: list[tuple[int, list[str]]] = []
        self.reviewers: list[tuple[int, list[str]]] = []

    def __enter__(self) -> FakeExistingPullRequestClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def find_open_pull_request(self, *, head_branch: str) -> AutomationPullRequest | None:
        assert head_branch == "automation/planning-validator"
        return automation_pr(77)

    def create_pull_request(self, **kwargs: object) -> AutomationPullRequest:
        self.created.append(kwargs)
        raise AssertionError("existing automation PR should be updated, not duplicated")

    def update_pull_request(
        self,
        *,
        number: int,
        title: str,
        body: str,
    ) -> AutomationPullRequest:
        self.updated.append({"number": number, "title": title, "body": body})
        return automation_pr(number)

    def add_labels(self, *, number: int, labels: list[str]) -> None:
        self.labels.append((number, labels))

    def request_reviewers(self, *, number: int, reviewers: list[str]) -> None:
        self.reviewers.append((number, reviewers))


class RecordingBranchManager:
    instances: list[RecordingBranchManager] = []

    def __init__(self, *, repo_root: object) -> None:
        self.repo_root = repo_root
        self.prepared: tuple[str, str] | None = None
        self.committed_patch: ValidatedPatch | None = None
        self.commit_message: str | None = None
        self.pushed_branch: str | None = None
        self.instances.append(self)

    def prepare_branch(self, *, base_branch: str, automation_branch: str) -> None:
        self.prepared = (base_branch, automation_branch)

    def commit_validated_patch(self, patch: ValidatedPatch, *, commit_message: str) -> bool:
        self.committed_patch = patch
        self.commit_message = commit_message
        return True

    def push_branch(self, branch: str) -> None:
        self.pushed_branch = branch


def test_idempotent_update_existing_pr(
    monkeypatch: pytest.MonkeyPatch,
    fixture_repo: Any,
    runner: CliRunner,
) -> None:
    repo_root = fixture_repo("idempotent-existing-pr")
    configure_offline_run(monkeypatch, repo_root)
    pull_request_clients: list[FakeExistingPullRequestClient] = []
    RecordingBranchManager.instances = []

    def fake_pull_request_client(**kwargs: object) -> FakeExistingPullRequestClient:
        client = FakeExistingPullRequestClient(**kwargs)
        pull_request_clients.append(client)
        return client

    monkeypatch.setattr("planning_validator.cli.GitHubPullRequestClient", fake_pull_request_client)
    monkeypatch.setattr("planning_validator.pr.pr_manager.BranchManager", RecordingBranchManager)

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
    assert "Status: pr_updated" in result.stdout
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["status"] == "pr_updated"
    assert payload["pr_action"] == "updated"
    assert payload["pr_url"] == "https://github.com/acme/widgets/pull/77"
    assert len(pull_request_clients) == 1
    assert pull_request_clients[0].created == []
    assert [update["number"] for update in pull_request_clients[0].updated] == [77]
    assert pull_request_clients[0].labels == [(77, ["documentation", "automation"])]
    assert pull_request_clients[0].reviewers == [(77, [])]
    assert len(RecordingBranchManager.instances) == 1
    branch_manager = RecordingBranchManager.instances[0]
    assert branch_manager.prepared == ("main", "automation/planning-validator")
    assert branch_manager.pushed_branch == "automation/planning-validator"
    assert branch_manager.committed_patch is not None
    assert [edit.path for edit in branch_manager.committed_patch.edits] == ["docs/roadmap.md"]
