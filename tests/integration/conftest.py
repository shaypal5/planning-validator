from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from planning_validator.models import (
    AutomationPullRequest,
    PatchResponse,
    RepoSnapshot,
    ValidatedPatch,
)


@dataclass(frozen=True)
class MetadataStub:
    repo: str = "acme/widgets"
    default_branch: str = "main"
    head_sha: str = "abc123"


class FakeGitHubEvidenceClient:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def __enter__(self) -> FakeGitHubEvidenceClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class FakeOpenAIClient:
    response_content: str = (
        "# Roadmap\n\n"
        "## Current\n\n"
        "- Patcher core shipped in #42.\n\n"
        "## Next\n\n"
        "- [x] Add patcher core shipped in #42.\n"
        "- Review generated planning-validator PRs before merging documentation updates.\n"
    )

    def __init__(self, **_kwargs: object) -> None:
        pass

    def __enter__(self) -> FakeOpenAIClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def generate_patch(self, _request: object) -> PatchResponse:
        return PatchResponse.model_validate(
            {
                "summary": "Updated roadmap for merged PR #42.",
                "edits": [
                    {
                        "path": "docs/roadmap.md",
                        "operation": "replace_file",
                        "new_content": self.response_content,
                        "rationale": "Reflects merged PR #42.",
                        "evidence_refs": ["PR #42"],
                    }
                ],
            }
        )


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Any:
    def copy_fixture(name: str) -> Path:
        source = Path(__file__).resolve().parents[1] / "fixtures" / name
        destination = tmp_path / name
        shutil.copytree(source, destination)
        return destination

    return copy_fixture


def configure_offline_run(
    monkeypatch: pytest.MonkeyPatch,
    repo_root: Path,
    *,
    model_content: str | None = None,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-token")
    monkeypatch.setattr(
        "planning_validator.cli.collect_repo_metadata",
        lambda _root: MetadataStub(),
    )
    monkeypatch.setattr("planning_validator.cli.GitHubEvidenceClient", FakeGitHubEvidenceClient)
    monkeypatch.setattr("planning_validator.cli.OpenAIResponsesClient", FakeOpenAIClient)
    if model_content is not None:
        FakeOpenAIClient.response_content = model_content
    else:
        FakeOpenAIClient.response_content = (
            "# Roadmap\n\n"
            "## Current\n\n"
            "- Patcher core shipped in #42.\n\n"
            "## Next\n\n"
            "- [x] Add patcher core shipped in #42.\n"
            "- Review generated planning-validator PRs before merging documentation updates.\n"
        )
    monkeypatch.setattr(
        "planning_validator.cli.collect_recent_pr_snapshot",
        lambda *args, **kwargs: build_fixture_snapshot(repo_root),
    )


def build_fixture_snapshot(repo_root: Path) -> RepoSnapshot:
    return RepoSnapshot.model_validate(
        {
            "repo": "acme/widgets",
            "default_branch": "main",
            "head_sha": "abc123",
            "planning_files": [
                {
                    "path": "docs/roadmap.md",
                    "content": (repo_root / "docs/roadmap.md").read_text(encoding="utf-8"),
                    "sha": "roadmap-sha",
                }
            ],
            "tracking_files": [
                {
                    "path": "docs/tasks.md",
                    "content": (repo_root / "docs/tasks.md").read_text(encoding="utf-8"),
                    "sha": "tasks-sha",
                }
            ],
            "recent_prs": [
                {
                    "number": 42,
                    "title": "Add patcher core",
                    "merged_at": "2026-04-24T10:00:00Z",
                    "changed_files": ["src/planning_validator/patcher/patcher.py"],
                    "url": "https://github.com/acme/widgets/pull/42",
                }
            ],
            "recent_issues": [],
        }
    )


def automation_pr(number: int = 77) -> AutomationPullRequest:
    return AutomationPullRequest(
        number=number,
        title="docs: refresh planning/tracking files",
        url=f"https://github.com/acme/widgets/pull/{number}",
        head_branch="automation/planning-validator",
        base_branch="main",
        draft=True,
    )


def assert_patch_targets_roadmap(patch: object) -> None:
    assert isinstance(patch, ValidatedPatch)
    assert [edit.path for edit in patch.edits] == ["docs/roadmap.md"]
