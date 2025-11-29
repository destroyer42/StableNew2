# Testing Strategy v2  

---

## 1. Goals

- Enable **fast, reliable feedback** on every change.
- Protect critical behaviors (pipeline execution, cancellation, learning, randomizer parity, GUI wiring).
- Make it safe for AI assistants (e.g., Codex) to work on the codebase without breaking invariants.

This strategy replaces any prior ad‑hoc testing notes and aligns with the v2 architecture.

---

## 2. Test Layers

### 2.1 Unit Tests

- For:
  - Randomizer core.
  - Learning plan/runner/record modules.
  - PipelineRunner behavior (without network calls).
  - Controller configuration assembly and lifecycle transitions.
- Characteristics:
  - Fast, deterministic, no network, no filesystem dependencies where possible.

### 2.2 Integration Tests

- For:
  - Controller + PipelineRunner (using stub or mocked SD WebUI client).
  - Pipeline + Learning hooks (learning records written correctly).
  - GUI V2 + controller (button wiring, status bar updates).
- Characteristics:
  - May touch filesystem in a controlled way (e.g., temp dirs).
  - No real SD models required; API calls mocked.

### 2.3 GUI V2 Harness Tests

- Focused on:
  - Layout skeleton and panel construction.
  - Button wiring (Run, Stop).
  - Config roundtrips for stage cards.
  - StatusBarV2 progress/ETA behavior.
  - RandomizerPanelV2 variant count previews.

- These should:
  - Avoid heavy Tk dependencies where possible.
  - Skip gracefully if Tk is unavailable in CI environments.

### 2.4 Safety Tests

- Enforce:
  - No GUI imports from utils/randomizer.
  - Codex and other tools cannot inadvertently modify forbidden modules.
  - File IO is limited to known writers (StructuredLogger, LearningRecordWriter, etc.).

---

## 3. Directory Layout

- `tests/controller/` – controller and lifecycle tests.
- `tests/pipeline/` – pipeline runner and stage sequencing tests.
- `tests/gui_v2/` – new GUI tests; the only GUI tests run by default.
- `tests/gui_v1_legacy/` – archived GUI tests; not run by default.
- `tests/utils/` – randomizer and utilities.
- `tests/learning/` – learning plan, runner, record, adapter tests.
- `tests/safety/` – guard tests (imports, Codex wrappers, etc.).

---

## 4. Test Doctrine

- **Failing test first** for any behavioral change.
- **Small, composable tests** – each should validate one specific behavior or invariant.
- Prefer **pure functions** wherever possible (especially in randomizer and learning).

- For GUI V2:
  - Use fixture‑backed construction of StableNewGUI with dummy controllers.
  - Avoid real network calls or file IO.
  - Only test what is necessary to confirm correct wiring and layout.

---

## 5. AI Assistant Safety

To work safely with AI tools (e.g., Codex), we enforce the following via tests and scripts:

- Certain modules are **protected**:
  - They require explicit PRs and added tests to change (e.g., pipeline_runner, controller skeletons, learning records, randomizer core).
- Safety tests verify:
  - No new imports from GUI into utils.
  - No forbidden paths for file IO.
  - No direct network calls outside the API client layer.

Codex instructions and PR templates will:

- Remind the tool not to touch out‑of‑scope modules.
- Require test commands to be run and pasted into the PR description.
- Keep diffs small and constrained to the PR’s scope.

---

## 6. Performance Considerations

- The default `pytest` run should complete quickly enough for frequent local runs.
- Heavier integration tests can be grouped under a separate marker (e.g., `slow`) and run less frequently.
- Cluster tests (when added) should include a **loopback mode** that doesn’t require multiple physical machines.

---

## 7. Evolving the Test Suite

- When new subsystems are introduced (e.g., cluster scheduler, settings generator AI), update this strategy:
  - Add folders for new test domains.
  - Add safety tests for any sensitive new modules.
- When legacy tests become irrelevant, move them to an archive or delete them rather than letting them rot in the main suite.
- Queue domain tests validate Job/JobQueue ordering, status transitions, and SingleNodeJobRunner loopback execution without GUI or networking dependencies.

---

## 8. Summary

- v2 testing is about **clarity and confidence**, not sheer test count.
- Each new PR should add or update tests that clearly tie to user‑visible behavior or architectural invariants.
- The combination of unit, integration, GUI V2, learning, and safety tests provides guardrails for both human and AI contributors.
