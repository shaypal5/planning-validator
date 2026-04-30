"""Typed models shared across the planning-validator package."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator


class PatchingProvider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class PullRequestBodyMode(StrEnum):
    STRUCTURED = "structured"
    SHORT = "short"


class PullRequestManagerAction(StrEnum):
    DISABLED = "disabled"
    NO_CHANGES = "no_changes"
    CREATED = "created"
    UPDATED = "updated"


class RunCommandStatus(StrEnum):
    CLEAN = "clean"
    NO_CHANGES = "no_changes"
    PR_CREATED = "pr_created"
    PR_UPDATED = "pr_updated"
    PR_DISABLED = "pr_disabled"
    FAILED = "failed"


class RunPatchStatus(StrEnum):
    SKIPPED = "skipped"
    VALIDATED = "validated"
    FAILED = "failed"


class GitHubIssueState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class StaleSignalType(StrEnum):
    MISSING_PR_REFLECTION = "missing_pr_reflection"
    STATUS_OUTDATED = "status_outdated"
    ISSUE_STATE_OUTDATED = "issue_state_outdated"
    TODO_NOT_MARKED_DONE = "todo_not_marked_done"
    ROADMAP_STAGE_INCORRECT = "roadmap_stage_incorrect"
    RECENT_WORK_MISSING_FROM_CHANGELOG = "recent_work_missing_from_changelog"
    FILE_MENTIONS_CLOSED_PR_AS_OPEN = "file_mentions_closed_pr_as_open"


class LookbackConfig(BaseModel):
    merged_pr_hours: int = 30
    commit_hours: int = 30

    model_config = ConfigDict(extra="forbid")

    @field_validator("merged_pr_hours", "commit_hours")
    @classmethod
    def validate_positive_hours(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be a positive integer")
        return value


class StalenessConfig(BaseModel):
    require_pr_reflection: bool = True
    require_issue_reflection: bool = False
    min_signal_score: float = 0.55
    max_files_to_update: int = 5
    ignore_pr_labels: list[str] = Field(default_factory=list)
    ignore_paths: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("min_signal_score")
    @classmethod
    def validate_score_range(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("must be between 0 and 1")
        return value

    @field_validator("max_files_to_update")
    @classmethod
    def validate_max_files(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be greater than or equal to 1")
        return value


class PatchingConfig(BaseModel):
    provider: PatchingProvider
    model: str = Field(min_length=1)
    temperature: float = 0.1
    max_input_chars_per_file: int = 50_000
    max_total_input_chars: int = 180_000
    allowed_update_globs: list[str] = Field(min_length=1)
    forbidden_update_globs: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "max_input_chars_per_file",
        "max_total_input_chars",
    )
    @classmethod
    def validate_positive_ints(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be a positive integer")
        return value

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, value: float) -> float:
        if not 0 <= value <= 2:
            raise ValueError("must be between 0 and 2")
        return value

    @field_validator("allowed_update_globs", "forbidden_update_globs", mode="before")
    @classmethod
    def validate_glob_strings(cls, globs: object) -> object:
        if not isinstance(globs, list) or any(
            not isinstance(glob, str) or not glob.strip() for glob in globs
        ):
            raise ValueError("all glob entries must be non-empty strings")
        return globs

    @model_validator(mode="after")
    def validate_limits(self) -> PatchingConfig:
        if self.max_total_input_chars < self.max_input_chars_per_file:
            raise ValueError(
                "max_total_input_chars must be greater than or equal to max_input_chars_per_file",
            )
        return self


class PullRequestConfig(BaseModel):
    enabled: bool = True
    branch: str = "automation/planning-validator"
    base: str = "default"
    draft: bool = True
    title_template: str = "docs: refresh planning/tracking files"
    body_mode: PullRequestBodyMode = PullRequestBodyMode.STRUCTURED
    labels: list[str] = Field(default_factory=list)
    reviewers: list[str] = Field(default_factory=list)
    update_existing: bool = True
    close_when_clean: bool = False

    model_config = ConfigDict(extra="forbid")


class RenderingConfig(BaseModel):
    preserve_frontmatter: bool = True
    preserve_unrecognized_sections: bool = True
    prefer_checklists: bool = True
    add_pr_links: bool = True
    add_issue_links: bool = True

    model_config = ConfigDict(extra="forbid")


class GitHubConfig(BaseModel):
    include_recent_closed_issues: bool = True
    include_recent_commits: bool = False
    include_pr_file_lists: bool = True
    include_linked_issues: bool = True

    model_config = ConfigDict(extra="forbid")


class RecentIssue(BaseModel):
    number: int
    title: str
    state: GitHubIssueState
    closed_at: datetime | None = None
    url: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("closed_at")
    @classmethod
    def validate_closed_at_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include timezone info")
        return value


class RecentPullRequest(BaseModel):
    number: int
    title: str
    body: str | None = None
    author: str | None = None
    merged_at: datetime
    labels: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    linked_issues: list[RecentIssue] = Field(default_factory=list)
    url: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("merged_at")
    @classmethod
    def validate_merged_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include timezone info")
        return value


class LocalDocument(BaseModel):
    path: str = Field(min_length=1)
    content: str
    sha: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_content(cls, *, path: str, content: str) -> LocalDocument:
        return cls(path=path, content=content, sha=sha256(content.encode("utf-8")).hexdigest())


class LocalDocumentInventory(BaseModel):
    planning_documents: list[LocalDocument] = Field(default_factory=list)
    tracking_documents: list[LocalDocument] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @computed_field
    @property
    def all_documents(self) -> list[LocalDocument]:
        documents_by_path: dict[str, LocalDocument] = {}
        for document in [*self.planning_documents, *self.tracking_documents]:
            documents_by_path.setdefault(document.path, document)
        return list(documents_by_path.values())

    @computed_field
    @property
    def planning_paths(self) -> list[str]:
        return [document.path for document in self.planning_documents]

    @computed_field
    @property
    def tracking_paths(self) -> list[str]:
        return [document.path for document in self.tracking_documents]


class RepoSnapshot(BaseModel):
    repo: str = Field(min_length=1)
    default_branch: str = Field(min_length=1)
    head_sha: str = Field(min_length=1)
    planning_files: list[LocalDocument] = Field(default_factory=list)
    tracking_files: list[LocalDocument] = Field(default_factory=list)
    recent_prs: list[RecentPullRequest] = Field(default_factory=list)
    recent_issues: list[RecentIssue] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class StaleSignal(BaseModel):
    signal_type: StaleSignalType
    target_file: str = Field(min_length=1)
    score: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)
    evidence: dict[str, object] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class TargetFileDecision(BaseModel):
    path: str = Field(min_length=1)
    aggregate_score: float = Field(ge=0, le=1)
    matched_signals: list[StaleSignal] = Field(default_factory=list)
    allowed_to_patch: bool

    model_config = ConfigDict(extra="forbid")


class DetectionResult(BaseModel):
    is_stale: bool
    summary: str = Field(min_length=1)
    signals: list[StaleSignal] = Field(default_factory=list)
    target_files: list[TargetFileDecision] = Field(default_factory=list)
    ignored_prs: list[int] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class PatchTargetFile(BaseModel):
    path: str = Field(min_length=1)
    original_content: str
    matched_signals: list[StaleSignal] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class PatchRequest(BaseModel):
    repo: str = Field(min_length=1)
    head_sha: str = Field(min_length=1)
    config_summary: dict[str, object] = Field(default_factory=dict)
    recent_prs: list[RecentPullRequest] = Field(default_factory=list)
    recent_issues: list[RecentIssue] = Field(default_factory=list)
    target_files: list[PatchTargetFile] = Field(default_factory=list)
    global_instructions: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class FileEdit(BaseModel):
    path: str = Field(min_length=1)
    operation: Literal["replace_file"]
    new_content: str
    rationale: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class PatchResponse(BaseModel):
    summary: str = Field(min_length=1)
    edits: list[FileEdit] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_unique_edit_paths(self) -> PatchResponse:
        paths = [edit.path for edit in self.edits]
        duplicate_paths = sorted({path for path in paths if paths.count(path) > 1})
        if duplicate_paths:
            joined = ", ".join(duplicate_paths)
            raise ValueError(f"duplicate edits for path(s): {joined}")
        return self


class PatchValidationFailure(BaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    path: str | None = None

    model_config = ConfigDict(extra="forbid")


class ValidatedPatch(BaseModel):
    repo: str = Field(min_length=1)
    head_sha: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    edits: list[FileEdit] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class AutomationPullRequest(BaseModel):
    number: int
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    head_branch: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    draft: bool

    model_config = ConfigDict(extra="forbid")


class PullRequestManagerResult(BaseModel):
    action: PullRequestManagerAction
    branch: str = Field(min_length=1)
    pull_request: AutomationPullRequest | None = None
    committed: bool = False
    pushed: bool = False
    message: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


class RunCommandSummary(BaseModel):
    ok: bool
    status: RunCommandStatus
    config_path: str
    repo: str | None = None
    default_branch: str | None = None
    head_sha: str | None = None
    recent_pr_count: int = 0
    stale_signal_count: int = 0
    target_files: list[str] = Field(default_factory=list)
    patch_status: RunPatchStatus = RunPatchStatus.SKIPPED
    edited_files: list[str] = Field(default_factory=list)
    pr_action: PullRequestManagerAction | None = None
    pr_url: str | None = None
    message: str = Field(min_length=1)
    error: str | None = None

    model_config = ConfigDict(extra="forbid")


class ValidatorConfig(BaseModel):
    schema_version: str
    planning_files: list[str] = Field(min_length=1)
    tracking_files: list[str] = Field(default_factory=list)
    lookback: LookbackConfig = Field(default_factory=LookbackConfig)
    staleness: StalenessConfig = Field(default_factory=StalenessConfig)
    patching: PatchingConfig
    pull_request: PullRequestConfig = Field(default_factory=PullRequestConfig)
    rendering: RenderingConfig = Field(default_factory=RenderingConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)

    model_config = ConfigDict(extra="forbid")

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != "v1alpha1":
            raise ValueError("schema_version must be 'v1alpha1'")
        return value

    @field_validator("planning_files", "tracking_files", mode="before")
    @classmethod
    def validate_glob_lists(cls, globs: object) -> object:
        if not isinstance(globs, list) or any(
            not isinstance(glob, str) or not glob.strip() for glob in globs
        ):
            raise ValueError("all glob entries must be non-empty strings")
        return globs
