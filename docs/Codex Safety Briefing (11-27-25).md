1. Codex Safety Briefing (for you / future you / any AI agent)

You can drop this into docs/CODEX_SAFETY_BRIEFING.md and link it from PR templates.

Codex Safety Briefing — StableNew

Purpose:
Keep StableNew moving fast without blowing up the repo every third PR.

This briefing applies to all AI agents (Codex, Copilot, ChatGPT, etc.) working on StableNew.

1. Prime Directive

Do not change more than you can fully understand and verify.
If a change touches many files, it’s probably the wrong change.

AI work must be:

Small – one concern at a time

Local – one file or tightly related pair

Reversible – always backed by a snapshot

Tested – at least the relevant test subset must run

2. Snapshot Before You Touch Anything

Before starting any non-trivial change:

Run the snapshot tool from the repo root:

python stablenew_snapshot_and_inventory.py


Note the generated files:

snapshots/StableNew-snapshot-YYYYMMDD-HHMMSS.zip

snapshots/repo_inventory.json

In your PR description, record:

Snapshot used as baseline: StableNew-snapshot-YYYYMMDD-HHMMSS.zip

No snapshot = no green light for a big Codex session.

3. Scope: File-Level, Not “Repo-Wide Magic”

Every Codex/LLM task should look like:

“Modify this file to do X.”

“Modify these 2–3 files that all live under src/gui/ to do Y.”

Hard rule:

❌ No “refactor the whole repo” prompts

❌ No “update all usages of X across the codebase” in a single pass

✅ Yes to “update this function and adjust the 2 direct callers I show you.”

If a change affects more than ~3 files, split it into multiple PRs.

4. Core Files Are Locked by Default

There are core / dangerous files that must not be edited unless explicitly unlocked:

src/main.py

src/app_factory.py

src/controller/app_controller.py (except in very targeted PRs)

src/pipeline/executor.py

src/api/client.py

src/gui/main_window_v2.py

src/gui/theme_v2.py

When writing Codex prompts, always include:

“Do not modify: src/main.py, src/app_factory.py, src/pipeline/executor.py, src/gui/main_window_v2.py, src/gui/theme_v2.py, except where explicitly allowed.”

If you must touch one of these, the entire PR should be only about that file (plus its tests).

5. Tests: The Minimum Contract

For any change that touches:

WebUI API / healthcheck / resources → run:

pytest tests/api -q


Controller / pipeline wiring → run:

pytest tests/controller -q
pytest tests/pipeline -q


GUI widgets / layout → run:

pytest tests/gui -q


Entry points / high-level behavior → run:

pytest -q


If tests fail:

Stop.

Capture the full error text.

Roll back or narrow the change.

Never try to “fix” failing tests by editing them unless the test is clearly wrong and the change is intentional.

6. No Silent Type/System Changes

AI agents must not:

Change dataclass fields or signatures without checking all usages.

Rename config keys or API payload fields casually.

Change defaults for core pipeline behavior without calling it out in the PR.

If a config shape or contract is changed:

Update type hints

Update tests

Update any docstring / docs mentioning it.

7. GUI Guardrails

Tkinter/ttk are fragile. Rules:

Do not pass non-Tk options to widget constructors (e.g., config_manager=...); attach as attributes instead.

All GUI writes must go through AppController or a well-defined callback.

Stage cards must follow a clear contract:

They receive a controller reference.

They read/write config only via controller or config objects.

No direct pipeline or WebUI calls from the GUI.

8. Controller as the Router

All flows must look like:

GUI → AppController → Pipeline/Executor → WebUI

Not:

GUI → WebUI directly
GUI → random helper that writes to disk

If you find direct WebUI calls from GUI code, the correct fix is to:

Move that logic into AppController or a dedicated service.

Have GUI call the controller/service instead.

9. Commentary & Logging

Every non-trivial PR should include:

A short summary of what changed and why

Notes on:

Which tests were run

Which snapshot was used as the baseline

Any new constraints or assumptions

Logging:

Use existing loggers and patterns.

Do not spray print() across the codebase.

Prefer structured, leveled logging (DEBUG, INFO, WARNING, ERROR).

10. Escape Hatch: When Things Go Sideways

If a Codex session goes bad:

Stop.

Run the snapshot tool again to capture the broken state (for autopsy if needed).

Roll back to the last known-good snapshot or Git commit.

Narrow the scope and try again with a tighter prompt.

Remember: Snapshots are your parachute. Use them.