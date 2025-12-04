# Learning System Spec v2  
_Hybrid Passive + Active Learning (L3)_

---

## 1. Overview

The Learning System makes StableNew **self‑improving** over time by turning each run into signal about “what works” for a given style, prompt, and pipeline config.

It supports:

- **Passive Learning** – user runs pipelines normally, optionally rating outputs after the fact.
- **Active Learning (Learning Runs)** – the system proposes controlled experiments for a single variable (e.g., steps), and the user rates the resulting grid.
- **Hybrid (L3)** – user can switch between passive‑only and active learning mode per session or per pack.

Learning is **backend‑agnostic**: it works the same whether the pipeline is executed on a single machine or distributed across the cluster.

---

## 2. Data Structures

### 2.1 LearningRecord

A **LearningRecord** captures a single pipeline run (or a single variant from a randomizer/learning run). It includes:

- Run context
  - run_id
  - timestamp
  - prompt_pack_id / prompt_id
  - stage sequence used
  - whether the run was interactive or batch

- Configuration snapshot
  - Full effective **PipelineConfig** used for the run (all stages).
  - Any randomizer metadata (variant index, matrix values used).
  - Learning mode info (passive vs active, plan id).

- Outputs
  - Paths or IDs of images produced (per stage where relevant).
  - Derived metrics (e.g., size, sampler, steps, CFG).

- User feedback (optional at first)
  - rating (e.g., 1–5)
  - tags (too noisy, too smooth, great composition, bad anatomy, etc.).

The record is written via **LearningRecordWriter** as **append-only JSONL**, enabling later analysis and LLM consumption.
Passive learning (L2) is now live for single pipeline runs when learning is enabled in configuration, emitting LearningRecords without changing user-visible behavior.
GUI V2 now exposes a Learning toggle and a simple Review Recent Runs dialog for rating/tagging past runs; this remains optional and off by default.
Review dialog and toggle provide passive L2 entrypoint: users can enable learning, list recent records, and append ratings/tags via GUI V2 without affecting pipeline semantics.

### 2.2 LearningPlan and LearningRunStep

A **LearningPlan** defines a structured experiment, usually focused on a single variable:

- plan_id
- focus_parameter (e.g., "txt2img.steps")
- base_config (PipelineConfig compatible structure)
- variant_values (e.g., [15, 20, 25, 30, 35])
- images_per_variant (e.g., 1–3)
- metadata (who triggered the plan, when, any notes).

A **LearningRunStep** is a concrete execution step derived from a plan:

- step_id
- plan_id
- variant_index
- config_for_step (base_config + focused override value)
- stage sequence
- output references.

### 2.3 LearningRunResult

A **LearningRunResult** aggregates records and feedback for an entire LearningPlan:

- plan_id
- steps: list of (step_id, rating, tags)
- summary stats (best performing value, spread of ratings, etc.).

### 2.4 Model & LoRA Profile Priors (NEW)

StableNew now supports structured sidecar files—**ModelProfile** and **LoraProfile**—as external "priors" for learning runs. These JSON files can be co-located with model and LoRA files and encode recommended presets (sampler, scheduler, steps, CFG, resolution, LoRA pairings/weights) sourced from community best practices or local learning history.

- **ModelProfile**: Encodes recommended pipeline settings for a base model, including preset tiers (good/better/best) and summary stats.
- **LoraProfile**: Encodes recommended weights, pairings, and trigger phrases for a LoRA.

The controller can assemble pipeline configs using these priors, merging them with user overrides and learning records. This enables "cold start" runs with sensible defaults and lays the foundation for future GUI surfacing and automated preset updates.

See `src/learning/model_profiles.py` for schema and helpers.

---

## 3. Passive Learning Workflow

1. User runs a normal pipeline (with or without randomizer).
2. PipelineRunner produces outputs and (if learning is enabled) emits a **LearningRecord** for the run/variant.
3. GUI optionally prompts the user to rate the result:
   - Immediately after the run.
   - Or later via a “Review recent runs” screen.
4. Updated ratings are merged back into the LearningRecord.

Key properties:

- Minimal UX overhead – user can ignore learning if they choose.
- Records are still valuable, even if they remain unrated (for future inspection).

---

## 4. Active Learning Workflow (Learning Runs)

A **Learning Run** is a user‑initiated, controlled experiment that varies one variable at a time.

### 4.1 Setup

- User selects:
  - Prompt pack / prompt to focus on.
  - Stage to test (typically txt2img first, later possibly img2img or upscale).
  - Parameter to vary (steps, CFG, sampler, scheduler, denoising_strength, etc.).
  - Range of values (e.g., steps: 15–45 in increments of 5).
  - Images per variant (1–3).

- StableNew builds a **LearningPlan** based on these inputs.

### 4.2 Execution

- LearningRunner feeds each **LearningRunStep** into the pipeline (either local or distributed via the cluster).
- For txt2img example:
  - All non‑focus parameters (model, LoRAs, CFG, etc.) stay fixed.
  - Only steps changes across variants.

- Outputs are grouped for easy visual comparison (e.g., 3x3 grid).

### 4.3 Feedback Collection

- After the run, the user sees the set of variants (organized by the focus parameter value).
- For each value, the user can:
  - Rate the result (1–5).
  - Add quick tags.
- LearningRunResult is stored and aggregated.

### 4.4 Insights and Preset Updates

- A minimal, local insights layer can show:
  - Which parameter values scored best for this prompt pack.
  - Trends over time.
- Optionally, new **preset configs** can be generated, e.g.:
  - “For this pack, use 30–35 steps and CFG ~7–8 as the default one‑click setting.”

---

## 5. Hybrid Mode (L3)

L3 combines the above:

- Each run can be configured to:
  - Use **passive learning only** (record + optional rating).
  - Trigger an **active Learning Run** (per‑param experiment).

- Settings can be per‑project or per‑pack:
  - Example: heroic fantasy pack is in “Learning mode” while a comic‑style pack is “locked in” and mainly uses randomizer variants.

---

## 6. Integration Points

### 6.1 GUI

- Settings / toggle:
  - Global “Enable learning” checkbox.
  - Learning mode selector: Off / Passive only / Passive + Active.
- Per‑run options:
  - “Capture learning record for this run” checkbox.
  - “Convert this run into a Learning Run” button when applicable.

- Learning UI:
  - A simple “Review & Rate Recent Runs” dialog.
  - A “Create Learning Run” wizard.

### 6.2 Controller & Pipeline

- Controller decides:
  - Whether a given run should produce LearningRecords.
  - Whether it should be treated as a LearningRunStep vs normal run.

- PipelineRunner:
  - Receives a learning callback / writer.
  - Emits LearningRecords as runs complete, including variant info.

### 6.3 Cluster

- LearningRuns can be distributed across cluster nodes.
- Each LearningRunStep maps cleanly to a **cluster job**, and results feed back into the same LearningRecord format.

---

## 7. External LLM Integration (Future)

LearningRecords are designed to be LLM‑friendly:

- Self‑contained JSONL lines with clear fields.
- No heavy binary payloads – only references to images on disk.

Future responsibilities of an external LLM could include:

- Suggesting new preset configs per pack.
- Suggesting learning plans (“Try varying Sampler between X and Y next.”).
- Explaining trends in human‑readable language.

These are **future PRs**; the v2 spec only ensures that records and structures are ready for that integration.

---

## 8. Non‑Goals

- No on‑device deep learning models for auto‑rating images (at least initially).
- No heavy analytics UI beyond basic tables and simple charts.
- No multi‑user learning; the system is optimized for a single operator/home lab setup.

---

## 9. Testing Expectations

- Unit tests for core data structures and serializers.
- Tests for LearningRunner stub behavior and pipeline hooks.
- Tests that ensure LearningRecords are written atomically and never corrupt on failure.
- Future tests for the Learning Run GUI (once implemented) using the GUI V2 harness.
#### 2.4.1 ModelProfile & StyleProfile Schema for Defaults (V2-P1)

In V2-P1, ModelProfiles are extended to encode **refiner and hires-fix defaults**
so StableNew can start each model from a sane, opinionated baseline without hardcoding
values in GUI code or controller wiring.

##### ModelProfile default fields

At minimum, each ModelProfile MAY provide:

- `default_refiner_id: Optional[str]`  
  Logical ID of the recommended refiner (see `docs/model_defaults_v2/V2-P1.md §2.1`; e.g.,
  `sdxl_refiner_official`, `realvisxl_refiner`, `wd15_refiner`).

- `default_hires_upscaler_id: Optional[str]`  
  Logical ID of the hires-fix upscaler (see §2.2; e.g., `swinir_4x`, `4x_ultrasharp`, `4x_animesharp`).

- `default_hires_denoise: Optional[float]`  
  Suggested hires denoise strength; ranges used for Learning sweeps/UI hints:
  * 0.20–0.40 for realism  
  * 0.20–0.35 for portrait realism  
  * 0.30–0.50 for stylized / semi-real  
  * 0.35–0.60 for anime

- `style_profile_id: Optional[str]`  
  Optional link to a StyleProfile (see `docs/model_defaults_v2/V2-P1.md`), such as
  `sdxl_realism`, `sdxl_portrait_realism`, `sdxl_stylized`, `sd15_realism`, or `anime`.

These fields are **soft defaults**: they are applied only when there is no last-run or explicit
preset override for the current base model/pack.

##### Precedence (ModelProfiles vs Last-Run vs Presets)

When constructing a new `PipelineConfig` for a model:

1. If a **last-run config** exists for the current context, its refiner/hires values take precedence.
2. Else, if a **user preset** is explicitly loaded, the preset values win.
3. Else, if a **ModelProfile** (optionally with `style_profile_id`) defines defaults, apply them.
4. Else, fall back to engine defaults (e.g., refiner disabled, base upscaler, conservative denoise).

ModelProfiles therefore provide a first-good guess but never override explicit user or historical intent.

##### Learning & Randomizer Considerations

- **Learning** treats these ModelProfile defaults as the baseline configuration when designing experiments
  (especially when sweeping hires denoise around `default_hires_denoise`). LearningRecords still capture
  the actual values used per run.
- **Randomizer** does **not** randomize `refiner_id` or `hires_upscaler_id` by default. Those keys belong to the
  base configuration defined by ModelProfiles + Learning, while Randomizer focuses on creative axes
  (prompt matrices, LoRAs, style toggles, CFG/steps, etc.).

Together, the rules above ensure:

* Defaults are defined once (ModelProfiles + StyleProfiles).  
* Pipeline tab only displays and edits those defaults.  
* Learning can later adjust defaults without touching GUI logic.  
* Randomizer remains a controlled, secondary exploration layer.
