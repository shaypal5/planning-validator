"""Deterministic stale-document detector orchestration."""

from __future__ import annotations

from fnmatch import fnmatch

from planning_validator.config import ResolvedConfig
from planning_validator.detector.scoring import build_target_file_decisions, dedupe_signals
from planning_validator.detector.signals import (
    build_document_contexts,
    build_eligible_pull_request,
    generate_issue_state_signals,
    generate_pr_signals,
    signal_sort_key,
)
from planning_validator.models import DetectionResult, RecentIssue, RepoSnapshot


def run_detector(resolved_config: ResolvedConfig, snapshot: RepoSnapshot) -> DetectionResult:
    document_contexts = build_document_contexts(snapshot)
    eligible_pull_requests = []
    ignored_prs: list[int] = []
    for pull_request in snapshot.recent_prs:
        if _has_ignored_label(
            pull_request.labels,
            resolved_config.config.staleness.ignore_pr_labels,
        ):
            ignored_prs.append(pull_request.number)
            continue
        if not resolved_config.config.staleness.require_pr_reflection:
            continue

        relevant_changed_files = [
            path
            for path in pull_request.changed_files
            if not _matches_any(path, resolved_config.config.staleness.ignore_paths)
        ]
        if not relevant_changed_files:
            continue

        eligible_pull_requests.append(
            build_eligible_pull_request(pull_request, changed_files=relevant_changed_files)
        )

    signals = generate_pr_signals(document_contexts, eligible_pull_requests)

    if resolved_config.config.staleness.require_issue_reflection:
        issues = _collect_recent_issues(snapshot, eligible_pull_requests)
        signals.extend(generate_issue_state_signals(document_contexts, issues=issues))

    deduped_signals = dedupe_signals(sorted(signals, key=signal_sort_key))
    deduped_signals.sort(key=signal_sort_key)
    target_files = build_target_file_decisions(
        deduped_signals,
        patchable_paths=set(resolved_config.patchable_paths),
        min_signal_score=resolved_config.config.staleness.min_signal_score,
        max_files_to_update=resolved_config.config.staleness.max_files_to_update,
    )
    eligible_pr_count = len(eligible_pull_requests)

    return DetectionResult(
        is_stale=bool(target_files),
        summary=_build_summary(
            signal_count=len(deduped_signals),
            file_count=len(target_files),
            pr_count=eligible_pr_count,
        ),
        signals=deduped_signals,
        target_files=target_files,
        ignored_prs=sorted(ignored_prs),
    )


def _collect_recent_issues(
    snapshot: RepoSnapshot,
    eligible_pull_requests: list,
) -> list[RecentIssue]:
    issues_by_number: dict[int, RecentIssue] = {}
    for issue in snapshot.recent_issues:
        issues_by_number.setdefault(issue.number, issue)
    for eligible_pull_request in eligible_pull_requests:
        for issue in eligible_pull_request.pull_request.linked_issues:
            issues_by_number.setdefault(issue.number, issue)
    return list(issues_by_number.values())


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch(path, pattern) for pattern in patterns)


def _has_ignored_label(labels: list[str], ignored_labels: list[str]) -> bool:
    ignored_set = {label.lower() for label in ignored_labels}
    return any(label.lower() in ignored_set for label in labels)


def _build_summary(*, signal_count: int, file_count: int, pr_count: int) -> str:
    if file_count == 0:
        return "No stale documentation signals detected."
    return (
        f"Detected {signal_count} stale signals across {file_count} files based on {pr_count} "
        "recent merged PRs."
    )
