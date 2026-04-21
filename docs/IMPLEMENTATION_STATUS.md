# Implementation Status

## Completed

- Milestone 1 complete: scaffolding and config validation baseline established.
- Read and locked to the v1 design docs in `docs/`.
- Established the initial Python package, CLI skeleton, config models, tests, CI, examples, and repo tooling baseline.
- Integrated `pr-agent-context` into repository CI and added a refresh workflow that uses append-mode managed comments with coverage artifact reuse.
- Aligned `pr-agent-context` coverage reporting with the working downstream pattern: raw coverage upload in test jobs, combined XML/report artifacts in a dedicated coverage job, and XML-based patch coverage input for comment rendering.

## Remaining

- Milestone 2: GitHub data collection and repository snapshot building.
- Milestone 3: deterministic stale detector.
- Milestone 4: bounded LLM patcher and patch validation.
- Milestone 5: branch and draft PR manager.
- Milestone 6: end-to-end `run` command and reusable workflow wiring.
- Milestone 7: fixtures, polish, release preparation, and OSS docs hardening.

## Current planned PR breakdown

- Planned implementation slices use `P-<Milestone><Letter>` notation such as `P-M2A`.
- Milestone 2 is split into:
  - `P-M2A`: GitHub evidence client and normalized evidence models.
  - `P-M2B`: local planning/tracking file inventory plus gitignore and path filtering.
  - `P-M2C`: repository snapshot assembly that combines local files with GitHub evidence.
- `P-M2A` is the next implementation slice in progress.

## Decisions

- Milestone 1 rejects non-markdown planning/tracking matches during config validation instead of warning.
- Milestone 1 rejects unbounded patch allowlists such as `**/*` to keep v1 edit scope narrow.
- The reusable workflow is intentionally a validation-only stub until the `run` command exists.
- PR handoff automation uses `shaypal5/pr-agent-context` with raw `coverage.py` artifacts plus a combined coverage-report artifact for richer downstream patch-coverage reporting.

## Clarifications

- `validate-config` resolves globs against an explicit repo root and fails early when patterns do not match files.
- A config is considered actionable only if at least one discovered planning/tracking file remains patchable after allowlist and denylist rules are applied.
