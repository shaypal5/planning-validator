"""Pull request body rendering for planning-validator automation PRs."""

from __future__ import annotations

from pathlib import Path

from planning_validator.config import ResolvedConfig
from planning_validator.models import PullRequestBodyMode, RecentPullRequest, ValidatedPatch


def render_pull_request_body(
    *,
    resolved_config: ResolvedConfig,
    patch: ValidatedPatch,
    recent_prs: list[RecentPullRequest],
    base_branch: str,
    automation_branch: str,
) -> str:
    if resolved_config.config.pull_request.body_mode is PullRequestBodyMode.SHORT:
        return _render_short_body(
            resolved_config=resolved_config,
            patch=patch,
            base_branch=base_branch,
            automation_branch=automation_branch,
        )
    return _render_structured_body(
        resolved_config=resolved_config,
        patch=patch,
        recent_prs=recent_prs,
        base_branch=base_branch,
        automation_branch=automation_branch,
    )


def _render_structured_body(
    *,
    resolved_config: ResolvedConfig,
    patch: ValidatedPatch,
    recent_prs: list[RecentPullRequest],
    base_branch: str,
    automation_branch: str,
) -> str:
    evidence = _render_evidence(recent_prs)
    files = _render_files(patch)
    metadata = _render_metadata(
        resolved_config=resolved_config,
        patch=patch,
        base_branch=base_branch,
        automation_branch=automation_branch,
    )
    return (
        "## Why this PR exists\n\n"
        "Planning/tracking documents appear stale relative to recent merged pull requests.\n\n"
        "## Evidence considered\n\n"
        f"{evidence}\n\n"
        "## Files updated\n\n"
        f"{files}\n\n"
        "## Validator run metadata\n\n"
        f"{metadata}\n\n"
        "## Notes\n\n"
        "This PR was generated automatically and should be reviewed like any other docs PR.\n"
    )


def _render_short_body(
    *,
    resolved_config: ResolvedConfig,
    patch: ValidatedPatch,
    base_branch: str,
    automation_branch: str,
) -> str:
    return (
        "Planning/tracking documents were refreshed from recent repository evidence.\n\n"
        "## Files updated\n\n"
        f"{_render_files(patch)}\n\n"
        "## Validator run metadata\n\n"
        f"{
            _render_metadata(
                resolved_config=resolved_config,
                patch=patch,
                base_branch=base_branch,
                automation_branch=automation_branch,
            )
        }\n"
    )


def _render_evidence(recent_prs: list[RecentPullRequest]) -> str:
    if not recent_prs:
        return "- No recent merged pull requests were included in the patch artifact."
    return "\n".join(
        f"- PR #{pull_request.number} - {pull_request.title}" for pull_request in recent_prs
    )


def _render_files(patch: ValidatedPatch) -> str:
    if not patch.edits:
        return "- No files updated."
    return "\n".join(f"- {edit.path}" for edit in patch.edits)


def _render_metadata(
    *,
    resolved_config: ResolvedConfig,
    patch: ValidatedPatch,
    base_branch: str,
    automation_branch: str,
) -> str:
    config_path = _repo_relative_path(resolved_config.config_path, resolved_config.repo_root)
    return "\n".join(
        [
            f"- Head SHA: {patch.head_sha}",
            f"- Config path: {config_path}",
            f"- Lookback window: {resolved_config.config.lookback.merged_pr_hours}h",
            f"- Base branch: {base_branch}",
            f"- Automation branch: {automation_branch}",
        ]
    )


def _repo_relative_path(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()
