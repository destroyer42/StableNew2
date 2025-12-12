PR-CORE-A — Single Source of Truth for Jobs.md

Discovery Reference: D-23
Date: 2025-12-08
Author: ChatGPT (Planner), approved by Rob
Tier: Tier 2 (Controller + Data Model + Summary Layer)

1. Summary (Executive Abstract)

PR-CORE-A defines the canonical job representation for StableNew:

NormalizedJobRecord — the immutable, fully-resolved job spec that flows into the queue and runner.

UnifiedJobSummary — the read-only DTO used by GUI, Debug Hub, History, and Learning.

This version is updated to match the real PromptPack TXT + Config JSON structure you use:

Prompt packs with:

embedding tags,

LoRA tags with strengths,

quality/style lines,

subject templates with [[environment]] and other matrix tokens.

Config JSONs with:

txt2img, img2img, upscale, adetailer, pipeline, randomization.matrix, aesthetic sections.

It also encodes the PromptPack-only invariant:

Every job must originate from a Prompt Pack; prompt_pack_id is required on both NormalizedJobRecord and UnifiedJobSummary.
The Pipeline tab cannot run on free-text prompts.

2. Motivation / Problem Statement

Previous versions of this spec described job fields in very abstract terms (prompt, negative_prompt, model, etc.). That’s not enough for your real packs, which include:

Structured prompt rows with:

positive embeddings, style tokens, subject line, LoRA tags, per-row negatives.

Complex config snapshots with:

SDXL-specific sampler/scheduler/clip_skip,

stage toggles, loop semantics, images per prompt, variant mode,

randomization matrix slots (e.g., environment, lighting, style, camera, world_flavor, etc.).

To make Debug Hub, Learning, and “Restore & Re-Run” actually useful, those details must be part of the canonical job model — not hidden in opaque JSON blobs.

PR-CORE-A updates the schemas so:

We capture prompt row structure (embeddings, LoRAs, base text, negatives).

We carry config snapshot structure (per-stage config, pipeline flags, randomization matrix slot selections).

These fields are available consistently in the runner, history, and learning.

3. Scope & Non-Goals

In scope

Define concrete fields for NormalizedJobRecord based on your actual TXT/JSON.

Define concrete fields for UnifiedJobSummary sufficient for UI and Debug Hub.

Enforce prompt_pack_id as required.

Update PipelineController/summary builder to populate these fields.

Out of scope

How prompts/configs are built (that’s PR-CORE-B).

Queue/runner lifecycle (PR-CORE-C).

UI layout changes (PR-CORE-D).

4. Architectural Alignment (PromptPack-Only)

Same as before, with one key reinforcement:

PromptPack is the only source of prompts.

Advanced Prompt Builder writes packs (*.txt + config JSON).

Pipeline tab selects one pack and config snapshot.

UnifiedPromptResolver consumes pack + config; no raw prompt text from Pipeline UI.

5. Data Models (Updated With Real Fields)
5.1 PromptPack structure (informative, not implemented here)

From your SDXL_angelic_warriors_Realistic.txt and SDXL_mythical_beasts_Fantasy.txt, a PromptPackRow concept naturally falls out:

Each row roughly has:

Positive embeddings (first line)

e.g. <embedding:stable_yogis_pdxl_positives> <embedding:stable_yogis_realism_positives_v1>

Quality/style line

e.g. (masterpiece, best quality) portrait, detailed skin, natural light, grounded realism, subtle grading

Subject template with matrix tokens

e.g. armored angelic knight with radiant wings over [[environment]]

LoRA tags with strengths

e.g. <lora:add-detail-xl:0.65> ...

Negative blocks

negative embeddings line (neg: <embedding:...> ...)

explicit negative phrase line (neg: deformed hands, twisted wrists, ...)

We don’t implement PromptPack parsing in PR-CORE-A, but we shape the job model so the resolved results from PR-CORE-B have clear homes.

5.2 Config snapshot structure (from JSON)

From the *_Realistic.json and *_Fantasy.json files, the key sections we care about are:

txt2img — steps, cfg_scale, width/height, sampler_name, scheduler, seed, clip_skip, model, VAE, refiner options, hires options.

img2img — steps, cfg_scale, denoise, sampler_name, scheduler, etc.

upscale — upscaler, resize, sampler, denoise, face restoration sliders.

pipeline — stage toggles, loop_type, loop_count, images_per_prompt, variant_mode, etc.

adetailer — enable flag, model, conf, mask feather, sampler, steps, denoise, cfg, prompts.

randomization.matrix — enabled flag, mode, prompt_mode, slots (name + values), base_prompt template.

aesthetic — enabled, weight, text, etc.

PR-CORE-A doesn’t define how these are merged; it ensures the important parts show up in the job record and summary.

6. NormalizedJobRecord (Concrete Field Schema)

This is the runner-facing job spec. Fields are grouped logically.

6.1 Identity & provenance
job_id: str
prompt_pack_id: str
prompt_pack_name: str
prompt_pack_row_index: int          # which row in the .txt this job came from
prompt_pack_version: Optional[str]  # or hash for future immutable packs

6.2 Prompt resolution (post-resolver, ready for WebUI)
positive_prompt: str         # fully resolved string (embeddings + quality line + subject + matrix substitutions + LoRAs)
negative_prompt: str         # fully merged (row negatives + global negatives + config negative)
positive_embeddings: list[str]  # e.g. ["stable_yogis_pdxl_positives", "stable_yogis_realism_positives_v1"]
negative_embeddings: list[str]  # e.g. ["negative_hands", "stable_yogis_anatomy_negatives_v1-neg", ...]
lora_tags: list[LoRATag]        # name + weight, e.g. ("add-detail-xl", 0.65)
matrix_slot_values: dict[str, str]
# e.g. {"environment": "volcanic lair", "lighting": "hellish backlight", ...} from randomization.matrix.slots


positive_prompt is what actually gets sent to txt2img after embedding and matrix substitution.

matrix_slot_values encodes the per-job selection from the randomization matrix (e.g., environment/lighting/style/camera/world_flavor).

6.3 Global & stage-independent config
seed: int               # final resolved seed for this job
cfg_scale: float        # primary cfg (txt2img)
steps: int              # primary steps (txt2img)
width: int
height: int
sampler_name: str
scheduler: str
clip_skip: int
base_model: str         # e.g. "juggernautXL_ragnarokBy.safetensors [dd08fa32f9]"
vae: Optional[str]


These come from the txt2img block of the config JSON, after any preset/pack overrides.

6.4 Stage chain configuration

We represent the stage chain as a structured list:

class StageConfig(BaseModel):
    stage_type: Literal["txt2img", "img2img", "adetailer", "upscale"]
    enabled: bool
    steps: Optional[int]
    cfg_scale: Optional[float]
    denoising_strength: Optional[float]
    sampler_name: Optional[str]
    scheduler: Optional[str]
    model: Optional[str]
    vae: Optional[str]
    extra: dict[str, Any]  # adetailer_prompt, upscaler, resize, etc.


And in the record:

stage_chain: list[StageConfig]


Examples:

txt2img stage: steps=34, cfg=6.1, model=juggernautXL..., width/height=1216×832.

adetailer stage: enabled=true, sampler="DPM++ 2M", steps=12, denoise≈0.26, cfg=6.0, plus adetailer prompt/negative.

upscale stage: upscaler="4xUltrasharp…", resize=2.0, denoise=0.2.

6.5 Pipeline & loop semantics
loop_type: Literal["pipeline", "prompt", "image"]  # from pipeline.loop_type
loop_count: int                                    # pipeline.loop_count
images_per_prompt: int                             # pipeline.images_per_prompt
variant_mode: str                                  # pipeline.variant_mode (e.g., "fanout")
run_mode: Literal["DIRECT", "QUEUE"]              # from run controls
queue_source: Literal["RUN_NOW", "ADD_TO_QUEUE"]   # for audit/debug


From the pipeline block: loop_type, loop_count, images_per_prompt, variant_mode.

6.6 Randomization metadata

Even though PR-CORE-B will be the one actually building variants, we want job records to encode which variant they correspond to:

randomization_enabled: bool
matrix_name: Optional[str]       # descriptive label, e.g. "mythical_beasts_matrix"
matrix_mode: Optional[str]       # e.g. "rotate"
matrix_prompt_mode: Optional[str]# e.g. "prepend"
matrix_slot_values: dict[str, str]
variant_index: int
batch_index: int


matrix_slot_values is the per-job selection for each slot (environment, lighting, style, camera, world_flavor, etc.).

variant_index and batch_index are how we track where in the variant×batch expansion this job sits.

6.7 Aesthetic + extras (future-proof)
aesthetic_enabled: bool
aesthetic_weight: Optional[float]
aesthetic_text: Optional[str]
aesthetic_embedding: Optional[str]
extra_metadata: dict[str, Any]   # for future extensions


This corresponds to the aesthetic section.

6.8 Outputs
output_paths: list[str]        # images produced by this job
thumbnail_path: Optional[str]  # for quick display in History/Learning
created_at: datetime
completed_at: Optional[datetime]
status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
error_message: Optional[str]

7. UnifiedJobSummary (Concrete Field Schema)

This is the UI/Debug view version — lighter than NormalizedJobRecord but still rich enough to drive panels.

class UnifiedJobSummary(BaseModel):
    # Identity
    job_id: str
    prompt_pack_id: str
    prompt_pack_name: str
    prompt_pack_row_index: int

    # Prompt preview (single line / compact)
    positive_prompt_preview: str
    negative_prompt_preview: str
    lora_preview: str                  # e.g. "add-detail-xl(0.65), CinematicStyle_v1(0.5)..."
    embedding_preview: str             # e.g. "stable_yogis_pdxl_positives + ..."

    # Model & stage preview
    base_model: str
    sampler_name: str
    cfg_scale: float
    steps: int
    width: int
    height: int
    stage_chain_labels: list[str]      # e.g. ["txt2img", "adetailer", "upscale"]

    # Randomization preview
    randomization_enabled: bool
    matrix_mode: Optional[str]
    matrix_slot_values_preview: str    # compact "env=volcanic lair; lighting=hellish backlight; ..."

    # Volume / indices
    variant_index: int
    batch_index: int
    estimated_image_count: int         # images_per_prompt × loops for this job

    # Status
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
    created_at: datetime
    completed_at: Optional[datetime]


Panels like Preview, Queue, Running Job, History, and Debug Hub → Explain Job should display data exclusively from UnifiedJobSummary, not re-deriving anything from raw config or GUI state.

8. Controller Responsibilities (unchanged intent, richer data)

Key enforcement:

Any call to “build jobs” must supply:

prompt_pack_id

prompt_pack_row_indices (if doing per-row fanout)

selected config snapshot id

Controllers hand this to the summary/builder layer, which returns:

list[NormalizedJobRecord]

list[UnifiedJobSummary] (or derived on the fly)

If prompt_pack_id is missing, controller must:

Abort job build.

Surface a clear UI error (“Select a Prompt Pack to run a job.”).

Do not create partial or “promptless” jobs.

9. Tests (focus on fields)

On top of what we already had, add explicit expectations around the new fields:

For a job built from SDXL_angelic_warriors_Realistic + its JSON:

positive_prompt contains the embeddings + style + subject line with resolved environment/lighting/etc.

negative_prompt includes both the row-specific negatives and the config negative.

stage_chain includes txt2img + adetailer + upscale with correct parameters.

matrix_slot_values has keys environment, lighting, style, camera, world_flavor.

For a job built from SDXL_mythical_beasts_Fantasy + its JSON:

positive_prompt matches that pack’s creature concept structure.

matrix_slot_values has the correct fantasy slots (environment, lighting, style, camera, world_flavor or equivalents).

variant_index increments across matrix fanout; batch_index increments across batch.

10. Acceptance Criteria (delta)

Add to the earlier list:

NormalizedJobRecord instances for your angelic & mythical packs carry:

correct embeddings, LoRA tags, matrix slot selections, and stage configs.

UnifiedJobSummary gives enough information to reconstruct:

which pack row and config produced the image,

which matrix variant and batch it was,

which model/pipeline configuration was used.

NormalizedJobRecord and UnifiedJobSummary both contain valid prompt_pack_id.

No controller path allows job creation without a Prompt Pack.

Pipeline Tab run buttons remain disabled until a pack is selected.

Preview, Queue, Running Job, History, and Debug Hub all reflect the same summary DTO.

Learning system receives prompt_pack_id with every job.

All new tests pass.

11. Validation Checklist

App boots.

Selecting a Prompt Pack enables run controls; no pack = no-run.

Preview panel resolves correct prompts from pack.

Queue & Runner receive correct NormalizedJobRecord.

History contains correct pack metadata.

Debug Hub Explain Job displays unified summary.

No cross-tab prompt editing survives.

12. Documentation Impact Assessment
Update Required:

ARCHITECTURE_v2.5.md (sections 0.1, 0.4, GUI, resolver, JobBuilder) — already patched above.

Roadmap_v2.5.md — PromptPack-only is now a Phase 1 milestone.

StableNew_Coding_and_Testing_v2.5.md — tests requiring prompt packs.

Learning_System_Spec_v2.5.md — LearningRecord includes prompt_pack_id.

CHANGELOG Entry
## [PR-CORE-A] 2025-12-08
Updated job summary and normalization layers to enforce PromptPack-only job construction.
Added required prompt_pack_id to NormalizedJobRecord and UnifiedJobSummary.
Updated controller logic, view-models, and tests accordingly.

13. Rollback Plan

Revert added fields in NormalizedJobRecord and UnifiedJobSummary.

Restore Pipeline tab free-text prompt entry (if desired).

Remove controller-level pack requirement.

Remove UI disable logic tied to pack selection.

Revert updated tests and documentation changes.