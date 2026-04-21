# planning-validator v1 — Patcher and PR Contract

## Purpose

This document defines the contract for the two actuation-facing layers in v1:

1. **patcher** — LLM-driven generation of bounded markdown file replacements
2. **PR manager** — branch and draft-PR orchestration

The patcher and PR manager are separate components, but they operate sequentially and are tightly coupled in the end-to-end flow.

---

## High-level rule

The patcher is allowed to rewrite only those files selected by the detector.

The PR manager is allowed to act only on validated edits.

No component in this layer may expand scope beyond:
- the selected files,
- the configured branch/PR policy,
- the evidence provided by the detector.

---

## Patcher contract

### Inputs

The patcher receives:

- repository identity and head SHA,
- config-derived rendering and safety rules,
- recent PR/issue evidence,
- selected target files,
- original file contents,
- stale signals attached to each target.

### Reference input models

```python
from pydantic import BaseModel

class PatchTargetFile(BaseModel):
    path: str
    original_content: str
    matched_signals: list[dict]

class PatchRequest(BaseModel):
    repo: str
    head_sha: str
    config_summary: dict
    recent_prs: list[dict]
    recent_issues: list[dict]
    target_files: list[PatchTargetFile]
    global_instructions: list[str]
```

The exact internal representation may vary, but the semantics should be preserved.

---

## Required model-output contract

For v1, the patcher must request and parse **JSON only**.

### Reference output models

```python
from typing import Literal
from pydantic import BaseModel

class FileEdit(BaseModel):
    path: str
    operation: Literal["replace_file"]
    new_content: str
    rationale: str
    evidence_refs: list[str]

class PatchResponse(BaseModel):
    summary: str
    edits: list[FileEdit]
```

Only `replace_file` is supported in v1.

---

## Why full-file replacement in v1

Use full-file replacement because it is easier to validate:

- the final file is explicit,
- frontmatter preservation is testable,
- unrelated sections can be checked for accidental deletion,
- markdown planning docs are often structurally edited rather than line-patched.

Do not implement unified-diff application in v1.

---

## Required patcher behaviors

### Behavior 1: bounded target set
The patcher must only propose edits for files included in `PatchRequest.target_files`.

### Behavior 2: no new files
The patcher must not create new files in v1.

### Behavior 3: no non-markdown edits
The patcher must not edit source code, tests, workflows, configs, or arbitrary repository files.

### Behavior 4: evidence-grounded updates only
The patcher must only make claims that can be supported by the provided recent PR/issue data and stale signals.

### Behavior 5: preserve unrelated structure
Unless necessary, headings, frontmatter, and unrelated sections should remain unchanged.

### Behavior 6: minimal edits
The patcher should prefer the smallest coherent edit set.

---

## Prompt requirements

The prompt builder should include:

1. system-level rules,
2. edit safety rules,
3. evidence summaries,
4. per-file original content,
5. target output schema,
6. explicit prohibition against unsupported claims.

### Core instruction themes
- update only listed files,
- preserve frontmatter verbatim,
- preserve sections unrelated to provided evidence,
- do not invent PRs/issues/tasks,
- do not change statuses without supporting evidence,
- prefer minimal markdown edits,
- return strict JSON only.

---

## Response parsing

The response parser should:

1. extract raw model text,
2. parse JSON,
3. validate against Pydantic schema,
4. fail clearly if any step fails.

No permissive “best effort” partial parsing in v1.

If the provider supports structured output natively, use it. Otherwise, validate strictly after plain text generation.

---

## Patch validation rules

After parsing, every proposed edit must go through a validator.

Reject the patch response if **any** of the following are true:

1. A file path is not in the detector-selected target set.
2. A file path matches forbidden globs.
3. The response contains duplicate edits for the same file.
4. `new_content` is empty.
5. Frontmatter is missing or altered when preservation is required.
6. Large unrelated sections are removed without justification.
7. The file introduces PR or issue numbers not present in the patch request.
8. The file marks work complete without supporting merged-PR evidence.
9. The number of edited files exceeds `staleness.max_files_to_update`.
10. The response schema is invalid.

The validator should return precise machine-readable failure reasons.

---

## Recommended validation checks

### File-path validation
- exact path match against allowed target files
- forbidden glob check

### Content-preservation validation
- frontmatter equality check
- heading inventory comparison
- optional section-preservation heuristics
- no total file collapse

### Evidence validation
- allowed PR/issue reference set
- no hallucinated IDs
- no unsupported state transitions

### Size sanity
- reject pathological outputs such as tiny placeholder content replacing large docs

---

## Suggested internal patcher modules

- `prompt_builder.py`
- `llm_client.py`
- `response_parser.py`
- `file_patch_validator.py`
- `patcher.py`

Keep provider-specific behavior isolated inside `llm_client.py`.

---

## Provider abstraction

The provider interface should be minimal. Example conceptual interface:

```python
class LLMClient:
    def generate_patch(self, request: PatchRequest) -> PatchResponse:
        ...
```

Provider-specific subclasses or strategies may implement:
- OpenAI calls,
- Anthropic calls.

The rest of the codebase should not need to know provider-specific request formats.

---

## Failure handling for patching

If model generation or validation fails:

- do not write any file changes,
- do not open/update a PR,
- exit with a clear failure summary.

Optional later enhancement:
- one repair prompt retry for schema-invalid output.

For v1, zero retries or one narrowly scoped retry is acceptable. Keep behavior deterministic and simple.

---

## PR manager contract

Once edits have been validated and applied locally, the PR manager is responsible for:

1. ensuring the automation branch exists or is updated,
2. committing the documentation changes,
3. creating or updating a single draft PR,
4. generating a structured PR body.

It must not reinterpret the contents of the patch.

---

## Branch policy

v1 should use exactly one fixed branch per repo, configurable via:

```yaml
pull_request:
  branch: automation/planning-validator
```

Required behavior:
- if branch does not exist, create it from base branch,
- if branch exists, update it in place,
- do not create per-run or per-date branches in v1.

This is essential for idempotency and avoiding PR spam.

---

## PR policy

### One PR maximum
At most one open planning-validator PR may exist per repository.

### Draft by default
PRs should be draft PRs in v1.

### Update existing by default
If an open PR already exists from the automation branch, update it rather than creating a new one.

### Stable title
Default title:
```text
docs: refresh planning/tracking files
```

Keep title stable unless there is a compelling reason not to.

---

## PR body format

Use a structured PR body that includes:

- why the PR exists,
- which PRs/issues were considered,
- which files were updated,
- run metadata.

### Suggested body template

```md
## Why this PR exists

Planning/tracking documents appear stale relative to recent merged pull requests.

## Evidence considered

- PR #123 — add feature X
- PR #124 — finish roadmap milestone Y

## Files updated

- docs/roadmap.md
- docs/tasks/feature-x.md

## Validator run metadata

- Head SHA: abcdef1
- Config path: .github/planning-validator.yml
- Lookback window: 30h

## Notes

This PR was generated automatically and should be reviewed like any other docs PR.
```

The body should be easy to regenerate on each run.

---

## Commit policy

Use a stable commit message in v1, such as:

```text
docs: refresh planning/tracking files
```

One commit per run is fine.

If there are no actual file changes after validation, do not commit or update the PR.

---

## Idempotency rules

The PR manager must ensure:

1. repeated runs with no new changes create no new commits,
2. repeated stale runs update the same PR,
3. clean runs do not create duplicate draft PRs,
4. no duplicate branches are created.

---

## Handling an existing open PR

If the configured branch already has an open PR:

- pull/recreate working tree state,
- apply validated edits,
- commit only if the tree changed,
- update the existing PR body if needed,
- keep the same PR open.

If no tree changes remain after validation:
- do not push a no-op commit.

---

## Handling a clean repo while PR exists

v1 does not need aggressive automated closure of stale automation PRs.

If `pull_request.close_when_clean` exists, it may remain unimplemented or explicitly unsupported in v1.

The preferred v1 behavior is:
- do nothing special,
- leave closure decisions to later milestones.

---

## CLI expectations

The patch/PR layer should support:

```bash
planning-validator patch --config .github/planning-validator.yml --detection-json detection.json
planning-validator run --config .github/planning-validator.yml
```

`patch` may write files locally for testing.
`run` may create/update the PR in CI mode.

---

## Test expectations

### Patcher tests
- valid JSON response accepted
- schema-invalid response rejected
- forbidden path edit rejected
- hallucinated PR reference rejected
- frontmatter removal rejected

### PR manager tests
- create new branch and draft PR
- update existing PR instead of creating duplicate
- no-op when no file changes
- structured PR body generation

### Integration tests
- stale repo -> validated edits -> one PR
- invalid patch output -> fail without PR
- rerun -> same PR updated, not duplicated

---

## v1 simplifications

These simplifications are deliberate and should remain in place unless they block implementation:

- one branch,
- one PR,
- markdown only,
- full-file replacements only,
- direct provider APIs only,
- strict validation,
- no automatic merge,
- no automatic issue creation,
- no general prompt customization per target repo.
