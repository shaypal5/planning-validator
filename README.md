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
