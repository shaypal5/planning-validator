from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import planning_validator.cli as cli_module
from planning_validator.cli import app
from planning_validator.models import (
    AutomationPullRequest,
    DetectionResult,
    FileEdit,
    PatchResponse,
    PullRequestManagerAction,
    PullRequestManagerResult,
    RepoSnapshot,
    ValidatedPatch,
)
from planning_validator.patcher.llm_client import LLMClientError

runner = CliRunner()


class MetadataStub:
    repo = "acme/widgets"
    default_branch = "main"
    head_sha = "abc123"


def test_detect_writes_detection_result_and_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / ".github/planning-validator.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
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
        ),
        encoding="utf-8",
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/roadmap.md").write_text("# Roadmap\n", encoding="utf-8")

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(
        "planning_validator.cli.collect_repo_metadata",
        lambda _repo_root: MetadataStub(),
    )
    monkeypatch.setattr("planning_validator.cli.GitHubEvidenceClient", FakeClient)
    monkeypatch.setattr(
        "planning_validator.cli.collect_recent_pr_snapshot",
        lambda *args, **kwargs: RepoSnapshot.model_validate(
            {
                "repo": "acme/widgets",
                "default_branch": "main",
                "head_sha": "abc123",
                "planning_files": [
                    {"path": "docs/roadmap.md", "content": "# Roadmap\n", "sha": "1"}
                ],
                "tracking_files": [],
                "recent_prs": [],
                "recent_issues": [],
            }
        ),
    )
    monkeypatch.setattr(
        "planning_validator.cli.run_detector",
        lambda resolved, snapshot: DetectionResult.model_validate(
            {
                "is_stale": False,
                "summary": "No stale documentation signals detected.",
                "signals": [],
                "target_files": [],
                "ignored_prs": [],
            }
        ),
    )

    json_out = tmp_path / "artifacts/detection.json"
    result = runner.invoke(
        app,
        [
            "detect",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--json-out",
            str(json_out),
        ],
    )

    assert result.exit_code == 0
    assert "No stale documentation signals detected." in result.stdout
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["is_stale"] is False


def test_detect_surfaces_failures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / ".github/planning-validator.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("schema_version: bad\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "detect",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--json-out",
            str(tmp_path / "detection.json"),
        ],
    )

    assert result.exit_code == 1
    assert "Detection failed:" in result.stderr


def test_detect_requires_github_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / ".github/planning-validator.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
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
        ),
        encoding="utf-8",
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/roadmap.md").write_text("# Roadmap\n", encoding="utf-8")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(
        "planning_validator.cli.collect_repo_metadata",
        lambda _repo_root: MetadataStub(),
    )

    result = runner.invoke(
        app,
        [
            "detect",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--json-out",
            str(tmp_path / "detection.json"),
        ],
    )

    assert result.exit_code == 1
    assert "GITHUB_TOKEN environment variable is required" in result.stderr


def test_patch_dry_run_writes_artifact_without_editing_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = _write_patch_config(tmp_path)
    detection_json = tmp_path / "detection.json"
    detection_json.write_text(json.dumps(_stale_detection_payload()), encoding="utf-8")
    roadmap_path = tmp_path / "docs/roadmap.md"
    original_content = roadmap_path.read_text(encoding="utf-8")
    _patch_cli_dependencies(monkeypatch)

    json_out = tmp_path / "artifacts/patch.json"
    result = runner.invoke(
        app,
        [
            "patch",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--detection-json",
            str(detection_json),
            "--json-out",
            str(json_out),
        ],
    )

    assert result.exit_code == 0
    assert "Validated 1 file replacement" in result.stdout
    assert roadmap_path.read_text(encoding="utf-8") == original_content
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["edits"][0]["path"] == "docs/roadmap.md"


def test_patch_apply_writes_validated_file_replacements(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = _write_patch_config(tmp_path)
    detection_json = tmp_path / "detection.json"
    detection_json.write_text(json.dumps(_stale_detection_payload()), encoding="utf-8")
    _patch_cli_dependencies(monkeypatch)

    result = runner.invoke(
        app,
        [
            "patch",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--detection-json",
            str(detection_json),
            "--json-out",
            str(tmp_path / "patch.json"),
            "--apply",
        ],
    )

    assert result.exit_code == 0
    assert "Applied 1 validated file replacement" in result.stdout
    assert "Patcher core completed in #42" in (tmp_path / "docs/roadmap.md").read_text(
        encoding="utf-8"
    )


def test_patch_no_stale_skips_provider_and_github_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = _write_patch_config(tmp_path)
    detection_json = tmp_path / "detection.json"
    detection_json.write_text(
        json.dumps(
            {
                "is_stale": False,
                "summary": "No stale documentation signals detected.",
                "signals": [],
                "target_files": [],
                "ignored_prs": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "planning_validator.cli.collect_repo_metadata",
        lambda _repo_root: MetadataStub(),
    )

    json_out = tmp_path / "patch.json"
    result = runner.invoke(
        app,
        [
            "patch",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--detection-json",
            str(detection_json),
            "--json-out",
            str(json_out),
        ],
    )

    assert result.exit_code == 0
    assert "No patchable stale documentation targets" in result.stdout
    assert json.loads(json_out.read_text(encoding="utf-8"))["edits"] == []


def test_patch_requires_github_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = _write_patch_config(tmp_path)
    detection_json = tmp_path / "detection.json"
    detection_json.write_text(json.dumps(_stale_detection_payload()), encoding="utf-8")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-token")
    monkeypatch.setattr(
        "planning_validator.cli.collect_repo_metadata",
        lambda _repo_root: MetadataStub(),
    )

    result = runner.invoke(
        app,
        [
            "patch",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--detection-json",
            str(detection_json),
            "--json-out",
            str(tmp_path / "patch.json"),
        ],
    )

    assert result.exit_code == 1
    assert "GITHUB_TOKEN environment variable is required for patch" in result.stderr


def test_patch_requires_openai_api_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = _write_patch_config(tmp_path)
    detection_json = tmp_path / "detection.json"
    detection_json.write_text(json.dumps(_stale_detection_payload()), encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "planning_validator.cli.collect_repo_metadata",
        lambda _repo_root: MetadataStub(),
    )

    result = runner.invoke(
        app,
        [
            "patch",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--detection-json",
            str(detection_json),
            "--json-out",
            str(tmp_path / "patch.json"),
        ],
    )

    assert result.exit_code == 1
    assert "OPENAI_API_KEY environment variable is required for patch" in result.stderr


def test_patch_rejects_unsupported_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = _write_patch_config(tmp_path, provider="anthropic", model="claude-sonnet-4-5")
    detection_json = tmp_path / "detection.json"
    detection_json.write_text(json.dumps(_stale_detection_payload()), encoding="utf-8")
    monkeypatch.setattr(
        "planning_validator.cli.collect_repo_metadata",
        lambda _repo_root: MetadataStub(),
    )

    result = runner.invoke(
        app,
        [
            "patch",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--detection-json",
            str(detection_json),
            "--json-out",
            str(tmp_path / "patch.json"),
        ],
    )

    assert result.exit_code == 1
    assert "Unsupported patching provider" in result.stderr


def test_patch_surfaces_validation_failure_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = _write_patch_config(tmp_path)
    detection_json = tmp_path / "detection.json"
    detection_json.write_text(json.dumps(_stale_detection_payload()), encoding="utf-8")
    _patch_cli_dependencies(monkeypatch, replacement_content="TBD")

    result = runner.invoke(
        app,
        [
            "patch",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--detection-json",
            str(detection_json),
            "--json-out",
            str(tmp_path / "patch.json"),
        ],
    )

    assert result.exit_code == 1
    assert "Patching failed: empty_or_placeholder_content" in result.stderr


def test_run_clean_noop_skips_patch_and_pr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = _write_patch_config(tmp_path)
    _run_cli_common_dependencies(monkeypatch)
    monkeypatch.setattr(
        "planning_validator.cli.run_detector",
        lambda _resolved, _snapshot: DetectionResult.model_validate(
            {
                "is_stale": False,
                "summary": "No stale documentation signals detected.",
                "signals": [],
                "target_files": [],
                "ignored_prs": [],
            }
        ),
    )

    def fail_patcher(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("patcher must not run for a clean detection result")

    def fail_pr_manager(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("PR manager must not run for a clean detection result")

    monkeypatch.setattr("planning_validator.cli.run_patcher", fail_patcher)
    monkeypatch.setattr("planning_validator.cli.manage_patch_pull_request", fail_pr_manager)

    summary_json = tmp_path / "summary.json"
    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--summary-json",
            str(summary_json),
        ],
    )

    assert result.exit_code == 0
    assert "Status: clean" in result.stdout
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["status"] == "clean"
    assert payload["patch_status"] == "skipped"


def test_run_default_summary_path_creates_parent_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = _write_patch_config(tmp_path)
    _run_cli_common_dependencies(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "planning_validator.cli.run_detector",
        lambda _resolved, _snapshot: DetectionResult.model_validate(
            {
                "is_stale": False,
                "summary": "No stale documentation signals detected.",
                "signals": [],
                "target_files": [],
                "ignored_prs": [],
            }
        ),
    )

    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
        ],
        catch_exceptions=False,
    )

    summary_json = tmp_path / ".planning-validator/run-summary.json"
    assert result.exit_code == 0
    assert summary_json.is_file()
    assert json.loads(summary_json.read_text(encoding="utf-8"))["status"] == "clean"


def test_run_stale_creates_or_updates_one_pr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = _write_patch_config(tmp_path)
    calls: dict[str, int] = {"pr_manager": 0}
    _run_cli_common_dependencies(monkeypatch)
    _run_cli_stale_detection(monkeypatch)

    def fake_manage_patch_pull_request(**kwargs: object) -> PullRequestManagerResult:
        calls["pr_manager"] += 1
        assert kwargs["repo"] == "acme/widgets"
        patch = kwargs["patch"]
        assert [edit.path for edit in patch.edits] == ["docs/roadmap.md"]
        return PullRequestManagerResult(
            action=PullRequestManagerAction.UPDATED,
            branch="automation/planning-validator",
            pull_request=AutomationPullRequest(
                number=77,
                title="docs: refresh planning/tracking files",
                url="https://github.com/acme/widgets/pull/77",
                head_branch="automation/planning-validator",
                base_branch="main",
                draft=True,
            ),
            committed=True,
            pushed=True,
            message="Updated planning-validator PR #77.",
        )

    monkeypatch.setattr(
        "planning_validator.cli.manage_patch_pull_request",
        fake_manage_patch_pull_request,
    )

    summary_json = tmp_path / "summary.json"
    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--summary-json",
            str(summary_json),
        ],
    )

    assert result.exit_code == 0
    assert calls["pr_manager"] == 1
    assert "PR action: updated" in result.stdout
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["status"] == "pr_updated"
    assert payload["pr_url"] == "https://github.com/acme/widgets/pull/77"
    assert payload["edited_files"] == ["docs/roadmap.md"]


def test_run_invalid_patch_output_fails_before_pr_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = _write_patch_config(tmp_path)
    _run_cli_common_dependencies(monkeypatch, replacement_content="TBD")
    _run_cli_stale_detection(monkeypatch)

    def fail_pr_manager(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("PR manager must not run after invalid patch output")

    monkeypatch.setattr("planning_validator.cli.manage_patch_pull_request", fail_pr_manager)

    summary_json = tmp_path / "summary.json"
    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--summary-json",
            str(summary_json),
        ],
    )

    assert result.exit_code == 1
    assert "Run failed: empty_or_placeholder_content" in result.stderr
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["patch_status"] == "failed"
    assert payload["pr_action"] is None


def test_run_marks_patch_status_failed_for_llm_client_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = _write_patch_config(tmp_path)
    _run_cli_common_dependencies(monkeypatch)
    _run_cli_stale_detection(monkeypatch)

    def fail_patcher(*_args: object, **_kwargs: object) -> None:
        raise LLMClientError("model provider failed")

    monkeypatch.setattr("planning_validator.cli.run_patcher", fail_patcher)

    summary_json = tmp_path / "summary.json"
    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--summary-json",
            str(summary_json),
        ],
    )

    assert result.exit_code == 1
    assert "Run failed: model provider failed" in result.stderr
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["patch_status"] == "failed"


def test_run_failure_summary_write_is_best_effort(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = _write_patch_config(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(
        "planning_validator.cli.collect_repo_metadata",
        lambda _repo_root: MetadataStub(),
    )

    def fail_write_summary(_path: Path, _summary: object) -> None:
        raise OSError("summary path is not writable")

    monkeypatch.setattr(cli_module, "_write_run_summary", fail_write_summary)

    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--summary-json",
            str(tmp_path / "summary.json"),
        ],
    )

    assert result.exit_code == 1
    assert "Warning: failed to write run summary artifact" in result.stderr
    assert "Run failed: GITHUB_TOKEN environment variable is required for run." in result.stderr


def test_run_requires_github_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = _write_patch_config(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(
        "planning_validator.cli.collect_repo_metadata",
        lambda _repo_root: MetadataStub(),
    )

    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--summary-json",
            str(tmp_path / "summary.json"),
        ],
    )

    assert result.exit_code == 1
    assert "GITHUB_TOKEN environment variable is required for run" in result.stderr


def test_run_requires_openai_api_key_for_stale_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = _write_patch_config(tmp_path)
    _run_cli_common_dependencies(monkeypatch)
    _run_cli_stale_detection(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--summary-json",
            str(tmp_path / "summary.json"),
        ],
    )

    assert result.exit_code == 1
    assert "OPENAI_API_KEY environment variable is required for run" in result.stderr


def test_run_rejects_unsupported_provider_after_stale_detection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = _write_patch_config(tmp_path, provider="anthropic", model="claude-sonnet-4-5")
    _run_cli_common_dependencies(monkeypatch)
    _run_cli_stale_detection(monkeypatch)

    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--summary-json",
            str(tmp_path / "summary.json"),
        ],
    )

    assert result.exit_code == 1
    assert "Unsupported patching provider for run command: anthropic" in result.stderr


def test_run_validated_empty_patch_exits_without_pr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = _write_patch_config(tmp_path)
    _run_cli_common_dependencies(monkeypatch)
    _run_cli_stale_detection(monkeypatch)
    monkeypatch.setattr(
        "planning_validator.cli.run_patcher",
        lambda _resolved, snapshot, _detection_result, *, llm_client: ValidatedPatch(
            repo=snapshot.repo,
            head_sha=snapshot.head_sha,
            summary="Validated patch contained no edits.",
            edits=[],
        ),
    )

    def fail_pr_manager(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("PR manager must not run when validated patch has no edits")

    monkeypatch.setattr("planning_validator.cli.manage_patch_pull_request", fail_pr_manager)

    summary_json = tmp_path / "summary.json"
    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--summary-json",
            str(summary_json),
        ],
    )

    assert result.exit_code == 0
    assert "Status: no_changes" in result.stdout
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["status"] == "no_changes"
    assert payload["patch_status"] == "validated"
    assert payload["edited_files"] == []


@pytest.mark.parametrize(
    ("action", "expected_status", "expected_stdout"),
    [
        (PullRequestManagerAction.CREATED, "pr_created", "PR action: created"),
        (PullRequestManagerAction.DISABLED, "pr_disabled", "PR action: disabled"),
        (PullRequestManagerAction.NO_CHANGES, "no_changes", "PR action: no_changes"),
    ],
)
def test_run_maps_pr_manager_actions_to_summary_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    action: PullRequestManagerAction,
    expected_status: str,
    expected_stdout: str,
) -> None:
    config_path = _write_patch_config(tmp_path)
    _run_cli_common_dependencies(monkeypatch)
    _run_cli_stale_detection(monkeypatch)

    def fake_run_patcher(
        _resolved: object,
        snapshot: RepoSnapshot,
        _detection_result: object,
        *,
        llm_client: object,
    ) -> ValidatedPatch:
        del llm_client
        return ValidatedPatch(
            repo=snapshot.repo,
            head_sha=snapshot.head_sha,
            summary="Updated roadmap.",
            edits=[
                FileEdit(
                    path="docs/roadmap.md",
                    operation="replace_file",
                    new_content=(
                        "---\ntitle: Roadmap\n---\n# Roadmap\nPatcher core completed in #42.\n"
                    ),
                    rationale="Reflects merged PR #42.",
                    evidence_refs=["PR #42"],
                )
            ],
        )

    def fake_manage_patch_pull_request(**_kwargs: object) -> PullRequestManagerResult:
        pull_request = None
        if action is PullRequestManagerAction.CREATED:
            pull_request = AutomationPullRequest(
                number=88,
                title="docs: refresh planning/tracking files",
                url="https://github.com/acme/widgets/pull/88",
                head_branch="automation/planning-validator",
                base_branch="main",
                draft=True,
            )
        return PullRequestManagerResult(
            action=action,
            branch="automation/planning-validator",
            pull_request=pull_request,
            committed=action is not PullRequestManagerAction.DISABLED,
            pushed=action is not PullRequestManagerAction.DISABLED,
            message=f"PR manager returned {action.value}.",
        )

    monkeypatch.setattr("planning_validator.cli.run_patcher", fake_run_patcher)
    monkeypatch.setattr(
        "planning_validator.cli.manage_patch_pull_request",
        fake_manage_patch_pull_request,
    )

    summary_json = tmp_path / "summary.json"
    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--summary-json",
            str(summary_json),
        ],
    )

    assert result.exit_code == 0
    assert expected_stdout in result.stdout
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["status"] == expected_status
    assert payload["pr_action"] == action.value


def test_reusable_workflow_invokes_run_command() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    workflow = (repo_root / ".github/workflows/reusable-planning-validator.yml").read_text(
        encoding="utf-8"
    )

    assert "contents: write" in workflow
    assert "issues: write" in workflow
    assert "pull-requests: write" in workflow
    assert 'planning-validator run --config "${{ inputs.config_path }}"' in workflow
    assert "path: .planning-validator/run-summary.json" in workflow


def _write_patch_config(
    tmp_path: Path,
    *,
    provider: str = "openai",
    model: str = "gpt-5.4-thinking",
) -> Path:
    config_path = tmp_path / ".github/planning-validator.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs/roadmap.md").write_text(
        "---\ntitle: Roadmap\n---\n# Roadmap\n- [ ] Patcher core\n",
        encoding="utf-8",
    )
    config_path.write_text(
        (
            "schema_version: v1alpha1\n"
            "planning_files:\n"
            "  - docs/roadmap.md\n"
            "patching:\n"
            f"  provider: {provider}\n"
            f"  model: {model}\n"
            "  allowed_update_globs:\n"
            "    - docs/**/*.md\n"
        ),
        encoding="utf-8",
    )
    return config_path


def _stale_detection_payload() -> dict[str, object]:
    signal = {
        "signal_type": "todo_not_marked_done",
        "target_file": "docs/roadmap.md",
        "score": 0.4,
        "reason": "Patcher core is still unchecked.",
        "evidence": {"pr_number": 42},
    }
    return {
        "is_stale": True,
        "summary": "Detected stale docs.",
        "signals": [signal],
        "target_files": [
            {
                "path": "docs/roadmap.md",
                "aggregate_score": 0.7,
                "matched_signals": [signal],
                "allowed_to_patch": True,
            }
        ],
        "ignored_prs": [],
    }


def _patch_cli_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    replacement_content: str = (
        "---\ntitle: Roadmap\n---\n# Roadmap\nPatcher core completed in #42.\n"
    ),
) -> None:
    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    class FakeOpenAIClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> FakeOpenAIClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def generate_patch(self, _request: object) -> PatchResponse:
            return PatchResponse.model_validate(
                {
                    "summary": "Updated roadmap.",
                    "edits": [
                        {
                            "path": "docs/roadmap.md",
                            "operation": "replace_file",
                            "new_content": replacement_content,
                            "rationale": "Reflects merged PR #42.",
                            "evidence_refs": ["PR #42"],
                        }
                    ],
                }
            )

    monkeypatch.setenv("GITHUB_TOKEN", "github-token")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-token")
    monkeypatch.setattr(
        "planning_validator.cli.collect_repo_metadata",
        lambda _repo_root: MetadataStub(),
    )
    monkeypatch.setattr("planning_validator.cli.GitHubEvidenceClient", FakeClient)
    monkeypatch.setattr("planning_validator.cli.OpenAIResponsesClient", FakeOpenAIClient)
    monkeypatch.setattr(
        "planning_validator.cli.collect_recent_pr_snapshot",
        lambda *args, **kwargs: RepoSnapshot.model_validate(
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
                "tracking_files": [],
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
        ),
    )


def _run_cli_common_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    replacement_content: str = (
        "---\ntitle: Roadmap\n---\n# Roadmap\nPatcher core completed in #42.\n"
    ),
) -> None:
    _patch_cli_dependencies(monkeypatch, replacement_content=replacement_content)
    monkeypatch.setattr("planning_validator.cli.GitHubPullRequestClient", _FakePullRequestClient)


def _run_cli_stale_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "planning_validator.cli.run_detector",
        lambda _resolved, _snapshot: DetectionResult.model_validate(_stale_detection_payload()),
    )


class _FakePullRequestClient:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def __enter__(self) -> _FakePullRequestClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None
