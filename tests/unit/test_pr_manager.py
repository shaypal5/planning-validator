from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest

from planning_validator.config import load_config
from planning_validator.models import (
    AutomationPullRequest,
    FileEdit,
    PullRequestManagerAction,
    RecentPullRequest,
    ValidatedPatch,
)
from planning_validator.pr.branch_manager import BranchManager, GitRunResult
from planning_validator.pr.github_client import GitHubPullRequestClient, GitHubPullRequestError
from planning_validator.pr.pr_body import render_pull_request_body
from planning_validator.pr.pr_manager import PRManagerError, manage_patch_pull_request


class FakeGitRunner:
    def __init__(
        self,
        *,
        local_branches: set[str] | None = None,
        remote_branches: set[str] | None = None,
        staged_changes: bool = True,
    ) -> None:
        self.local_branches = local_branches or set()
        self.remote_branches = remote_branches or set()
        self.staged_changes = staged_changes
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        _repo_root: Path,
        args: Sequence[str],
        *,
        check: bool = True,
    ) -> GitRunResult:
        del check
        command = tuple(args)
        self.calls.append(command)
        if command[:3] == ("rev-parse", "--verify", "refs/heads/automation/planning-validator"):
            return GitRunResult(
                returncode=0 if "automation/planning-validator" in self.local_branches else 1
            )
        if command[:3] == (
            "rev-parse",
            "--verify",
            "refs/remotes/origin/automation/planning-validator",
        ):
            return GitRunResult(
                returncode=0 if "automation/planning-validator" in self.remote_branches else 1
            )
        if command == ("diff", "--cached", "--quiet", "--", "docs/roadmap.md"):
            return GitRunResult(returncode=1 if self.staged_changes else 0)
        return GitRunResult()


class FakeBranchManager:
    def __init__(self, *, committed: bool = True) -> None:
        self.committed = committed
        self.prepared: tuple[str, str] | None = None
        self.commit_message: str | None = None
        self.pushed_branch: str | None = None

    def prepare_branch(self, *, base_branch: str, automation_branch: str) -> None:
        self.prepared = (base_branch, automation_branch)

    def commit_validated_patch(self, patch: ValidatedPatch, *, commit_message: str) -> bool:
        assert [edit.path for edit in patch.edits] == ["docs/roadmap.md"]
        self.commit_message = commit_message
        return self.committed

    def push_branch(self, branch: str) -> None:
        self.pushed_branch = branch


class FakePullRequestClient:
    def __init__(self, *, existing: AutomationPullRequest | None = None) -> None:
        self.existing = existing
        self.created: dict[str, object] | None = None
        self.updated: dict[str, object] | None = None
        self.labels: list[str] = []
        self.reviewers: list[str] = []

    def find_open_pull_request(self, *, head_branch: str) -> AutomationPullRequest | None:
        assert head_branch == "automation/planning-validator"
        return self.existing

    def create_pull_request(
        self,
        *,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str,
        draft: bool,
    ) -> AutomationPullRequest:
        self.created = {
            "title": title,
            "body": body,
            "head_branch": head_branch,
            "base_branch": base_branch,
            "draft": draft,
        }
        return _automation_pr(
            number=77,
            title=title,
            head_branch=head_branch,
            base_branch=base_branch,
        )

    def update_pull_request(self, *, number: int, title: str, body: str) -> AutomationPullRequest:
        self.updated = {"number": number, "title": title, "body": body}
        return _automation_pr(number=number, title=title)

    def add_labels(self, *, number: int, labels: list[str]) -> None:
        assert number in {12, 77}
        self.labels = labels

    def request_reviewers(self, *, number: int, reviewers: list[str]) -> None:
        assert number in {12, 77}
        self.reviewers = reviewers


def test_branch_manager_creates_missing_automation_branch_from_base(tmp_path: Path) -> None:
    runner = FakeGitRunner()
    manager = BranchManager(repo_root=tmp_path, runner=runner)

    manager.prepare_branch(base_branch="main", automation_branch="automation/planning-validator")

    assert ("fetch", "origin") in runner.calls
    assert ("switch", "-c", "automation/planning-validator", "origin/main") in runner.calls


def test_branch_manager_updates_existing_remote_branch(tmp_path: Path) -> None:
    runner = FakeGitRunner(remote_branches={"automation/planning-validator"})
    manager = BranchManager(repo_root=tmp_path, runner=runner)

    manager.prepare_branch(base_branch="main", automation_branch="automation/planning-validator")

    assert (
        "switch",
        "-c",
        "automation/planning-validator",
        "--track",
        "origin/automation/planning-validator",
    ) in runner.calls
    assert ("pull", "--ff-only", "origin", "automation/planning-validator") in runner.calls


def test_branch_manager_commits_only_when_staged_changes_exist(tmp_path: Path) -> None:
    patch = _patch()
    no_change_runner = FakeGitRunner(staged_changes=False)
    manager = BranchManager(repo_root=tmp_path, runner=no_change_runner)

    assert manager.commit_validated_patch(patch, commit_message="docs: refresh") is False
    assert ("add", "--", "docs/roadmap.md") in no_change_runner.calls
    assert ("commit", "-m", "docs: refresh", "--", "docs/roadmap.md") not in no_change_runner.calls

    changed_runner = FakeGitRunner(staged_changes=True)
    manager = BranchManager(repo_root=tmp_path, runner=changed_runner)

    assert manager.commit_validated_patch(patch, commit_message="docs: refresh") is True
    assert ("commit", "-m", "docs: refresh", "--", "docs/roadmap.md") in changed_runner.calls


def test_branch_manager_pushes_automation_branch(tmp_path: Path) -> None:
    runner = FakeGitRunner()
    manager = BranchManager(repo_root=tmp_path, runner=runner)

    manager.push_branch("automation/planning-validator")

    assert ("push", "--set-upstream", "origin", "automation/planning-validator") in runner.calls


def test_github_pull_request_client_creates_pr_and_applies_metadata() -> None:
    requests: list[tuple[str, str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode()) if request.content else None
        requests.append((request.method, request.url.path, payload))
        if request.method == "POST" and request.url.path == "/repos/acme/widgets/pulls":
            assert payload == {
                "title": "docs: refresh planning/tracking files",
                "body": "body",
                "head": "automation/planning-validator",
                "base": "main",
                "draft": True,
            }
            return httpx.Response(201, json=_github_pr_payload(number=12))
        if request.method == "POST" and request.url.path == "/repos/acme/widgets/issues/12/labels":
            assert payload == {"labels": ["docs", "automation"]}
            return httpx.Response(200, json=[])
        if (
            request.method == "POST"
            and request.url.path == "/repos/acme/widgets/pulls/12/requested_reviewers"
        ):
            assert payload == {"reviewers": ["shay"]}
            return httpx.Response(201, json={})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubPullRequestClient(
        owner="acme",
        repo="widgets",
        token="token",
        transport=httpx.MockTransport(handler),
    )

    pull_request = client.create_pull_request(
        title="docs: refresh planning/tracking files",
        body="body",
        head_branch="automation/planning-validator",
        base_branch="main",
        draft=True,
    )
    client.add_labels(number=pull_request.number, labels=["docs", "automation"])
    client.request_reviewers(number=pull_request.number, reviewers=["shay"])

    assert pull_request.number == 12
    assert requests[-1][1] == "/repos/acme/widgets/pulls/12/requested_reviewers"


def test_github_pull_request_client_finds_and_updates_existing_pr() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/repos/acme/widgets/pulls":
            assert "head=acme%3Aautomation%2Fplanning-validator" in str(request.url)
            return httpx.Response(200, json=[_github_pr_payload(number=12)])
        if request.method == "PATCH" and request.url.path == "/repos/acme/widgets/pulls/12":
            payload = json.loads(request.content.decode())
            assert payload == {"title": "docs: refresh", "body": "updated"}
            return httpx.Response(200, json=_github_pr_payload(number=12, title="docs: refresh"))
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubPullRequestClient(
        owner="acme",
        repo="widgets",
        token="token",
        transport=httpx.MockTransport(handler),
    )

    existing = client.find_open_pull_request(head_branch="automation/planning-validator")
    assert existing is not None
    updated = client.update_pull_request(
        number=existing.number,
        title="docs: refresh",
        body="updated",
    )

    assert updated.title == "docs: refresh"
    assert updated.head_branch == "automation/planning-validator"


def test_github_pull_request_client_surfaces_api_failures() -> None:
    client = GitHubPullRequestClient(
        owner="acme",
        repo="widgets",
        token="token",
        transport=httpx.MockTransport(lambda _request: httpx.Response(500, json={})),
    )

    with pytest.raises(GitHubPullRequestError, match="GitHub API request failed"):
        client.find_open_pull_request(head_branch="automation/planning-validator")


def test_structured_pr_body_includes_evidence_files_and_metadata(tmp_path: Path) -> None:
    resolved = _resolved_config(tmp_path)

    body = render_pull_request_body(
        resolved_config=resolved,
        patch=_patch(),
        recent_prs=[_recent_pr()],
        base_branch="main",
        automation_branch="automation/planning-validator",
    )

    assert "## Why this PR exists" in body
    assert "PR #42 - Add patcher core" in body
    assert "- docs/roadmap.md" in body
    assert "- Head SHA: abc123" in body
    assert "- Config path: .github/planning-validator.yml" in body


def test_short_pr_body_is_deterministic_and_compact(tmp_path: Path) -> None:
    resolved = _resolved_config(tmp_path, extra_pull_request="  body_mode: short\n")

    body = render_pull_request_body(
        resolved_config=resolved,
        patch=_patch(),
        recent_prs=[_recent_pr()],
        base_branch="main",
        automation_branch="automation/planning-validator",
    )

    assert "## Evidence considered" not in body
    assert body == render_pull_request_body(
        resolved_config=resolved,
        patch=_patch(),
        recent_prs=[_recent_pr()],
        base_branch="main",
        automation_branch="automation/planning-validator",
    )


def test_manage_patch_pull_request_noops_when_disabled_or_empty(tmp_path: Path) -> None:
    disabled = manage_patch_pull_request(
        resolved_config=_resolved_config(tmp_path, extra_pull_request="  enabled: false\n"),
        patch=_patch(),
        recent_prs=[],
        repo="acme/widgets",
        default_branch="main",
        github_client=FakePullRequestClient(),
        branch_manager=FakeBranchManager(),
    )
    empty = manage_patch_pull_request(
        resolved_config=_resolved_config(tmp_path),
        patch=_patch(edits=[]),
        recent_prs=[],
        repo="acme/widgets",
        default_branch="main",
        github_client=FakePullRequestClient(),
        branch_manager=FakeBranchManager(),
    )

    assert disabled.action is PullRequestManagerAction.DISABLED
    assert empty.action is PullRequestManagerAction.NO_CHANGES


def test_manage_patch_pull_request_creates_new_pr(tmp_path: Path) -> None:
    branch_manager = FakeBranchManager()
    github_client = FakePullRequestClient()

    result = manage_patch_pull_request(
        resolved_config=_resolved_config(
            tmp_path,
            extra_pull_request=("  labels: [docs]\n  reviewers: [shay]\n"),
        ),
        patch=_patch(),
        recent_prs=[_recent_pr()],
        repo="acme/widgets",
        default_branch="main",
        github_client=github_client,
        branch_manager=branch_manager,
    )

    assert result.action is PullRequestManagerAction.CREATED
    assert branch_manager.prepared == ("main", "automation/planning-validator")
    assert branch_manager.commit_message == "docs: refresh planning/tracking files"
    assert branch_manager.pushed_branch == "automation/planning-validator"
    assert github_client.created is not None
    assert github_client.labels == ["docs"]
    assert github_client.reviewers == ["shay"]


def test_manage_patch_pull_request_updates_existing_pr(tmp_path: Path) -> None:
    github_client = FakePullRequestClient(existing=_automation_pr(number=12))

    result = manage_patch_pull_request(
        resolved_config=_resolved_config(tmp_path),
        patch=_patch(),
        recent_prs=[_recent_pr()],
        repo="acme/widgets",
        default_branch="main",
        github_client=github_client,
        branch_manager=FakeBranchManager(),
    )

    assert result.action is PullRequestManagerAction.UPDATED
    assert github_client.created is None
    assert github_client.updated is not None
    assert github_client.updated["number"] == 12


def test_manage_patch_pull_request_refuses_duplicate_when_updates_disabled(tmp_path: Path) -> None:
    with pytest.raises(PRManagerError, match="already exists"):
        manage_patch_pull_request(
            resolved_config=_resolved_config(
                tmp_path,
                extra_pull_request="  update_existing: false\n",
            ),
            patch=_patch(),
            recent_prs=[_recent_pr()],
            repo="acme/widgets",
            default_branch="main",
            github_client=FakePullRequestClient(existing=_automation_pr(number=12)),
            branch_manager=FakeBranchManager(),
        )


def test_manage_patch_pull_request_no_push_or_pr_when_git_has_no_changes(tmp_path: Path) -> None:
    branch_manager = FakeBranchManager(committed=False)
    github_client = FakePullRequestClient()

    result = manage_patch_pull_request(
        resolved_config=_resolved_config(tmp_path),
        patch=_patch(),
        recent_prs=[],
        repo="acme/widgets",
        default_branch="main",
        github_client=github_client,
        branch_manager=branch_manager,
    )

    assert result.action is PullRequestManagerAction.NO_CHANGES
    assert branch_manager.pushed_branch is None
    assert github_client.created is None


def _resolved_config(tmp_path: Path, *, extra_pull_request: str = ""):
    config_path = tmp_path / ".github/planning-validator.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs/roadmap.md").write_text("# Roadmap\n", encoding="utf-8")
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
            f"{_pull_request_yaml(extra_pull_request)}"
        ),
        encoding="utf-8",
    )
    return load_config(config_path, repo_root=tmp_path)


def _pull_request_yaml(extra_pull_request: str) -> str:
    if extra_pull_request:
        return "pull_request:\n" + extra_pull_request
    return ""


def _patch(*, edits: list[FileEdit] | None = None) -> ValidatedPatch:
    return ValidatedPatch(
        repo="acme/widgets",
        head_sha="abc123",
        summary="Updated docs.",
        edits=[
            FileEdit(
                path="docs/roadmap.md",
                operation="replace_file",
                new_content="# Roadmap\nDone.\n",
                rationale="Reflects PR #42.",
                evidence_refs=["PR #42"],
            )
        ]
        if edits is None
        else edits,
    )


def _recent_pr() -> RecentPullRequest:
    return RecentPullRequest.model_validate(
        {
            "number": 42,
            "title": "Add patcher core",
            "merged_at": "2026-04-20T09:00:00Z",
            "url": "https://github.com/acme/widgets/pull/42",
        }
    )


def _automation_pr(
    *,
    number: int,
    title: str = "docs: refresh planning/tracking files",
    head_branch: str = "automation/planning-validator",
    base_branch: str = "main",
) -> AutomationPullRequest:
    return AutomationPullRequest(
        number=number,
        title=title,
        url=f"https://github.com/acme/widgets/pull/{number}",
        head_branch=head_branch,
        base_branch=base_branch,
        draft=True,
    )


def _github_pr_payload(
    *,
    number: int,
    title: str = "docs: refresh planning/tracking files",
) -> dict[str, object]:
    return {
        "number": number,
        "title": title,
        "html_url": f"https://github.com/acme/widgets/pull/{number}",
        "head": {"ref": "automation/planning-validator"},
        "base": {"ref": "main"},
        "draft": True,
    }
