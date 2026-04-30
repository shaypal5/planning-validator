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
    RecentPullRequest,
    ValidatedPatch,
)


@dataclass(frozen=True)
class MetadataStub:
    repo: str = "acme/widgets"
    default_branch: str = "main"
    head_sha: str = "abc123"


class FakeGitHubEvidenceClient:
    def __init__(self, **_kwargs: object) -> None:
        self.calls: list[dict[str, object]] = []

    def __enter__(self) -> FakeGitHubEvidenceClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def fetch_recent_merged_pull_requests(
        self,
        *,
        merged_since: object,
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
        return [
            RecentPullRequest.model_validate(
                {
                    "number": 42,
                    "title": "Add patcher core",
                    "merged_at": "2026-04-24T10:00:00Z",
                    "changed_files": ["src/planning_validator/patcher/patcher.py"],
                    "url": "https://github.com/acme/widgets/pull/42",
                }
            )
        ]


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
