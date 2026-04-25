"""High-level orchestration for branch updates and draft PR management."""

from __future__ import annotations

from typing import Protocol

from planning_validator.config import ResolvedConfig
from planning_validator.models import (
    AutomationPullRequest,
    PullRequestManagerAction,
    PullRequestManagerResult,
    RecentPullRequest,
    ValidatedPatch,
)
from planning_validator.pr.branch_manager import BranchManager
from planning_validator.pr.pr_body import render_pull_request_body


class PRManagerError(RuntimeError):
    """Raised when automation PR orchestration cannot proceed safely."""


class PullRequestClient(Protocol):
    def find_open_pull_request(self, *, head_branch: str) -> AutomationPullRequest | None:
        """Return the existing open automation PR, if any."""

    def create_pull_request(
        self,
        *,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str,
        draft: bool,
    ) -> AutomationPullRequest:
        """Create a pull request."""

    def update_pull_request(self, *, number: int, title: str, body: str) -> AutomationPullRequest:
        """Update an existing pull request."""

    def add_labels(self, *, number: int, labels: list[str]) -> None:
        """Apply labels to a pull request through the GitHub issues API."""

    def request_reviewers(self, *, number: int, reviewers: list[str]) -> None:
        """Request reviewers for a pull request."""


def manage_patch_pull_request(
    *,
    resolved_config: ResolvedConfig,
    patch: ValidatedPatch,
    recent_prs: list[RecentPullRequest],
    repo: str,
    default_branch: str,
    github_client: PullRequestClient | None = None,
    branch_manager: BranchManager | None = None,
) -> PullRequestManagerResult:
    pr_config = resolved_config.config.pull_request
    automation_branch = pr_config.branch

    if not pr_config.enabled:
        return PullRequestManagerResult(
            action=PullRequestManagerAction.DISABLED,
            branch=automation_branch,
            message="Pull request management is disabled by configuration.",
        )
    if not patch.edits:
        return PullRequestManagerResult(
            action=PullRequestManagerAction.NO_CHANGES,
            branch=automation_branch,
            message="Validated patch contained no file edits.",
        )

    base_branch = default_branch if pr_config.base == "default" else pr_config.base
    _validate_repo_name(repo)
    if github_client is None:
        raise PRManagerError("github_client is required for pull request management.")
    existing_pr = github_client.find_open_pull_request(head_branch=automation_branch)
    if existing_pr is not None and not pr_config.update_existing:
        raise PRManagerError(
            f"Open automation PR #{existing_pr.number} already exists for {automation_branch}"
        )

    manager = branch_manager or BranchManager(repo_root=resolved_config.repo_root)
    manager.prepare_branch(base_branch=base_branch, automation_branch=automation_branch)

    committed = manager.commit_validated_patch(patch, commit_message=pr_config.title_template)
    if not committed:
        return PullRequestManagerResult(
            action=PullRequestManagerAction.NO_CHANGES,
            branch=automation_branch,
            message="Validated patch produced no git changes.",
        )

    manager.push_branch(automation_branch)

    body = render_pull_request_body(
        resolved_config=resolved_config,
        patch=patch,
        recent_prs=recent_prs,
        base_branch=base_branch,
        automation_branch=automation_branch,
    )

    if existing_pr is not None:
        pull_request = github_client.update_pull_request(
            number=existing_pr.number,
            title=pr_config.title_template,
            body=body,
        )
        _apply_metadata(
            github_client,
            pull_request=pull_request,
            labels=pr_config.labels,
            reviewers=pr_config.reviewers,
        )
        return PullRequestManagerResult(
            action=PullRequestManagerAction.UPDATED,
            branch=automation_branch,
            pull_request=pull_request,
            committed=True,
            pushed=True,
            message=f"Updated planning-validator PR #{pull_request.number}.",
        )

    pull_request = github_client.create_pull_request(
        title=pr_config.title_template,
        body=body,
        head_branch=automation_branch,
        base_branch=base_branch,
        draft=pr_config.draft,
    )
    _apply_metadata(
        github_client,
        pull_request=pull_request,
        labels=pr_config.labels,
        reviewers=pr_config.reviewers,
    )
    return PullRequestManagerResult(
        action=PullRequestManagerAction.CREATED,
        branch=automation_branch,
        pull_request=pull_request,
        committed=True,
        pushed=True,
        message=f"Created planning-validator PR #{pull_request.number}.",
    )


def _apply_metadata(
    github_client: PullRequestClient,
    *,
    pull_request: AutomationPullRequest,
    labels: list[str],
    reviewers: list[str],
) -> None:
    github_client.add_labels(number=pull_request.number, labels=labels)
    github_client.request_reviewers(number=pull_request.number, reviewers=reviewers)


def _validate_repo_name(repo: str) -> None:
    parts = repo.split("/", maxsplit=1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise PRManagerError(f"Repository name must be in owner/name form: {repo}")
