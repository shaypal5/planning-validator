{{ prompt_preamble }}

# planning-validator PR #{{ pr_number }}

Use the repository design docs under `docs/` as the product source of truth.

Hard constraints for this repository:

- keep the detector deterministic and evidence-based
- do not use an LLM in detection logic
- keep patching bounded to detector-selected, allowlisted markdown files
- do not broaden v1 beyond the documented GitHub-native scope
- run `ruff check .`, `ruff format --check .`, and `pytest` before handing off code changes

{{ opening_instructions }}

{{ copilot_comments_section }}
{{ review_comments_section }}
{{ failing_checks_section }}
{{ approval_gated_actions_run_notes_section }}
{{ patch_coverage_section }}
