# Implementation Status

## Completed

- Milestone 1 complete: scaffolding and config validation baseline established.
- Milestone 2 complete: GitHub evidence collection, local planning/tracking inventory loading, and repository snapshot assembly are now implemented with unit coverage.
- `P-M2B` complete: shared repo-relative glob resolution, `.gitignore` filtering, and local planning/tracking document inventory loading are now implemented with unit coverage.
- `P-M2C` complete: typed `RepoSnapshot` assembly now combines local markdown inventory with recent PR evidence, with deterministic ordering, local git metadata helpers, and unit coverage.
- `P-M3A` complete: deterministic stale-document detection, signal scoring, target-file selection, and detection JSON CLI output are implemented with unit coverage.
- `P-M4A` complete: bounded dry-run-first patcher core, strict model response parsing, patch validation, optional local apply, and tests are implemented.
- `P-M5A` complete: fixed-branch git orchestration, draft PR create/update behavior, structured body rendering, duplicate protection, and unit coverage are implemented.
- `P-M6A` complete: end-to-end `planning-validator run` orchestration, safe clean/invalid-patch behavior, reusable workflow runtime wiring, summary artifact upload, and focused unit coverage are implemented.
- `P-M7A` complete: fixture target repositories, offline integration-style runtime coverage, example target-repo hardening, v1 README usage docs, and release-readiness notes are implemented.
- `P-REL1A` complete: CI now validates the documented target-repo config and package build, and release docs define the pre-release command sequence, version/tag strategy, and manual release boundaries.
- Read and locked to the v1 design docs in `docs/`.
- Established the initial Python package, CLI skeleton, config models, tests, CI, examples, and repo tooling baseline.
- Integrated `pr-agent-context` into repository CI and added a refresh workflow that uses append-mode managed comments with coverage artifact reuse.
- Aligned `pr-agent-context` coverage reporting with the working downstream pattern: raw coverage upload in test jobs, combined XML/report artifacts in a dedicated coverage job, and XML-based patch coverage input for comment rendering.
- Hardened the `pr-agent-context` refresh workflow with the approval-gated fallback pattern from `v4.0.19`, including scheduled fan-out dispatch, explicit PR SHA overrides, and same-head dispatch dedupe for same-repo PRs.

## Current and Remaining

- Current slice: none.
- Milestone 7: fixtures, polish, release preparation, and OSS docs hardening is complete.
- Release gate hardening: `P-REL1A` is complete and ready for PR review.

## Current planned PR breakdown

- Planned implementation slices use `P-<Milestone><Letter>` notation such as `P-M2A`.
- Milestone 2 is split into:
  - `P-M2A`: GitHub evidence client and normalized evidence models.
  - `P-M2B`: local planning/tracking file inventory plus gitignore and path filtering.
  - `P-M2C`: repository snapshot assembly that combines local files with GitHub evidence.
- `P-M2A` is complete.
- `P-M2B` is complete.
- `P-M2C` is complete.
- `P-M3A` is complete.
- `P-M4A` is complete.
- `P-M5A` is complete.
- `P-M6A` is complete.
- `P-M7A` is complete.
- `P-REL1A` is complete.

## Decisions

- Milestone 1 rejects non-markdown planning/tracking matches during config validation instead of warning.
- Milestone 1 rejects unbounded patch allowlists such as `**/*` to keep v1 edit scope narrow.
- The reusable workflow installs the package from the workflow ref, invokes `planning-validator run`, and uploads the run summary artifact.
- `P-M7A` integration coverage uses fixture repositories plus mocked GitHub/model/PR-manager edges so normal tests do not require live GitHub or live model calls.
- `P-REL1A` keeps release readiness as validation-only CI: documented example config validation and local package artifact build, without publishing, release creation, or automatic tagging.
- PR handoff automation uses `shaypal5/pr-agent-context` with raw `coverage.py` artifacts plus a combined coverage-report artifact for richer downstream patch-coverage reporting.
- Slice IDs such as `P-M5A` are stable identifiers, not status carriers. Status is represented by placement under Current, Completed, or Remaining sections; do not encode branch/main state inside slice IDs.

## Clarifications

- `validate-config` resolves globs against an explicit repo root and fails early when patterns do not match files.
- A config is considered actionable only if at least one discovered planning/tracking file remains patchable after allowlist and denylist rules are applied.
