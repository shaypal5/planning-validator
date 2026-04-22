"""Repository snapshot assembly for detector inputs."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from planning_validator.config import ResolvedConfig
from planning_validator.file_io import read_local_document_inventory
from planning_validator.github_api import GitHubEvidenceClient
from planning_validator.models import RecentIssue, RecentPullRequest, RepoSnapshot

_GIT_SSH_REMOTE_PATTERN = re.compile(r"^(?P<host>[^@]+@[^:]+):(?P<path>.+)$")


@dataclass(frozen=True)
class RepoMetadata:
    repo: str
    default_branch: str
    head_sha: str


def build_repo_snapshot(
    resolved_config: ResolvedConfig,
    *,
    repo: str,
    default_branch: str,
    head_sha: str,
    recent_prs: list[RecentPullRequest],
    recent_issues: list[RecentIssue] | None = None,
) -> RepoSnapshot:
    """Build a typed repository snapshot from local documents and recent GitHub evidence."""

    inventory = read_local_document_inventory(resolved_config)

    return RepoSnapshot(
        repo=repo,
        default_branch=default_branch,
        head_sha=head_sha,
        planning_files=inventory.planning_documents,
        tracking_files=inventory.tracking_documents,
        recent_prs=sorted(
            recent_prs,
            key=lambda pull_request: pull_request.merged_at,
            reverse=True,
        ),
        recent_issues=[] if recent_issues is None else list(recent_issues),
    )


def collect_recent_pr_snapshot(
    resolved_config: ResolvedConfig,
    *,
    github_client: GitHubEvidenceClient,
    repo: str,
    default_branch: str,
    head_sha: str,
    now: datetime | None = None,
    recent_issues: list[RecentIssue] | None = None,
) -> RepoSnapshot:
    """Build a repository snapshot after fetching recent merged PR evidence."""

    current_time = _resolve_current_time(now)
    merged_since = current_time - timedelta(hours=resolved_config.config.lookback.merged_pr_hours)
    recent_prs = github_client.fetch_recent_merged_pull_requests(
        merged_since=merged_since,
        include_file_lists=resolved_config.config.github.include_pr_file_lists,
        include_linked_issues=resolved_config.config.github.include_linked_issues,
    )
    return build_repo_snapshot(
        resolved_config,
        repo=repo,
        default_branch=default_branch,
        head_sha=head_sha,
        recent_prs=recent_prs,
        recent_issues=recent_issues,
    )


def collect_repo_metadata(
    repo_root: Path,
    *,
    repo: str | None = None,
    default_branch: str | None = None,
) -> RepoMetadata:
    """Collect repository metadata from the local git checkout without network access."""

    head_sha = _git_stdout(repo_root, "rev-parse", "HEAD")
    resolved_default_branch = default_branch or _resolve_default_branch(repo_root)
    resolved_repo = repo or _resolve_repo_name(repo_root)
    return RepoMetadata(
        repo=resolved_repo,
        default_branch=resolved_default_branch,
        head_sha=head_sha,
    )


def _resolve_current_time(now: datetime | None) -> datetime:
    current_time = datetime.now(UTC) if now is None else now
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("now must include timezone info")
    return current_time


def _resolve_default_branch(repo_root: Path) -> str:
    symbolic_ref = _try_git_stdout(repo_root, "symbolic-ref", "refs/remotes/origin/HEAD")
    if symbolic_ref:
        return symbolic_ref.rsplit("/", maxsplit=1)[-1]

    current_branch = _try_git_stdout(repo_root, "branch", "--show-current")
    if current_branch:
        return current_branch

    abbrev_ref = _try_git_stdout(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    if abbrev_ref and abbrev_ref != "HEAD":
        return abbrev_ref

    raise ValueError(
        "Could not resolve default branch from local git checkout. "
        "Tried refs/remotes/origin/HEAD, git branch --show-current, "
        "and git rev-parse --abbrev-ref HEAD. "
        "Pass default_branch explicitly if the repository is detached or "
        "does not have a configured origin/HEAD ref."
    )


def _resolve_repo_name(repo_root: Path) -> str:
    remote_url = _git_stdout(repo_root, "config", "--get", "remote.origin.url")
    ssh_match = _GIT_SSH_REMOTE_PATTERN.match(remote_url)
    if ssh_match:
        remote_path = ssh_match.group("path")
    else:
        parsed = urlparse(remote_url)
        remote_path = parsed.path.lstrip("/")

    if not remote_path:
        raise ValueError("Could not derive repository name from remote.origin.url")

    if remote_path.endswith(".git"):
        remote_path = remote_path[:-4]

    path_parts = [part for part in remote_path.split("/") if part]
    if len(path_parts) < 2:
        raise ValueError("Could not derive repository name from remote.origin.url")

    return "/".join(path_parts[-2:])


def _git_stdout(repo_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()
        message = stderr or f"git {' '.join(args)} failed"
        raise ValueError(message) from exc

    return completed.stdout.strip()


def _try_git_stdout(repo_root: Path, *args: str) -> str | None:
    try:
        return _git_stdout(repo_root, *args)
    except ValueError:
        return None
