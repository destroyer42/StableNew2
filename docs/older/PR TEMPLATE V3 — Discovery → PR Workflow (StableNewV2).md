PR TEMPLATE V3 — Discovery → PR Workflow (StableNewV2)

Version: V3 (Discovery-Driven)
Status: Authoritative
For: ChatGPT, Codex, GitHub Copilot
Purpose: Provide a fast, safe, deterministic structure for all StableNewV2 PRs under the Discovery → PR model.

1. PR Header
PR-ID:

(e.g., PR-021 or PR-021A if split)

Discovery Reference:

D-##
(Every PR must refer to a Discovery Result)

Scope / Subsystem(s):

(check all that apply)

 GUI V2

 Controller

 Pipeline

 API/WebUI

 Learning

 Randomizer

 Queue

 Cluster

 Tests

 Documentation

2. Baseline Snapshot (Required)

Baseline Snapshot ZIP:
StableNew-snapshot-YYYYMMDD-HHMMSS.zip

Baseline Inventory:
repo_inventory.json

✔︎ Codex/Copilot must treat these as the authoritative truth source.
✔︎ No reasoning or assumptions about earlier snapshots.

3. Summary (2–3 sentences)

State the purpose of the PR in plain language.
Example:

“This PR wires StageCard callbacks in the Pipeline tab to their corresponding AppController update methods, as scoped in D-05. This enables config roundtrip for txt2img, img2img, and upscale without touching the pipeline runner or forbidden GUI scaffolding.”

4. Problem Statement (Why This Exists)

Short description of the underlying issue or missing behavior, per Discovery.

Examples:

Missing callback wiring

Dropdown does not populate

Controller method not invoked

PipelineConfig not updated

Learning record not written

5. Goals (What This PR Will Do)

Bullet points. Example:

Implement the wiring identified in Discovery D-07

Add or update controller methods as scoped

Populate specific GUI elements

Update configuration roundtrip

Fix test failures related to this specific area

6. Non-Goals (What This PR Will NOT Do)

Short bullets. Prevents drift.

Will not refactor any GUI panels

Will not modify pipeline runner

Will not update theme_v2

Will not create new architecture

Will not modify forbidden files

7. Files to Modify (Exact Paths Only)

Codex may only touch these files.

<insert exact file list from Discovery>

8. Forbidden Files (Do Not Touch)

This list is always enforced. PR may add more, but never remove.

src/gui/main_window_v2.py
src/gui/theme_v2.py
src/main.py
src/pipeline/executor.py
src/pipeline/pipeline_runner.py
<+ any Discovery-specific forbiddens>


Codex must not modify these files under any circumstances.

9. Risk Level (From Discovery)

Choose one:

Low — GUI wiring, callbacks, simple logic, tests-only

Medium — controller-to-GUI contract updates, payload builder tweaks

High — pipeline runner, executor, threading, lifecycle, learning core, cluster

Risk Level determines how strictly Codex/Copilot must interpret guardrails.

10. Step-by-Step Implementation (Authoritative Instructions)

This is the only source of truth for Codex.
Each step must be atomic, surgical, and explicit.

Example format:

In src/gui/panels_v2/pipeline_panel_v2.py, update method on_sampler_changed to call:
self.controller.update_sampler(value)

In src/controller/app_controller.py, add method:

def update_sampler(self, value: str): 
    self.state.sampler = value


Update tests in tests/gui_v2/test_pipeline_panel_callbacks.py to assert state → GUI roundtrip.

11. Required Tests to Run (Must Stay Green)

Only the tests listed here matter for PR correctness.

pytest tests/<path>/<test_file>.py -q
<repeat for each test>


If tests are missing, PR must add them here.

12. Acceptance Criteria

All must be true for PR to be considered complete:

 Only allowed files modified

 All forbidden files untouched

 Implementation matches every step in Section 10

 All required tests pass

 App boots without Tk errors

 GUI V2 loads and displays affected widgets

 Pipeline config roundtrip works (if applicable)

 No regressions in dropdown population

 Snapshot remains valid

13. Rollback Plan

If this PR introduces errors:

Restore snapshot baseline

Revert modifications from allowed-file list

Re-run Phase-1 test suite

File a Discovery to re-scope solution

14. Codex Execution Constraints (Critical)

Codex and Copilot must:

Modify only files in Section 7

Never touch files in Section 8

Implement only what Section 10 specifies

Keep diffs minimal

Not create new classes or modules unless explicitly stated

Stop and request clarification if instructions require:

new APIs

cross-layer changes

missing symbols

ambiguous behavior

15. Smoke Test Checklist

The human or automated agent must verify:

 Run main.py successfully loads GUI V2

 Affected GUI components render without exceptions

 Dropdown selections or callbacks work as intended

 Pipeline executes at least one simple txt2img run if relevant

 No new console errors or warnings

End of PR TEMPLATE V3

Fully compatible with:

Discovery workflow

StableNew PR governance

Architecture V2

Snapshot discipline

Codex/Copilot safety rules