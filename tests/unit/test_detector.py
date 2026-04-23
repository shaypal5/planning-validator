from __future__ import annotations

from pathlib import Path

from planning_validator.config import load_config
from planning_validator.detector import run_detector
from planning_validator.detector.signals import (
    build_document_contexts,
    generate_issue_state_signals,
)
from planning_validator.models import RecentIssue, RecentPullRequest, RepoSnapshot, StaleSignalType


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_resolved_config(
    tmp_path: Path,
    *,
    planning_content: str = "# Roadmap\n",
    tracking_content: str = "# Tasks\n",
    patching_allowed: list[str] | None = None,
    staleness_block: str = "",
) -> object:
    write_file(tmp_path / "docs/roadmap.md", planning_content)
    write_file(tmp_path / "docs/tasks.md", tracking_content)
    allowed_globs = patching_allowed or ["docs/**/*.md"]
    allowed_lines = "\n".join(f"        - {glob}" for glob in allowed_globs)
    write_file(
        tmp_path / ".github/planning-validator.yml",
        (
            "schema_version: v1alpha1\n"
            "planning_files:\n"
            "  - docs/roadmap.md\n"
            "tracking_files:\n"
            "  - docs/tasks.md\n"
            f"{staleness_block}"
            "patching:\n"
            "  provider: openai\n"
            "  model: gpt-5.4-thinking\n"
            "  allowed_update_globs:\n"
            f"{allowed_lines}\n"
        ),
    )
    return load_config(tmp_path / ".github/planning-validator.yml", repo_root=tmp_path)


def make_snapshot(
    *,
    planning_path: str,
    planning_content: str,
    tracking_path: str,
    tracking_content: str,
    recent_prs: list[RecentPullRequest],
    recent_issues: list[RecentIssue] | None = None,
) -> RepoSnapshot:
    return RepoSnapshot.model_validate(
        {
            "repo": "acme/widgets",
            "default_branch": "main",
            "head_sha": "abc123",
            "planning_files": [{"path": planning_path, "content": planning_content, "sha": "1"}],
            "tracking_files": [{"path": tracking_path, "content": tracking_content, "sha": "2"}],
            "recent_prs": [pull_request.model_dump(mode="json") for pull_request in recent_prs],
            "recent_issues": []
            if recent_issues is None
            else [issue.model_dump(mode="json") for issue in recent_issues],
        }
    )


def recent_pull_request(
    *,
    number: int = 42,
    title: str = "Add detector command",
    changed_files: list[str] | None = None,
    labels: list[str] | None = None,
    linked_issues: list[RecentIssue] | None = None,
) -> RecentPullRequest:
    return RecentPullRequest.model_validate(
        {
            "number": number,
            "title": title,
            "merged_at": "2026-04-22T08:00:00Z",
            "labels": [] if labels is None else labels,
            "changed_files": (
                ["src/planning_validator/cli.py"] if changed_files is None else changed_files
            ),
            "linked_issues": []
            if linked_issues is None
            else [issue.model_dump(mode="json") for issue in linked_issues],
            "url": f"https://github.com/acme/widgets/pull/{number}",
        }
    )


def recent_issue(*, number: int = 17, state: str = "closed") -> RecentIssue:
    return RecentIssue.model_validate(
        {
            "number": number,
            "title": "Ship detector",
            "state": state,
            "closed_at": "2026-04-22T08:30:00Z" if state == "closed" else None,
            "url": f"https://github.com/acme/widgets/issues/{number}",
        }
    )


def test_ignored_label_pr_is_excluded_and_recorded(tmp_path: Path) -> None:
    resolved = make_resolved_config(
        tmp_path,
        staleness_block="staleness:\n  ignore_pr_labels:\n    - skip-planning-validator\n",
    )
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\nplanned detector work\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n- [ ] detector command\n",
        recent_prs=[recent_pull_request(labels=["skip-planning-validator"])],
    )

    result = run_detector(resolved, snapshot)

    assert result.ignored_prs == [42]
    assert result.signals == []
    assert result.target_files == []


def test_ignore_paths_exclude_pr_without_recording_ignored_number(tmp_path: Path) -> None:
    resolved = make_resolved_config(
        tmp_path,
        staleness_block="staleness:\n  ignore_paths:\n    - docs/**\n",
    )
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\nplanned detector work\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n- [ ] detector command\n",
        recent_prs=[recent_pull_request(changed_files=["docs/roadmap.md"])],
    )

    result = run_detector(resolved, snapshot)

    assert result.ignored_prs == []
    assert result.signals == []


def test_pr_reflection_can_be_disabled_without_ignoring_prs(tmp_path: Path) -> None:
    resolved = make_resolved_config(
        tmp_path,
        staleness_block="staleness:\n  require_pr_reflection: false\n",
    )
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\nplanned detector work\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n- [ ] detector command\n",
        recent_prs=[recent_pull_request()],
    )

    result = run_detector(resolved, snapshot)

    assert result.ignored_prs == []
    assert result.signals == []
    assert result.summary == "No stale documentation signals detected."


def test_todo_not_marked_done_signal_is_emitted(tmp_path: Path) -> None:
    resolved = make_resolved_config(
        tmp_path,
        staleness_block="staleness:\n  min_signal_score: 0.4\n",
    )
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n- [ ] add detector command for cli support\n",
        recent_prs=[recent_pull_request(title="Add detector command for CLI support")],
    )

    result = run_detector(resolved, snapshot)

    assert any(
        signal.signal_type is StaleSignalType.TODO_NOT_MARKED_DONE for signal in result.signals
    )
    assert result.target_files[0].path == "docs/tasks.md"


def test_roadmap_stage_incorrect_signal_is_emitted(tmp_path: Path) -> None:
    resolved = make_resolved_config(tmp_path)
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\nNext up: add detector command for cli support\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n",
        recent_prs=[recent_pull_request(title="Add detector command for CLI support")],
    )

    result = run_detector(resolved, snapshot)

    assert any(
        signal.signal_type is StaleSignalType.ROADMAP_STAGE_INCORRECT for signal in result.signals
    )


def test_file_mentions_closed_pr_as_open_signal_is_emitted(tmp_path: Path) -> None:
    resolved = make_resolved_config(tmp_path)
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\nPR #42 is still pending review.\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n",
        recent_prs=[recent_pull_request()],
    )

    result = run_detector(resolved, snapshot)

    assert any(
        signal.signal_type is StaleSignalType.FILE_MENTIONS_CLOSED_PR_AS_OPEN
        for signal in result.signals
    )


def test_issue_state_outdated_uses_recent_issues_when_enabled(tmp_path: Path) -> None:
    resolved = make_resolved_config(
        tmp_path,
        staleness_block="staleness:\n  require_issue_reflection: true\n",
    )
    closed_issue = recent_issue()
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\nIssue #17 remains open and pending.\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n",
        recent_prs=[recent_pull_request()],
        recent_issues=[closed_issue],
    )

    result = run_detector(resolved, snapshot)

    assert any(
        signal.signal_type is StaleSignalType.ISSUE_STATE_OUTDATED for signal in result.signals
    )


def test_issue_state_outdated_uses_linked_issues_and_deduplicates_numbers(tmp_path: Path) -> None:
    resolved = make_resolved_config(
        tmp_path,
        staleness_block="staleness:\n  require_issue_reflection: true\n",
    )
    linked_issue = recent_issue(number=17)
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\nIssue #17 remains open and pending.\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n",
        recent_prs=[
            recent_pull_request(number=42, linked_issues=[linked_issue]),
            recent_pull_request(number=43, linked_issues=[linked_issue]),
        ],
    )

    result = run_detector(resolved, snapshot)

    issue_signals = [
        signal
        for signal in result.signals
        if signal.signal_type is StaleSignalType.ISSUE_STATE_OUTDATED
    ]
    assert len(issue_signals) == 1


def test_issue_state_outdated_skips_duplicate_recent_issue_numbers(tmp_path: Path) -> None:
    resolved = make_resolved_config(
        tmp_path,
        staleness_block="staleness:\n  require_issue_reflection: true\n",
    )
    duplicate_issue = recent_issue(number=17).model_dump(mode="json")
    snapshot = RepoSnapshot.model_validate(
        {
            "repo": "acme/widgets",
            "default_branch": "main",
            "head_sha": "abc123",
            "planning_files": [
                {
                    "path": "docs/roadmap.md",
                    "content": "# Roadmap\nIssue #17 remains open and pending.\n",
                    "sha": "1",
                }
            ],
            "tracking_files": [{"path": "docs/tasks.md", "content": "# Tasks\n", "sha": "2"}],
            "recent_prs": [recent_pull_request().model_dump(mode="json")],
            "recent_issues": [duplicate_issue, duplicate_issue],
        }
    )

    result = run_detector(resolved, snapshot)

    issue_signals = [
        signal
        for signal in result.signals
        if signal.signal_type is StaleSignalType.ISSUE_STATE_OUTDATED
    ]
    assert len(issue_signals) == 1


def test_generate_issue_state_signals_skips_duplicate_numbers_in_issue_input(
    tmp_path: Path,
) -> None:
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\nIssue #17 remains open and pending.\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n",
        recent_prs=[],
    )
    duplicate_issue = recent_issue(number=17)

    signals = generate_issue_state_signals(
        build_document_contexts(snapshot),
        issues=[duplicate_issue, duplicate_issue],
    )

    assert len(signals) == 1


def test_issue_state_outdated_skips_open_issues_and_missing_stale_language(tmp_path: Path) -> None:
    resolved = make_resolved_config(
        tmp_path,
        staleness_block="staleness:\n  require_issue_reflection: true\n",
    )
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\nIssue #17 is noted here without stale wording.\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n",
        recent_prs=[recent_pull_request()],
        recent_issues=[recent_issue(number=17, state="open")],
    )

    result = run_detector(resolved, snapshot)

    assert all(
        signal.signal_type is not StaleSignalType.ISSUE_STATE_OUTDATED for signal in result.signals
    )


def test_issue_state_outdated_skips_closed_issues_without_stale_language(tmp_path: Path) -> None:
    resolved = make_resolved_config(
        tmp_path,
        staleness_block="staleness:\n  require_issue_reflection: true\n",
    )
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\nIssue #17 was discussed in planning notes.\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n",
        recent_prs=[recent_pull_request()],
        recent_issues=[recent_issue(number=17, state="closed")],
    )

    result = run_detector(resolved, snapshot)

    assert all(
        signal.signal_type is not StaleSignalType.ISSUE_STATE_OUTDATED for signal in result.signals
    )


def test_issue_reflection_uses_linked_issues_when_pr_reflection_is_disabled(tmp_path: Path) -> None:
    resolved = make_resolved_config(
        tmp_path,
        staleness_block=(
            "staleness:\n  require_pr_reflection: false\n  require_issue_reflection: true\n"
        ),
    )
    linked_issue = recent_issue(number=17, state="closed")
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\nIssue #17 remains open and pending.\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n",
        recent_prs=[recent_pull_request(linked_issues=[linked_issue])],
    )

    result = run_detector(resolved, snapshot)

    assert any(
        signal.signal_type is StaleSignalType.ISSUE_STATE_OUTDATED for signal in result.signals
    )


def test_fresh_docs_with_pr_reference_and_completion_language_are_clean(tmp_path: Path) -> None:
    resolved = make_resolved_config(tmp_path)
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\nDelivered in PR #42 and now complete.\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n- [x] add detector command for cli support\n",
        recent_prs=[recent_pull_request()],
    )

    result = run_detector(resolved, snapshot)

    assert result.summary == "No stale documentation signals detected."
    assert result.signals == []


def test_duplicate_document_membership_does_not_duplicate_signals(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs/shared.md",
        "# Roadmap\nNext: add detector command for cli support\n",
    )
    write_file(
        tmp_path / ".github/planning-validator.yml",
        (
            "schema_version: v1alpha1\n"
            "planning_files:\n"
            "  - docs/shared.md\n"
            "tracking_files:\n"
            "  - docs/shared.md\n"
            "patching:\n"
            "  provider: openai\n"
            "  model: gpt-5.4-thinking\n"
            "  allowed_update_globs:\n"
            "    - docs/**/*.md\n"
        ),
    )
    resolved = load_config(tmp_path / ".github/planning-validator.yml", repo_root=tmp_path)
    snapshot = RepoSnapshot.model_validate(
        {
            "repo": "acme/widgets",
            "default_branch": "main",
            "head_sha": "abc123",
            "planning_files": [
                {
                    "path": "docs/shared.md",
                    "content": "# Roadmap\nNext: add detector command for cli support\n",
                    "sha": "1",
                }
            ],
            "tracking_files": [
                {
                    "path": "docs/shared.md",
                    "content": "# Roadmap\nNext: add detector command for cli support\n",
                    "sha": "1",
                }
            ],
            "recent_prs": [recent_pull_request().model_dump(mode="json")],
        }
    )

    result = run_detector(resolved, snapshot)

    assert {signal.target_file for signal in result.signals} == {"docs/shared.md"}
    assert len(result.target_files) == 1


def test_non_patchable_docs_can_emit_signals_but_not_targets(tmp_path: Path) -> None:
    resolved = make_resolved_config(tmp_path, patching_allowed=["docs/tasks.md"])
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\nNext: add detector command for cli support\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n",
        recent_prs=[recent_pull_request()],
    )

    result = run_detector(resolved, snapshot)

    assert any(signal.target_file == "docs/roadmap.md" for signal in result.signals)
    assert all(target.path != "docs/roadmap.md" for target in result.target_files)


def test_thresholding_excludes_below_threshold_files(tmp_path: Path) -> None:
    resolved = make_resolved_config(
        tmp_path,
        staleness_block="staleness:\n  min_signal_score: 0.5\n",
    )
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Changelog\n",
        recent_prs=[recent_pull_request()],
    )

    result = run_detector(resolved, snapshot)

    assert any(
        signal.signal_type is StaleSignalType.RECENT_WORK_MISSING_FROM_CHANGELOG
        for signal in result.signals
    )
    assert result.target_files == []
    assert "but none were actionable for updates" in result.summary


def test_checkbox_only_lines_do_not_emit_status_outdated(tmp_path: Path) -> None:
    resolved = make_resolved_config(tmp_path)
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n- [ ] add detector command for cli support\n",
        recent_prs=[recent_pull_request(title="Add detector command for CLI support")],
    )

    result = run_detector(resolved, snapshot)

    assert any(
        signal.signal_type is StaleSignalType.TODO_NOT_MARKED_DONE for signal in result.signals
    )
    assert all(
        signal.signal_type is not StaleSignalType.STATUS_OUTDATED for signal in result.signals
    )


def test_checklist_with_low_term_overlap_does_not_emit_todo_signal(tmp_path: Path) -> None:
    resolved = make_resolved_config(tmp_path)
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n- [ ] write docs\n",
        recent_prs=[recent_pull_request(title="Add detector command for CLI support")],
    )

    result = run_detector(resolved, snapshot)

    assert all(
        signal.signal_type is not StaleSignalType.TODO_NOT_MARKED_DONE for signal in result.signals
    )


def test_completed_language_blocks_status_outdated_signal(tmp_path: Path) -> None:
    resolved = make_resolved_config(tmp_path)
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\nDetector command is planned and complete now.\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n",
        recent_prs=[recent_pull_request(title="Add detector command")],
    )

    result = run_detector(resolved, snapshot)

    assert all(
        signal.signal_type is not StaleSignalType.STATUS_OUTDATED for signal in result.signals
    )


def test_changelog_detection_by_path_keyword_without_body_keyword(tmp_path: Path) -> None:
    write_file(tmp_path / "docs/release-notes.md", "# Notes\n")
    write_file(
        tmp_path / ".github/planning-validator.yml",
        (
            "schema_version: v1alpha1\n"
            "planning_files:\n"
            "  - docs/release-notes.md\n"
            "patching:\n"
            "  provider: openai\n"
            "  model: gpt-5.4-thinking\n"
            "  allowed_update_globs:\n"
            "    - docs/**/*.md\n"
        ),
    )
    resolved = load_config(tmp_path / ".github/planning-validator.yml", repo_root=tmp_path)
    snapshot = RepoSnapshot.model_validate(
        {
            "repo": "acme/widgets",
            "default_branch": "main",
            "head_sha": "abc123",
            "planning_files": [
                {"path": "docs/release-notes.md", "content": "# Notes\n", "sha": "1"}
            ],
            "tracking_files": [],
            "recent_prs": [recent_pull_request().model_dump(mode="json")],
        }
    )

    result = run_detector(resolved, snapshot)

    assert any(
        signal.signal_type is StaleSignalType.RECENT_WORK_MISSING_FROM_CHANGELOG
        for signal in result.signals
    )


def test_max_files_cap_keeps_top_ranked_targets(tmp_path: Path) -> None:
    write_file(
        tmp_path / "docs/roadmap.md",
        "# Roadmap\nNext: add detector command for cli support\n",
    )
    write_file(
        tmp_path / "docs/tasks.md",
        "# Tasks\n- [ ] add detector command for cli support\n",
    )
    write_file(
        tmp_path / "docs/status.md",
        "# Status\npending detector command for cli support\n",
    )
    write_file(
        tmp_path / ".github/planning-validator.yml",
        (
            "schema_version: v1alpha1\n"
            "planning_files:\n"
            "  - docs/roadmap.md\n"
            "  - docs/status.md\n"
            "tracking_files:\n"
            "  - docs/tasks.md\n"
            "staleness:\n"
            "  max_files_to_update: 1\n"
            "patching:\n"
            "  provider: openai\n"
            "  model: gpt-5.4-thinking\n"
            "  allowed_update_globs:\n"
            "    - docs/**/*.md\n"
        ),
    )
    resolved = load_config(tmp_path / ".github/planning-validator.yml", repo_root=tmp_path)
    snapshot = RepoSnapshot.model_validate(
        {
            "repo": "acme/widgets",
            "default_branch": "main",
            "head_sha": "abc123",
            "planning_files": [
                {
                    "path": "docs/roadmap.md",
                    "content": "# Roadmap\nNext: add detector command for cli support\n",
                    "sha": "1",
                },
                {
                    "path": "docs/status.md",
                    "content": "# Status\npending detector command for cli support\n",
                    "sha": "2",
                },
            ],
            "tracking_files": [
                {
                    "path": "docs/tasks.md",
                    "content": "# Tasks\n- [ ] add detector command for cli support\n",
                    "sha": "3",
                }
            ],
            "recent_prs": [recent_pull_request().model_dump(mode="json")],
        }
    )

    result = run_detector(resolved, snapshot)

    assert len(result.target_files) == 1
    assert result.target_files[0].path == "docs/roadmap.md"


def test_output_is_stable_across_repeated_runs(tmp_path: Path) -> None:
    resolved = make_resolved_config(tmp_path)
    snapshot = make_snapshot(
        planning_path="docs/roadmap.md",
        planning_content="# Roadmap\nNext: add detector command for cli support\n",
        tracking_path="docs/tasks.md",
        tracking_content="# Tasks\n- [ ] add detector command for cli support\n",
        recent_prs=[recent_pull_request()],
    )

    first = run_detector(resolved, snapshot)
    second = run_detector(resolved, snapshot)

    assert first.model_dump() == second.model_dump()
