from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from planning_validator.models import (
    GitHubIssueState,
    LookbackConfig,
    PatchingConfig,
    PatchingProvider,
    PullRequestBodyMode,
    PullRequestConfig,
    RecentIssue,
    RecentPullRequest,
    RenderingConfig,
    StalenessConfig,
    ValidatorConfig,
)


def test_validator_config_defaults_are_applied() -> None:
    config = ValidatorConfig.model_validate(
        {
            "schema_version": "v1alpha1",
            "planning_files": ["README.md"],
            "patching": {
                "provider": "openai",
                "model": "gpt-5.4-thinking",
                "allowed_update_globs": ["README.md"],
            },
        }
    )

    assert config.lookback == LookbackConfig()
    assert config.staleness == StalenessConfig()
    assert config.pull_request == PullRequestConfig()
    assert config.rendering == RenderingConfig()
    assert config.patching.provider is PatchingProvider.OPENAI
    assert config.pull_request.body_mode is PullRequestBodyMode.STRUCTURED


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"merged_pr_hours": 0}, "positive integer"),
        ({"commit_hours": -1}, "positive integer"),
    ],
)
def test_lookback_config_rejects_invalid_values(payload: dict[str, int], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        LookbackConfig.model_validate(payload)


def test_lookback_config_accepts_positive_values() -> None:
    config = LookbackConfig.model_validate({"merged_pr_hours": 1, "commit_hours": 2})

    assert config.merged_pr_hours == 1
    assert config.commit_hours == 2


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"min_signal_score": -0.1}, "between 0 and 1"),
        ({"min_signal_score": 1.1}, "between 0 and 1"),
        ({"max_files_to_update": 0}, "greater than or equal to 1"),
    ],
)
def test_staleness_config_rejects_invalid_values(
    payload: dict[str, float | int], match: str
) -> None:
    with pytest.raises(ValidationError, match=match):
        StalenessConfig.model_validate(payload)


def test_staleness_config_accepts_boundary_values() -> None:
    config = StalenessConfig.model_validate({"min_signal_score": 0, "max_files_to_update": 1})

    assert config.min_signal_score == 0
    assert config.max_files_to_update == 1


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        (
            {
                "provider": "openai",
                "model": "gpt-5.4-thinking",
                "allowed_update_globs": ["README.md"],
                "temperature": 2.5,
            },
            "between 0 and 2",
        ),
        (
            {
                "provider": "openai",
                "model": "gpt-5.4-thinking",
                "allowed_update_globs": ["README.md"],
                "max_input_chars_per_file": 0,
            },
            "positive integer",
        ),
        (
            {
                "provider": "openai",
                "model": "gpt-5.4-thinking",
                "allowed_update_globs": ["README.md"],
                "max_input_chars_per_file": 100,
                "max_total_input_chars": 50,
            },
            "greater than or equal to max_input_chars_per_file",
        ),
        (
            {
                "provider": "openai",
                "model": "gpt-5.4-thinking",
                "allowed_update_globs": [""],
            },
            "non-empty strings",
        ),
        (
            {
                "provider": "openai",
                "model": "gpt-5.4-thinking",
                "allowed_update_globs": [123],
            },
            "non-empty strings",
        ),
    ],
)
def test_patching_config_rejects_invalid_values(
    payload: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValidationError, match=match):
        PatchingConfig.model_validate(payload)


def test_patching_config_accepts_boundary_temperature() -> None:
    config = PatchingConfig.model_validate(
        {
            "provider": "openai",
            "model": "gpt-5.4-thinking",
            "allowed_update_globs": ["README.md"],
            "temperature": 2,
        }
    )

    assert config.temperature == 2


def test_validator_config_rejects_invalid_schema_and_globs() -> None:
    with pytest.raises(ValidationError, match="schema_version must be 'v1alpha1'"):
        ValidatorConfig.model_validate(
            {
                "schema_version": "v2",
                "planning_files": ["README.md"],
                "patching": {
                    "provider": "openai",
                    "model": "gpt-5.4-thinking",
                    "allowed_update_globs": ["README.md"],
                },
            }
        )

    with pytest.raises(ValidationError, match="non-empty strings"):
        ValidatorConfig.model_validate(
            {
                "schema_version": "v1alpha1",
                "planning_files": [123],
                "patching": {
                    "provider": "openai",
                    "model": "gpt-5.4-thinking",
                    "allowed_update_globs": ["README.md"],
                },
            }
        )


def test_recent_issue_accepts_timezone_aware_closed_at() -> None:
    issue = RecentIssue.model_validate(
        {
            "number": 17,
            "title": "Ship the parser",
            "state": "closed",
            "closed_at": "2026-04-20T10:15:00Z",
            "url": "https://github.com/example/repo/issues/17",
        }
    )

    assert issue.state is GitHubIssueState.CLOSED
    assert issue.closed_at == datetime.fromisoformat("2026-04-20T10:15:00+00:00")


def test_recent_issue_rejects_naive_closed_at() -> None:
    with pytest.raises(ValidationError, match="timezone info"):
        RecentIssue.model_validate(
            {
                "number": 17,
                "title": "Ship the parser",
                "state": "closed",
                "closed_at": datetime(2026, 4, 20, 10, 15, 0),
                "url": "https://github.com/example/repo/issues/17",
            }
        )


def test_recent_pull_request_accepts_timezone_aware_merged_at() -> None:
    pull_request = RecentPullRequest.model_validate(
        {
            "number": 42,
            "title": "Add snapshot builder",
            "merged_at": "2026-04-20T08:30:00Z",
            "labels": ["docs"],
            "url": "https://github.com/example/repo/pull/42",
        }
    )

    assert pull_request.merged_at == datetime.fromisoformat("2026-04-20T08:30:00+00:00")
    assert pull_request.labels == ["docs"]


def test_recent_pull_request_rejects_naive_merged_at() -> None:
    with pytest.raises(ValidationError, match="timezone info"):
        RecentPullRequest.model_validate(
            {
                "number": 42,
                "title": "Add snapshot builder",
                "merged_at": datetime(2026, 4, 20, 8, 30, 0),
                "url": "https://github.com/example/repo/pull/42",
            }
        )
