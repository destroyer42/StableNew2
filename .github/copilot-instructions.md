# StableNew – GitHub Copilot Repository Instructions (V2/V2.5) (11/26/2025-1519)

These instructions tell GitHub Copilot how to work effectively in this repository.  
They are **repository-wide**, not task-specific. Copilot should trust these over ad-hoc guesses and only explore when something is missing or clearly outdated.

---

StableNewV2 — AGENT_INSTRUCTIONS.txt (Lightweight Version for Faster PR Execution)

Version: V2-P1

This file is designed to minimize Codex/Copilot cognitive load and maximize reliability and speed.

1. Everything Starts With the PR

For any task:

Do NOT infer

Do NOT explore

Do NOT reason about architecture

Do NOT consider other files

Only carry out the instructions in the PR provided.

2. File Boundaries

Modify ONLY files explicitly listed under:

Files to Modify


Never touch files under:

Forbidden Files


This prevents drift into GUI V2 scaffolding, main entrypoint, or pipeline executor.

3. Prohibited Behaviors (Absolute Rules)

No refactors

No renames

No moves

No deleting existing behavior

No new modules

No cross-layer changes

No “cleanup”

No “improvements”

No expanding functionality unless the PR states it

You must implement the PR exactly, no more.

4. Allowed Behaviors

Add or edit functions only as specified

Fill in TODOs the PR calls for

Update callbacks, event wiring, or controller flows only if in the allowed files list

Add small helper functions within the same file only if the PR calls for them

5. Snapshot Discipline

Every PR is anchored to a snapshot ZIP and repo_inventory.json.

Codex/Copilot must assume:

Snapshot = truth

All paths in snapshot are authoritative

Anything not in the snapshot is ignored

Do NOT attempt to reconstruct missing context or infer alternative designs.

6. Tests Define Done

The PR will list tests that must pass.
These are the only tests that matter for correctness.

7. Asking for Clarification

Agents must STOP if:

They cannot find a symbol

A required function does not exist

The PR steps contradict file contents

The implementation would require touching forbidden files

A dependency is unclear

Then request:
“Need clarification: <describe the ambiguity>”

Do NOT proceed with assumptions.

8. Examples of Correct Agent Behavior
GOOD

Add a new callback method exactly as described

Modify one method body without touching other methods

Add one import ONLY if the PR directly instructed it

Raise a clarification request when encountering missing definitions

BAD

Adding multiple helper methods “just in case”

Modifying styling, spacing, or formatting across unrelated lines

Refactoring stage card or controller classes

Creating new classes

9. Quick Compliance Checklist

Before submitting:

 Only allowed files modified

 Forbidden files untouched

 Diffs minimal

 PR steps implemented exactly

 Required tests pass

 No invented functions/classes

 No new behavior beyond scope

End of AGENT_INSTRUCTIONS.txt