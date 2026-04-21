# planning-validator v1 — Config Schema

## Purpose

Each target repository configures `planning-validator` through one YAML file, typically:

```text
.github/planning-validator.yml
```

The v1 config is intentionally narrow:
- discover candidate planning/tracking files,
- define staleness policy knobs,
- define patch safety boundaries,
- define PR behavior.

It should not become a general prompt-programming surface.

---

## Canonical minimal example

```yaml
schema_version: v1alpha1

planning_files:
  - README.md
  - docs/roadmap.md
  - docs/plans/**/*.md

tracking_files:
  - docs/tasks/**/*.md
  - docs/status/**/*.md

patching:
  provider: openai
  model: gpt-5.4-thinking
  allowed_update_globs:
    - README.md
    - docs/**/*.md
```

This is the smallest useful config.

---

## Recommended full example

```yaml
schema_version: v1alpha1

planning_files:
  - README.md
  - docs/roadmap.md
  - docs/plans/**/*.md

tracking_files:
  - docs/tasks/**/*.md
  - docs/status/**/*.md

lookback:
  merged_pr_hours: 30
  commit_hours: 30

staleness:
  require_pr_reflection: true
  require_issue_reflection: true
  min_signal_score: 0.55
  max_files_to_update: 5
  ignore_pr_labels:
    - skip-planning-validator
  ignore_paths:
    - vendor/**
    - data/**
    - snapshots/**
    - .github/workflows/**

patching:
  provider: openai
  model: gpt-5.4-thinking
  temperature: 0.1
  max_input_chars_per_file: 50000
  max_total_input_chars: 180000
  allowed_update_globs:
    - README.md
    - docs/**/*.md
  forbidden_update_globs:
    - src/**
    - tests/**
    - pyproject.toml
    - .github/workflows/**

pull_request:
  enabled: true
  branch: automation/planning-validator
  base: default
  draft: true
  title_template: "docs: refresh planning/tracking files"
  body_mode: structured
  labels:
    - documentation
    - automation
  reviewers: []
  update_existing: true
  close_when_clean: false

rendering:
  preserve_frontmatter: true
  preserve_unrecognized_sections: true
  prefer_checklists: true
  add_pr_links: true
  add_issue_links: true

github:
  include_recent_closed_issues: true
  include_recent_commits: false
  include_pr_file_lists: true
  include_linked_issues: true
```

---

## Schema

### `schema_version`
Required.

```yaml
schema_version: v1alpha1
```

Rules:
- must be present,
- must equal `v1alpha1` in v1,
- reject unknown major schema versions.

---

### `planning_files`
Required, non-empty list of glob strings.

These are the files most likely to need updates when recently delivered work changes project state.

Examples:
- `README.md`
- `docs/roadmap.md`
- `docs/plans/**/*.md`

Rules:
- must expand to one or more files in normal operation,
- must not include binary files,
- should generally be markdown files only in v1.

---

### `tracking_files`
Optional list of glob strings.

These are additional docs that reflect execution state:
- task trackers,
- status files,
- milestone docs,
- changelog-like markdown files.

Default:
```yaml
tracking_files: []
```

Rules:
- same file-type constraints as `planning_files`,
- may overlap with `planning_files`,
- duplicates should be normalized internally.

---

### `lookback`
Optional object defining how far back the validator should inspect repository activity.

#### `lookback.merged_pr_hours`
Default: `30`

How far back to look for merged PRs.

#### `lookback.commit_hours`
Default: `30`

Reserved for optional future commit-level signals. v1 may parse and store it even if commit-based logic is minimal.

Example:
```yaml
lookback:
  merged_pr_hours: 30
  commit_hours: 30
```

Rules:
- integers only,
- positive values,
- recommended range for v1: 12–72 hours.

---

### `staleness`
Optional object controlling detector behavior.

#### `staleness.require_pr_reflection`
Default: `true`

If true, recent merged PRs should influence staleness detection.

#### `staleness.require_issue_reflection`
Default: `false`

If true, closed/changed issue state can contribute to staleness signals.

#### `staleness.min_signal_score`
Default: `0.55`

Files are patch-eligible only if their aggregate stale score meets or exceeds this threshold.

#### `staleness.max_files_to_update`
Default: `5`

Hard cap on number of files the system may update in one run.

#### `staleness.ignore_pr_labels`
Default: `[]`

PRs with any of these labels are excluded from stale detection.

Example:
```yaml
ignore_pr_labels:
  - skip-planning-validator
```

#### `staleness.ignore_paths`
Default: `[]`

Paths matching these globs are ignored when interpreting recent PR file changes.

Example:
```yaml
ignore_paths:
  - vendor/**
  - data/**
```

Rules:
- `min_signal_score` should be between 0 and 1,
- `max_files_to_update` must be >= 1,
- ignore labels and ignore paths are advisory filters, not security boundaries.

---

### `patching`
Required object.

This section defines model backend choice and edit safety constraints.

#### `patching.provider`
Required. Enum:
- `openai`
- `anthropic`

#### `patching.model`
Required string.

Examples:
- `gpt-5.4-thinking`
- `claude-sonnet-4-5`

#### `patching.temperature`
Default: `0.1`

Low temperature is recommended for stable, minimal edits.

#### `patching.max_input_chars_per_file`
Default: `50000`

Soft limit for how much of a single file is included in prompt context.

#### `patching.max_total_input_chars`
Default: `180000`

Hard cap for the total textual prompt payload.

#### `patching.allowed_update_globs`
Required non-empty list of globs.

The patcher may only edit files matching these globs.

#### `patching.forbidden_update_globs`
Optional list of globs, default `[]`.

Any file matching these globs must not be edited even if it also matches allowed globs.

Example:
```yaml
patching:
  provider: openai
  model: gpt-5.4-thinking
  allowed_update_globs:
    - README.md
    - docs/**/*.md
  forbidden_update_globs:
    - src/**
    - tests/**
```

Rules:
- `allowed_update_globs` is the primary edit allowlist,
- forbidden globs override allowed globs,
- in v1, allowed files should almost always be markdown,
- security validation must not rely solely on this config; runtime validators must enforce it too.

---

### `pull_request`
Optional object controlling PR behavior.

#### `pull_request.enabled`
Default: `true`

If false, the system may still detect and optionally patch locally, but should not open/update PRs in normal `run`.

#### `pull_request.branch`
Default: `automation/planning-validator`

Fixed branch name for the automation.

#### `pull_request.base`
Default: `default`

Base branch target. `default` means the repository's default branch.

#### `pull_request.draft`
Default: `true`

v1 should create draft PRs by default.

#### `pull_request.title_template`
Default:
```yaml
title_template: "docs: refresh planning/tracking files"
```

Keep this simple in v1.

#### `pull_request.body_mode`
Enum:
- `structured`
- `short`

Default: `structured`

#### `pull_request.labels`
Default: `[]`

Optional labels to apply to the automation PR.

#### `pull_request.reviewers`
Default: `[]`

Optional reviewers to request. This may be a no-op in some repos depending on permissions.

#### `pull_request.update_existing`
Default: `true`

If true, reuse/update the existing automation PR rather than creating duplicates.

#### `pull_request.close_when_clean`
Default: `false`

Reserved for future behavior. v1 does not need to actively close PRs when docs become clean again, but the field may exist.

---

### `rendering`
Optional object controlling content-preservation behavior.

#### `rendering.preserve_frontmatter`
Default: `true`

If the file begins with YAML frontmatter, it must be preserved verbatim unless there is strong evidence to change it, which v1 should not attempt.

#### `rendering.preserve_unrecognized_sections`
Default: `true`

Sections unrelated to recent evidence should be preserved.

#### `rendering.prefer_checklists`
Default: `true`

When updating task-like docs, prefer preserving checklist structure.

#### `rendering.add_pr_links`
Default: `true`

The patcher may insert PR references where appropriate.

#### `rendering.add_issue_links`
Default: `true`

The patcher may insert issue references where appropriate.

---

### `github`
Optional object controlling data collection.

#### `github.include_recent_closed_issues`
Default: `true`

If true, include recently closed issues in snapshot data when available.

#### `github.include_recent_commits`
Default: `false`

Reserved for future commit-level signals. Keep off by default in v1.

#### `github.include_pr_file_lists`
Default: `true`

If true, include changed-file lists for recent PRs in detector inputs.

#### `github.include_linked_issues`
Default: `true`

If true, include linked issue references discovered from PRs.

---

## Validation rules

The config parser must validate:

1. `schema_version` is supported.
2. `planning_files` is non-empty.
3. `patching.provider` and `patching.model` are present.
4. `patching.allowed_update_globs` is non-empty.
5. numeric fields are in valid ranges.
6. glob fields are strings.
7. allowed/forbidden glob interaction is sane.
8. no forbidden update glob broadens into markdown planning files accidentally without warning.
9. expanded candidate files are text files.

The config validator should fail early with clear error messages.

---

## Semantic rules

These are not raw YAML-schema rules; they are policy-level constraints:

### Rule 1
At least one file discovered from `planning_files` or `tracking_files` must also match `patching.allowed_update_globs`.

Otherwise the system cannot act meaningfully.

### Rule 2
Files under forbidden globs must never be returned as patch targets.

### Rule 3
In v1, if non-markdown files are discovered in planning/tracking globs, they should either:
- be rejected, or
- be ignored with a warning, depending on strictness mode.

Prefer rejection during early implementation.

### Rule 4
Configs should not allow unbounded patch scope such as:
```yaml
allowed_update_globs:
  - "**/*"
```

This should be rejected or at least warned strongly against in v1.

---

## Suggested defaults

If fields are omitted, use:

```yaml
lookback:
  merged_pr_hours: 30
  commit_hours: 30

staleness:
  require_pr_reflection: true
  require_issue_reflection: false
  min_signal_score: 0.55
  max_files_to_update: 5
  ignore_pr_labels: []
  ignore_paths: []

patching:
  temperature: 0.1
  max_input_chars_per_file: 50000
  max_total_input_chars: 180000
  forbidden_update_globs: []

pull_request:
  enabled: true
  branch: automation/planning-validator
  base: default
  draft: true
  title_template: "docs: refresh planning/tracking files"
  body_mode: structured
  labels: []
  reviewers: []
  update_existing: true
  close_when_clean: false

rendering:
  preserve_frontmatter: true
  preserve_unrecognized_sections: true
  prefer_checklists: true
  add_pr_links: true
  add_issue_links: true

github:
  include_recent_closed_issues: true
  include_recent_commits: false
  include_pr_file_lists: true
  include_linked_issues: true
```

---

## Configuration philosophy

The config should answer:

- which docs matter,
- what evidence window matters,
- what files may be edited,
- how PR creation should behave.

It should **not** answer:

- exact prompt wording,
- custom agent personalities,
- arbitrary file transformation policies,
- per-section generation policies.

Those belong in the codebase, not in repo-level configuration.

---

## Example profiles

### Simple repo
```yaml
schema_version: v1alpha1

planning_files:
  - README.md
  - docs/roadmap.md

patching:
  provider: openai
  model: gpt-5.4-thinking
  allowed_update_globs:
    - README.md
    - docs/**/*.md
```

### Docs-heavy repo
```yaml
schema_version: v1alpha1

planning_files:
  - docs/roadmap.md
  - docs/plans/**/*.md

tracking_files:
  - docs/tasks/**/*.md
  - docs/status/**/*.md
  - CHANGELOG.md

staleness:
  require_issue_reflection: true
  max_files_to_update: 3

patching:
  provider: anthropic
  model: claude-sonnet-4-5
  allowed_update_globs:
    - docs/**/*.md
    - CHANGELOG.md
  forbidden_update_globs:
    - docs/archive/**
```

---

## CLI expectations around config

The CLI should expose:

```bash
planning-validator validate-config --config .github/planning-validator.yml
```

This command should:
- parse the file,
- validate syntax and semantics,
- optionally print discovered files,
- fail with actionable diagnostics.
