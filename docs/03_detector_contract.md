# planning-validator v1 — Detector Contract

## Purpose

The detector is the deterministic core of `planning-validator`.

Its responsibilities are:

1. inspect recent repository evidence,
2. decide whether planning/tracking docs appear stale,
3. identify which files are likely stale,
4. provide evidence-backed reasons for each target.

The detector must not call an LLM.
The detector must not rewrite files.
The detector must be fully unit-testable.

---

## Design rule

**The detector is the authority on whether action is warranted.**

If the detector does not find sufficient stale evidence, the system must not invoke the patcher.

---

## Inputs

The detector consumes:

- parsed config,
- repository snapshot,
- recent merged PR metadata,
- optional recent issue metadata,
- current contents of planning/tracking files.

### Reference input models

```python
from typing import Literal
from pydantic import BaseModel

class RecentPR(BaseModel):
    number: int
    title: str
    body: str | None = None
    author: str | None = None
    merged_at: str
    labels: list[str] = []
    changed_files: list[str] = []
    linked_issues: list[int] = []
    url: str

class RecentIssue(BaseModel):
    number: int
    title: str
    state: Literal["open", "closed"]
    closed_at: str | None = None
    url: str

class RepoFile(BaseModel):
    path: str
    content: str
    sha: str | None = None

class RepoSnapshot(BaseModel):
    repo: str
    default_branch: str
    head_sha: str
    planning_files: list[RepoFile]
    tracking_files: list[RepoFile]
    recent_prs: list[RecentPR]
    recent_issues: list[RecentIssue] = []
```

The actual implementation may separate these models differently, but the contract should remain equivalent.

---

## Outputs

The detector returns a structured result containing:

- overall stale vs not stale decision,
- stale signals,
- file-level scoring,
- patch-eligible target files.

### Reference output models

```python
from typing import Literal
from pydantic import BaseModel

class StaleSignal(BaseModel):
    signal_type: Literal[
        "missing_pr_reflection",
        "status_outdated",
        "issue_state_outdated",
        "todo_not_marked_done",
        "roadmap_stage_incorrect",
        "recent_work_missing_from_changelog",
        "file_mentions_closed_pr_as_open",
    ]
    target_file: str
    score: float
    reason: str
    evidence: dict

class TargetFileDecision(BaseModel):
    path: str
    aggregate_score: float
    matched_signals: list[StaleSignal]
    allowed_to_patch: bool

class DetectionResult(BaseModel):
    is_stale: bool
    summary: str
    signals: list[StaleSignal]
    target_files: list[TargetFileDecision]
    ignored_prs: list[int] = []
```

---

## Signal taxonomy for v1

Implement these signals first.

### 1. `missing_pr_reflection`
A recent merged PR changed meaningful repo content, but relevant planning/tracking docs do not reflect the delivery.

Typical evidence:
- recent merged PR exists within lookback window,
- PR changed non-ignored files,
- tracked docs do not mention the relevant feature, milestone, or PR,
- or the docs still describe it as pending.

### 2. `status_outdated`
A task/status document still says work is planned, pending, unchecked, or in progress even though a recent merged PR indicates completion.

### 3. `issue_state_outdated`
A planning/tracking doc refers to an issue or PR state incorrectly relative to current GitHub state.

Examples:
- references an issue as open when it has closed,
- references a PR as pending when it has merged.

### 4. `todo_not_marked_done`
A checklist item or task entry remains unchecked although a recent merged PR strongly indicates completion.

### 5. `roadmap_stage_incorrect`
A roadmap document still places delivered work in a future/in-progress milestone state.

### 6. `recent_work_missing_from_changelog`
Used only if changelog-like docs are included in tracked files. A recent merged change should have been reflected in a maintained recent-work section but is absent.

### 7. `file_mentions_closed_pr_as_open`
A document explicitly mentions a PR or linked issue with stale state wording.

---

## Detection heuristics

The detector should use explicit heuristics, not free-form semantic judgment.

### PR inclusion filter
A recent merged PR participates in detection only if:
- it falls within `lookback.merged_pr_hours`,
- it does not have an ignored label,
- it touched at least one meaningful file path outside ignored paths.

### File targeting heuristic
A file becomes a candidate target when:
- it is a planning or tracking file,
- one or more stale signals point to it,
- its aggregate score exceeds the configured threshold,
- it is allowed by the patching allowlist and not forbidden.

### Markdown pattern heuristics
For v1, it is acceptable to use simple textual heuristics such as:
- checklist patterns (`- [ ]`, `- [x]`)
- headings like `Status`, `Roadmap`, `Next`, `Planned`, `Done`
- keywords such as `planned`, `pending`, `in progress`, `complete`, `merged`
- explicit PR/issue references like `#123`

The detector does not need deep markdown AST understanding in v1.

---

## Scoring model

Signals should contribute weighted evidence to a file-level aggregate score.

Suggested initial weights:

```python
WEIGHTS = {
    "missing_pr_reflection": 0.35,
    "status_outdated": 0.40,
    "issue_state_outdated": 0.30,
    "todo_not_marked_done": 0.40,
    "roadmap_stage_incorrect": 0.35,
    "recent_work_missing_from_changelog": 0.20,
    "file_mentions_closed_pr_as_open": 0.30,
}
```

These do not need to be configurable in v1.

Aggregate score may be a capped sum or a normalized weighted sum. Keep the implementation simple and deterministic.

A file is patch-eligible if:

- aggregate score >= `staleness.min_signal_score`
- file path is allowed by patch config
- file path is not forbidden by patch config

---

## Required detector behaviors

### Behavior 1: ignore excluded PRs
If a PR has an ignored label, it must not contribute stale signals.

### Behavior 2: ignore non-meaningful path changes
Changes limited to ignored paths should not trigger stale signals.

### Behavior 3: no patch targets without evidence
A file must not be selected only because it is likely related. It must have at least one signal with explicit evidence.

### Behavior 4: deterministic output
Given the same snapshot and config, the detector should produce the same result every time.

### Behavior 5: conservative bias
When uncertain, prefer false negatives over false positives in v1.

---

## Evidence structure

Each stale signal should carry an `evidence` payload sufficient for both:
- debugging,
- patch prompt grounding.

Suggested evidence fields include:
- `pr_number`
- `pr_title`
- `pr_url`
- `changed_files`
- `matched_terms`
- `issue_number`
- `issue_state`
- `doc_excerpt_locator` or section heading
- `reason_code`

Keep evidence structured and small.

---

## Examples

### Example A — stale roadmap
Recent PR #123 merged yesterday and delivered feature X. `docs/roadmap.md` still lists feature X under “Planned”.

Expected signals:
- `roadmap_stage_incorrect`
- possibly `status_outdated`

Expected result:
- `docs/roadmap.md` selected as patch target

### Example B — fresh repo
Recent PR #124 merged yesterday and `docs/tasks.md` already marks the task complete with a PR reference.

Expected result:
- no stale signals,
- no patch targets,
- `is_stale = false`

### Example C — ignored PR
Recent PR #125 merged, but carries label `skip-planning-validator`.

Expected result:
- PR ignored,
- no stale signal solely from that PR

### Example D — checklist task
`docs/tasks.md` contains:
```md
- [ ] Add config validation command
```
Recent PR #130 merged implementing the config validation command.

Expected signals:
- `todo_not_marked_done`
- maybe `missing_pr_reflection`

---

## Edge cases

The detector should explicitly handle:

### 1. Overlapping file globs
If a file belongs to both planning and tracking sets, it should be deduplicated.

### 2. Empty doc set
If globs resolve to no files, the config validator should already have failed or warned strongly.

### 3. PRs without linked issues
This is normal; issue-based signals should be optional.

### 4. PRs that update docs themselves
A PR may already have updated planning docs. This should reduce or eliminate stale signals.

### 5. Large markdown files
The detector should scan them conservatively using section/keyword heuristics; it does not need full semantic parsing.

### 6. Ambiguous completion
If evidence does not clearly show completion, do not emit high-confidence completion signals.

---

## Acceptance criteria

The detector implementation is acceptable for v1 if:

1. It can generate no-op results on fresh fixture repos.
2. It can identify obvious stale task/roadmap cases.
3. It excludes ignored PRs correctly.
4. It produces stable, typed outputs.
5. It selects only allowlisted files as patch-eligible targets.
6. It can be tested without network calls when given fixture snapshots.

---

## Test plan

### Unit tests
Create tests for:
- label filtering
- ignored path filtering
- checklist stale detection
- roadmap stage detection
- issue-state mismatch detection
- score aggregation
- target-file eligibility

### Integration-style tests
Create end-to-end fixture tests for:
- fresh repo -> no-op
- stale repo -> one or more patch targets
- invalid config -> fail early
- mixed signals -> only above-threshold files selected

---

## Recommended implementation split

Implement the detector in these internal units:

- `recent_prs.py` — PR filtering and normalization
- `issue_links.py` — issue extraction/link enrichment
- `doc_inventory.py` — file loading / inventory
- `signals.py` — individual signal generators
- `scoring.py` — aggregation and threshold logic
- `detector.py` — orchestration entrypoint

Keep signal generators small and composable.

---

## Output summary expectations

The detector should return a human-readable summary such as:

- `No stale documentation signals detected.`
- `Detected 3 stale signals across 2 files based on 2 recent merged PRs.`

This summary should be suitable for logs, artifacts, and PR metadata generation.
