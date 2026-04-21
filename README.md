# planning-validator

`planning-validator` is a GitHub-native automation for keeping repository planning and tracking
markdown files aligned with recent merged pull requests and repository state.

The repository is being built directly from the design set under
[`docs/`](./docs/README_bundle.md). The current implementation baseline includes:

- a Python 3.12 package in `src/planning_validator/`
- a Typer CLI entrypoint
- YAML config parsing and semantic validation
- unit tests, Ruff, coverage, pre-commit, and CI
- example configs and target-repo workflow scaffolding

Implementation planning uses `P-<Milestone><Letter>` identifiers such as `P-M2A` to avoid
confusion with real GitHub pull request numbers. Milestone 2 is currently split into `P-M2A`
(GitHub evidence client), `P-M2B` (local file inventory and filtering), and `P-M2C`
(repo snapshot assembly).

## Local setup

```bash
python -m pip install -e ".[dev]"
pre-commit install
pytest
```

## Current CLI

```bash
planning-validator validate-config --config .github/planning-validator.yml
```

The `detect`, `patch`, and `run` commands are reserved for later milestones from
[`docs/05_implementation_plan.md`](./docs/05_implementation_plan.md).

## PR Agent Context

This repository now integrates
[`shaypal5/pr-agent-context`](https://github.com/shaypal5/pr-agent-context) as a downstream
consumer for PR handoff comments and patch-coverage feedback.

- [`.github/workflows/ci.yml`](./.github/workflows/ci.yml) uploads raw `coverage.py` data from the
  test job, combines it in a dedicated `coverage` job, and uploads `coverage.xml` plus
  `coverage-report.txt` as `pr-agent-context-coverage-report`.
- [`.github/workflows/pr-agent-context-refresh.yml`](./.github/workflows/pr-agent-context-refresh.yml)
  provides the later-lifecycle refresh path, uses `execution_mode: refresh` with
  `publish_mode: append`, and now includes the approval-gated `schedule` ->
  `workflow_dispatch` fallback pattern recommended in `pr-agent-context` v4.0.19 for
  same-repo PRs.
- [`.github/pr-agent-context-template.md`](./.github/pr-agent-context-template.md) supplies the
  repository-specific prompt template used by both flows.
