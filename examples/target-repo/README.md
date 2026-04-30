# Example Target Repository

This repository demonstrates the minimum files needed to run `planning-validator` from a
consuming GitHub repository.

The example is intentionally small, but it is structured like a real target repository:

- `.github/planning-validator.yml` defines the planning and tracking markdown files.
- `.github/workflows/planning-validator.yml` calls the reusable workflow from this repository.
- `docs/roadmap.md` captures planning state.
- `docs/tasks.md` captures execution state.

The config is valid from this directory:

```bash
planning-validator validate-config --config .github/planning-validator.yml --repo-root .
```
