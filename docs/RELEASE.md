# Release Readiness

This repository currently uses the package version declared in `pyproject.toml`.

## Pre-release checklist

- Run `ruff check .`.
- Run `ruff format --check .`.
- Run `pytest`.
- Validate the target-repo example:
  `planning-validator validate-config --config examples/target-repo/.github/planning-validator.yml --repo-root examples/target-repo`.
- Confirm the README documents the current reusable workflow inputs, required permissions, and
  supported provider secrets.
- Confirm normal tests do not require live GitHub or live model calls.

## v1 compatibility notes

- Keep the detector deterministic and evidence-based.
- Keep patching limited to detector-selected, allowlisted markdown files.
- Keep the runtime PR behavior on one fixed automation branch and one open PR.
- Treat generated PRs as review artifacts; the tool does not merge them automatically.
