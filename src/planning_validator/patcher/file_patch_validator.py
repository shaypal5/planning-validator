"""Validation for model-proposed full-file markdown replacements."""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path

from planning_validator.models import (
    FileEdit,
    PatchRequest,
    PatchResponse,
    PatchValidationFailure,
    ValidatedPatch,
)

_REFERENCE_PATTERN = re.compile(r"(?:#|/(?:pull|issues)/)(?P<number>\d+)\b")
_HEADING_PATTERN = re.compile(r"^#{1,6}\s+\S.*$", re.MULTILINE)
_COMPLETION_PATTERN = re.compile(
    r"(?:-\s+\[x\])|\b(?:done|complete|completed|merged|shipped|landed)\b",
    re.IGNORECASE,
)
_COMPLETION_MARKER_PATTERN = re.compile(
    r"-\s+\[x\]|\b(?:done|complete|completed|merged|shipped|landed)\b",
    re.IGNORECASE,
)
_PLACEHOLDER_VALUES = {"...", "todo", "tbd", "n/a", "none"}


class PatchValidationError(ValueError):
    """Raised when a patch response violates patch safety policy."""

    def __init__(self, failures: list[PatchValidationFailure]) -> None:
        self.failures = failures
        super().__init__("Patch validation failed")


def validate_patch_response(request: PatchRequest, response: PatchResponse) -> ValidatedPatch:
    """Validate all proposed edits and return an accepted patch artifact."""

    failures: list[PatchValidationFailure] = []
    target_files = {target.path: target for target in request.target_files}
    patchable_paths = _string_list(request.config_summary.get("patchable_paths"))
    forbidden_globs = _string_list(request.config_summary.get("forbidden_update_globs"))
    max_files = _int_value(request.config_summary.get("max_files_to_update"))
    preserve_frontmatter = _rendering_flag(request, "preserve_frontmatter", default=True)
    preserve_sections = _rendering_flag(
        request,
        "preserve_unrecognized_sections",
        default=True,
    )

    if max_files is not None and len(response.edits) > max_files:
        failures.append(
            PatchValidationFailure(
                code="too_many_edits",
                message=f"Patch edits exceed configured maximum of {max_files}",
            )
        )

    allowed_reference_numbers = _allowed_reference_numbers(request)
    for edit in response.edits:
        target = target_files.get(edit.path)
        original_content = target.original_content if target is not None else ""
        if target is None:
            failures.append(
                PatchValidationFailure(
                    code="unselected_path",
                    path=edit.path,
                    message="Edit path was not selected by the detector",
                )
            )
        if patchable_paths and edit.path not in patchable_paths:
            failures.append(
                PatchValidationFailure(
                    code="path_not_patchable",
                    path=edit.path,
                    message="Edit path is not in the resolved patchable path set",
                )
            )
        if not _is_markdown_path(edit.path):
            failures.append(
                PatchValidationFailure(
                    code="non_markdown_path",
                    path=edit.path,
                    message="Only markdown files may be edited",
                )
            )
        if _matches_any(edit.path, forbidden_globs):
            failures.append(
                PatchValidationFailure(
                    code="forbidden_path",
                    path=edit.path,
                    message="Edit path matches patching.forbidden_update_globs",
                )
            )

        _validate_content(
            edit,
            original_content=original_content,
            preserve_frontmatter=preserve_frontmatter,
            preserve_sections=preserve_sections,
            allowed_reference_numbers=allowed_reference_numbers,
            failures=failures,
            request=request,
        )

    if failures:
        raise PatchValidationError(failures)

    return ValidatedPatch(
        repo=request.repo,
        head_sha=request.head_sha,
        summary=response.summary,
        edits=response.edits,
    )


def _validate_content(
    edit: FileEdit,
    *,
    original_content: str,
    preserve_frontmatter: bool,
    preserve_sections: bool,
    allowed_reference_numbers: set[int],
    failures: list[PatchValidationFailure],
    request: PatchRequest,
) -> None:
    new_content = edit.new_content
    stripped = new_content.strip().lower()
    if not new_content or stripped in _PLACEHOLDER_VALUES:
        failures.append(
            PatchValidationFailure(
                code="empty_or_placeholder_content",
                path=edit.path,
                message="Replacement content is empty or placeholder-like",
            )
        )

    if preserve_frontmatter and _frontmatter(original_content) != _frontmatter(new_content):
        failures.append(
            PatchValidationFailure(
                code="frontmatter_changed",
                path=edit.path,
                message="YAML frontmatter must be preserved exactly",
            )
        )

    if preserve_sections and _large_unrelated_removal(original_content, new_content):
        failures.append(
            PatchValidationFailure(
                code="large_unrelated_removal",
                path=edit.path,
                message="Replacement removed too much existing document structure",
            )
        )

    introduced_refs = _references(new_content) - _references(original_content)
    hallucinated_refs = sorted(introduced_refs - allowed_reference_numbers)
    if hallucinated_refs:
        failures.append(
            PatchValidationFailure(
                code="unsupported_reference",
                path=edit.path,
                message=(
                    "Replacement introduced PR/issue references not present in supplied evidence: "
                    + ", ".join(f"#{number}" for number in hallucinated_refs)
                ),
            )
        )

    if _marks_work_complete(original_content, new_content) and not _has_merged_pr_evidence(
        request,
        edit.path,
    ):
        failures.append(
            PatchValidationFailure(
                code="unsupported_completion",
                path=edit.path,
                message="Replacement marks work complete without merged PR evidence for this file",
            )
        )


def _frontmatter(content: str) -> str | None:
    if not content.startswith(("---\n", "---\r\n")):
        return None
    lines = content.splitlines(keepends=True)
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "".join(lines[: index + 1])
    return None


def _large_unrelated_removal(original_content: str, new_content: str) -> bool:
    if len(original_content) >= 200 and len(new_content) < len(original_content) * 0.25:
        return True
    original_headings = set(_HEADING_PATTERN.findall(original_content))
    if len(original_headings) < 3:
        return False
    new_headings = set(_HEADING_PATTERN.findall(new_content))
    removed = original_headings - new_headings
    return len(removed) > max(1, len(original_headings) // 3)


def _references(content: str) -> set[int]:
    return {int(match.group("number")) for match in _REFERENCE_PATTERN.finditer(content)}


def _allowed_reference_numbers(request: PatchRequest) -> set[int]:
    numbers = {pull_request.number for pull_request in request.recent_prs}
    numbers.update(issue.number for issue in request.recent_issues)
    for pull_request in request.recent_prs:
        numbers.update(issue.number for issue in pull_request.linked_issues)
    return numbers


def _marks_work_complete(original_content: str, new_content: str) -> bool:
    return len(_completion_markers(new_content)) > len(_completion_markers(original_content))


def _completion_markers(content: str) -> list[str]:
    return [match.group(0).lower() for match in _COMPLETION_MARKER_PATTERN.finditer(content)]


def _has_merged_pr_evidence(request: PatchRequest, path: str) -> bool:
    target = next(
        (target_file for target_file in request.target_files if target_file.path == path),
        None,
    )
    if target is None:
        return False
    merged_pr_numbers = {pull_request.number for pull_request in request.recent_prs}
    for signal in target.matched_signals:
        pr_number = signal.evidence.get("pr_number")
        if isinstance(pr_number, int) and pr_number in merged_pr_numbers:
            return True
    return False


def _rendering_flag(request: PatchRequest, key: str, *, default: bool) -> bool:
    rendering = request.config_summary.get("rendering")
    if not isinstance(rendering, dict):
        return default
    value = rendering.get(key)
    return value if isinstance(value, bool) else default


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _int_value(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch(path, pattern) for pattern in patterns)


def _is_markdown_path(path: str) -> bool:
    return Path(path).suffix.lower() in {".md", ".markdown"}
