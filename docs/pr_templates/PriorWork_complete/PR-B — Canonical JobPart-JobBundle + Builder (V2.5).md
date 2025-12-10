#CANONICAL
PR-B — Canonical JobPart-JobBundle + Builder (V2.5).md

Discovery Reference: D-11 (Pipeline Run Controls / Queue Integration)
Date: 2025-12-07 12:00 (local time)
Author: ChatGPT (Planner)

1. Summary (Executive Abstract)

This PR introduces a canonical job input model—JobPart, JobBundle, PipelineConfigSnapshot, and JobBundleBuilder—to unify how StableNew represents “what should be run” before it is expanded into NormalizedJobRecord objects. Today, prompt text, pack metadata, stage toggles, randomizer options, and output configuration are scattered across controllers and GUI state, making it difficult to build a correct, testable job bundle for the queue and runner.

The changes live primarily in the pipeline data/model layer (src/pipeline/job_models_v2.py, src/pipeline/job_builder_v2.py) and the test layer (tests/pipeline/test_job_builder_v2.py), with no queue/runner or GUI wiring changes in this PR. Conceptually, the new types become the single “source of truth” for what the GUI and controllers hand to the pipeline builder.

By isolating a clean, well-typed JobBundleBuilder with explicit methods for single prompts and prompt packs, we enable future PRs (PR-C etc.) to wire “Add to Job” / preview / queue / history behavior without re-deriving job structure in multiple places. This significantly reduces the risk of bugs where preview, queue, and runner disagree on prompts, stages, or config.

This PR is Tier 2 (Standard): it touches the pipeline builder/model and adds unit tests, but does not yet alter JobService, queue execution paths, or GUI wiring.

2. Motivation / Problem Statement
Current Behavior

There is no single canonical UI/Controller-level representation of “a job bundle to run.”

The architecture doc calls out NormalizedJobRecord as the canonical post-builder job format, but the inputs to JobBuilderV2 are a mix of:

Ad-hoc parameters (prompts, packs, variants, etc.),

Pipeline state scattered across PipelineControllerV2, AppController, and GUI state objects,

Randomizer inputs and stage configs coming from different places.

Prompt packs, prepend text, global negative text, and per-pack configs are combined in multiple locations with incomplete or duplicated logic.

Problems

Preview vs queue vs runner drift: Different layers infer “what job is” from different slices of state, so:

Preview may show one set of prompts/stages.

Queue stores another.

Runner ultimately executes yet another (expanded) set via NormalizedJobRecord.

Difficult to test:

tests/pipeline/test_job_builder_v2.py can validate builder logic in isolation, but there is no clear DTO that represents the high-level intent “run these prompts with this config and global negative.”

GUI & controller tests often assert behaviors indirectly through mocks instead of checking a structured job bundle.

Bug magnet for packs:

Prompt pack semantics (prepend text, global negative, per-pack JSON configs) are tricky and are currently not captured in a dedicated data model.

This creates regressions whenever we tweak pack behavior or global negative handling.

Consequences of Not Fixing

Continued difficulty in getting “Add to Job → Preview → Queue → Run → History” working reliably.

Every new feature (global negative persistence, job-part details modal, advanced randomizer behavior) risks introducing more drift between UI expectations and actual runner behavior.

Debugging broken pipelines remains expensive: engineers must mentally reconstruct job structure from scattered state instead of inspecting a single coherent object.

Why Now

We are currently pushing to “once and for all” establish a reliable, fully wired job pipeline.

Upstream PRs (A / C / GUI wiring) depend on having a stable job-bundle DTO they can target.

Doing this now isolates risk: we can introduce the canonical models and unit tests before we wire them into GUI and queue, reducing the blast radius of future changes.

3. Scope & Non-Goals
In Scope

Introduce canonical DTOs and builder:

PipelineConfigSnapshot

JobPart

JobBundle

JobBundleBuilder

Implement builder methods for:

Single-prompt job part creation (current prompt field + config).

Pack-based job part creation (prompt packs + prepend text + global negative).

Ensure builder output is structurally compatible with existing JobBuilderV2 / NormalizedJobRecord expectations (i.e., it should be possible to map a JobBundle into one or more NormalizedJobRecord instances).

Add unit tests in tests/pipeline/test_job_builder_v2.py for:

Single prompt with/without global negative.

Prompt pack expansion with prepend text and per-pack config.

Light documentation updates in architecture and PR notes to recognize the new DTOs as the canonical pre-builder job representation.

Out of Scope (This PR)

No GUI changes (no modifications to “Add to Job,” preview, or details modal).

No changes to JobService, JobQueueV2, or SingleNodeJobRunner.

No changes to tests/gui_v2/ or queue/history panels.

No direct modifications to NormalizedJobRecord or queue storage formats beyond what’s strictly needed to refer to the new DTOs conceptually.

4. Architecture / Design
High-Level Design

We introduce a three-layer job model consistent with the v2.5 architecture:

UI/Controller Intent Layer (new)

JobPart

JobBundle

PipelineConfigSnapshot

JobBundleBuilder

Pipeline Builder Layer (existing)

JobBuilderV2 in src/pipeline/job_builder_v2.py

Converts a JobBundle (intent) into one or more NormalizedJobRecord objects, expanding variants, batches, seeds, and stages.

Queue/Execution Layer (existing)

JobService, JobQueueV2, SingleNodeJobRunner

Consume NormalizedJobRecord and manage job lifecycle.

New Types (Conceptual)

PipelineConfigSnapshot (dataclass; lives in src/pipeline/job_models_v2.py)

Represents the fully merged pipeline configuration for a single job-part:

Model & base stage:

base_model_name: str

sampler_name: str

scheduler_name: str

steps: int

cfg_scale: float

width: int

height: int

seed_mode: Literal["fixed","random","per_prompt"]

seed_value: Optional[int]

Stages:

enable_img2img: bool

enable_adetailer: bool

enable_hires_fix: bool

enable_upscale: bool

Stage-level configs (denoise, refiner, hires settings, upscaler, face restore, etc.) are included as structured fields but initially can be minimal to keep this PR scope manageable.

Randomizer & output:

randomizer_config: Optional[RandomizerConfigDTO] (placeholder / minimal struct)

output_dir: str

save_manifest: bool

batch_size: int

batch_count: int

JobPart (dataclass; src/pipeline/job_models_v2.py)

Represents one logical “job part” (one positive/negative prompt combination + config), which may expand into many NormalizedJobRecord instances due to batches, variants, or seeds:

id: str (UUID4 string)

positive_prompt: str

negative_prompt: str

prompt_source: Literal["single","pack","preset","other"]

pack_name: Optional[str]

config_snapshot: PipelineConfigSnapshot

estimated_image_count: int (batch_size × batch_count; helpful for UI but not required by builder)

Optional metadata dict for future extension.

JobBundle (dataclass; src/pipeline/job_models_v2.py)

Represents a bundle of JobParts added together (e.g., via “Add to Job” repeatedly) and ultimately enqueued as one entry:

id: str (UUID4 string)

label: str (short description, e.g., “Angelic warriors pack + manual prompt 1”)

parts: list[JobPart]

global_negative_text: str (informational; actual application is already baked into each JobPart.negative_prompt)

run_mode: Literal["queue","direct"]

created_at: datetime

Optional tags: list[str] (e.g., ["sdxl","fantasy"]) for future history filtering.

JobBundleBuilder (class; src/pipeline/job_models_v2.py or new helper module)

Responsibility: provide a simple, pure-Python API that controllers can use to assemble a JobBundle:

__init__(self, base_config: PipelineConfigSnapshot, global_negative_text: str = "", apply_global_negative: bool = True)

reset(self) -> None

add_single_prompt(self, positive_prompt: str, override_config: Optional[PipelineConfigSnapshot] = None, prompt_source: str = "single") -> JobPart

add_pack_prompts(self, pack_name: str, prompts: list[str], prepend_text: str, pack_config: PipelineConfigSnapshot) -> list[JobPart]

Applies global negative if configured.

to_job_bundle(self, label: Optional[str] = None, run_mode: str = "queue") -> JobBundle

Relationship to Existing Components

JobBuilderV2 will be updated later (in a follow-on PR) to accept a JobBundle and produce NormalizedJobRecord objects.

For now, JobBundleBuilder is standalone and fully testable, and will be the target API for:

“Add to Job” wiring in preview.

“Add pack to job” behaviors.

Future replay/history features.

5. Detailed Implementation Plan
Step 1 – Add DTOs to src/pipeline/job_models_v2.py

Introduce PipelineConfigSnapshot dataclass:

Define the fields listed above.

Provide a from_runtime_config(...) classmethod that can be used later to build snapshots from current pipeline config objects (without needing that wiring in this PR).

Provide a copy_with_overrides(...) helper for tests (e.g., override prompts/batch sizes).

Introduce JobPart dataclass.

Ensure id is generated via uuid.uuid4() by default (factory).

Compute estimated_image_count from config_snapshot.batch_size * config_snapshot.batch_count.

Introduce JobBundle dataclass.

Provide convenience methods:

total_image_count() → sum of part.estimated_image_count.

summary_label() (optional) → generate a human-friendly label if label is empty.

Step 2 – Implement JobBundleBuilder

Create JobBundleBuilder in src/pipeline/job_models_v2.py (or src/pipeline/job_bundle_builder.py if separation is clearer; either is acceptable as long as it’s reflected in Files section):

Internal state:

_parts: list[JobPart]

_base_config: PipelineConfigSnapshot

_global_negative_text: str

_apply_global_negative: bool

reset():

Clears parts but leaves base config + global negative as is.

add_single_prompt(...):

Compose final positive prompt directly from argument.

Compose negative prompt:

Start from "" or perhaps a base negative (if provided in config; for now treat as "").

If _apply_global_negative and _global_negative_text non-empty, append it with a separator (e.g., ", ").

Choose config:

Use override_config if provided, else copy _base_config.

Build and append JobPart with prompt_source="single" and pack_name=None.

Return the created JobPart.

add_pack_prompts(...):

For each prompt p in prompts:

positive_prompt = prepend_text + p (with spacing rules tested).

Compose negative prompt similarly, applying _global_negative_text if configured.

Use pack_config (or a copy thereof) as the config_snapshot.

Build JobPart with prompt_source="pack" and pack_name=pack_name.

Append to _parts.

Return list of created JobPart instances.

to_job_bundle(...):

If no parts, raise a clear error (tests will assert this).

Use provided label or compute via simple heuristic (e.g., “N parts, X images”).

Return JobBundle containing all parts and copying _global_negative_text.

Keep builder pure (no logging, no side effects, no access to global state) to ensure easy unit testing.

Step 3 – Update / Extend tests/pipeline/test_job_builder_v2.py

Add tests to validate PipelineConfigSnapshot:

test_pipeline_config_snapshot_basic_defaults:

Construct snapshot with simple values; assert fields.

test_pipeline_config_snapshot_copy_with_overrides:

Override width/height/batch settings and assert new values.

Add tests for JobBundleBuilder single prompt:

test_job_bundle_builder_single_prompt_without_global_negative:

Base config with batch_size=1, batch_count=1.

_apply_global_negative=False.

Add single prompt "castle in the sky".

Assert:

One part in bundle.

Positive prompt as provided.

Negative prompt empty.

estimated_image_count == 1.

test_job_bundle_builder_single_prompt_with_global_negative:

Global negative "bad_anatomy, lowres".

_apply_global_negative=True.

Add single prompt.

Assert negative prompt contains the global negative and no duplication.

Add tests for pack prompts:

test_job_bundle_builder_pack_prompts_with_prepend_and_global_negative:

Pack name "SDXL_angelic_warriors".

Prepend text "cinematic, 8k, ".

Prompts: ["hero with wings", "angelic knight"].

Global negative as above.

pack_config with batch_size=2, batch_count=3.

Assert:

Two JobParts created.

Each positive prompt starts with the prepend text and respective prompt.

Each negative prompt includes the global negative.

Each estimated_image_count equals 2 * 3 == 6.

Bundle total_image_count() equals 12.

Optionally add a test that ensures to_job_bundle() without parts raises an error:

test_job_bundle_builder_to_job_bundle_without_parts_raises.

Step 4 – (Optional) Light integration doc in docs/ (no code changes)

Add or update a short section in an existing doc (e.g., ARCHITECTURE_v2.5.md or a new smaller doc in docs/) explaining:

“UI/Controller intent model (JobBundle) → NormalizedJobRecord → Queue → Runner.”

This will be fleshed out further in later PRs but should mention the new DTOs by name.

6. Files & Modules Touched

New / Modified Files

Pipeline Models / Builder

src/pipeline/job_models_v2.py

Add PipelineConfigSnapshot dataclass.

Add JobPart, JobBundle dataclasses.

Implement JobBundleBuilder.

(Optional) src/pipeline/job_bundle_builder.py

If we prefer to separate builder from models, document that here instead of embedding it in job_models_v2.py.

Tests

tests/pipeline/test_job_builder_v2.py

Extend with new tests for:

PipelineConfigSnapshot

JobBundleBuilder single prompt.

JobBundleBuilder pack prompts.

Files Explicitly Not Touched in this PR

src/controller/pipeline_controller.py

src/controller/app_controller.py

src/controller/job_execution_controller.py

src/controller/job_history_service.py

src/queue/job_model.py

src/queue/job_queue_v2.py (or equivalents)

src/queue/single_node_runner.py

tests/gui_v2/*

tests/queue/*

These will be addressed by follow-on PRs (e.g., PR-C) once the canonical DTOs are in place.

7. Test Plan
Unit Tests

tests/pipeline/test_job_builder_v2.py

test_pipeline_config_snapshot_basic_defaults

test_pipeline_config_snapshot_copy_with_overrides

test_job_bundle_builder_single_prompt_without_global_negative

test_job_bundle_builder_single_prompt_with_global_negative

test_job_bundle_builder_pack_prompts_with_prepend_and_global_negative

test_job_bundle_builder_to_job_bundle_without_parts_raises

All tests should:

Avoid any dependency on the GUI or WebUI.

Run in isolation with plain Python objects.

Integration Tests (Deferred / Not in this PR)

No new integration or GUI tests in this PR by design.

Future PRs will:

Bind controllers/GUI actions to JobBundleBuilder.

Add “preview → queue → run → history” journey tests.

8. Risks & Mitigations
Risk 1 – Divergence from Existing NormalizedJobRecord Expectations

Concern: If the new DTOs don’t align with how JobBuilderV2 currently works, future wiring could be messy or require another large refactor.

Mitigation:

Keep PipelineConfigSnapshot deliberately close to the structure JobBuilderV2 already expects (fields for model, sampler, steps, cfg, etc.).

Add comments in job_models_v2.py describing how each field maps to builder/payload fields.

In a follow-on PR, add a simple mapping function (JobBundle → List[NormalizedJobRecord]) and verify using tests.

Risk 2 – Over-Engineering the Builder API

Concern: JobBundleBuilder might become a second “mini-framework” that duplicates responsibilities of JobBuilderV2.

Mitigation:

Keep JobBundleBuilder narrow in this PR:

Purpose = translate prompts + global negative + pipeline config into JobPart/JobBundle.

Do not add variant expansion, randomization, or seed logic here; that remains in JobBuilderV2.

Risk 3 – Hidden Dependencies on GUI-State Types

Concern: It might be tempting to import GUI types (e.g. pipeline config panels) directly into job_models_v2.py.

Mitigation:

Strictly treat PipelineConfigSnapshot as a pure DTO with no GUI imports.

Conversion from GUI/app state → PipelineConfigSnapshot will live in controllers in later PRs.

9. Rollout / Migration Plan

Phase 1 (this PR):

Introduce DTOs + builder + tests.

Ensure all existing tests still pass (no imports from these new types yet).

Phase 2 (next PR):

Start using JobBundleBuilder in controller-level code (e.g., PipelineControllerV2 / AppController) instead of assembling jobs ad hoc.

Add journey tests that go from UI intent → JobBundle → NormalizedJobRecord.

Phase 3 (later):

Integrate JobBundle into queue/history semantics (e.g., naming jobs after their bundle).

Deprecate any legacy pre-v2 job structures that are now redundant.

Because this PR is additive and not yet wired into production paths, rollback is trivial: the new classes are unused and can be removed in a straightforward revert if needed.

10. Telemetry & Debugging

Even though this PR is mostly data structures, it’s helpful to plan ahead:

Add __repr__ or to_debug_dict() helpers on:

JobPart

JobBundle

PipelineConfigSnapshot

This will allow later PRs to:

Log complete, structured job bundle information in debug logs.

Display per-bundle/part info in a debug console or inspector.

For now, no additional logging is required in this PR; these helpers just enable richer logging later.

11. Documentation Updates

ARCHITECTURE_v2.5.md

Add a short subsection under the pipeline builder section:

“Job Intent Model (JobBundle) → NormalizedJobRecord → Queue → Runner”

Mention JobPart, JobBundle, and PipelineConfigSnapshot by name as the canonical pre-builder DTOs.

Potential New Doc (optional)

docs/older/ or docs/:

A small “Job Model V2 Primer” doc summarizing:

How controllers should build jobs via JobBundleBuilder.

How this feeds into JobBuilderV2.

12. Open Questions / Decisions

Where should JobBundleBuilder live?

Option A: Inside src/pipeline/job_models_v2.py next to DTOs.

Option B: New file src/pipeline/job_bundle_builder.py with models imported from job_models_v2.py.

Recommendation: Start with Option A to reduce file churn; split later if it grows.

How much of the stage config should be captured now?

This PR can start with a core subset (model, sampler, sizes, batch, etc.).

A follow-on PR can extend PipelineConfigSnapshot with ADetailer/hires/refiner fields as we wire those stage cards.

How strict should the mapping to NormalizedJobRecord be in this PR?

For now, we will keep the DTOs structurally compatible and document expected mapping.

The actual mapping implementation and tests belong in a follow-on (PR-C).

13. Out of Scope / Follow-On Work

Wiring “Add to Job” and preview panel to JobBundleBuilder.

Implementing Details modal that presents JobParts as user-selectable cards.

Integrating JobBundle into JobService / JobQueueV2 / history.

Extending PipelineConfigSnapshot to fully cover:

ADetailer configuration.

Hires/refiner model selection + refiner start.

Final Size computations.

Face restore pipeline options.

Adding GUI journey tests for preview → queue → run → history.

These will be addressed in subsequent PRs (e.g., PR-C and GUI-focused PRs).

14. Checklist

 Define PipelineConfigSnapshot in src/pipeline/job_models_v2.py.

 Define JobPart and JobBundle dataclasses.

 Implement JobBundleBuilder with:

 reset

 add_single_prompt

 add_pack_prompts

 to_job_bundle

 Extend tests/pipeline/test_job_builder_v2.py with new unit tests.

 Ensure all tests pass (python -m pytest tests/pipeline/test_job_builder_v2.py).

 Update ARCHITECTURE_v2.5.md with a brief “JobBundle → NormalizedJobRecord” note.

 Add or update CHANGELOG.md with a short entry for PR-B.