"""Scoring and target-file selection for deterministic stale detection."""

from __future__ import annotations

from planning_validator.models import StaleSignal, TargetFileDecision


def build_target_file_decisions(
    signals: list[StaleSignal],
    *,
    patchable_paths: set[str],
    min_signal_score: float,
    max_files_to_update: int,
) -> list[TargetFileDecision]:
    signals_by_path: dict[str, list[StaleSignal]] = {}
    for signal in signals:
        signals_by_path.setdefault(signal.target_file, []).append(signal)

    decisions: list[TargetFileDecision] = []
    for path, path_signals in signals_by_path.items():
        deduped_signals = dedupe_signals(path_signals)
        aggregate_score = min(sum(signal.score for signal in deduped_signals), 1.0)
        allowed_to_patch = path in patchable_paths
        if aggregate_score < min_signal_score or not allowed_to_patch:
            continue
        decisions.append(
            TargetFileDecision(
                path=path,
                aggregate_score=aggregate_score,
                matched_signals=deduped_signals,
                allowed_to_patch=allowed_to_patch,
            )
        )

    decisions.sort(key=lambda item: (-item.aggregate_score, item.path))
    return decisions[:max_files_to_update]


def dedupe_signals(signals: list[StaleSignal]) -> list[StaleSignal]:
    deduped: dict[tuple[str, int | None, int | None, str], StaleSignal] = {}
    for signal in sorted(signals, key=_signal_dedupe_sort_key):
        pr_number = signal.evidence.get("pr_number")
        issue_number = signal.evidence.get("issue_number")
        deduped.setdefault(
            (
                signal.signal_type.value,
                pr_number if isinstance(pr_number, int) else None,
                issue_number if isinstance(issue_number, int) else None,
                signal.reason,
            ),
            signal,
        )
    return list(deduped.values())


def _signal_dedupe_sort_key(signal: StaleSignal) -> tuple[str, str, int, int, str]:
    pr_number = signal.evidence.get("pr_number")
    issue_number = signal.evidence.get("issue_number")
    return (
        signal.target_file,
        signal.signal_type.value,
        pr_number if isinstance(pr_number, int) else -1,
        issue_number if isinstance(issue_number, int) else -1,
        signal.reason,
    )
