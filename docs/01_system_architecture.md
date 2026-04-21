# planning-validator v1 — System Architecture

## Overview

`planning-validator` is composed of three major layers:

1. **Detection layer** — deterministic, evidence-first stale detection
2. **Patching layer** — LLM-based markdown rewrite within strict bounds
3. **Actuation layer** — branch and pull-request management

The central repository ships:
- a Python package/CLI,
- a reusable GitHub Actions workflow,
- prompts/templates,
- example configs,
- tests and fixtures.

Each target repository supplies:
- a YAML config file,
- a tiny caller workflow,
- model API secrets.

---

## Repository architecture

```text
planning-validator/
├── .github/
│   └── workflows/
│       ├── reusable-planning-validator.yml
│       ├── ci.yml
│       └── release.yml
├── docs/
│   ├── 00_project_overview.md
│   ├── 01_system_architecture.md
│   ├── 02_config_schema.md
│   ├── 03_detector_contract.md
│   ├── 04_patcher_pr_contract.md
│   └── 05_implementation_plan.md
├── examples/
│   ├── target-repo/
│   │   ├── .github/
│   │   │   ├── planning-validator.yml
│   │   │   └── workflows/
│   │   │       └── planning-validator.yml
│   │   └── docs/
│   │       ├── roadmap.md
│   │       └── tasks.md
│   └── configs/
│       ├── simple.yml
│       └── monorepo.yml
├── prompts/
│   ├── system.md
│   ├── stale-to-patch.md
│   ├── repair-invalid-output.md
│   └── summarize-pr.md
├── src/
│   └── planning_validator/
│       ├── __init__.py
│       ├── cli.py
│       ├── logging.py
│       ├── config.py
│       ├── models.py
│       ├── file_io.py
│       ├── gitignore_filter.py
│       ├── github_api.py
│       ├── repo_snapshot.py
│       ├── planner.py
│       ├── detector/
│       │   ├── __init__.py
│       │   ├── recent_prs.py
│       │   ├── issue_links.py
│       │   ├── doc_inventory.py
│       │   ├── signals.py
│       │   ├── scoring.py
│       │   └── detector.py
│       ├── patcher/
│       │   ├── __init__.py
│       │   ├── prompt_builder.py
│       │   ├── llm_client.py
│       │   ├── response_parser.py
│       │   ├── file_patch_validator.py
│       │   └── patcher.py
│       ├── pr/
│       │   ├── __init__.py
│       │   ├── branch_manager.py
│       │   ├── pr_manager.py
│       │   └── pr_body.py
│       └── evals/
│           ├── golden_cases.py
│           └── fixtures.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── pyproject.toml
├── README.md
└── LICENSE
```

---

## Target repository architecture

Each consuming repository should require only:

```text
target-repo/
├── .github/
│   ├── planning-validator.yml
│   └── workflows/
│       └── planning-validator.yml
```

Optional example planning docs for the example target repo:

```text
target-repo/
└── docs/
    ├── roadmap.md
    ├── tasks.md
    └── status.md
```

---

## High-level runtime flow

The end-to-end runtime is:

1. GitHub Actions scheduled or manual trigger starts in target repo.
2. Caller workflow invokes the central reusable workflow.
3. Reusable workflow:
   - checks out the target repository,
   - installs `planning-validator`,
   - runs the CLI with the target repo config.
4. CLI loads config and builds a repository snapshot.
5. Deterministic detector inspects recent PR/issue/repo evidence.
6. If no stale evidence exceeds threshold, exit with success and structured summary.
7. If stale evidence exists:
   - gather candidate file contents,
   - build a bounded patch request,
   - invoke model backend,
   - parse and validate output,
   - write accepted file replacements.
8. Branch/PR manager creates or updates one draft PR.
9. Workflow uploads summary artifact and exits.

---

## Module responsibilities

### `config.py`
- Parse YAML config.
- Validate schema and defaults.
- Expand and validate globs.
- Enforce semantic config constraints.

### `github_api.py`
- Fetch recent merged PRs.
- Fetch linked issues / recent issue transitions if enabled.
- Fetch PR file lists.
- Discover existing automation PR branch / PR.

### `repo_snapshot.py`
- Read configured planning/tracking files from repo.
- Build normalized in-memory snapshot for downstream logic.

### `detector/*`
- Compute stale signals from snapshot + recent PR/issue evidence.
- Rank target files.
- Produce deterministic `DetectionResult`.

### `patcher/*`
- Build model input from `DetectionResult` and file contents.
- Call model provider.
- Parse structured JSON response.
- Validate proposed edits against strict policy.

### `pr/*`
- Materialize accepted edits to git working tree.
- Create/update fixed branch.
- Create/update single draft PR.
- Generate structured PR body.

### `cli.py`
- Expose user-facing commands.
- Compose the end-to-end orchestration.

---

## Architectural boundaries

### Boundary 1: detector vs patcher
The detector:
- decides whether docs are stale,
- identifies evidence,
- determines which files are eligible targets.

The patcher:
- rewrites only the files selected by the detector,
- must not introduce unsupported claims,
- must not expand scope.

This is the key boundary in the entire system.

### Boundary 2: patcher vs PR manager
The patcher outputs validated file replacements.
The PR manager does not reinterpret content. It only:
- writes files,
- commits changes,
- manages branch and PR state.

### Boundary 3: config vs prompts
Target repos may configure file lists and policy knobs, but they do **not** provide arbitrary prompt text in v1.

---

## Data flow

```text
.github/planning-validator.yml
    ↓
ValidatorConfig
    ↓
RepoSnapshot
    ↓
DetectionResult
    ↓ if stale
PatchRequest
    ↓
PatchResponse
    ↓
ValidatedEdits
    ↓
Git branch + draft PR
```

The output of each stage must be explicit, typed, and testable.

---

## Workflow architecture

### Caller workflow in target repository

The caller workflow should:
- trigger on `schedule` and `workflow_dispatch`,
- set `concurrency` to one active run,
- set minimal `permissions`,
- call the reusable workflow with config path and secrets.

Example:

```yaml
name: planning-validator

on:
  schedule:
    - cron: "17 * * * *"
  workflow_dispatch:

concurrency:
  group: planning-validator
  cancel-in-progress: true

permissions:
  contents: write
  pull-requests: write

jobs:
  run:
    uses: your-org/planning-validator/.github/workflows/reusable-planning-validator.yml@v1
    with:
      config_path: .github/planning-validator.yml
    secrets:
      openai_api_key: ${{ secrets.OPENAI_API_KEY }}
      anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

### Reusable workflow in central repo

The reusable workflow should:
- accept `config_path` and optional `python_version`,
- accept provider secrets,
- install the package,
- run `planning-validator run --config <path>`,
- expose logs/artifacts,
- fail only when actual execution or validation fails.

---

## Repository snapshot model

The runtime snapshot should include:

- repository name
- default branch name
- head SHA
- planning files and content
- tracking files and content
- recent merged PRs
- optional recent closed issues
- optional recent commits, if enabled later

The snapshot should be the detector's full world state in v1.

---

## Why full-file replacement instead of diff patching in v1

v1 should use full-file replacements for markdown files rather than line-oriented diff patches because:

- markdown planning docs are often section-oriented rather than line-stable,
- validation is simpler when the entire final file is known,
- it is easier to enforce invariants such as preserved frontmatter and preserved unrelated sections,
- JSON response parsing is simpler than diff patch application.

Unified diffs can be reconsidered later, but they are not necessary for v1.

---

## Safety architecture

### File scope safety
Only files returned by the detector and allowed by config may be edited.

### Content safety
The model must only use evidence supplied in the patch request.
Any ungrounded claims must be rejected during validation.

### Operational safety
At most one PR branch may be active for the automation in a target repository.

### Failure safety
If model output is invalid, the run should fail safely without committing partial edits.

---

## Idempotency model

Repeated runs should be safe.

If there is no new relevant evidence:
- no new edits should be proposed,
- no duplicate PR should be created.

If the fixed automation branch already has an open PR:
- the same PR should be updated in place.

If docs are already aligned:
- the run should exit as a no-op.

---

## Recommended internal coding standards

The implementation should prefer:

- clear Pydantic models at all boundaries,
- pure functions for signal computation where possible,
- explicit logging and JSON summaries,
- narrow provider interfaces,
- unit tests for core logic and integration tests for end-to-end behavior.

Avoid opaque shell-heavy logic. Keep the business logic in Python.

---

## Example control flow inside `planning-validator run`

1. Parse config
2. Build repo snapshot
3. Run detector
4. If not stale:
   - print summary
   - exit 0
5. Build patch request
6. Call provider backend
7. Parse response
8. Validate edits
9. Materialize file changes
10. Commit/update branch
11. Create/update draft PR
12. Emit structured summary

---

## Extension points intentionally reserved for later

These are useful future seams, but do not need broad implementation in v1:

- additional provider backends,
- diff-based edit application,
- richer issue/commit inference,
- changelog-specific handling,
- automatic PR closure when repository becomes clean,
- more sophisticated markdown-aware section targeting.

The v1 architecture should keep room for those extensions without implementing them yet.
