# planning-validator

`planning-validator` is a GitHub-native automation for keeping repository planning and tracking
markdown files aligned with recent merged pull requests. It runs in a target repository, detects
stale planning docs from GitHub evidence, asks a configured patch provider for bounded markdown
replacements, and opens or updates one fixed-branch PR for human review.

The product source of truth lives in [`docs/`](./docs/README_bundle.md). The v1 implementation is
intentionally narrow: deterministic detection, bounded markdown patching, and GitHub PR handoff.

## Install

For local development in this repository:

```bash
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest
```

For a target repository workflow, call the reusable workflow from this repository. The workflow
installs the package from the same git ref as the reusable workflow file.

## Minimal Config

Create `.github/planning-validator.yml` in the target repository:

```yaml
schema_version: v1alpha1

planning_files:
  - README.md
  - docs/roadmap.md

tracking_files:
  - docs/tasks.md

patching:
  provider: openai
  model: gpt-5.4-thinking
  allowed_update_globs:
    - README.md
    - docs/**/*.md
```

Validate it locally from the target repository root:

```bash
planning-validator validate-config --config .github/planning-validator.yml
```

See [`examples/target-repo`](./examples/target-repo) for a complete small target repository.

## Caller Workflow

Create `.github/workflows/planning-validator.yml` in the target repository:

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
  issues: write
  pull-requests: write

jobs:
  run:
    uses: shaypal5/planning-validator/.github/workflows/reusable-planning-validator.yml@main
    with:
      config_path: .github/planning-validator.yml
    secrets:
      openai_api_key: ${{ secrets.OPENAI_API_KEY }}
```

Required permissions:

- `contents: write` to update the fixed automation branch.
- `pull-requests: write` to create or update the generated PR.
- `issues: write` to apply issue-backed PR labels.

Required secret for the current supported patch provider:

- `OPENAI_API_KEY`, passed to the reusable workflow as `openai_api_key`.

The workflow uses the built-in `GITHUB_TOKEN` for GitHub evidence and PR operations.

## CLI

Config validation:

```bash
planning-validator validate-config --config .github/planning-validator.yml
```

Detection artifact:

```bash
planning-validator detect \
  --config .github/planning-validator.yml \
  --json-out .planning-validator/detection.json
```

Patch artifact, without writing files:

```bash
planning-validator patch \
  --config .github/planning-validator.yml \
  --detection-json .planning-validator/detection.json \
  --json-out .planning-validator/patch.json
```

End-to-end CI runtime:

```bash
planning-validator run --config .github/planning-validator.yml
```

`run` writes `.planning-validator/run-summary.json`, skips model and PR work when docs are fresh,
fails before PR management when model output violates patch safety, and otherwise creates or updates
the configured fixed-branch PR.

## Runtime Behavior

- Recent merged PRs are collected from GitHub and normalized into internal evidence models.
- The detector is deterministic and evidence-based; it does not call a model.
- Only detector-selected files that also match `patching.allowed_update_globs` can be patched.
- Patch responses are validated as full-file markdown replacements before any PR work starts.
- Runtime PR behavior uses one fixed branch, `automation/planning-validator` by default.
- Repeated stale runs update the same PR when `pull_request.update_existing` is true.
- Clean runs exit without creating duplicate PRs.

## Safety Boundaries

`planning-validator` v1 does not:

- use an LLM in detection logic,
- edit non-markdown planning files,
- edit files outside detector-selected and allowlisted paths,
- create per-run automation branches,
- merge generated PRs automatically,
- implement GitHub App architecture,
- support GitLab or issue-only actuation,
- use embeddings, RAG, or semantic search for detection.

## Local Validation

Run these before opening a PR:

```bash
ruff check .
ruff format --check .
pytest
planning-validator validate-config \
  --config examples/target-repo/.github/planning-validator.yml \
  --repo-root examples/target-repo
```

## Release Prep

Version metadata is in [`pyproject.toml`](./pyproject.toml). Release readiness is tracked in
[`docs/RELEASE.md`](./docs/RELEASE.md); keep it aligned with the current package version and the
supported v1 workflow surface.

## Repository CI

This repository also integrates
[`shaypal5/pr-agent-context`](https://github.com/shaypal5/pr-agent-context) for PR handoff comments
and patch-coverage feedback. See [`.github/workflows/ci.yml`](./.github/workflows/ci.yml),
[`.github/workflows/pr-agent-context-refresh.yml`](./.github/workflows/pr-agent-context-refresh.yml),
and [`.github/pr-agent-context-template.md`](./.github/pr-agent-context-template.md) for the
repository-specific workflow details.
