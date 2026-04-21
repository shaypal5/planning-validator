# Agent Instructions

## Scope

- Keep this file static. Do not store dynamic status, milestone notes, or roadmaps here.
- Treat the design docs under `docs/` as the product source of truth.
- Use repo-specific GitHub MCP tools first for PR and issue actions. Use `gh` only when MCP support is missing.

## Commands

- Install/dev setup: `python -m pip install -e ".[dev]"`
- Lint: `ruff check .`
- Format check: `ruff format --check .`
- Tests: `pytest`
- Config validation: `planning-validator validate-config --config .github/planning-validator.yml`

## Branch and PR Rules

- Continue work on the current feature branch unless the user explicitly asks for a new branch.
- For new implementation branches, prefer the `codex/<scope>` prefix.
- Use planned-PR identifiers such as `P-M2A` for implementation planning slices; reserve `PR #123` for actual GitHub pull requests.
- Feature work is not complete until changes are pushed and a labeled, non-draft GitHub PR is open.
- Reuse the existing PR when the work belongs to the same branch.
- Apply an appropriate milestone when one exists. If none exists, note that explicitly in the PR.

## Code and Editing Rules

- Target Python 3.12.
- Keep package code under `src/planning_validator/`.
- Keep tests under `tests/`.
- Use typed, explicit Pydantic models at package boundaries.
- Prefer standard library code unless a dependency is already justified in `pyproject.toml`.
- Use `apply_patch` for manual file edits.
- Do not revert or discard user changes unless explicitly requested.

## Architecture Constraints

- Preserve the v1 boundary: the detector is deterministic and evidence-based.
- Do not use an LLM in detection logic.
- The patcher may edit only detector-selected, allowlisted markdown files.
- Do not add GitHub App architecture, GitLab support, non-markdown planning files, embeddings/RAG, automatic merge, or issue-only actuation unless the docs explicitly require them.
- Keep one fixed automation branch and one draft PR for the runtime product behavior.

## Canonical Reference Files

- Product overview: `docs/00_project_overview.md`
- System architecture: `docs/01_system_architecture.md`
- Config schema: `docs/02_config_schema.md`
- Detector contract: `docs/03_detector_contract.md`
- Patcher and PR contract: `docs/04_patcher_pr_contract.md`
- Implementation sequence: `docs/05_implementation_plan.md`
- Dynamic short-form state: `.agent-plan.md`
