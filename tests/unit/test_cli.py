from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from planning_validator.cli import app
from planning_validator.models import DetectionResult, PatchResponse, RepoSnapshot

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


def test_run_command_is_reserved() -> None:
    result = runner.invoke(app, ["run"])

    assert result.exit_code == 1
    assert "'run' is reserved for a later milestone." in result.stderr


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


def _patch_cli_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
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
                            "new_content": (
                                "---\ntitle: Roadmap\n---\n# Roadmap\n"
                                "Patcher core completed in #42.\n"
                            ),
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
