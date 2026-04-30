# Release Readiness

This repository currently uses the package version declared in `pyproject.toml`: `0.1.0`.

## Pre-release command sequence

Run this exact sequence from the repository root before opening a release PR or creating a release
tag:

```bash
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest
planning-validator validate-config \
  --config examples/target-repo/.github/planning-validator.yml \
  --repo-root examples/target-repo
python -m build
```

The repository CI mirrors the lint, format, test, documented example config validation, and package
build checks. Normal tests must not require live GitHub or live model calls.

## Version and tag strategy

- Keep the package version in `pyproject.toml` as `0.1.0` until the project is ready for an
  explicitly tagged pre-v1 or v1 release.
- Use annotated git tags for release points.
- For the current package line, tag only versions that match `pyproject.toml`, such as `v0.1.0`.
- For future v1 adoption, publish stable reusable-workflow references with a `v1` tag only after
  the package is exercised successfully in at least one real target repository.
- Do not create an automatic v1 tag as part of CI or normal release-gate hardening.

## Manual release work

These steps are intentionally still manual:

- choosing when a release is ready,
- bumping the version in `pyproject.toml`,
- creating and pushing annotated tags,
- creating GitHub releases,
- publishing package artifacts,
- moving or updating a stable `v1` workflow tag.

There is no automatic PyPI publishing, automatic GitHub release creation, or automatic v1 tagging in
the v1 scope.

## v1 compatibility notes

- Keep the detector deterministic and evidence-based.
- Keep patching limited to detector-selected, allowlisted markdown files.
- Keep the runtime PR behavior on one fixed automation branch and one open PR.
- Treat generated PRs as review artifacts; the tool does not merge them automatically.
