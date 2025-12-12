Timestamp: 2025-11-22 19:01 (UTC-06:00)
PR Id: PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001
Spec Path: docs/pr_templates/PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md

# PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001  
**Title:** Finish PipelineConfigAssembler Enforcement (Controller & GUI Rewire)  

---

## 1. Summary

This PR **finishes PR-#46** by wiring the existing `PipelineConfigAssembler` into all production run paths and making it the **single source of truth** for pipeline configuration.

Today, the assembler exists and is partially used (GUI overrides, megapixel clamp, learning/randomizer metadata stubs), but the controller still constructs configs ad‑hoc, and the enforcement test fails (`test_pipeline_controller_config_path.py::test_controller_uses_assembler_for_runs`).

This PR:

- Rewrites the controller’s run paths (direct and queue‑backed) to **always** call `PipelineConfigAssembler` before executing or enqueuing a pipeline run.
- Ensures GUI V2 adapters only provide structured **GuiOverrides** (or equivalent) and never build configs directly.
- Ensures learning and randomizer flows attach their metadata **via the assembler**, not manual dict patching.
- Gets the enforcement tests and invariants green without touching queue, job history, or cluster internals.

After this PR, **all real pipeline runs** go through:

> GUI → Adapter → Controller → PipelineConfigAssembler → Runner/Queue → Pipeline

and the failing controller‑assembler test passes.

---

## 2. Problem Statement

From PR-#46’s current state (verified in the 2025-11-22-18:15 snapshot):

- `PipelineConfigAssembler` is present and implements:
  - `build_from_gui_input(...)` with megapixel clamp and metadata attachment.
  - `build_for_learning_run(...)` and helpers.
- `pipeline_adapter_v2` now emits **structured overrides** instead of building configs directly.
- However, `PipelineController` still:
  - Uses legacy patterns where it accepts a `pipeline_func` that returns an ad‑hoc dict.
  - Does **not** call the assembler in its main run path.
- The enforcement test is failing by design:
  - `tests/controller/test_pipeline_controller_config_path.py::test_controller_uses_assembler_for_runs` expects the controller to call `build_from_gui_input`, but it does not.

This leaves the system in a transitional state where:

- Some code treats PipelineConfig as first‑class, but
- The primary run entrypoint is not guaranteed to produce a config via the assembler.
- Megapixel clamps, learning metadata, and randomizer metadata are not enforced for all runs.

We need to finish the integration so **all production runs** use the assembler and the test suite becomes green again.

---

## 3. Goals

1. **Enforce assembler usage**  
   Guarantee that **every** pipeline run (txt2img, img2img, upscale, learning, randomizer/matrix, queue‑backed) uses `PipelineConfigAssembler` to construct `PipelineConfig`.

2. **Remove ad‑hoc config construction**  
   Eliminate direct dict‑based config building in `PipelineController` and GUI adapters for production paths.

3. **Preserve queue and history behavior**  
   Keep PR-#35–#45 behavior intact:
   - JobQueue semantics (priority + FIFO)
   - QueueExecutionController contract
   - JobHistoryStore/JobHistoryService
   - Worker/cluster foundations

4. **Enforce invariants**  
   Use the assembler to enforce:
   - Megapixel/size clamps from `PIPELINE_RULES.md`  
   - Consistent attachment of learning and randomizer metadata

5. **Make tests green**  
   Get:
   - `test_pipeline_controller_config_path.py`  
   - `test_pipeline_config_assembler.py`  
   - `test_pipeline_adapter_roundtrip.py`  
   - `test_pipeline_config_invariants.py`  
   and the full suite passing.

---

## 4. Non-goals

- No changes to:
  - Queue core internals (`job_queue`, `single_node_runner`, priority logic).
  - JobHistory store semantics (append, JSONL format, view models).
  - Worker registry and cluster controller behavior.
  - GUI layout/visual design (AppLayoutV2, window geometry, theming).

- No new pipeline stages or WebUI API behavior changes.
- No changes to the learning/rand specs beyond wiring metadata into configs per existing structures.

---

## 5. Allowed vs Forbidden Files

**Allowed files (expected touch points):**

- Controller / assembler:
  - `src/controller/pipeline_controller.py`
  - `src/controller/pipeline_config_assembler.py` (small adjustments only; no redesign)

- GUI adapters (no layout changes):
  - `src/gui/pipeline_adapter_v2.py` (or the actual V2 pipeline adapter module used in this snapshot)
  - `src/gui/controller.py` (only if needed to pass overrides cleanly to the controller)

- Learning / randomizer (wiring only):
  - `src/controller/learning_execution_controller.py`
  - `src/learning/learning_execution_runner.py` (if it constructs configs directly)
  - `src/randomizer/randomizer_controller.py` or equivalent (if it constructs configs directly)

- Tests:
  - `tests/controller/test_pipeline_controller_config_path.py`
  - `tests/controller/test_pipeline_config_assembler.py`
  - `tests/gui_v2/test_pipeline_adapter_roundtrip.py`
  - `tests/pipeline/test_pipeline_config_invariants.py`
  - Any small, directly related test helpers under `tests/controller`, `tests/gui_v2`, or `tests/pipeline` needed to keep invariants honest.

- Docs:
  - `docs/PIPELINE_RULES.md`
  - `docs/ARCHITECTURE_v2_COMBINED.md`
  - `docs/codex_context/ROLLING_SUMMARY.md`

**Forbidden (do not touch in this PR):**

- `src/queue/*` (queue internals, job_queue, job_history_store, single_node_runner).
- `src/controller/job_history_service.py` (beyond trivial type import alignment if absolutely necessary).
- `src/controller/job_execution_controller.py` (no behavioral changes).
- `src/controller/cluster_controller.py`, `src/cluster/*`.
- `src/gui/app_layout_v2.py` and `src/gui/main_window.py` (no layout or wiring changes beyond what is absolutely necessary for adapter/controller signature alignment; avoid if possible).
- Any WebUI API client modules under `src/api/`.
- Any files under `docs/` other than the three explicitly allowed above.

If you discover that another file must be changed to satisfy a compile error, **stop and document it** before editing.

---

## 6. Step-by-step Implementation Plan

### 6.1 Normalize the assembler API (minimal tuning)

**File:** `src/controller/pipeline_config_assembler.py`

- Confirm/ensure the following signatures exist and are stable:

  - `class GuiOverrides: ...` (or equivalent; do not rename public fields used by tests).
  - `class PipelineConfigAssembler:`
    - `def build_from_gui_input(self, overrides: GuiOverrides, *, learning_metadata: LearningMetadata | None = None, randomizer_metadata: RandomizerMetadata | None = None) -> PipelineConfig`
    - `def build_for_learning_run(self, overrides: GuiOverrides, learning_metadata: LearningMetadata) -> PipelineConfig`
    - `def apply_megapixel_clamp(self, config: PipelineConfig) -> PipelineConfig`
    - `def attach_randomizer_metadata(self, config: PipelineConfig, randomizer_metadata: RandomizerMetadata) -> PipelineConfig`

- Ensure `build_from_gui_input(...)`:
  - Applies megapixel clamp from `PIPELINE_RULES.md`.
  - Attaches `metadata["learning"]` and/or `metadata["randomizer"]` when metadata objects are provided.
  - Does not assume any GUI widget objects—only uses `GuiOverrides` and base/default config.

> **Rule:** Do not refactor the assembler significantly; only align signatures and behavior with tests and docs where needed.

---

### 6.2 Rewire PipelineController to always use the assembler

**File:** `src/controller/pipeline_controller.py`

- Replace the legacy “`pipeline_func` returns a dict” run path with an **assembler‑driven** path. Suggested pattern:

  1. Introduce a controller method like:

     - `def _build_pipeline_config_from_state(self) -> PipelineConfig:`  

       - Reads current GUI‑driven or stored overrides (through the adapter/controller bridge that already exists or via a passed‑in `GuiOverrides`).
       - Calls `self._config_assembler.build_from_gui_input(overrides, learning_metadata=..., randomizer_metadata=...)`.

  2. Update the direct run path (non‑queue) to:

     - Build a `PipelineConfig` via `_build_pipeline_config_from_state()`.
     - Pass that `PipelineConfig` into the pre‑existing pipeline runner / job execution layer.

  3. Update the **queue‑backed** path (from PR-#45) to:

     - Build the same `PipelineConfig` first.
     - Submit the `PipelineConfig` as the job payload to `QueueExecutionController.submit_pipeline_job(config)` or its equivalent, rather than raw dicts or ad‑hoc payloads.

  4. Ensure learning and randomizer scenarios also go through this path (see 6.3).

- Delete or migrate any remaining code that:
  - Accepts a `pipeline_func: Callable[[], dict]` for production use.
  - Manually constructs config dicts for txt2img/img2img/upscale runs.

> **Key invariant:** After this PR, any real pipeline run observable from GUI or controllers must be able to trace its config back to `PipelineConfigAssembler`.

---

### 6.3 Wire learning and randomizer flows to the assembler

**Files (as needed):**
- `src/controller/learning_execution_controller.py`
- `src/learning/learning_execution_runner.py`
- `src/randomizer/randomizer_controller.py` (or equivalent)

- For learning runs that previously built special configs:

  - Replace manual config construction with calls to:

    - `PipelineConfigAssembler.build_for_learning_run(overrides, learning_metadata)`
      or
    - `PipelineConfigAssembler.build_from_gui_input(overrides, learning_metadata=...)`

- For randomizer/matrix runs:

  - For each variant, build a `PipelineConfig` via `build_from_gui_input` with `randomizer_metadata` populated (e.g., run ID, matrix cell info).

> **Do not** introduce separate config code paths for learning or randomizer; they must all go through the assembler.

---

### 6.4 Ensure GUI V2 adapters only pass overrides, not configs

**File:** `src/gui/pipeline_adapter_v2.py` (or equivalent)

- Confirm that the adapter:

  - Reads widget state (prompt, width, height, sampler, steps, CFG, model, etc.).
  - Builds a `GuiOverrides` (or similar) structure.
  - Passes that structure to the controller via a clear call (for example, `controller.request_run_with_overrides(overrides)` or by setting state that `_build_pipeline_config_from_state()` reads).

- Remove any remaining code that:

  - Constructs full pipeline configs or mutable dicts intended to be passed directly into the pipeline.

> If you must adjust the controller’s public interface (for example to accept `GuiOverrides` explicitly), keep the change minimal and update only the necessary call sites in the GUI adapter and tests.

---

### 6.5 Documentation updates

**Files:**

- `docs/PIPELINE_RULES.md`

  - Update the configuration section to state explicitly:
    - All production pipeline configs are constructed by `PipelineConfigAssembler`.
    - Megapixel limits and related safety rules are enforced there.
    - Learning and randomizer metadata are attached in the assembler.

- `docs/ARCHITECTURE_v2_COMBINED.md`

  - Update the pipeline flow diagram/section to match:
    - GUI → Adapter → Controller → PipelineConfigAssembler → Runner/Queue → Pipeline.

- `docs/codex_context/ROLLING_SUMMARY.md`

  - Append the Rolling Summary block from this PR (see section 10) under the appropriate date.

---

## 7. Required Tests (Failing First → Green)

Run these in order and ensure each is green at the end.

1. **Targeted enforcement tests**

   - `pytest tests/controller/test_pipeline_controller_config_path.py -v`
   - `pytest tests/controller/test_pipeline_config_assembler.py -v`

   Expectation:
   - `test_controller_uses_assembler_for_runs` now passes:
     - Assembler’s `build_from_gui_input` is called for production run paths.
   - Assembler tests confirm megapixel clamp + metadata behavior.

2. **GUI adapter roundtrip**

   - `pytest tests/gui_v2/test_pipeline_adapter_roundtrip.py -v`

   Expectation:
   - For representative GUI inputs, the adapter→controller→assembler pipeline produces `PipelineConfig` objects with correct fields and clamped sizes when needed.

3. **Pipeline invariants**

   - `pytest tests/pipeline/test_pipeline_config_invariants.py -v`

   Expectation:
   - All configs produced by the assembler (and used by the controller and queue) respect width/height/MP constraints and required fields.

4. **Full regression sweep**

   - `pytest tests/controller -v`
   - `pytest tests/gui_v2 -v`
   - `pytest tests/pipeline -v`
   - `pytest -v`

   Expectation:
   - All pass.
   - No new xfails or skips beyond the known Tk‑unavailable skip.

If any test fails:

- Summarize the failure.
- Apply the **smallest** possible fix consistent with this PR’s scope.
- Re‑run the affected tests and document the updated results.

---

## 8. Acceptance Criteria

This PR is considered complete when:

1. **Assembler enforcement**  
   - All production pipeline run paths (including queue mode, learning, and randomizer) construct `PipelineConfig` via `PipelineConfigAssembler` and no longer build configs directly.

2. **Tests**  
   - `tests/controller/test_pipeline_controller_config_path.py` is green.
   - `tests/gui_v2/test_pipeline_adapter_roundtrip.py` is green.
   - `tests/pipeline/test_pipeline_config_invariants.py` is green.
   - Full `pytest` run passes (modulo the known Tk skip).

3. **Invariants**  
   - Megapixel clamp and size rules from `PIPELINE_RULES.md` are enforced for all runs.
   - Learning and randomizer metadata are present where expected and attached via the assembler.

4. **Docs and Rolling Summary**  
   - `PIPELINE_RULES.md` and `ARCHITECTURE_v2_COMBINED.md` reflect the new enforced flow.
   - `docs/codex_context/ROLLING_SUMMARY.md` has the new entry for PR-#47.

---

## 9. Rollback Plan

If this PR causes issues (for example, unexpected pipeline behavior or widespread test failures):

1. Revert changes to:
   - `src/controller/pipeline_controller.py`
   - `src/controller/pipeline_config_assembler.py` (only the deltas introduced by this PR)
   - `src/gui/pipeline_adapter_v2.py`
   - Any learning/randomizer controller wiring touched
   - The associated tests and docs

2. Restore behavior to the last known good snapshot:
   - The 2025-11-22-18:15 snapshot, where:
     - Assembler existed but was not enforced.
     - Queue/cluster/history were working.
     - Only the enforcement test was failing.

3. Re‑run:
   - `pytest -v` to confirm baseline is restored.

Because this PR is primarily wiring/contract work, rollback is straightforward and low‑risk.

---

## 10. Codex Execution Constraints

When implementing this PR, Codex must:

- **Follow this spec strictly.**
- **Not** modify forbidden files.
- Keep diffs **surgical and small**, focused on controller run paths, assembler usage, GUI adapter wiring, and the listed tests/docs.
- Always run the tests listed in section 7 and paste full output.
- If it encounters ambiguity (e.g., multiple possible adapter files), it must:
  - Inspect the existing code and tests.
  - Choose the smallest, least invasive option that satisfies the PR’s requirements.

Do **not** introduce new abstractions or layers unless strictly necessary to satisfy the tests and architecture rules.

---

## 11. Smoke Test Checklist (post-merge)

After this PR is merged and tests are green, perform a manual smoke test (via StableNew GUI) on a dev machine:

1. Start `python -m src.main`.
2. Launch WebUI if not auto‑started and confirm API connectivity.
3. Run a **basic txt2img** job:
   - Confirm it completes successfully.
   - Confirm logs show a `PipelineConfig` being built via assembler (diagnostic logging if available).
4. Run with:
   - A larger resolution that should trigger megapixel clamp.
   - A learning‑enabled run (if GUI wiring is in place).
   - A randomizer/matrix run (if available in GUI at this stage).
5. Confirm no crashes in controller, queue, or GUI, and that generated images look consistent with expectations.

---

## 12. Rolling Summary Update (for `docs/codex_context/ROLLING_SUMMARY.md`)

Append the following under the appropriate date (for example, `## 2025-11-22`):

- Completed **PipelineConfigAssembler enforcement** by rewiring `PipelineController` (and learning/randomizer paths) so that all production pipeline runs construct `PipelineConfig` via the assembler, eliminating ad‑hoc config assembly.
- Updated GUI V2 pipeline adapter wiring so that it supplies structured overrides rather than building configs directly, and validated adapter→controller→assembler roundtrips with new/extended tests.
- Strengthened pipeline invariants and documentation: megapixel clamp and learning/randomizer metadata are now centrally enforced in the assembler, and full controller/gui/pipeline test suites pass with the new config flow.
