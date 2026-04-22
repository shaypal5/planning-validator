from __future__ import annotations

import textwrap
from datetime import UTC, datetime
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from planning_validator.config import load_config
from planning_validator.models import RecentIssue, RecentPullRequest
from planning_validator.repo_snapshot import (
    RepoMetadata,
    build_repo_snapshot,
    collect_recent_pr_snapshot,
    collect_repo_metadata,
)


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def create_repo_with_config(tmp_path: Path) -> Path:
    write_file(tmp_path / "README.md", "# Example repo\n")
    write_file(tmp_path / "docs/roadmap.md", "# Roadmap\n")
    write_file(tmp_path / "docs/tasks.md", "# Tasks\n")
    write_file(
        tmp_path / ".github/planning-validator.yml",
        """
        schema_version: v1alpha1
        planning_files:
          - README.md
          - docs/roadmap.md
        tracking_files:
          - docs/tasks.md
        patching:
          provider: openai
          model: gpt-5.4-thinking
          allowed_update_globs:
            - README.md
            - docs/**/*.md
        """,
    )
    return tmp_path / ".github/planning-validator.yml"


class RecordingGitHubClient:
    def __init__(self, pull_requests: list[RecentPullRequest]) -> None:
        self.pull_requests = pull_requests
        self.calls: list[dict[str, object]] = []

    def fetch_recent_merged_pull_requests(
        self,
        *,
        merged_since: datetime,
        include_file_lists: bool = False,
        include_linked_issues: bool = False,
    ) -> list[RecentPullRequest]:
        self.calls.append(
            {
                "merged_since": merged_since,
                "include_file_lists": include_file_lists,
                "include_linked_issues": include_linked_issues,
            }
        )
        return list(self.pull_requests)


def test_build_repo_snapshot_loads_documents_and_preserves_issue_inputs(tmp_path: Path) -> None:
    config_path = create_repo_with_config(tmp_path)
    write_file(tmp_path / "docs/shared.md", "# Shared\n")
    write_file(
        tmp_path / ".github/planning-validator.yml",
        """
        schema_version: v1alpha1
        planning_files:
          - README.md
          - docs/shared.md
        tracking_files:
          - docs/shared.md
          - docs/tasks.md
        patching:
          provider: openai
          model: gpt-5.4-thinking
          allowed_update_globs:
            - README.md
            - docs/**/*.md
        """,
    )

    resolved = load_config(config_path, repo_root=tmp_path)
    recent_pr = RecentPullRequest.model_validate(
        {
            "number": 42,
            "title": "Add snapshot builder",
            "merged_at": "2026-04-20T08:30:00Z",
            "url": "https://github.com/acme/widgets/pull/42",
        }
    )
    recent_issue = RecentIssue.model_validate(
        {
            "number": 17,
            "title": "Ship detector",
            "state": "closed",
            "closed_at": "2026-04-20T10:15:00Z",
            "url": "https://github.com/acme/widgets/issues/17",
        }
    )

    snapshot = build_repo_snapshot(
        resolved,
        repo="acme/widgets",
        default_branch="main",
        head_sha="abc123",
        recent_prs=[recent_pr],
        recent_issues=[recent_issue],
    )

    assert [document.path for document in snapshot.planning_files] == [
        "README.md",
        "docs/shared.md",
    ]
    assert [document.path for document in snapshot.tracking_files] == [
        "docs/shared.md",
        "docs/tasks.md",
    ]
    assert snapshot.planning_files[1] is snapshot.tracking_files[0]
    assert [pull_request.number for pull_request in snapshot.recent_prs] == [42]
    assert snapshot.recent_issues == [recent_issue]


def test_build_repo_snapshot_defaults_recent_issues_and_sorts_prs(tmp_path: Path) -> None:
    config_path = create_repo_with_config(tmp_path)
    resolved = load_config(config_path, repo_root=tmp_path)
    newer_pr = RecentPullRequest.model_validate(
        {
            "number": 20,
            "title": "Newer change",
            "merged_at": "2026-04-20T09:00:00Z",
            "url": "https://github.com/acme/widgets/pull/20",
        }
    )
    older_pr = RecentPullRequest.model_validate(
        {
            "number": 10,
            "title": "Older change",
            "merged_at": "2026-04-19T09:00:00Z",
            "url": "https://github.com/acme/widgets/pull/10",
        }
    )

    first_snapshot = build_repo_snapshot(
        resolved,
        repo="acme/widgets",
        default_branch="main",
        head_sha="abc123",
        recent_prs=[older_pr, newer_pr],
    )
    second_snapshot = build_repo_snapshot(
        resolved,
        repo="acme/widgets",
        default_branch="main",
        head_sha="abc123",
        recent_prs=[older_pr, newer_pr],
    )

    assert [pull_request.number for pull_request in first_snapshot.recent_prs] == [20, 10]
    assert first_snapshot.recent_issues == []
    assert first_snapshot.model_dump() == second_snapshot.model_dump()


def test_build_repo_snapshot_supports_missing_tracking_files(tmp_path: Path) -> None:
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
            - README.md
        """,
    )
    resolved = load_config(tmp_path / ".github/planning-validator.yml", repo_root=tmp_path)

    snapshot = build_repo_snapshot(
        resolved,
        repo="acme/widgets",
        default_branch="main",
        head_sha="abc123",
        recent_prs=[],
    )

    assert [document.path for document in snapshot.planning_files] == ["README.md"]
    assert snapshot.tracking_files == []
    assert snapshot.recent_prs == []


def test_collect_recent_pr_snapshot_uses_configured_lookback_and_client_flags(
    tmp_path: Path,
) -> None:
    config_path = create_repo_with_config(tmp_path)
    write_file(
        tmp_path / ".github/planning-validator.yml",
        """
        schema_version: v1alpha1
        planning_files:
          - README.md
        lookback:
          merged_pr_hours: 12
        patching:
          provider: openai
          model: gpt-5.4-thinking
          allowed_update_globs:
            - README.md
        github:
          include_pr_file_lists: false
          include_linked_issues: true
        """,
    )
    resolved = load_config(config_path, repo_root=tmp_path)
    client = RecordingGitHubClient(
        [
            RecentPullRequest.model_validate(
                {
                    "number": 12,
                    "title": "Recent merged change",
                    "merged_at": "2026-04-20T09:00:00Z",
                    "url": "https://github.com/acme/widgets/pull/12",
                }
            )
        ]
    )
    now = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)

    snapshot = collect_recent_pr_snapshot(
        resolved,
        github_client=client,
        repo="acme/widgets",
        default_branch="main",
        head_sha="abc123",
        now=now,
    )

    assert len(client.calls) == 1
    assert client.calls[0] == {
        "merged_since": datetime(2026, 4, 21, 0, 0, tzinfo=UTC),
        "include_file_lists": False,
        "include_linked_issues": True,
    }
    assert [pull_request.number for pull_request in snapshot.recent_prs] == [12]


def test_collect_recent_pr_snapshot_rejects_naive_now(tmp_path: Path) -> None:
    config_path = create_repo_with_config(tmp_path)
    resolved = load_config(config_path, repo_root=tmp_path)
    client = RecordingGitHubClient([])

    with pytest.raises(ValueError, match="timezone info"):
        collect_recent_pr_snapshot(
            resolved,
            github_client=client,
            repo="acme/widgets",
            default_branch="main",
            head_sha="abc123",
            now=datetime(2026, 4, 21, 12, 0),
        )


def test_collect_repo_metadata_reads_local_git_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    outputs = {
        ("rev-parse", "HEAD"): "abc123\n",
        ("symbolic-ref", "refs/remotes/origin/HEAD"): "refs/remotes/origin/main\n",
        ("config", "--get", "remote.origin.url"): "git@github.com:acme/widgets.git\n",
    }

    def fake_run(
        args: list[str],
        *,
        cwd: Path,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> CompletedProcess[str]:
        assert cwd == tmp_path
        assert check is True
        assert capture_output is True
        assert text is True
        key = tuple(args[1:])
        return CompletedProcess(args=args, returncode=0, stdout=outputs[key], stderr="")

    monkeypatch.setattr("planning_validator.repo_snapshot.subprocess.run", fake_run)

    metadata = collect_repo_metadata(tmp_path)

    assert metadata == RepoMetadata(
        repo="acme/widgets",
        default_branch="main",
        head_sha="abc123",
    )
