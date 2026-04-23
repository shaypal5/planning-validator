"""Signal generation for deterministic stale-document detection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from planning_validator.models import (
    LocalDocument,
    RecentIssue,
    RecentPullRequest,
    RepoSnapshot,
    StaleSignal,
    StaleSignalType,
)

_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*")
_PR_REFERENCE_TEMPLATE = r"(?<!\w)#{number}(?!\w)"
_CHECKBOX_PATTERN = re.compile(r"^\s*[-*]\s+\[\s\]\s+(?P<body>.+)$", re.IGNORECASE)
_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>.+)$")
_ROADMAP_PATH_KEYWORDS = ("roadmap", "plan", "status", "milestone")
_ROADMAP_HEADING_KEYWORDS = ("roadmap", "milestone", "status", "timeline")
_CHANGELOG_KEYWORDS = ("changelog", "release", "recent work", "what shipped")
_STATUS_PHRASES = ("planned", "pending", "in progress", "todo", "next")
_FUTURE_PHRASES = ("planned", "upcoming", "future", "next", "later")
_STALE_PR_STATE_PHRASES = ("open", "pending", "waiting", "in review")
_STALE_CLOSED_ISSUE_PHRASES = ("open", "pending", "todo", "in progress")
_COMPLETION_PHRASES = ("done", "complete", "completed", "merged", "shipped")


@dataclass(frozen=True)
class EligiblePullRequest:
    pull_request: RecentPullRequest
    changed_files: tuple[str, ...]
    title_terms: frozenset[str]
    path_terms: frozenset[str]
    all_terms: frozenset[str]


@dataclass(frozen=True)
class DocumentContext:
    document: LocalDocument
    content_lower: str
    lines: tuple[str, ...]
    headings_lower: tuple[str, ...]
    is_roadmap_like: bool
    is_changelog_like: bool


def build_document_contexts(snapshot: RepoSnapshot) -> list[DocumentContext]:
    documents_by_path: dict[str, LocalDocument] = {}
    for document in [*snapshot.planning_files, *snapshot.tracking_files]:
        documents_by_path.setdefault(document.path, document)

    return [
        DocumentContext(
            document=document,
            content_lower=document.content.lower(),
            lines=tuple(document.content.splitlines()),
            headings_lower=tuple(
                match.group("title").strip().lower()
                for line in document.content.splitlines()
                if (match := _HEADING_PATTERN.match(line))
            ),
            is_roadmap_like=_is_roadmap_like(document),
            is_changelog_like=_is_changelog_like(document),
        )
        for document in sorted(documents_by_path.values(), key=lambda item: item.path)
    ]


def build_eligible_pull_request(
    pull_request: RecentPullRequest,
    *,
    changed_files: list[str],
) -> EligiblePullRequest:
    title_terms = frozenset(_extract_terms(pull_request.title))
    path_terms = frozenset(_extract_path_terms(changed_files))
    return EligiblePullRequest(
        pull_request=pull_request,
        changed_files=tuple(changed_files),
        title_terms=title_terms,
        path_terms=path_terms,
        all_terms=frozenset({*title_terms, *path_terms}),
    )


def generate_pr_signals(
    document_contexts: list[DocumentContext],
    eligible_pull_requests: list[EligiblePullRequest],
) -> list[StaleSignal]:
    signals: list[StaleSignal] = []
    for document_context in document_contexts:
        for eligible_pull_request in eligible_pull_requests:
            signals.extend(_generate_signals_for_document(document_context, eligible_pull_request))
    return signals


def generate_issue_state_signals(
    document_contexts: list[DocumentContext],
    *,
    issues: list[RecentIssue],
) -> list[StaleSignal]:
    signals: list[StaleSignal] = []
    seen_issue_numbers: set[int] = set()
    for issue in sorted(issues, key=lambda item: item.number):
        if issue.number in seen_issue_numbers:
            continue
        seen_issue_numbers.add(issue.number)
        if issue.state.value != "closed":
            continue

        issue_reference_pattern = re.compile(
            _PR_REFERENCE_TEMPLATE.format(number=issue.number),
            re.IGNORECASE,
        )
        for document_context in document_contexts:
            if not issue_reference_pattern.search(document_context.content_lower):
                continue

            stale_phrase = _find_phrase(document_context.content_lower, _STALE_CLOSED_ISSUE_PHRASES)
            if stale_phrase is None:
                continue

            signals.append(
                StaleSignal(
                    signal_type=StaleSignalType.ISSUE_STATE_OUTDATED,
                    target_file=document_context.document.path,
                    score=0.30,
                    reason=(
                        f"Issue #{issue.number} is closed but the document still says "
                        f"'{stale_phrase}'."
                    ),
                    evidence={
                        "issue_number": issue.number,
                        "issue_state": issue.state.value,
                        "issue_url": issue.url,
                    },
                )
            )

    return signals


def signal_sort_key(signal: StaleSignal) -> tuple[str, str, int, int, str]:
    pr_number = signal.evidence.get("pr_number")
    issue_number = signal.evidence.get("issue_number")
    return (
        signal.target_file,
        signal.signal_type.value,
        pr_number if isinstance(pr_number, int) else -1,
        issue_number if isinstance(issue_number, int) else -1,
        signal.reason,
    )


def _generate_signals_for_document(
    document_context: DocumentContext,
    eligible_pull_request: EligiblePullRequest,
) -> list[StaleSignal]:
    signals: list[StaleSignal] = []
    pull_request = eligible_pull_request.pull_request
    matched_terms = _matched_terms(document_context, eligible_pull_request)
    has_pr_reference = _contains_pr_reference(document_context.content_lower, pull_request.number)
    relevance_terms = _relevance_terms(document_context, eligible_pull_request)
    evidence = {
        "pr_number": pull_request.number,
        "pr_title": pull_request.title,
        "pr_url": pull_request.url,
        "changed_files": list(eligible_pull_request.changed_files),
        "matched_terms": sorted(matched_terms),
    }

    if not has_pr_reference and not matched_terms:
        signals.append(
            StaleSignal(
                signal_type=StaleSignalType.MISSING_PR_REFLECTION,
                target_file=document_context.document.path,
                score=0.35,
                reason=(
                    f"Recent merged PR #{pull_request.number} is not reflected in this document."
                ),
                evidence=evidence,
            )
        )

    stale_phrase = _find_relevant_stale_phrase(document_context, relevance_terms)
    if stale_phrase is not None and relevance_terms:
        signals.append(
            StaleSignal(
                signal_type=StaleSignalType.STATUS_OUTDATED,
                target_file=document_context.document.path,
                score=0.40,
                reason=(
                    f"Document still uses stale status wording '{stale_phrase}' "
                    f"for work tied to PR #{pull_request.number}."
                ),
                evidence=evidence,
            )
        )

    for line in document_context.lines:
        checkbox_match = _CHECKBOX_PATTERN.match(line)
        if checkbox_match is None:
            continue
        body = checkbox_match.group("body").strip().lower()
        body_terms = set(_extract_terms(body))
        if len(body_terms & eligible_pull_request.all_terms) < 2:
            continue
        signals.append(
            StaleSignal(
                signal_type=StaleSignalType.TODO_NOT_MARKED_DONE,
                target_file=document_context.document.path,
                score=0.40,
                reason=(
                    f"Unchecked checklist item still matches work delivered by PR "
                    f"#{pull_request.number}."
                ),
                evidence=evidence,
            )
        )
        break

    future_phrase = _find_phrase(document_context.content_lower, _FUTURE_PHRASES)
    if document_context.is_roadmap_like and relevance_terms and future_phrase is not None:
        signals.append(
            StaleSignal(
                signal_type=StaleSignalType.ROADMAP_STAGE_INCORRECT,
                target_file=document_context.document.path,
                score=0.35,
                reason=(
                    f"Roadmap-style document still places PR #{pull_request.number} work in "
                    f"'{future_phrase}'."
                ),
                evidence=evidence,
            )
        )

    if document_context.is_changelog_like and not has_pr_reference and not matched_terms:
        signals.append(
            StaleSignal(
                signal_type=StaleSignalType.RECENT_WORK_MISSING_FROM_CHANGELOG,
                target_file=document_context.document.path,
                score=0.20,
                reason=(
                    "Changelog-like document is missing recent work from PR "
                    f"#{pull_request.number}."
                ),
                evidence=evidence,
            )
        )

    if has_pr_reference:
        stale_pr_phrase = _find_phrase(document_context.content_lower, _STALE_PR_STATE_PHRASES)
        if stale_pr_phrase is not None:
            signals.append(
                StaleSignal(
                    signal_type=StaleSignalType.FILE_MENTIONS_CLOSED_PR_AS_OPEN,
                    target_file=document_context.document.path,
                    score=0.30,
                    reason=(
                        f"Document mentions merged PR #{pull_request.number} as "
                        f"'{stale_pr_phrase}'."
                    ),
                    evidence=evidence,
                )
            )

    return signals


def _extract_terms(text: str) -> list[str]:
    terms: list[str] = []
    for match in _TOKEN_PATTERN.finditer(text.lower()):
        token = match.group(0).strip("_-")
        if len(token) < 3 or token in _STOPWORDS:
            continue
        terms.append(token)
    return terms


def _extract_path_terms(paths: list[str]) -> list[str]:
    terms: set[str] = set()
    for path in paths:
        pure_path = PurePosixPath(path)
        for part in pure_path.parts:
            for token in _extract_terms(part.replace(".", "_")):
                terms.add(token)
        stem = pure_path.stem
        for token in _extract_terms(stem):
            terms.add(token)
    return sorted(terms)


def _contains_pr_reference(content_lower: str, number: int) -> bool:
    return re.search(_PR_REFERENCE_TEMPLATE.format(number=number), content_lower) is not None


def _matched_terms(
    document_context: DocumentContext,
    eligible_pull_request: EligiblePullRequest,
) -> set[str]:
    document_terms = set(_extract_terms(document_context.content_lower))
    return document_terms & set(eligible_pull_request.all_terms)


def _relevance_terms(
    document_context: DocumentContext,
    eligible_pull_request: EligiblePullRequest,
) -> set[str]:
    if _contains_pr_reference(
        document_context.content_lower,
        eligible_pull_request.pull_request.number,
    ):
        return {f"#{eligible_pull_request.pull_request.number}"}
    return _matched_terms(document_context, eligible_pull_request)


def _find_relevant_stale_phrase(
    document_context: DocumentContext,
    relevance_terms: set[str],
) -> str | None:
    for index, line in enumerate(document_context.lines):
        line_lower = line.lower()
        non_reference_terms = [term for term in relevance_terms if not term.startswith("#")]
        reference_terms = [term for term in relevance_terms if term.startswith("#")]
        if not any(term in line_lower for term in non_reference_terms) and not any(
            term in line_lower for term in reference_terms
        ):
            continue
        nearby_lines = document_context.lines[max(0, index - 1) : index + 2]
        nearby_text = "\n".join(nearby_lines).lower()
        if _CHECKBOX_PATTERN.match(line):
            continue
        phrase = _find_phrase(nearby_text, _STATUS_PHRASES)
        if phrase is not None:
            completion_phrase = _find_phrase(nearby_text, _COMPLETION_PHRASES)
            if completion_phrase is None:
                return phrase

    return None


def _find_phrase(content_lower: str, phrases: tuple[str, ...]) -> str | None:
    for phrase in phrases:
        if phrase in content_lower:
            return phrase
    return None


def _is_roadmap_like(document: LocalDocument) -> bool:
    path_lower = document.path.lower()
    if any(keyword in path_lower for keyword in _ROADMAP_PATH_KEYWORDS):
        return True

    for line in document.content.splitlines():
        match = _HEADING_PATTERN.match(line)
        if match and any(
            keyword in match.group("title").lower() for keyword in _ROADMAP_HEADING_KEYWORDS
        ):
            return True

    return False


def _is_changelog_like(document: LocalDocument) -> bool:
    path_lower = document.path.lower()
    if any(keyword in path_lower for keyword in _CHANGELOG_KEYWORDS):
        return True

    content_lower = document.content.lower()
    return any(keyword in content_lower for keyword in _CHANGELOG_KEYWORDS)
