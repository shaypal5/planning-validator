from __future__ import annotations

import pytest
from pydantic import ValidationError

from planning_validator.models import (
    LookbackConfig,
    PatchingConfig,
    PatchingProvider,
    PullRequestBodyMode,
    PullRequestConfig,
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
    ],
)
def test_patching_config_rejects_invalid_values(
    payload: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValidationError, match=match):
        PatchingConfig.model_validate(payload)


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
                "planning_files": [""],
                "patching": {
                    "provider": "openai",
                    "model": "gpt-5.4-thinking",
                    "allowed_update_globs": ["README.md"],
                },
            }
        )
