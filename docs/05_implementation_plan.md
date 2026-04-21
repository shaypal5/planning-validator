# planning-validator v1 — Implementation Plan

## Goal

Build `planning-validator` as a reusable, open-source, GitHub-native tool that:

- runs inside target repositories via GitHub Actions,
- detects stale planning/tracking docs based on recent merged PRs,
- proposes bounded markdown updates,
- opens or updates one draft PR per repository.

Implementation should proceed through well-scoped PRs, each independently reviewable and testable.

---

## Delivery principles

Every implementation PR should:

- be small enough to review cleanly,
- include tests,
- avoid speculative future complexity,
- preserve the detector/patcher boundary,
- leave the repo runnable at all times.

The project should be scaffolded as a normal Python package with strong CI from the start.

---

## Recommended repo setup in the first PR

The initial repository scaffolding should include:

- `pyproject.toml`
- `src/` layout
- `tests/`
- `ruff`
- `pytest`
- `coverage`
- `pre-commit`
- GitHub Actions CI
- MIT license if not already present
- README stub
- docs folder with these design docs
- reusable workflow stub

Suggested dependencies:
- `pydantic>=2`
- `typer`
- `httpx`
- `PyYAML`
- optional provider SDKs only if truly needed; plain HTTP is acceptable

Keep dependencies lean.

---

## Milestone breakdown

## Milestone 1 — Project scaffolding and config layer

### Objective
Create the repository skeleton and config parsing/validation foundations.

### Deliverables
- Python package scaffold
- CLI skeleton
- config models
- YAML parsing
- config validation command
- basic CI and local tooling
- initial docs/examples folder structure

### Expected files
- `pyproject.toml`
- `src/planning_validator/cli.py`
- `src/planning_validator/config.py`
- `src/planning_validator/models.py`
- `tests/unit/test_config.py`
- `.pre-commit-config.yaml`
- `.github/workflows/ci.yml`

### Required CLI
```bash
planning-validator validate-config --config .github/planning-validator.yml
```

### Tests
- valid minimal config
- invalid schema version
- missing required fields
- bad numeric ranges
- bad allowed/forbidden glob combinations

### Exit criteria
- package installs,
- tests pass,
- config validation works.

---

## Milestone 2 — GitHub data collection and repo snapshot

### Objective
Build the repository snapshot layer and GitHub API client for recent PR/issue collection.

### Deliverables
- GitHub API client abstraction
- recent merged PR fetch
- optional linked-issue fetch
- file inventory from planning/tracking globs
- snapshot builder

### Expected files
- `src/planning_validator/github_api.py`
- `src/planning_validator/repo_snapshot.py`
- `src/planning_validator/file_io.py`
- `src/planning_validator/gitignore_filter.py`
- `tests/unit/test_repo_snapshot.py`
- `tests/unit/test_github_api.py`

### Implementation notes
- Prefer direct REST/GraphQL calls through `httpx`
- Keep API surface narrow
- Normalize GitHub responses into internal models immediately

### Tests
- snapshot contains expected files
- recent PRs filtered by lookback
- ignored labels excluded
- ignored paths filtered

### Exit criteria
- snapshot can be built from fixture repo state and mocked API responses.

---

## Milestone 3 — Deterministic detector

### Objective
Implement the stale-detection core.

### Deliverables
- signal generators
- score aggregation
- file targeting
- detector entrypoint
- JSON detection output

### Expected files
- `src/planning_validator/detector/signals.py`
- `src/planning_validator/detector/scoring.py`
- `src/planning_validator/detector/detector.py`
- `tests/unit/test_signals.py`
- `tests/unit/test_detector.py`

### CLI
```bash
planning-validator detect --config .github/planning-validator.yml --json-out detection.json
```

### Required v1 signals
- `missing_pr_reflection`
- `status_outdated`
- `issue_state_outdated`
- `todo_not_marked_done`
- `roadmap_stage_incorrect`
- `recent_work_missing_from_changelog`
- `file_mentions_closed_pr_as_open`

### Tests
- fresh repo => no stale targets
- stale checklist => target selected
- stale roadmap => target selected
- ignored PR => no signal
- under-threshold file => not selected

### Exit criteria
- detector is fully testable without LLM calls,
- detection JSON is typed and stable.

---

## Milestone 4 — Patcher contracts and provider abstraction

### Objective
Implement the LLM-facing patcher with strict schema contracts, but no PR creation yet.

### Deliverables
- patch request builder
- provider abstraction
- one backend implementation
- JSON response parsing
- patch validation
- local file-write support for dry-run/testing

### Expected files
- `src/planning_validator/patcher/prompt_builder.py`
- `src/planning_validator/patcher/llm_client.py`
- `src/planning_validator/patcher/response_parser.py`
- `src/planning_validator/patcher/file_patch_validator.py`
- `src/planning_validator/patcher/patcher.py`
- `tests/unit/test_response_parser.py`
- `tests/unit/test_patch_validator.py`

### CLI
```bash
planning-validator patch --config .github/planning-validator.yml --detection-json detection.json
```

### Implementation notes
- Start with a single provider, probably OpenAI
- Add Anthropic once the interface is stable
- Prefer strict JSON response validation

### Tests
- valid model output accepted
- invalid JSON rejected
- forbidden path rejected
- hallucinated PR number rejected
- frontmatter deletion rejected

### Exit criteria
- patcher can produce validated file replacements locally from fixture inputs.

---

## Milestone 5 — Branch and PR manager

### Objective
Implement Git operations and GitHub PR creation/update behavior.

### Deliverables
- fixed branch handling
- commit logic
- PR discovery
- create/update draft PR logic
- structured PR body rendering

### Expected files
- `src/planning_validator/pr/branch_manager.py`
- `src/planning_validator/pr/pr_body.py`
- `src/planning_validator/pr/pr_manager.py`
- `tests/unit/test_pr_manager.py`

### Required behavior
- one fixed branch
- one draft PR max
- update existing PR
- no-op when no actual file changes

### Tests
- create new automation PR
- update existing PR
- do not duplicate PR
- do not commit if tree unchanged

### Exit criteria
- end-to-end local orchestration can update a mocked PR lifecycle.

---

## Milestone 6 — End-to-end `run` command and reusable workflow

### Objective
Connect the entire system and ship the GitHub Actions integration.

### Deliverables
- `planning-validator run`
- reusable workflow
- example target repo caller workflow
- secrets/input handling
- artifact/log summary generation

### Expected files
- `.github/workflows/reusable-planning-validator.yml`
- `examples/target-repo/.github/workflows/planning-validator.yml`
- integration tests covering end-to-end flow

### CLI
```bash
planning-validator run --config .github/planning-validator.yml
```

### Required behavior
- no-op clean run
- stale run opens/updates one draft PR
- invalid patch output aborts safely

### Exit criteria
- real or near-real integration works in GitHub Actions.

---

## Milestone 7 — Fixtures, evals, polish, and release prep

### Objective
Harden the repository for public open-source release.

### Deliverables
- fixture repos
- golden test cases
- examples
- README usage instructions
- versioning/tagging readiness
- release workflow
- docs polish

### Expected files
- `tests/fixtures/repo_a/`
- `tests/fixtures/repo_b/`
- `tests/integration/test_end_to_end_simple.py`
- `tests/integration/test_idempotent_update_existing_pr.py`
- `tests/integration/test_noop_when_fresh.py`
- `README.md`

### Exit criteria
- documentation is sufficient,
- v1 tag can be cut,
- example target repo setup is complete.

---

## PR breakdown recommendation

Aim for approximately these PRs:

1. scaffold + tooling + config schema
2. snapshot + GitHub API
3. detector core
4. patcher core
5. PR manager
6. reusable workflow + end-to-end wiring
7. polish + docs + release prep

If a PR becomes too large, split it further rather than broadening scope.

---

## Testing strategy by stage

### Unit tests
Prioritize for:
- config parsing
- detector heuristics
- score aggregation
- response parsing
- patch validation
- PR body generation

### Integration tests
Prioritize for:
- fresh repo no-op
- stale repo one PR
- rerun updates same PR
- invalid model output yields safe failure

### Mocking strategy
- mock GitHub API calls
- mock model provider calls
- use fixture repo directories for file-state inputs

Avoid needing live GitHub or live model calls in normal test runs.

---

## CI expectations

From the first meaningful implementation PR onward, CI should run:

- lint/format check via `ruff`
- unit tests via `pytest`
- coverage measurement
- optional integration subset on push/PR

The reusable workflow itself can be validated through targeted tests and example usage.

---

## Suggested `pyproject.toml` expectations

Codex should scaffold a modern `pyproject.toml` with:

- package metadata
- `src/` layout configuration
- dev dependency groups
- entry point for CLI
- pytest configuration
- coverage configuration
- ruff configuration or separate `ruff.toml`

Use `uv`-friendly layout.

---

## Example target repo expectations

The example target repo in `examples/target-repo/` should include:

- minimal config file
- caller workflow
- example roadmap/tasks markdown files
- sample comments showing how stale/fresh states look

This example should be simple enough to read quickly and realistic enough to guide adopters.

---

## Logging and artifacts expectations

The system should emit structured summaries suitable for CI logs and artifact upload.

Recommended summary outputs:
- config path used
- number of recent PRs considered
- number of stale signals
- target files selected
- patch validation outcome
- PR URL if created/updated

Prefer JSON summary files in addition to readable console output.

---

## Release readiness checklist for v1

Before tagging `v1`:

- all milestone deliverables are implemented,
- reusable workflow works from a consuming repo,
- at least one model backend is stable,
- detector/patcher boundary is preserved,
- one real target repo has been exercised successfully,
- README includes setup and example config,
- version tag strategy is documented.

---

## Codex implementation rules

Codex should follow these rules while implementing:

1. Do not broaden v1 scope.
2. Prefer explicit typed contracts.
3. Keep logic in Python, not shell.
4. Add tests alongside implementation.
5. Preserve small, reviewable PRs.
6. Keep provider-specific code isolated.
7. Do not add GitHub App support in v1.
8. Do not add arbitrary prompt customization in target configs.
9. Do not add non-markdown editing support.
10. Keep failure modes conservative and safe.

---

## Recommended first command sequence for local development

Document commands like:

```bash
uv sync
uv run ruff check .
uv run pytest
uv run planning-validator validate-config --config examples/target-repo/.github/planning-validator.yml
```

These should work early in the project lifecycle.

---

## Final implementation objective

At the end of v1, the repository should be able to say:

- install `planning-validator`,
- add a small config file and caller workflow to a repo,
- schedule it hourly,
- review one draft PR when docs drift behind delivered work.

That is the whole product.
