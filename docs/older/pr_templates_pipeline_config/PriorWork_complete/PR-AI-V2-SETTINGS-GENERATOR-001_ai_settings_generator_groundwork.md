# PR-AI-V2-SETTINGS-GENERATOR-001 — AI Settings Generator Groundwork

## Status

- **Type:** Feature groundwork / contracts
- **Scope:** `src/ai/*`, `src/learning/*`, `src/controller/*`, `tests/ai_v2/*`, docs
- **Pipeline Impact:** None (no change to image outputs yet)
- **GUI Impact:** Minimal (wiring for future “Ask AI” button; button may remain disabled/hidden by default)

---

## 1. Problem & Goals

We now have:

- A **learning stack** that records pipeline runs and user feedback.
- A **V2 pipeline and stage sequencer** that exposes clean config snapshots per run.
- A **V2 GUI** that separates core pipeline config, randomizer, and status.

What we lack is a **structured way to ask an AI system for better settings**, using:

- the user’s existing packs/configs,
- the models/Loras/embeddings available on disk,
- the historical run + feedback dataset,
- and the desired “One‑click action” (e.g., “crisp character portrait”, “fast concept thumbnails”).

This PR does **not** call any external LLM services. Instead, it defines a **pluggable AI Settings Generator contract** and the data pipelines needed so a future LLM client can be slotted in with minimal code churn.

### Goals

1. Introduce a **stable, versioned contract** for AI‑driven configuration suggestions.
2. Provide a small **adapter layer** between learning records and the AI settings generator so that prompt packs, stages, and user feedback can be fed in consistently.
3. Wire a **non-blocking, GUI‑safe path** for “Ask AI for settings” that:
   - can be stubbed and tested now,
   - can be upgraded later to call a real LLM without changing GUI code.

### Non‑Goals

- No integration with any specific LLM provider in this PR.
- No automatic modification of live pipeline configs without explicit user confirmation.
- No changes to the randomizer algorithms; this PR only **suggests configs**, not variants.

---

## 2. High‑Level Design

### 2.1 Core Idea

We introduce **AI Settings Suggestions** as a distinct concept:

- Input:
  - A **target prompt pack** (or freeform prompt),
  - Available models/Loras/VAEs/etc. (capabilities snapshot),
  - Recent **run + feedback records**,
  - The user’s intent / “one‑click action” (e.g., “hero portrait”, “quick thumbnails”, “high-detail upscale”).

- Output:
  - A **SettingsSuggestion** object that includes:
    - per‑stage configs (txt2img/img2img/upscale),
    - suggested overrides for sampler/steps/CFG/scheduler,
    - optional comments/rationale for UI display.

This is expressed as pure dataclasses and JSON‑serializable dicts. A later PR can bind these contracts to a real LLM client.

### 2.2 Architecture Placement

New components:

- `src/ai/settings_generator_contract.py`
  - Dataclasses for `SettingsSuggestionRequest`, `SettingsSuggestion`, `StageSuggestion`, etc.
  - Enum(s) for `SuggestionIntent` (e.g., “FAST_DRAFT”, “HIGH_QUALITY_PORTRAIT”).

- `src/ai/settings_generator_driver.py`
  - An abstract interface `SettingsGenerator` and a **LocalStubSettingsGenerator** implementation.
  - The stub may:
    - echo back the baseline config,
    - tweak a few fields deterministically for tests,
    - never call external APIs.

- `src/ai/settings_generator_adapter.py`
  - Bridges learning records + capabilities + prompt pack into `SettingsSuggestionRequest`.
  - Collects data from:
    - `src/learning/learning_record.py`,
    - `src/learning/dataset_builder.py`,
    - and a future “capabilities snapshot” source (for now, stubbed).

- `src/controller/settings_suggestion_controller.py`
  - Small controller wrapper that:
    - owns a `SettingsGenerator` instance,
    - exposes “request suggestion” and “apply suggestion to config” helpers,
    - stays independent from Tk/Tcl (GUI calls it via adapters).

GUI integration:

- `StableNewGUI` will optionally expose a **“Ask AI for Settings”** action that calls the controller method.
- This PR should only add the **plumbing and a disabled/hidden button**, depending on a feature flag or environment variable.

---

## 3. Detailed Changes

> Codex: use symbol names and docstrings as anchors, not line numbers.

### 3.1 Contracts: AI Settings Generator

**File:** `src/ai/settings_generator_contract.py`

- Define versioned dataclasses:
  - `SuggestionIntent` enum (e.g., `FAST_DRAFT`, `HIGH_DETAIL`, `PORTRAIT`, `LANDSCAPE`, `ANIMATION_FRAME`).
  - `StageSuggestion` with:
    - `stage_name` (e.g., "txt2img", "img2img", "upscale"),
    - `config_overrides: dict[str, object]`,
    - optional `notes: str`.
  - `SettingsSuggestionRequest` with:
    - `intent: SuggestionIntent`,
    - `prompt_text: str`,
    - `pack_id: str | None`,
    - `baseline_config: dict[str, object]`,
    - `recent_runs: list[LearningRecord]` (or a derived lightweight type),
    - `available_capabilities: dict[str, object]`.
  - `SettingsSuggestion` with:
    - `stages: list[StageSuggestion]`,
    - `global_notes: str | None`,
    - `internal_metadata: dict[str, object]` (for traceability).

- Include JSON (de)serialization helpers to ensure round‑tripping is deterministic.

### 3.2 Driver: Stubbed Settings Generator

**File:** `src/ai/settings_generator_driver.py`

- Define abstract `SettingsGenerator` interface with methods like:
  - `generate_suggestion(request: SettingsSuggestionRequest) -> SettingsSuggestion`
- Implement `LocalStubSettingsGenerator` that:
  - copies `baseline_config`,
  - applies a small, deterministic tweak per `SuggestionIntent` (e.g., more steps + CFG for HIGH_DETAIL),
  - logs a clear note that it is stubbed (for test inspection).

### 3.3 Adapter: From Learning Stack to AI Request

**File:** `src/ai/settings_generator_adapter.py`

- Provide helper functions:
  - `build_request_from_learning_data(intent, pack, baseline_config, dataset_snapshot) -> SettingsSuggestionRequest`
  - `summarize_capabilities_for_request(...) -> dict[str, object]`
- Integrate with:
  - `src/learning/dataset_builder.py` to get a small window of recent runs for the selected pack.
  - `src/learning/learning_record.py` for record structure.
- All logic here must remain **Tk-free** and **pipeline-executor-free**.

### 3.4 Controller: Settings Suggestion Controller

**File:** `src/controller/settings_suggestion_controller.py`

- Implement a small controller that:
  - accepts a `SettingsGenerator` (dependency-injected, default = `LocalStubSettingsGenerator`),
  - exposes methods:
    - `request_suggestion(intent, pack, baseline_config) -> SettingsSuggestion`,
    - `apply_suggestion_to_config(baseline_config, suggestion) -> dict[str, object]`.
- Ensure it does not import Tk/Tcl; it should be tested in isolation.

### 3.5 GUI: Optional Hook for “Ask AI”

**File:** `src/gui/main_window.py` (V2 section)

- Introduce a guarded hook (pseudocode):
  - feature flag: `ENABLE_AI_SETTINGS_GENERATOR` (env var or config).
  - if enabled:
    - create a small “Ask AI” button in the pipeline or learning context menu,
    - wire it to a helper `_on_ask_ai_for_settings_clicked` that:
      - gathers current pack + baseline config (via existing V2 adapters),
      - calls the settings suggestion controller (on a background thread if needed),
      - applies the suggestion only after user confirmation (simple dialog or log message for now).
- For this PR, it is acceptable if the button is **off by default** in production and only used in tests / internal runs.

### 3.6 Tests

**Directory:** `tests/ai_v2` (new)

Add the following tests:

1. `test_settings_generator_contract_roundtrip.py`
   - Validates JSON (de)serialization for `SettingsSuggestionRequest` and `SettingsSuggestion`.
   - Asserts version field presence if added.

2. `test_local_stub_settings_generator_behavior.py`
   - Ensures `LocalStubSettingsGenerator`:
     - returns deterministic changes for each `SuggestionIntent`,
     - never throws on missing optional fields.

3. `test_settings_generator_adapter_from_learning.py`
   - Uses a small fake dataset from `tests/learning` to build a request,
   - Asserts that prompt, baseline_config, and recent run excerpts are correctly included.

4. `test_settings_suggestion_controller_apply.py`
   - Verifies that `apply_suggestion_to_config` produces a merged config with stage overrides,
   - Ensures no mutation of the original baseline config dict.

5. GUI‑aware smoke test (in `tests/gui_v2`)
   - `test_gui_v2_ai_settings_button_guarded.py`
     - With feature flag off: button absent or disabled.
     - With feature flag on + stub generator: clicking the action triggers controller call and logs a summary.

### 3.7 Safety

- Add safety test: `tests/safety/test_ai_settings_generator_no_tk_imports.py`:
  - Asserts that `src/ai/*` and `src/controller/settings_suggestion_controller.py` do not import Tk/Tcl modules.

---

## 4. Acceptance Criteria

- [ ] Settings generator contracts exist and are JSON‑roundtrippable.
- [ ] Local stub generator can produce deterministic suggestions for all defined intents.
- [ ] Adapter can build a valid `SettingsSuggestionRequest` from learning/dataset data.
- [ ] Settings suggestion controller can merge stage overrides onto a baseline config without in‑place mutation.
- [ ] GUI V2 can optionally expose an “Ask AI for Settings” button, guarded behind a feature flag.
- [ ] All new tests in `tests/ai_v2` pass.
- [ ] `pytest tests/gui_v2 -v`, `pytest tests/learning* -v`, `pytest tests/safety -v`, and `pytest -v` all pass, with only previously agreed XFAILs.

---

## 5. Test Plan

1. Run focused suites:
   - `pytest tests/ai_v2 -v`
   - `pytest tests/gui_v2/test_gui_v2_ai_settings_button_guarded.py -v`
2. Regression:
   - `pytest tests/learning -v`
   - `pytest tests/learning_v2 -v`
   - `pytest tests/gui_v2 -v`
   - `pytest tests/safety -v`
   - `pytest -v`

---

## 6. Risks & Rollback

### Risks

- Poorly chosen initial contracts may require refactors once a real LLM is integrated.
- If the GUI hook is misconfigured, users might see an “Ask AI” button that still uses stub behavior.

### Rollback

- Revert all new files under `src/ai/` and `src/controller/settings_suggestion_controller.py`.
- Remove the feature flag and GUI button wiring from `src/gui/main_window.py`.
- Remove new tests under `tests/ai_v2` and related GUI/safety tests.

No changes to learning records or existing pipelines are persistent; no data migration is required.

---

## 7. Follow‑On Work

- Implement a real LLM-backed `SettingsGenerator` that uses the contracts defined here.
- Add Pack‑specific “One‑click action” presets (e.g., “Portrait lock-in”, “Landscape thumbnails”) that call the generator with appropriate intents.
- Tighten integration with the **learning runs and feedback flows**, so that suggested configs can be validated and improved over time.
