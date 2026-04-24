"""Patcher orchestration and validated file materialization."""

from __future__ import annotations

from pathlib import Path

from planning_validator.config import ResolvedConfig
from planning_validator.models import DetectionResult, PatchResponse, RepoSnapshot, ValidatedPatch
from planning_validator.patcher.file_patch_validator import validate_patch_response
from planning_validator.patcher.llm_client import LLMClient
from planning_validator.patcher.prompt_builder import build_patch_request


class PatcherError(RuntimeError):
    """Raised when patcher orchestration fails."""


def run_patcher(
    resolved_config: ResolvedConfig,
    snapshot: RepoSnapshot,
    detection_result: DetectionResult,
    *,
    llm_client: LLMClient,
) -> ValidatedPatch:
    """Generate and validate a bounded patch for detector-selected files."""

    request = build_patch_request(resolved_config, snapshot, detection_result)
    if not request.target_files:
        return ValidatedPatch(
            repo=snapshot.repo,
            head_sha=snapshot.head_sha,
            summary="No patchable stale documentation targets were selected.",
            edits=[],
        )
    response = llm_client.generate_patch(request)
    return validate_patch_response(request, response)


def validate_existing_response(
    resolved_config: ResolvedConfig,
    snapshot: RepoSnapshot,
    detection_result: DetectionResult,
    response: PatchResponse,
) -> ValidatedPatch:
    """Validate an already-generated response, useful for tests and future adapters."""

    request = build_patch_request(resolved_config, snapshot, detection_result)
    return validate_patch_response(request, response)


def apply_validated_patch(repo_root: Path, patch: ValidatedPatch) -> None:
    """Apply validated full-file markdown replacements to the working tree."""

    root = repo_root.resolve()
    for edit in patch.edits:
        destination = (root / edit.path).resolve()
        if not destination.is_relative_to(root):
            raise PatcherError(f"Patch edit escapes repository root: {edit.path}")
        destination.write_text(edit.new_content, encoding="utf-8")
