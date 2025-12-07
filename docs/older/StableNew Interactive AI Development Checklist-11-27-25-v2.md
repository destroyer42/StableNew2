StableNew Interactive AI Development Checklist
Version 1.0 — Full Text
Purpose

This checklist enforces the safety rails needed when developing using AI agents (ChatGPT, Copilot). It keeps the project stable, avoids drift, and ensures all changes are traceable and reversible.

✨ Section A — Pre-PR Setup (Mandatory)
1. Create a Development Snapshot

Run:

python snapshot_gen.py


Record in your PR:

Snapshot filename

repo_inventory.json checksum

Starting commit hash

2. Define PR Scope

Answer these questions:

What SINGLE problem are we fixing?

What SINGLE file (or micro-cluster) will change?

What tests must pass?

What GUI behaviors must remain unchanged?

3. Identify Forbidden Files

Explicit list (example):

src/main.py
src/gui/main_window_v2.py
src/theme/theme_v2.py
src/pipeline/executor.py


Add any additional sensitive files.

4. Verify No Legacy Code Is Involved

Search:

(OLD)
_v1
legacy
deprecated


Ensure zero V1 imports in the target module.

✨ Section B — AI Development Session (“Codex Mode”)
1. Provide Codex the Guardrails

You must supply:

Full PR Template

Explicit target file(s)

The snapshot diff

Expected behavior

Tests that must pass

Forbidden files list

Codex must operate in “Surgical mode.”

2. Require Line-Level Patches

Ask for:

Exact diff

No extraneous whitespace changes

No renaming of unrelated variables

No reformatting of unmodified code

3. Validate Codex's Assumptions

Ask Codex:

“Which lines will you modify?”

“Which imports will you add/remove?”

“Which functions are affected?”

4. Demand a Reasoning Summary

Before applying:

Codex must explain each change

Each change must relate directly to the PR scope

✨ Section C — Post-Patch Validation
1. Run full test suite
pytest -q

2. Run static analysis
mypy src/
ruff check src/

3. Run WebUI-offline smoke test

Start the app without WebUI — it must not crash.

4. Run WebUI-online smoke test

Start the app with WebUI — dropdowns must populate and pipelines must run.

5. Update snapshot

Run snapshot_gen.py AGAIN and attach final snapshot name to PR.

✨ Section D — Merge Safety Checklist

Before merging a PR:

 Did this PR modify only the allowed files?

 Did the PR stay fully in scope?

 Do all tests pass?

 Does the app launch cleanly?

 Do dropdowns populate correctly?

 Does txt2img run successfully?

 Did we avoid all legacy files?

 Did we update documentation as needed?

 Did we create a final snapshot?

 Are no regressions detected?

Only then is the PR allowed to merge.

✨ Section E — Codex Safety Rules (MUST READ BEFORE EVERY SESSION)

Codex cannot refactor uncontrolled areas.

Codex cannot modify more lines than required.

Codex cannot invent files without approval.

Codex cannot rename symbols or classes.

Codex cannot write new subsystems.

Codex cannot touch legacy code.

Codex cannot restructure directories.

If Codex starts drifting → STOP immediately.

✨ Section F — Manual Safeguards
1. Keep Local Backups

Never delete old snapshots.

2. Lock Critical Files

Keep a list in CRITICAL_FILES.md.

3. Review Changes Before Running

Never run uninspected patches from any AI agent.

✨ Section G — Emergency Protocol (“AI Drift Detected”)

If you see:

Duplicate classes

Missing imports

Entire files rewritten

Indentation disasters

Tkinter magic arguments

Unexplained behavior

Do this:

Stop PR

Restore last snapshot

Regenerate repo_inventory

Re-issue a surgical PR prompt

✨ End of Interactive AI Development Checklist