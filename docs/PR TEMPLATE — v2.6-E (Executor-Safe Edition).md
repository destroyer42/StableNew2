PR TEMPLATE — v2.6-E (Executor-Safe Edition).md
(An extension of v2.6 with guardrails, diff-plans, preconditions, and refusal conditions)
PR-### — Title (Short, Declarative)

Author:
Date:
Subsystem(s):
Risk Tier: (Tier 1 — GUI, Tier 2 — Controllers, Tier 3 — Pipeline/Queue/Runner)
Dependencies:
Architecture Version: v2.6-E

0. Executor Guardrails (MANDATORY — DO NOT REMOVE)

The executor model MUST comply with the following rules:

0.1 No Creativity

The executor must NOT:

invent behavior

infer missing logic

create new files unless explicitly listed

refactor for clarity

optimize code

generalize logic

repair architecture automatically

modify any line not explicitly targeted in this PR

0.2 Deterministic Execution

The executor MUST:

implement ONLY what is written

use EXACT path-level file operations

preserve all existing logic not explicitly modified

respect ownership boundaries defined in Architecture v2.6

0.3 Executor Refusal Conditions

The executor MUST REFUSE to execute the PR if:

any step is ambiguous

any file or function referenced does not exist

any instruction contradicts AGENTS.md

the PR results in a partial migration

the PR would create a second job path

the PR requires modifying a forbidden file

a required invariant cannot be satisfied

1. Purpose / Intent

State in 3–6 sentences:

the problem solved

capability restored or introduced

value to the pipeline

explicit ties to architectural invariants (PromptPack-only, single canonical job path, NJR-only, deterministic builder pipeline)

2. Summary of Changes (High-Level)

Use bullet points:

what is added

what is removed

what is rewritten

new invariants introduced

obsolete paths deleted

3. Architectural Alignment (MANDATORY)
3.1 PromptPack-Only Compliance

Affirmations:

All jobs originate from Prompt Packs

No GUI prompt fields touched

All mutations occur only within allowed domains

3.2 Single Canonical Pipeline Path

Must preserve:

PromptPack → ConfigMergerV2 → RandomizerEngineV2 → UnifiedResolvers →
JobBuilderV2 → NormalizedJobRecord → Queue → Runner → Outputs → History → Learning


State explicitly:

where this PR operates

obsolete paths being deleted

3.3 Ownership Boundaries

Affirm no violations in:

Pack TXT

Pack JSON

Negative prompt rules

Sweep rules

NJR immutability

3.4 No Partial Migrations / No Shims

State:

whether this PR completes the migration fully

which legacy paths are removed

4. Change Specification (Executor-Actionable)

THIS SECTION IS MACHINE-ACTIONABLE.
The executor must operate ONLY within this section.

For each file touched:

4.X FILE: src/.../...py
Preconditions (Executor MUST verify before modifying)

Example format:

Function foo_bar() exists at the top level.

Class PipelineController exists and includes method run_job().

Variable NJR is imported from src/pipeline/job_model.py.

If ANY precondition fails → executor must refuse.

Operations (Executor MUST follow literally)

Operations MUST be one of:

ADD:
  - Insert the following code at the exact location specified:
      (provide full code block)

MODIFY:
  - Replace the entire body of function X with:
      (provide full code block)

DELETE:
  - Remove the following lines exactly:
      (quote lines)

REPLACE:
  - Replace function signature:
      old: ...
      new: ...

REFACTOR:
  - Rename function/class/variable:
      old: ...
      new: ...
  - Move function X into Y without modifying contents.

NO OTHER MODIFICATIONS ALLOWED.


The executor may NOT:

change indentation except as needed for valid Python

reorder methods

alter imports unless explicitly stated

rewrite docstrings

compress logic

add helper methods

modify unrelated code blocks

5. Allowed Files / Forbidden Files (STRICT)
Allowed Files

List exact file paths.
If a file is NOT in this section → the executor must NOT modify it.

Forbidden Files

These may NOT be modified unless explicitly listed above:

src/gui/main_window_v2.py

src/gui/theme_v2.py

src/main.py

src/pipeline/executor.py

any pipeline runner core

any healthcheck core

any file not listed in Allowed Files

If PR requires edits to forbidden files → executor must refuse.

6. Tech Debt Evaluation
6.1 Debt Removed

List:

obsolete functions

legacy paths

DTOs replaced

compatibility layers eliminated

unused state managers removed

6.2 Debt Introduced (Should Be ZERO)

If ANY debt is introduced → executor must refuse unless PR includes remediation.

6.3 Immediate Remediation (MANDATORY)

If debt is introduced → PR must include complete removal here.

7. Tests
7.1 New Tests

List each new test and the exact behavior validated.

7.2 Updated Tests

List tests requiring modification and why.

7.3 Coverage Expectations

Specify the required coverage areas (builder pipeline, resolvers, queue, runner, etc.)

8. Documentation Updates

For each doc updated:

File: /docs/...
Sections Modified:
Summary of Changes:


Docs must align with architecture v2.6.

9. Acceptance Criteria (Binary Pass/Fail)

Examples:

Builder pipeline emits valid NJRs

Obsolete path X removed

Queue receives only NJRs

GUI displays correct previews

All tests pass

Docs updated

Architecture alignment maintained

10. Migration & Rollback Plan
10.1 Migration Steps

List sequential upgrade steps.

10.2 Rollback Plan

State exactly how to revert the changes.

11. Risks & Mitigations

List:

architectural divergence

regressions in builder, queue, or runner

loss of NJR determinism

reactivation of legacy functions

Mitigation strategies required.

✔️ END OF TEMPLATE — v2.6-E (EXECUTOR-SAFE EDITION)