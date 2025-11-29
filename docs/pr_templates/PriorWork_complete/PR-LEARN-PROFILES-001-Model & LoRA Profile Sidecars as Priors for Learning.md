PR-LEARN-PROFILES-001: Model & LoRA Profile Sidecars as Priors for Learning
1. Title

PR-LEARN-PROFILES-001: Model & LoRA Profile Sidecars as Priors for Learning

2. Summary

This PR introduces ModelProfile and LoraProfile sidecar files as structured “priors” for StableNew’s Learning system, allowing you to:

Attach recommended presets (sampler, scheduler, steps, CFG, resolution, LoRA pairings) to base models and LoRAs.

Seed those presets from external knowledge (e.g., internet best practices) while keeping LearningRecords as the canonical historical record.

Provide a controller-level API to lookup suggested presets for a given base model + LoRA combination, without GUI coupling.

It does not change how pipelines execute today; instead, it lays the foundation for future PRs to:

Surface “Good / Better / Best” presets in the GUI.

Update profiles over time based on LearningRecords (profile updater / aggregator).

3. Problem Statement
3.1 Context

StableNew’s Learning v2 design already defines:

LearningRecords as append-only JSONL capturing config + outputs + ratings.

LearningPlans / LearningExecutionRunner as the machinery to run targeted experiments.

However, today there is no structured way to:

Express known good starting points for a particular model or LoRA (e.g., “RealVisXL + PerfectEyesXL works best with DPM++ 2M Karras, 30 steps, CFG ~6.5, LoRA weight ~0.6”).

Distinguish between:

External priors (community/internet knowledge).

Local learning-derived presets (what your rig and taste found effective).

As a result:

Every new model or LoRA is “cold start”: the user must rediscover basic good settings manually.

LearningRecords accumulate, but there’s no structured place to summarize “this preset is usually good/better/best for this model/LoRA”.

3.2 Architectural Constraints

Per Architecture v2 and Learning System Spec:

Learning logic lives in learning / utils, not in GUI.

Controllers assemble PipelineConfig and integrate learning hooks.

LearningRecords must remain append-only; any “summary” artifacts should be derived and regenerable, not the source of truth.

We need a small, well-scoped layer that:

Encapsulates model/LoRA priors in structured sidecar files.

Provides a pure-function API to convert “model + LoRAs” → “suggested pipeline defaults”.

Fits cleanly into the existing layering.

4. Goals

Define ModelProfile and LoraProfile data structures and JSON sidecar schema, co-located with existing model/LoRA files.

Implement a profile loader API in src/learning that can:

Discover and load sidecars from the filesystem.

Return strongly typed profile objects or safe defaults when missing.

Implement a profile-based preset suggestion helper that:

Accepts base model name + optional list of LoRA names.

Returns a “recommended preset” (sampler, scheduler, steps, CFG, resolution, LoRA weights) suitable for building a PipelineConfig.

Provide a controller-level adapter that:

Uses the new profile API when assembling a pipeline config for a model + LoRA combination.

Is callable from the GUI in a future PR, but does not introduce GUI dependencies here.

Add tests to:

Verify profile parsing and defaults.

Verify preset suggestion logic given known example profiles.

Verify controller integration remains headless and architecture-compliant.

5. Non-goals

No GUI changes in this PR:

No new widgets or “Good/Better/Best” dropdowns yet.

No changes to the existing GUI layout or V2 harness tests.

No LearningRecord writer changes:

LearningRecords remain unchanged; profile updater / aggregator will be a separate PR.

No new pipeline behavior:

PipelineRunner, stage sequencing, and PipelineConfig semantics remain identical.

No external web access:

“Internet priors” are out-of-band content you create and save as sidecars; the code does not fetch from the internet.

6. Allowed Files

Codex may modify only the following (or equivalent paths if names differ slightly):

Learning / Profiles (new)

src/learning/model_profiles.py (new)

src/learning/__init__.py (only to export new types/helpers if needed)

Controller Integration (minimal adapter)

src/controller/pipeline_controller.py
(Limited to injecting a call to the profile helper when building initial PipelineConfig defaults; no GUI imports.)

src/controller/config_builder.py or equivalent config assembly helper (if present)

Utils (optional, if needed for file discovery)

src/utils/file_io.py (only if a small helper is required to locate sidecars; keep changes minimal and non-breaking).

Tests

tests/learning/test_model_profiles.py (new)

tests/controller/test_profile_integration.py (new)

Docs

docs/LEARNING_SYSTEM_SPEC.md or docs/LEARNING_SYSTEM_SPEC (append a short section referencing profiles as priors, if and only if such a note is needed).

docs/ARCHITECTURE_v2_COMBINED.md (optional, single short note under Learning layer / Config sources if needed).

If any of these files are missing or named differently, Codex must ask for clarification instead of guessing.

7. Forbidden Files

Do not modify:

src/gui/* (GUI V2 or legacy GUI)

src/pipeline/* (PipelineRunner, stages, PipelineConfig)

src/api/* (WebUI client)

src/utils/randomizer.py and any randomizer adapters

src/learning/learning_execution.py, learning_execution_controller.py, or LearningRecordWriter core (no changes to Learning execution/writer behavior).

tests/gui* (no GUI test changes)

CI configs, tools/, or any scripts/ directories.

Any project-wide configuration (pyproject.toml, etc.).

If Codex believes a forbidden file must change to complete the PR, it must stop and request a dedicated PR.

8. Step-by-step Implementation

Important: Follow TDD. Write failing tests first.

8.1 Define ModelProfile / LoraProfile data structures

In src/learning/model_profiles.py (new file), define:

ModelPreset dataclass:

id: str

label: str

rating: str (expected values: "bad" | "neutral" | "good" | "better" | "best")

source: str (e.g., "internet_prior", "local_learning")

sampler: str

scheduler: str | None

steps: int

cfg: float

resolution: tuple[int, int]

lora_overlays: list[LoraOverlay] (see below)

LoraOverlay dataclass:

name: str

weight: float

ModelProfile dataclass:

kind: Literal["model_profile"]

version: int

model_name: str

base_type: str (e.g., "sd15", "sdxl", "unknown")

tags: list[str]

recommended_presets: list[ModelPreset]

learning_summary: dict[str, Any] or a small typed summary dataclass (runs_observed: int, mean_rating: float | None).

LoraRecommendedWeight dataclass:

label: str

weight: float

rating: str

LoraRecommendedPairing dataclass:

model: str (model_name)

preset_id: str | None

rating: str

LoraProfile dataclass:

kind: Literal["lora_profile"]

version: int

lora_name: str

target_base_type: str (e.g., "sdxl", "sd15", "unknown")

intended_use: list[str]

trigger_phrases: list[str]

recommended_weights: list[LoraRecommendedWeight]

recommended_pairings: list[LoraRecommendedPairing]

learning_summary: dict[str, Any] or typed summary.

Ensure definitions follow coding standards (logging imports, type hints, dataclasses).

8.2 Implement JSON sidecar load helpers

In the same module, implement pure helpers:

load_model_profile(path: Path) -> ModelProfile | None

Reads a *.modelprofile.json file.

Validates kind == "model_profile" and version == 1 (for now).

Returns None if file missing; raises a clear error for malformed schema.

load_lora_profile(path: Path) -> LoraProfile | None

Similar semantics; kind == "lora_profile".

A higher-level helper, e.g.:

def find_model_profile_for_checkpoint(checkpoint_path: Path) -> ModelProfile | None:
    # e.g., looks for <stem>.modelprofile.json next to the checkpoint file

def find_lora_profile_for_name(lora_name: str, lora_search_paths: Sequence[Path]) -> LoraProfile | None:
    # maps LoRA name to file, then tries to load <stem>.loraprofile.json


Keep all helpers headless (no GUI imports, no controller imports), consistent with Learning layer constraints.

8.3 Implement preset suggestion helper

Still in model_profiles.py, implement a pure helper:

@dataclass
class SuggestedPreset:
    sampler: str
    scheduler: str | None
    steps: int
    cfg: float
    resolution: tuple[int, int]
    lora_weights: dict[str, float]  # lora_name -> weight
    source: str  # "internet_prior", "local_learning", etc.
    preset_id: str | None


Implement:

def suggest_preset_for(
    model_profile: ModelProfile | None,
    lora_profiles: Sequence[LoraProfile],
) -> SuggestedPreset | None:


Behavior:

If no model_profile is provided or it has no recommended_presets, return None.

Start from the highest rated preset (best > better > good > neutral > bad).

Overlay LoRA weights from matching LoraProfile.recommended_weights and recommended_pairings where model matches model_profile.model_name or where the base type is compatible.

Return a SuggestedPreset encapsulating:

Sampler, scheduler, steps, cfg, resolution from ModelPreset.

A lora_weights dict keyed by lora_name with recommended weight (fallback to a safe default like 0.6 if no explicit weight exists for a given LoRA).

This function must be a pure function consuming Python objects; it does not do any filesystem IO.

8.4 Controller integration (config assembly hook)

In src/controller/pipeline_controller.py (or the relevant config-builder helper it uses), add a single, well-contained integration point:

Introduce a method or helper, e.g.:

def build_pipeline_config_with_profiles(
    self,
    base_model_name: str,
    lora_names: Sequence[str],
    user_overrides: dict[str, Any],
) -> PipelineConfig:


Internally, this should:

Resolve the checkpoint path for base_model_name (using existing config/lookup mechanisms).

Call find_model_profile_for_checkpoint(...).

For each lora_name, attempt to load a LoraProfile.

Call suggest_preset_for(model_profile, lora_profiles) to get a SuggestedPreset (possibly None).

Build a PipelineConfig that:

Starts from your existing default config for the stage(s).

Applies the suggested sampler/scheduler/steps/cfg/resolution if a SuggestedPreset exists.

Applies suggested LoRA weights onto the config (e.g., into a LoRA overlay structure).

Applies user_overrides last (user overrides always win).

This method must:

Not import Tk or any GUI module.

Not change current behavior if no profiles exist (i.e., falls back to existing default config).

Optionally, log at INFO or DEBUG level when a preset is applied, e.g.:

“Using model profile preset rvxl_photoreal_default (source=internet_prior) for RealVisXL + PerfectEyesXL.”

Follow logging standards.

8.5 Tests – Learning layer

Create tests/learning/test_model_profiles.py:

test_load_model_profile_from_json_success

Create a temp JSON file with a valid minimal ModelProfile.

Assert it loads correctly.

test_load_lora_profile_from_json_success

Same for LoraProfile.

test_suggest_preset_picks_highest_rated_preset

Build ModelProfile with multiple presets across ratings; assert suggest_preset_for chooses the highest tier.

test_suggest_preset_merges_lora_weights

Provide a ModelProfile + a couple LoraProfiles with different recommended weights; assert SuggestedPreset.lora_weights matches expectations.

test_suggest_preset_returns_none_if_no_presets

ModelProfile with empty recommended_presets → result is None.

8.6 Tests – Controller integration

Create tests/controller/test_profile_integration.py:

Use stubs/mocks for:

Model/LoRA file resolution (if necessary).

Loading profiles (can be patched to return predefined ModelProfile/LoraProfile instances instead of hitting the filesystem).

test_build_pipeline_config_with_profiles_applies_suggested_preset

Mock suggest_preset_for to return a SuggestedPreset with specific sampler/steps/cfg/resolution and lora_weights.

Call build_pipeline_config_with_profiles and assert the resulting PipelineConfig matches those values, absent user overrides.

test_build_pipeline_config_with_profiles_respects_user_overrides

Provide user_overrides that change, for example, CFG and steps; assert these override the suggested preset.

test_build_pipeline_config_with_profiles_falls_back_without_profiles

Patch profile loaders to return None.

Assert resulting PipelineConfig matches existing default behavior (e.g., same sampler/steps as before; you may assert on key fields rather than entire object to keep the test stable).

These tests must not import GUI modules and should remain deterministic and fast.

9. Required Tests (Failing First)

Before implementing behavior, Codex must create and run the following tests so they fail on the current codebase:

pytest tests/learning/test_model_profiles.py::test_load_model_profile_from_json_success -v

pytest tests/learning/test_model_profiles.py::test_load_lora_profile_from_json_success -v

pytest tests/learning/test_model_profiles.py::test_suggest_preset_picks_highest_rated_preset -v

pytest tests/learning/test_model_profiles.py::test_suggest_preset_merges_lora_weights -v

pytest tests/learning/test_profile_integration.py::test_build_pipeline_config_with_profiles_applies_suggested_preset -v

pytest tests/learning/test_profile_integration.py::test_build_pipeline_config_with_profiles_respects_user_overrides -v

pytest tests/learning/test_profile_integration.py::test_build_pipeline_config_with_profiles_falls_back_without_profiles -v

After implementation:

pytest tests/learning -v

pytest tests/controller -v

pytest -v (if runtime is acceptable)

All tests must pass, aside from known/intentional global skips.

10. Acceptance Criteria

This PR is complete when:

All new tests in tests/learning/test_model_profiles.py and tests/controller/test_profile_integration.py pass.

No existing tests fail (unless expectations were legitimately updated; in that case, changes must be documented and minimal).

ModelProfile and LoraProfile sidecars can be:

Loaded from JSON.

Used to compute SuggestedPreset for a given model + LoRA combo.

build_pipeline_config_with_profiles:

Applies suggested presets when available.

Falls back to previous behavior when profiles are missing.

Always lets user overrides win.

No GUI, pipeline, or API modules have been modified.

LearningRecords remain unchanged; this PR only introduces priors, not changes to the Learning log format.

11. Rollback Plan

If regressions occur:

Revert changes to:

src/learning/model_profiles.py

Any changes to src/learning/__init__.py

Any changes to src/controller/pipeline_controller.py (and/or config_builder helper)

New tests:

tests/learning/test_model_profiles.py

tests/controller/test_profile_integration.py

Any doc changes in docs/LEARNING_SYSTEM_SPEC* or docs/ARCHITECTURE_v2* referencing profiles.

Re-run:

pytest tests/learning -v

pytest tests/controller -v

pytest -v

Confirm behavior returns to the previous known-good state where pipeline config assembly does not consult profiles.

12. Codex Execution Constraints

For Codex (Implementer):

Load this spec from:

docs/codex/prs/PR-LEARN-PROFILES-001_model_and_lora_profiles_as_priors.md (or actual path).

Do not modify any file outside the Allowed Files list.

Follow TDD:

Create tests listed in §9.

Run them and paste failing output.

Only then implement the production code.

After implementation:

Run:

pytest tests/learning -v

pytest tests/controller -v

pytest -v (if reasonable)

Paste full test output and a concise summary of changes.

If file paths or module names differ from what’s listed, ask for clarification before guessing.

13. Smoke Test Checklist (Manual / High-level)

After tests are green, perform the following conceptual / light manual checks:

Profile load sanity (dev-only)

Create a small *.modelprofile.json and *.loraprofile.json in a temp test dir.

In a Python shell:

Import ModelProfile, LoraProfile, and load helpers.

Confirm they deserialize and produce the expected objects.

Preset suggestion sanity (dev-only)

In a Python shell:

Construct a ModelProfile with multiple presets and a couple LoraProfiles with recommended weights.

Call suggest_preset_for and confirm:

Highest-rated preset is used.

LoRA weights are merged as expected.

Controller integration behavior

From a test harness or small script (no GUI):

Instantiate the controller or config builder.

Patch profile loaders to return a known ModelProfile + LoraProfile(s).

Call build_pipeline_config_with_profiles and:

Confirm sampler/steps/cfg/resolution match the suggested preset.

Confirm LoRA weights are reflected in the resulting config.

Confirm user overrides win when provided.

Fallback behavior

With profile loaders patched to return None:

Call build_pipeline_config_with_profiles.

Confirm the config resembles the previous default behavior (no crashes, no missing fields).

If all these checks pass, the Model/LoRA profile priors layer can be considered stable and ready for follow-on PRs (GUI surfacing, LearningRecord-driven profile updates, etc.).