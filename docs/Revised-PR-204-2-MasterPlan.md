1. Top 5 critiques of the current PR-204 plan
1) Layering & ownership of JobBuilder (controller vs pipeline vs GUI)

What PR-204 says

job_builder_v2.py lives under src/pipeline/ and takes app_state in its constructor:

src/pipeline/job_builder_v2.py (new)
class JobBuilderV2: def __init__(self, app_state): self.app_state = app_state

AppController then instantiates the builder and calls _queue.add_jobs(jobs) directly.

Why this is a problem

The canonical architecture says:

Dependency direction is: utils → api → pipeline → learning → controller → gui. Lower layers must not depend on higher layers.

PipelineController is responsible for job construction and for calling JobService; AppController is just the run entrypoint.

So:

Putting JobBuilderV2 in src/pipeline/ but handing it app_state (a GUI/controller concept) breaks the clean architecture.

Having AppController own job building and call _queue.add_jobs sidesteps PipelineController + JobService, contradicting the official run path.

Verdict

✅ Critique confirmed.

Fix in revised plan

JobBuilderV2 becomes a controller-layer helper used by PipelineController (not AppController):

File: src/controller/job_builder_v2.py (or an inner helper within pipeline_controller.py, depending on snapshot layout).

Inputs: pure data (run_config, PipelineConfig, prompt selection, randomization plan), not app_state itself.

PipelineController.start_pipeline():

Builds PipelineConfig via PipelineConfigAssembler.build_from_gui_input(...).

Uses JobBuilderV2 to create job specs.

Submits them via JobService.submit_direct/submit_queued.

AppController remains the thin “run_config builder + delegator”, as the architecture demands.

2) RunConfigV2 vs PipelineConfig confusion (dual sources of truth)

What PR-204 says

Repeatedly refers to building each job’s RunConfigV2 and returning config: RunConfigV2 in NormalizedJobRecord.

Talks about PromptPackConfig + stage config producing a “RunConfigV2”.

But the canonical architecture says

PipelineConfig is the typed configuration container used by PipelineRunner and StageExecutionPlan.

The official pipeline flow is: run_config → PipelineController.build PipelineConfig → Job → JobService → _run_pipeline_job(config) → PipelineRunner.run(config).

If PR-204 introduces a separate RunConfigV2 parallel to PipelineConfig, you end up with two config types, both “canonical”, which re-creates the ambiguity we’re trying to get rid of.

Verdict

✅ Critique confirmed.

Fix in revised plan

Use PipelineConfig as the single canonical job config:

ConfigMergerV2 produces merged PipelineConfig instances or stage sub-configs, not a separate RunConfigV2.

NormalizedJobRecord (or JobSpecV2) carries pipeline_config: PipelineConfig, plus metadata (variant/batch, output paths, etc.).

“RunConfigV2” in PR-204’s text becomes a conceptual “job config” but is concretely PipelineConfig in code.

This keeps the run path exactly aligned to the architecture docs.

3) Where config merging happens (Prompt Pack vs Stage overrides vs PipelineConfigAssembler)

What PR-204 says

Inside JobBuilderV2.build_jobs:

BaseConfig = PromptPackConfig(app_state.selected_pack)
If override enabled → merge stage config → override wins, using StageConfigMerger.

So merging is framed as:

Prompt Pack config (base) + Stage card config (override) → RunConfigV2

Why this is risky

The authoritative run-path doc already states:

PipelineController.start_pipeline builds a PipelineConfig from the current pipeline state (stages, toggles, models, refs, etc.).

That pipeline state already encodes:

Selected prompt pack ID / prompt source (from AppController’s run_config).

Stage card settings, toggles, model choices, etc.

If JobBuilder starts from a separate PromptPackConfig + stage config again, you risk:

Two different “base configs” (one in PipelineConfigAssembler, one in JobBuilder).

Divergence between what the GUI thinks it set and what the job actually uses.

Verdict

✅ Critique confirmed.

Fix in revised plan

Config merging is formalized as part of the pipeline layer, not inside JobBuilder’s controller wiring:

ConfigMergerV2 lives in src/pipeline/config_merger_v2.py.

Inputs are domain types the pipeline layer already knows:

PipelineConfig (from PipelineConfigAssembler).

Zero or more “override” structures (e.g., a PromptOverrides, StageOverrides, RandomizerOverrides), all plain dataclasses.

It produces a fully merged PipelineConfig that:

Implements the “config override checkbox” semantics.

Correctly merges nested refiner/hires/adetailer configs.

JobBuilderV2 consumes the already-assembled or merged PipelineConfig; it doesn’t recreate configs from scratch using app_state.

So the single source of truth is:

GUI state → AppController.run_config → PipelineController + PipelineConfigAssembler (+ ConfigMergerV2) → merged PipelineConfig → JobBuilderV2.

4) Job model & metadata scope (NormalizedJobRecord too skinny)

What PR-204 says

NormalizedJobRecord is:

@dataclass
class NormalizedJobRecord:
    job_id: str
    config: RunConfigV2
    path_output_dir: str
    filename_template: str
    seed: int | None
    variant_index: int | None
    variant_total: int | None
    created_ts: float


It’s a good start, but it misses several things the architecture and run-path describe.

What’s missing

Run metadata that PipelineController is supposed to track:

run_mode (direct/queue), source, prompt_pack_id, randomizer metadata, learning flags, etc.

Batch information:

batch_size, batch_runs, specific batch_index if we’re expanding jobs.

Queue-layer expectations:

JobService and JobExecutionController care about job lifecycle: order, status, and enough metadata to support queue UI & history.

If we keep a too-narrow job record, we’ll either:

Bolt metadata on somewhere else (re-introducing scattering), or

Have a mismatch between what the queue layer needs vs what JobBuilder produces.

Verdict

✅ Critique confirmed.

Fix in revised plan

Define a richer JobSpecV2 / NormalizedJobRecordV2 in job_models_v2.py, along lines of:

@dataclass
class JobSpecV2:
    job_id: str
    run_mode: RunMode            # direct / queue
    source: RunSource            # run / run_now / add_to_queue
    prompt_pack_id: str | None
    pipeline_config: PipelineConfig

    # Variant expansion
    variant_index: int = 0
    variant_total: int = 1

    # Batch expansion
    batch_index: int = 0
    batch_total: int = 1

    # Output / seeds
    output_dir: str
    filename_template: str
    seed: int | None

    # Randomizer / learning hooks (minimal now, extensible later)
    randomizer_summary: dict[str, Any] | None = None
    learning_context_id: str | None = None

    created_ts: float = field(default_factory=time.time)


This becomes the one object:

Preview panel renders.

Queue panel lists/updates.

JobService wraps in its internal Job representation for execution.

5) Queue integration path (_queue.add_jobs vs JobService & known pitfalls)

What PR-204 says

In AppController:

builder = JobBuilderV2(self._app_state)
jobs = builder.build_jobs(draft)
self._queue.add_jobs(jobs)
self._preview_panel.update_with_jobs(jobs)


That implies:

AppController is holding and mutating queue state directly.

JobService / JobExecutionController are bypassed.

Why this conflicts with the queue design

The architecture + queue pitfall doc emphasize:

Queue / Job execution is asynchronous and centralized in JobService & SingleNodeJobRunner.

PipelineController should submit through JobService, not manipulate queue structures from AppController.

By re-introducing a self._queue in AppController, PR-204 would:

Compete with the existing queue abstraction.

Make queue behavior harder to test (tests already know how to exercise JobService and runner; they don’t know about an extra _queue in AppController).

Verdict

✅ Critique confirmed.

Fix in revised plan

JobService remains the single queue façade:

PipelineController calls:

if run_config.run_mode == RunMode.DIRECT:
    job_service.submit_direct(job_spec)
else:
    job_service.submit_queued(job_spec)


Queue UI (right panel) is fed via queue events or via a read-only snapshot of JobHistory/Queue state, not by AppController pushing jobs into a private _queue.

Preview panel still gets the same JobSpecV2 list, but via controller callbacks, not by sharing a mutable queue object.

2. PR-204-2 – MasterPlanRevised

Below is the revised master spec that fixes those five issues while preserving the spirit of PR-204: make every job explicit, deterministic, and fully normalized before execution.

Title

PR-204-2 – Unified JobSpec Pipeline (Controller-centric JobBuilder + ConfigMerger + Payload Normalization, V2.5)

1. Intent / Summary

Deliver a single, controller-centric job construction pipeline that:

Builds a canonical PipelineConfig for each job, using:

GUI pipeline state (stage cards, toggles, models, etc.).

Prompt selection (prompt pack, positive/negative).

Optional stage-level “override” semantics (“config override” checkbox).

Randomizer variants and seed modes.

Batch size / batch runs expansion.

Produces explicit JobSpecV2 objects (normalized job payloads) before they enter JobService:

No missing prompts / seeds.

No ambiguous CFG/steps.

Refiner/hires/adetailer flags baked in.

Output directory and filename template resolved.

Keeps architecture layering intact:

AppController builds run_config and delegates.

PipelineController orchestrates config assembly + job construction.

ConfigMerger lives in pipeline layer.

Randomizer engine remains in randomizer layer, GUI-agnostic.

JobService & queue handle execution and lifecycle.

Ensures GUI preview, Queue view, and actual executor all share the same JobSpecV2s:

Preview = Queue = Executor input.

This is the “single throat to choke” for what actually runs in Phase-1.

2. Scope & Files

Controller layer

src/controller/pipeline_controller.py

Integrate job building into start_pipeline / _build_job path.

src/controller/job_builder_v2.py (new helper; small and testable)

Or an inner class/function living in pipeline_controller.py if that better matches snapshot.

Pipeline layer

src/pipeline/config_merger_v2.py (new)

Pure merging logic for PipelineConfig + overrides.

Reuse PipelineConfigAssembler as the entry point to build base PipelineConfig.

Randomizer layer

Use existing RandomizationPlanV2 + generate_run_config_variants/equivalent from the Randomizer engine PRs.

No rewrites of randomizer engine; only integrate it.

Queue / Job models

src/pipeline/job_models_v2.py

Define JobSpecV2 (or extend existing models) to represent normalized jobs.

App state / GUI wiring

src/gui/app_state_v2.py

Ensure pipeline state exposes:

Selected prompt pack id / prompt source.

Config override flag.

Randomizer plan (already or via previous PRs).

src/gui/panels_v2/preview_panel_v2.py

Update to consume JobSpecV2 for preview instead of raw app_state fragments.

Tests

tests/pipeline/test_config_merger_v2.py (config merging)

tests/controller/test_job_builder_v2.py (job building & expansion)

tests/pipeline/test_job_spec_normalization_v2.py (JobSpec completeness / invariants)

tests/controller/test_pipeline_controller_job_path_v2.py (integration: run_config → jobs → JobService)

Forbidden (unchanged):

src/main.py, src/pipeline/executor*.py, src/gui/main_window_v2.py, src/gui/theme_v2.py, all legacy V1/V1.5 modules, randomizer engine core.

3. Revised Design
3.1 Data types

3.1.1 RunConfig metadata (controller input)

Already defined by the architecture:

@dataclass
class RunConfigV2:
    run_mode: RunMode           # direct / queue
    source: RunSource           # run / run_now / add_to_queue
    prompt_pack_id: str | None
    # snapshot id / other metadata as currently in code


This remains AppController’s domain: it never knows about PipelineConfig internals.

3.1.2 PipelineConfig (pipeline canonical config)

As per ARCHITECTURE_v2.5:

Holds per-stage parameters (txt2img, img2img, upscalers, ADetailer, refiner, hires fix).

Contains metadata: run id, prompt pack id, randomizer metadata, learning flags, etc.

3.1.3 RandomizationPlanV2

From previous randomizer engine PRs (already defined).

Controller gets it from AppState (Randomizer panel), but passes just the dataclass down to JobBuilder / ConfigMerger.

3.1.4 JobSpecV2 (normalized job record)

Defined in job_models_v2.py as the canonical job payload:

@dataclass
class JobSpecV2:
    job_id: str
    run_mode: RunMode
    source: RunSource
    prompt_pack_id: str | None

    pipeline_config: PipelineConfig  # fully merged & randomizer/batch aware

    # Variant & batch indexing
    variant_index: int = 0
    variant_total: int = 1
    batch_index: int = 0
    batch_total: int = 1

    # Output & seeds
    output_dir: str
    filename_template: str
    seed: int | None

    # Optional metadata for GUI/Learning
    randomizer_summary: dict[str, Any] | None = None
    learning_context_id: str | None = None

    created_ts: float = field(default_factory=time.time)


Queue/JobService can either:

Wrap JobSpecV2 in a Job object; or

Use it directly depending on current snapshot.

3.2 ConfigMergerV2 (pipeline layer)

Purpose

Provide one place where override semantics are defined and tested:

Prompt / pack-level defaults.

Stage card overrides (including the “config override” checkbox from the Pipeline tab).

Nested refiner/hires/adetailer enable/disable behavior.

API (conceptual)

class ConfigMergerV2:
    @staticmethod
    def merge(
        base: PipelineConfig,
        overrides: StageOverrideConfig | None,
        *,
        override_enabled: bool,
    ) -> PipelineConfig:
        ...


Rules

If override_enabled is False:

The base PipelineConfig (built from pipeline state + prompt selection) is trusted.

If override_enabled is True:

For each field:

If override field is not None → use override.

Else → keep base.

For nested configs (e.g., refiner, hires, adetailer):

If override enabled=False → stage disabled, subfields ignored.

If override enabled=True → base and override merged field-by-field.

ConfigMerger remains pure and pipeline-local: no Tk, no AppState, no queue types.

3.3 JobBuilderV2 (controller layer)

Location

src/controller/job_builder_v2.py or as a helper in pipeline_controller.py.

Inputs

run_config: RunConfigV2 (from AppController).

base_pipeline_config: PipelineConfig (from PipelineConfigAssembler.build_from_gui_input(...)).

randomizer_plan: RandomizationPlanV2 (from AppState but passed as a dataclass).

override_enabled: bool + any stage override structures extracted by the controller from AppState.

Responsibility

Orchestrate:

Config merging via ConfigMergerV2.

Variant expansion via randomizer engine.

Seed mode application.

Batch expansion using batch_size / batch_runs.

Output_dir + filename template resolution.

Construction of JobSpecV2 list, with correct indices and metadata.

Conceptual pipeline

class JobBuilderV2:
    def build_job_specs(
        self,
        run_config: RunConfigV2,
        base_config: PipelineConfig,
        randomizer_plan: RandomizationPlanV2,
        override_enabled: bool,
        overrides: StageOverrideConfig | None,
    ) -> list[JobSpecV2]:
        # 1. Merge config
        merged_config = ConfigMergerV2.merge(
            base=base_config,
            overrides=overrides,
            override_enabled=override_enabled,
        )

        # 2. Randomizer expansion (variants of PipelineConfig)
        variant_configs = RandomizerEngineV2.generate_pipeline_variants(
            merged_config,
            randomizer_plan,
        )

        # 3. Seed mode rules applied inside that call or as a second pass

        # 4. Batch expansion per variant
        job_specs: list[JobSpecV2] = []
        for variant_idx, cfg in enumerate(variant_configs):
            for batch_idx in range(cfg.core.batch_runs or 1):
                job_specs.append(
                    JobSpecV2(
                        job_id=uuid4().hex,
                        run_mode=run_config.run_mode,
                        source=run_config.source,
                        prompt_pack_id=run_config.prompt_pack_id,
                        pipeline_config=cfg,
                        variant_index=variant_idx,
                        variant_total=len(variant_configs),
                        batch_index=batch_idx,
                        batch_total=cfg.core.batch_runs or 1,
                        output_dir=resolve_output_dir(cfg),
                        filename_template=resolve_filename_template(cfg),
                        seed=cfg.txt2img.seed,
                        randomizer_summary=build_randomizer_summary(
                            randomizer_plan, variant_idx, cfg
                        ),
                    )
                )

        return job_specs


(Helpers like resolve_output_dir, resolve_filename_template, build_randomizer_summary can be internal pure functions or small utilities.)

3.4 Controller integration (PipelineController + JobService)

PipelineController.start_pipeline(run_config) now does:

Validate pipeline state.

Build base PipelineConfig:

base_config = self._config_assembler.build_from_gui_input(
    pipeline_state=self._app_state.pipeline_state,
    prompt_pack_id=run_config.prompt_pack_id,
)


Fetch:

randomizer_plan from AppState (already stored by Randomizer panel).

Override flags/structures from AppState (middle panel config override checkbox).

Call JobBuilderV2.build_job_specs(...) with those inputs.

For each JobSpecV2:

If run_config.run_mode == RunMode.DIRECT (or after we simplify to “queue-only plus auto-run later PRs), call:

self._job_service.submit_direct(job_spec)


Else:

self._job_service.submit_queued(job_spec)


Notify GUI:

Preview panel gets the same JobSpecV2 list to render.

Queue panel reflects JobService queue state (or the same list plus status).

This keeps JobService as the only owner of actual queue operations.

3.5 Preview panel & queue UI

PreviewPanelV2

Public API becomes something like:

def update_with_job_specs(self, job_specs: list[JobSpecV2]) -> None:
    ...


It displays, per job:

Positive prompt / negative prompt (from pipeline_config).

Seed (+ seed mode summary).

Batch size × batch runs.

Resolution.

Refiner/hires/adetailer status.

Variant index / total.

Any randomizer summary (e.g., which field varied).

Queue panel

Uses JobService / JobHistory to show:

Job order, status, ability to select and reorder, etc. (per your queue UX wishlist, to be handled in another PR set).

The important part for PR-204-2 is: both views consume JobSpecV2, not ad-hoc fragments of AppState.

4. Planned Child PRs (sufficient direction for 204A, 204B, etc.)

This revised plan still breaks down naturally into child PRs:

PR-204A – ConfigMergerV2 implementation

Implement ConfigMergerV2.merge(...) and associated tests.

Ensure it operates purely on PipelineConfig + overrides.

PR-204B – JobSpecV2 definition & JobBuilderV2 core

Define JobSpecV2 in job_models_v2.py.

Implement JobBuilderV2.build_job_specs(...) with unit tests for:

No randomizer, no batch → 1 job.

Randomizer only → N variants.

Batch only → batch_runs jobs.

Both together → variants × batch_runs jobs.

PR-204C – PipelineController integration

Wire JobBuilderV2 into start_pipeline / _build_job.

Ensure it uses JobService for direct vs queue modes.

PR-204D – Preview & Queue UI normalization

Update PreviewPanelV2 and any queue view to operate on JobSpecV2.

Tests for “preview matches JobSpecV2 contents”.

PR-204E – End-to-end tests & queue parity

Controller tests asserting:

Given a run_config + pipeline state + randomizer plan, the exact JobSpecV2 list is produced.

Direct vs queue semantics preserved.

Queue tests asserting:

Submitting JobSpecV2 through JobService leads to correct _run_pipeline_job(pipeline_config) call.

5. Acceptance criteria (for PR-204-2 master goal)

We consider the revised master plan “achieved” once the child PRs deliver:

Single job construction path

All jobs originate from PipelineController via JobBuilderV2 using ConfigMergerV2.

No other code paths build pipeline configs for jobs.

Single config type

PipelineConfig is the only config type used by StageExecutionPlan & PipelineRunner.

JobSpecV2 wraps PipelineConfig; no competing “RunConfigV2” config used downstream.

Preview = Queue = Executor

Preview panel shows prompts/settings derived from the same PipelineConfig that the executor runs.

Queue view lists the same JobSpecV2 that JobService executes.

No layering violations

Pipeline layer has no knowledge of AppState/Tk.

Controllers do not manipulate JobQueue directly; they call JobService.

Randomizer usage is via the randomizer layer’s pure functions, no GUI coupling.

Bug classes eliminated

No missing prompts / seeds.

Batch size vs batch runs handled consistently.

Refiner/hires/ADetailer toggles always match what runs.

Seed mode behaves predictably across variants.

All of the tests introduced in 204A–204E are green.