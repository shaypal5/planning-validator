# planning-validator v1 — Project Overview

## Purpose

`planning-validator` is an open-source, GitHub-native automation for keeping repository planning and tracking documents aligned with recent repository reality.

The core use case is a maintainer with multiple open-source GitHub repositories who wants to:

- implement the logic once in a central repository,
- configure each target repository with minimal setup,
- run it on a schedule inside each target repository's GitHub Actions,
- detect when planning/tracking markdown files are stale relative to recent merged PRs and repository state,
- open or update a draft PR with proposed documentation updates.

v1 is intentionally optimized for this use case. It is not a generic project management platform.

---

## Product statement

`planning-validator` should make it cheap to keep repository planning docs honest.

It should do this by:

1. collecting recent merged PR and issue state from GitHub,
2. deterministically detecting stale documentation signals,
3. using an LLM only to rewrite bounded, whitelisted markdown files,
4. validating the proposed edits aggressively,
5. opening or updating a single draft PR with the resulting changes.

---

## Primary design principles

### 1. GitHub-native, repo-local execution
Each consuming repository runs the validator in its own GitHub Actions. The central repository ships the Python package and reusable workflow.

### 2. Deterministic detection first
The system must not ask the model whether docs are stale. It must detect stale signals deterministically and use the model only after there is evidence-backed justification to act.

### 3. Minimal per-repo configuration
A target repository should need only:
- a tiny caller workflow,
- one YAML config file,
- model API secrets.

### 4. Tight edit boundaries
The validator may only edit explicitly allowed markdown files. It must not modify source code, tests, workflows, packaging, or arbitrary repository files.

### 5. One branch, one PR
v1 should maintain at most one open automation PR per repository:
- one fixed branch,
- one draft PR,
- update existing instead of creating new duplicates.

### 6. Auditable behavior
All actions should be traceable to concrete evidence:
- recent merged PRs,
- recent issue transitions,
- explicit stale signals,
- explicit file-level patch targets.

### 7. Open-source, but narrow
The repository should be cleanly open source, but the product does not need to optimize for:
- GitLab support,
- users without GitHub,
- users without direct model API access,
- enterprise-scale multi-tenant control planes.

---

## v1 scope

v1 includes:

- Python package + CLI
- reusable GitHub Actions workflow
- YAML config schema
- deterministic stale detector
- bounded LLM patcher for markdown files
- patch validation layer
- branch/PR manager
- fixture repos and golden tests
- example target-repo setup

v1 supports:

- markdown planning/tracking files only,
- scheduled and manual runs,
- direct OpenAI or Anthropic API backends,
- recent merged PR lookback,
- recent issue/PR state reflection in docs,
- full-file markdown replacements after validation.

---

## Explicit non-goals for v1

v1 does **not** need to support:

- GitHub App auth,
- GitLab/Bitbucket support,
- arbitrary document types beyond markdown,
- multi-repo central orchestration service,
- semantic retrieval / embeddings / vector DB,
- automatic merge of the generated PR,
- issue creation instead of PR creation,
- new-file creation,
- arbitrary free-form prompt customization in target repos,
- broad project-management interpretation beyond repo docs,
- Copilot-cloud-agent delegation,
- unified diff patch application,
- editing source code or tests.

---

## User experience in a consuming repository

A consuming repository should set up:

1. `.github/planning-validator.yml`
2. `.github/workflows/planning-validator.yml`
3. `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` secret

Then, once per hour or by manual dispatch:

- the workflow runs,
- recent merged PRs are inspected,
- if docs appear fresh, the run exits cleanly,
- if docs appear stale, a draft PR is created or updated with suggested changes.

The maintainer reviews the PR like any other docs PR.

---

## Success criteria for v1

A v1 release is successful if:

1. It can be installed and run in at least one real target repository.
2. It can detect clearly stale markdown planning/tracking docs based on recent merged PRs.
3. It opens or updates exactly one draft PR with bounded markdown edits.
4. It does not touch forbidden files.
5. It is idempotent across repeated runs.
6. It has fixture-based tests for:
   - fresh/no-op case,
   - stale/create-PR case,
   - stale/update-existing-PR case,
   - invalid-model-output rejection.

---

## Product constraints

### Operational constraints
- Runs inside GitHub Actions of the target repository.
- Scheduled runs should avoid the top of the hour.
- Scheduled runs operate from the default branch.
- Public repositories may have scheduled workflows disabled after inactivity.

### Security constraints
- Use minimal `GITHUB_TOKEN` permissions.
- Use direct provider API keys from repository secrets.
- Treat model output as untrusted data.
- Do not allow the model to choose arbitrary files to edit.

### Maintenance constraints
- The implementation should be testable locally.
- Core logic should not depend on GitHub Actions runtime assumptions except at the workflow/PR edges.
- The model backend must be abstracted behind a small provider interface.

---

## Recommended technology choices for v1

Use these by default unless implementation realities force a change:

- Python 3.12
- `uv` for environment/dependency management
- `pydantic` v2 for schemas and validation
- `typer` for CLI
- `httpx` for API calls
- `PyYAML` or `ruamel.yaml` for config parsing
- `ruff` for linting/formatting
- `pytest` for tests
- `coverage` for coverage reporting
- `pre-commit` for local hooks

Avoid heavy frameworks unless they provide clear value.

---

## Repository naming and packaging expectations

The repository should be named `planning-validator`.

The Python package should also be `planning_validator`.

The reusable workflow should be versioned by git tags, with consumers referencing `@v1` once released.

---

## Core product rule

The single most important architectural rule in v1 is:

**The detector decides whether action is warranted. The patcher only rewrites a bounded set of evidence-backed markdown files.**

Every implementation decision should preserve that boundary.
