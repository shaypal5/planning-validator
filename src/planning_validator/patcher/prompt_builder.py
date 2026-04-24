"""Build bounded patch requests and model prompts."""

from __future__ import annotations

import json

from planning_validator.config import ResolvedConfig
from planning_validator.models import (
    DetectionResult,
    PatchRequest,
    PatchResponse,
    PatchTargetFile,
    RepoSnapshot,
)


class PatchRequestError(ValueError):
    """Raised when a patch request cannot be built safely."""


def build_patch_request(
    resolved_config: ResolvedConfig,
    snapshot: RepoSnapshot,
    detection_result: DetectionResult,
) -> PatchRequest:
    """Build the model-facing patch request from detector-selected target files."""

    target_paths = [
        target.path for target in detection_result.target_files if target.allowed_to_patch
    ]
    if not detection_result.is_stale or not target_paths:
        return PatchRequest(
            repo=snapshot.repo,
            head_sha=snapshot.head_sha,
            config_summary=_build_config_summary(resolved_config),
            recent_prs=snapshot.recent_prs,
            recent_issues=snapshot.recent_issues,
            target_files=[],
            global_instructions=_build_global_instructions(resolved_config),
        )

    documents_by_path = {
        document.path: document for document in [*snapshot.planning_files, *snapshot.tracking_files]
    }
    targets: list[PatchTargetFile] = []
    for path in target_paths:
        document = documents_by_path.get(path)
        if document is None:
            raise PatchRequestError(f"Detector target is missing from repository snapshot: {path}")
        targets.append(
            PatchTargetFile(
                path=path,
                original_content=document.content,
                matched_signals=[
                    signal for signal in detection_result.signals if signal.target_file == path
                ],
            )
        )

    request = PatchRequest(
        repo=snapshot.repo,
        head_sha=snapshot.head_sha,
        config_summary=_build_config_summary(resolved_config),
        recent_prs=snapshot.recent_prs,
        recent_issues=snapshot.recent_issues,
        target_files=targets,
        global_instructions=_build_global_instructions(resolved_config),
    )
    _validate_input_size_limits(resolved_config, request)
    return request


def build_patch_prompt(request: PatchRequest) -> str:
    """Render a compact JSON prompt payload for the patch model."""

    payload = {
        "task": "Update stale planning/tracking markdown by replacing only listed files.",
        "rules": request.global_instructions,
        "repo": request.repo,
        "head_sha": request.head_sha,
        "config": request.config_summary,
        "recent_prs": [
            pull_request.model_dump(mode="json", exclude_none=True)
            for pull_request in request.recent_prs
        ],
        "recent_issues": [
            issue.model_dump(mode="json", exclude_none=True) for issue in request.recent_issues
        ],
        "target_files": [
            {
                "path": target.path,
                "original_content": target.original_content,
                "matched_signals": [
                    signal.model_dump(mode="json") for signal in target.matched_signals
                ],
            }
            for target in request.target_files
        ],
        "output_schema": PatchResponse.model_json_schema(),
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _build_config_summary(resolved_config: ResolvedConfig) -> dict[str, object]:
    config = resolved_config.config
    return {
        "patchable_paths": list(resolved_config.patchable_paths),
        "max_files_to_update": config.staleness.max_files_to_update,
        "allowed_update_globs": list(config.patching.allowed_update_globs),
        "forbidden_update_globs": list(config.patching.forbidden_update_globs),
        "rendering": config.rendering.model_dump(mode="json"),
    }


def _build_global_instructions(resolved_config: ResolvedConfig) -> list[str]:
    rendering = resolved_config.config.rendering
    instructions = [
        "Return strict JSON only.",
        "Use operation='replace_file' for every edit.",
        "Edit only target_files paths. Do not create files.",
        "Do not edit source code, tests, workflows, or non-markdown files.",
        "Use only the supplied recent PR, issue, and stale-signal evidence.",
        "Do not invent PRs, issues, tasks, dates, or unsupported status changes.",
        "Prefer the smallest coherent markdown updates.",
    ]
    if rendering.preserve_frontmatter:
        instructions.append("Preserve YAML frontmatter byte-for-byte when present.")
    if rendering.preserve_unrecognized_sections:
        instructions.append("Preserve headings and sections unrelated to supplied evidence.")
    if rendering.prefer_checklists:
        instructions.append(
            "Prefer checklist state updates when the original document uses checklists."
        )
    if rendering.add_pr_links:
        instructions.append("Include PR links only when they are present in supplied evidence.")
    if rendering.add_issue_links:
        instructions.append("Include issue links only when they are present in supplied evidence.")
    return instructions


def _validate_input_size_limits(resolved_config: ResolvedConfig, request: PatchRequest) -> None:
    per_file_limit = resolved_config.config.patching.max_input_chars_per_file
    total_limit = resolved_config.config.patching.max_total_input_chars
    total_chars = 0
    for target in request.target_files:
        content_chars = len(target.original_content)
        if content_chars > per_file_limit:
            raise PatchRequestError(
                f"Patch target exceeds patching.max_input_chars_per_file: {target.path}"
            )
        total_chars += content_chars
    if total_chars > total_limit:
        raise PatchRequestError("Patch targets exceed patching.max_total_input_chars")
