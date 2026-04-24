from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from planning_validator.config import load_config
from planning_validator.models import (
    DetectionResult,
    FileEdit,
    PatchingConfig,
    PatchRequest,
    PatchResponse,
    PatchTargetFile,
    RecentPullRequest,
    RepoSnapshot,
    StaleSignal,
    ValidatedPatch,
)
from planning_validator.patcher.file_patch_validator import (
    PatchValidationError,
    _has_merged_pr_evidence,
    validate_patch_response,
)
from planning_validator.patcher.llm_client import LLMClientError, OpenAIResponsesClient
from planning_validator.patcher.patcher import (
    PatcherError,
    apply_validated_patch,
    run_patcher,
    validate_existing_response,
)
from planning_validator.patcher.prompt_builder import (
    PatchRequestError,
    build_patch_prompt,
    build_patch_request,
)
from planning_validator.patcher.response_parser import PatchResponseParseError, parse_patch_response


def _edit_payload(path: str, content: str) -> dict[str, object]:
    return {
        "path": path,
        "operation": "replace_file",
        "new_content": content,
        "rationale": "Reflects supplied evidence.",
        "evidence_refs": ["PR #42"],
    }


def test_parse_patch_response_accepts_valid_json() -> None:
    response = parse_patch_response(
        json.dumps(
            {
                "summary": "Updated docs.",
                "edits": [
                    {
                        "path": "docs/roadmap.md",
                        "operation": "replace_file",
                        "new_content": "# Roadmap\nDone.\n",
                        "rationale": "Reflects PR #42.",
                        "evidence_refs": ["PR #42"],
                    }
                ],
            }
        )
    )

    assert response.edits[0].path == "docs/roadmap.md"


def test_parse_patch_response_rejects_invalid_json() -> None:
    with pytest.raises(PatchResponseParseError, match="not valid JSON"):
        parse_patch_response("{not-json")


def test_parse_patch_response_rejects_schema_invalid_output() -> None:
    with pytest.raises(PatchResponseParseError, match="does not match patch schema"):
        parse_patch_response(json.dumps({"summary": "bad", "edits": [{"path": "docs/x.md"}]}))


def test_parse_patch_response_rejects_duplicate_paths() -> None:
    payload = {
        "summary": "Duplicate.",
        "edits": [
            _edit_payload("docs/roadmap.md", "# Roadmap\nDone.\n"),
            _edit_payload("docs/roadmap.md", "# Roadmap\nDone again.\n"),
        ],
    }

    with pytest.raises(PatchResponseParseError, match="duplicate edits"):
        parse_patch_response(json.dumps(payload))


def test_build_patch_request_includes_only_allowed_detector_targets(tmp_path: Path) -> None:
    resolved = _resolved_config(tmp_path)
    snapshot = _snapshot()
    detection = DetectionResult.model_validate(
        {
            "is_stale": True,
            "summary": "stale",
            "signals": [_signal().model_dump()],
            "target_files": [
                {
                    "path": "docs/roadmap.md",
                    "aggregate_score": 0.7,
                    "matched_signals": [_signal().model_dump()],
                    "allowed_to_patch": True,
                },
                {
                    "path": "docs/tasks.md",
                    "aggregate_score": 0.7,
                    "matched_signals": [],
                    "allowed_to_patch": False,
                },
            ],
            "ignored_prs": [],
        }
    )

    request = build_patch_request(resolved, snapshot, detection)
    prompt = build_patch_prompt(request)

    assert [target.path for target in request.target_files] == ["docs/roadmap.md"]
    assert "preserve_frontmatter" in prompt
    assert "Add patcher core" in prompt


def test_build_patch_request_rejects_oversized_inputs(tmp_path: Path) -> None:
    resolved = _resolved_config(tmp_path, extra_patching="  max_input_chars_per_file: 5\n")

    with pytest.raises(PatchRequestError, match="max_input_chars_per_file"):
        build_patch_request(resolved, _snapshot(), _detection_result())


def test_build_patch_request_returns_empty_targets_when_detection_not_stale(
    tmp_path: Path,
) -> None:
    detection = DetectionResult.model_validate(
        {
            "is_stale": False,
            "summary": "Fresh.",
            "signals": [],
            "target_files": [],
            "ignored_prs": [],
        }
    )

    request = build_patch_request(_resolved_config(tmp_path), _snapshot(), detection)

    assert request.target_files == []
    assert request.global_instructions


def test_build_patch_request_rejects_missing_snapshot_document(tmp_path: Path) -> None:
    snapshot = _snapshot().model_copy(update={"planning_files": [], "tracking_files": []})

    with pytest.raises(PatchRequestError, match="missing from repository snapshot"):
        build_patch_request(_resolved_config(tmp_path), snapshot, _detection_result())


def test_build_patch_prompt_omits_disabled_rendering_instructions(tmp_path: Path) -> None:
    resolved = _resolved_config(
        tmp_path,
        extra_config=(
            "rendering:\n"
            "  preserve_frontmatter: false\n"
            "  preserve_unrecognized_sections: false\n"
            "  prefer_checklists: false\n"
            "  add_pr_links: false\n"
            "  add_issue_links: false\n"
        ),
    )
    request = build_patch_request(resolved, _snapshot(), _detection_result())

    prompt = build_patch_prompt(request)

    assert "Preserve YAML frontmatter" not in prompt
    assert "Include PR links" not in prompt
    assert "Include issue links" not in prompt


def test_build_patch_request_rejects_total_input_limit(tmp_path: Path) -> None:
    resolved = _resolved_config(
        tmp_path,
        extra_patching=("  max_input_chars_per_file: 70\n  max_total_input_chars: 70\n"),
    )
    tracking_signal = _signal().model_copy(update={"target_file": "docs/tasks.md"})
    detection = DetectionResult.model_validate(
        {
            "is_stale": True,
            "summary": "Detected stale docs.",
            "signals": [_signal().model_dump(), tracking_signal.model_dump()],
            "target_files": [
                {
                    "path": "docs/roadmap.md",
                    "aggregate_score": 0.7,
                    "matched_signals": [_signal().model_dump()],
                    "allowed_to_patch": True,
                },
                {
                    "path": "docs/tasks.md",
                    "aggregate_score": 0.7,
                    "matched_signals": [tracking_signal.model_dump()],
                    "allowed_to_patch": True,
                },
            ],
            "ignored_prs": [],
        }
    )

    with pytest.raises(PatchRequestError, match="max_total_input_chars"):
        build_patch_request(resolved, _snapshot(), detection)


def test_openai_responses_client_uses_strict_structured_outputs(
    tmp_path: Path,
) -> None:
    captured_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payload.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "summary": "Updated docs.",
                                        "edits": [
                                            _edit_payload(
                                                "docs/roadmap.md",
                                                "# Roadmap\nDone in #42.\n",
                                            )
                                        ],
                                    }
                                ),
                            }
                        ]
                    }
                ]
            },
        )

    request = build_patch_request(_resolved_config(tmp_path), _snapshot(), _detection_result())
    config = PatchingConfig.model_validate(
        {
            "provider": "openai",
            "model": "gpt-5.4-thinking",
            "allowed_update_globs": ["docs/**/*.md"],
        }
    )

    with OpenAIResponsesClient(
        api_key="token",
        config=config,
        transport=httpx.MockTransport(handler),
    ) as client:
        response = client.generate_patch(request)

    assert response.summary == "Updated docs."
    text_format = captured_payload["text"]["format"]  # type: ignore[index]
    assert text_format["type"] == "json_schema"
    assert text_format["strict"] is True
    assert text_format["schema"]["properties"]["edits"]["items"]["properties"]["operation"][
        "enum"
    ] == ["replace_file"]


def test_openai_responses_client_surfaces_http_errors(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    request = build_patch_request(_resolved_config(tmp_path), _snapshot(), _detection_result())

    with OpenAIResponsesClient(
        api_key="token",
        config=_openai_config(),
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(LLMClientError, match="request failed"):
            client.generate_patch(request)


def test_openai_responses_client_rejects_invalid_provider_json(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    request = build_patch_request(_resolved_config(tmp_path), _snapshot(), _detection_result())

    with OpenAIResponsesClient(
        api_key="token",
        config=_openai_config(),
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(LLMClientError, match="invalid JSON"):
            client.generate_patch(request)


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"output_text": json.dumps({"summary": "ok", "edits": []})}, "ok"),
        ({}, "did not include output text"),
        ({"output": [{"type": "refusal", "refusal": "No."}]}, "refused"),
        ({"output": ["bad", {"content": "bad"}]}, "did not include output text"),
        (
            {
                "output": [
                    {
                        "content": [
                            "bad",
                            {"type": "text", "text": "not-json"},
                            {"type": "output_text", "text": ""},
                        ]
                    }
                ]
            },
            "not valid JSON",
        ),
    ],
)
def test_openai_responses_client_output_text_branches(
    tmp_path: Path,
    payload: dict[str, object],
    match: str,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    request = build_patch_request(_resolved_config(tmp_path), _snapshot(), _detection_result())

    with OpenAIResponsesClient(
        api_key="token",
        config=_openai_config(),
        transport=httpx.MockTransport(handler),
    ) as client:
        if match == "ok":
            assert client.generate_patch(request).summary == "ok"
        else:
            with pytest.raises((LLMClientError, PatchResponseParseError), match=match):
                client.generate_patch(request)


def test_validate_patch_response_accepts_valid_replacement(tmp_path: Path) -> None:
    request = build_patch_request(_resolved_config(tmp_path), _snapshot(), _detection_result())
    response = PatchResponse.model_validate(
        {
            "summary": "Updated roadmap.",
            "edits": [
                _edit_payload(
                    "docs/roadmap.md",
                    "---\ntitle: Roadmap\n---\n# Roadmap\nPatcher core completed in #42.\n",
                )
            ],
        }
    )

    patch = validate_patch_response(request, response)

    assert patch.edits[0].path == "docs/roadmap.md"


@pytest.mark.parametrize(
    ("response_payload", "code"),
    [
        (
            {
                "summary": "Bad path.",
                "edits": [_edit_payload("docs/secret.md", "# Secret\n")],
            },
            "unselected_path",
        ),
        (
            {
                "summary": "Non markdown.",
                "edits": [_edit_payload("src/app.py", "print('x')\n")],
            },
            "non_markdown_path",
        ),
        (
            {
                "summary": "Placeholder.",
                "edits": [_edit_payload("docs/roadmap.md", "TBD")],
            },
            "empty_or_placeholder_content",
        ),
        (
            {
                "summary": "Frontmatter changed.",
                "edits": [
                    _edit_payload(
                        "docs/roadmap.md",
                        "---\ntitle: Changed\n---\n# Roadmap\nPatcher core completed in #42.\n",
                    )
                ],
            },
            "frontmatter_changed",
        ),
        (
            {
                "summary": "Unsupported reference.",
                "edits": [
                    _edit_payload(
                        "docs/roadmap.md",
                        "---\ntitle: Roadmap\n---\n# Roadmap\nPatcher core completed in #999.\n",
                    )
                ],
            },
            "unsupported_reference",
        ),
    ],
)
def test_validate_patch_response_rejects_invalid_edits(
    tmp_path: Path,
    response_payload: dict[str, object],
    code: str,
) -> None:
    request = build_patch_request(_resolved_config(tmp_path), _snapshot(), _detection_result())

    with pytest.raises(PatchValidationError) as exc_info:
        validate_patch_response(request, PatchResponse.model_validate(response_payload))

    assert any(failure.code == code for failure in exc_info.value.failures)


def test_validate_patch_response_rejects_forbidden_path() -> None:
    request = _direct_request(path="docs/secret.md")
    response = PatchResponse.model_validate(
        {
            "summary": "Forbidden.",
            "edits": [_edit_payload("docs/secret.md", "# Secret\nUpdated by #42.\n")],
        }
    )

    with pytest.raises(PatchValidationError) as exc_info:
        validate_patch_response(request, response)

    assert any(failure.code == "forbidden_path" for failure in exc_info.value.failures)


def test_validate_patch_response_rejects_unsupported_completion() -> None:
    request = _direct_request(
        path="docs/roadmap.md",
        original_content="# Roadmap\n- [ ] Patcher core\n",
        recent_prs=[],
        signal_evidence={},
    )
    response = PatchResponse.model_validate(
        {
            "summary": "Unsupported completion.",
            "edits": [_edit_payload("docs/roadmap.md", "# Roadmap\n- [x] Patcher core\n")],
        }
    )

    with pytest.raises(PatchValidationError) as exc_info:
        validate_patch_response(request, response)

    assert any(failure.code == "unsupported_completion" for failure in exc_info.value.failures)


def test_validate_patch_response_enforces_max_files() -> None:
    request = _direct_request()
    response = PatchResponse.model_validate(
        {
            "summary": "Too many.",
            "edits": [
                _edit_payload("docs/roadmap.md", "# Roadmap\nDone in #42.\n"),
                _edit_payload("docs/tasks.md", "# Tasks\nDone in #42.\n"),
            ],
        }
    )

    with pytest.raises(PatchValidationError) as exc_info:
        validate_patch_response(request, response)

    assert any(failure.code == "too_many_edits" for failure in exc_info.value.failures)


def test_validate_patch_response_rejects_large_unrelated_removal() -> None:
    original = "\n".join(
        [
            "# Roadmap",
            "A" * 220,
            "## One",
            "content",
            "## Two",
            "content",
            "## Three",
            "content",
            "## Four",
            "content",
        ]
    )
    request = _direct_request(original_content=original)
    response = PatchResponse.model_validate(
        {
            "summary": "Collapsed.",
            "edits": [_edit_payload("docs/roadmap.md", "# Roadmap\nDone in #42.\n")],
        }
    )

    with pytest.raises(PatchValidationError) as exc_info:
        validate_patch_response(request, response)

    assert any(failure.code == "large_unrelated_removal" for failure in exc_info.value.failures)


def test_validate_patch_response_rejects_heading_inventory_removal() -> None:
    original = "\n".join(
        [
            "# Roadmap",
            "## One",
            "content",
            "## Two",
            "content",
            "## Three",
            "content",
            "## Four",
            "content",
        ]
    )
    request = _direct_request(original_content=original)
    response = PatchResponse.model_validate(
        {
            "summary": "Removed headings.",
            "edits": [_edit_payload("docs/roadmap.md", "# Roadmap\nDone in #42.\n")],
        }
    )

    with pytest.raises(PatchValidationError) as exc_info:
        validate_patch_response(request, response)

    assert any(failure.code == "large_unrelated_removal" for failure in exc_info.value.failures)


def test_has_merged_pr_evidence_returns_false_for_missing_target() -> None:
    request = _direct_request()

    assert _has_merged_pr_evidence(request, "docs/missing.md") is False


def test_validate_patch_response_allows_short_documents_without_section_check() -> None:
    request = _direct_request(
        original_content="# Roadmap\n## One\ncontent\n",
    )
    response = PatchResponse.model_validate(
        {
            "summary": "Small update.",
            "edits": [_edit_payload("docs/roadmap.md", "# Roadmap\nDone in #42.\n")],
        }
    )

    patch = validate_patch_response(request, response)

    assert patch.summary == "Small update."


def test_validate_patch_response_rejects_unclosed_frontmatter() -> None:
    request = _direct_request(original_content="---\ntitle: Roadmap\n# Roadmap\n")
    response = PatchResponse.model_validate(
        {
            "summary": "Changed.",
            "edits": [_edit_payload("docs/roadmap.md", "---\ntitle: Roadmap\n---\n# Roadmap\n")],
        }
    )

    with pytest.raises(PatchValidationError) as exc_info:
        validate_patch_response(request, response)

    assert any(failure.code == "frontmatter_changed" for failure in exc_info.value.failures)


def test_validate_patch_response_defaults_rendering_when_summary_is_missing() -> None:
    request = _direct_request(original_content="---\ntitle: Roadmap\n---\n# Roadmap\n")
    request = request.model_copy(
        update={"config_summary": {"patchable_paths": ["docs/roadmap.md"]}},
    )
    response = PatchResponse.model_validate(
        {
            "summary": "Changed.",
            "edits": [_edit_payload("docs/roadmap.md", "# Roadmap\n")],
        }
    )

    with pytest.raises(PatchValidationError) as exc_info:
        validate_patch_response(request, response)

    assert any(failure.code == "frontmatter_changed" for failure in exc_info.value.failures)


def test_validate_patch_response_defaults_lists_when_summary_values_are_wrong_type() -> None:
    request = _direct_request()
    request = request.model_copy(
        update={
            "config_summary": {
                "patchable_paths": "docs/roadmap.md",
                "forbidden_update_globs": "docs/*.md",
                "max_files_to_update": "1",
                "rendering": {"preserve_frontmatter": False},
            }
        },
    )
    response = PatchResponse.model_validate(
        {
            "summary": "Updated.",
            "edits": [_edit_payload("docs/roadmap.md", "# Roadmap\nDone in #42.\n")],
        }
    )

    patch = validate_patch_response(request, response)

    assert patch.edits[0].path == "docs/roadmap.md"


def test_validate_patch_response_rejects_completion_when_signal_pr_is_not_merged() -> None:
    request = _direct_request(signal_evidence={"pr_number": 99})
    response = PatchResponse.model_validate(
        {
            "summary": "Unsupported.",
            "edits": [_edit_payload("docs/roadmap.md", "# Roadmap\n- [x] Patcher core\n")],
        }
    )

    with pytest.raises(PatchValidationError) as exc_info:
        validate_patch_response(request, response)

    assert any(failure.code == "unsupported_completion" for failure in exc_info.value.failures)


def test_run_patcher_returns_noop_without_targets(tmp_path: Path) -> None:
    class FailClient:
        def generate_patch(self, _request: PatchRequest) -> PatchResponse:
            raise AssertionError("provider should not be called")

    detection = DetectionResult.model_validate(
        {
            "is_stale": False,
            "summary": "Fresh.",
            "signals": [],
            "target_files": [],
            "ignored_prs": [],
        }
    )

    patch = run_patcher(
        _resolved_config(tmp_path),
        _snapshot(),
        detection,
        llm_client=FailClient(),
    )

    assert patch.edits == []


def test_validate_existing_response_uses_same_validation_path(tmp_path: Path) -> None:
    response = PatchResponse.model_validate(
        {
            "summary": "Updated roadmap.",
            "edits": [
                _edit_payload(
                    "docs/roadmap.md",
                    "---\ntitle: Roadmap\n---\n# Roadmap\nPatcher core completed in #42.\n",
                )
            ],
        }
    )

    patch = validate_existing_response(
        _resolved_config(tmp_path),
        _snapshot(),
        _detection_result(),
        response,
    )

    assert patch.summary == "Updated roadmap."


def test_apply_validated_patch_rejects_paths_outside_repo(tmp_path: Path) -> None:
    patch = ValidatedPatch(
        repo="acme/widgets",
        head_sha="abc123",
        summary="Bad path.",
        edits=[
            FileEdit(
                path="../escape.md",
                operation="replace_file",
                new_content="bad",
                rationale="test",
                evidence_refs=[],
            )
        ],
    )

    with pytest.raises(PatcherError, match="escapes repository root"):
        apply_validated_patch(tmp_path, patch)


def test_apply_validated_patch_writes_valid_paths(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    patch = ValidatedPatch(
        repo="acme/widgets",
        head_sha="abc123",
        summary="Apply.",
        edits=[
            FileEdit(
                path="docs/roadmap.md",
                operation="replace_file",
                new_content="# Roadmap\nDone.\n",
                rationale="test",
                evidence_refs=[],
            )
        ],
    )

    apply_validated_patch(tmp_path, patch)

    assert (tmp_path / "docs/roadmap.md").read_text(encoding="utf-8") == "# Roadmap\nDone.\n"


def _resolved_config(
    tmp_path: Path,
    *,
    extra_patching: str = "",
    extra_config: str = "",
):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/roadmap.md").write_text("# Roadmap\n", encoding="utf-8")
    (tmp_path / "docs/tasks.md").write_text("# Tasks\n", encoding="utf-8")
    config_path = tmp_path / "planning-validator.yml"
    config_path.write_text(
        (
            "schema_version: v1alpha1\n"
            "planning_files:\n"
            "  - docs/roadmap.md\n"
            "tracking_files:\n"
            "  - docs/tasks.md\n"
            "patching:\n"
            "  provider: openai\n"
            "  model: gpt-5.4-thinking\n"
            f"{extra_patching}"
            "  allowed_update_globs:\n"
            "    - docs/**/*.md\n"
            "  forbidden_update_globs:\n"
            "    - docs/secret.md\n"
            f"{extra_config}"
        ),
        encoding="utf-8",
    )
    return load_config(config_path, repo_root=tmp_path)


def _snapshot() -> RepoSnapshot:
    return RepoSnapshot.model_validate(
        {
            "repo": "acme/widgets",
            "default_branch": "main",
            "head_sha": "abc123",
            "planning_files": [
                {
                    "path": "docs/roadmap.md",
                    "content": "---\ntitle: Roadmap\n---\n# Roadmap\n- [ ] Patcher core\n",
                    "sha": "1",
                }
            ],
            "tracking_files": [
                {"path": "docs/tasks.md", "content": "# Tasks\n- [ ] Patcher core\n", "sha": "2"}
            ],
            "recent_prs": [_recent_pr().model_dump(mode="json")],
            "recent_issues": [],
        }
    )


def _recent_pr() -> RecentPullRequest:
    return RecentPullRequest.model_validate(
        {
            "number": 42,
            "title": "Add patcher core",
            "merged_at": "2026-04-24T10:00:00Z",
            "changed_files": ["src/planning_validator/patcher/patcher.py"],
            "url": "https://github.com/acme/widgets/pull/42",
        }
    )


def _openai_config() -> PatchingConfig:
    return PatchingConfig.model_validate(
        {
            "provider": "openai",
            "model": "gpt-5.4-thinking",
            "allowed_update_globs": ["docs/**/*.md"],
        }
    )


def _signal(evidence: dict[str, object] | None = None) -> StaleSignal:
    return StaleSignal.model_validate(
        {
            "signal_type": "todo_not_marked_done",
            "target_file": "docs/roadmap.md",
            "score": 0.4,
            "reason": "Patcher core is still unchecked.",
            "evidence": {"pr_number": 42, **(evidence or {})},
        }
    )


def _detection_result() -> DetectionResult:
    return DetectionResult.model_validate(
        {
            "is_stale": True,
            "summary": "Detected stale docs.",
            "signals": [_signal().model_dump()],
            "target_files": [
                {
                    "path": "docs/roadmap.md",
                    "aggregate_score": 0.7,
                    "matched_signals": [_signal().model_dump()],
                    "allowed_to_patch": True,
                }
            ],
            "ignored_prs": [],
        }
    )


def _direct_request(
    *,
    path: str = "docs/roadmap.md",
    original_content: str = "# Roadmap\n- [ ] Patcher core\n",
    recent_prs: list[RecentPullRequest] | None = None,
    signal_evidence: dict[str, object] | None = None,
) -> PatchRequest:
    pull_requests = [_recent_pr()] if recent_prs is None else recent_prs
    return PatchRequest(
        repo="acme/widgets",
        head_sha="abc123",
        config_summary={
            "patchable_paths": ["docs/roadmap.md", "docs/tasks.md", "docs/secret.md"],
            "forbidden_update_globs": ["docs/secret.md"],
            "max_files_to_update": 1,
            "rendering": {"preserve_frontmatter": True, "preserve_unrecognized_sections": True},
        },
        recent_prs=pull_requests,
        recent_issues=[],
        target_files=[
            PatchTargetFile(
                path=path,
                original_content=original_content,
                matched_signals=[_signal(signal_evidence)],
            )
        ],
        global_instructions=[],
    )
