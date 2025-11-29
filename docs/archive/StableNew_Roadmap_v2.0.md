# StableNew Roadmap v2.0  
_Status: Draft – V2 Strategic Baseline_

## 1. Purpose and Vision

StableNew V2 is a **controller and UX layer for high‑throughput, multi‑stage AI imaging**, designed to:
- Give non‑experts **one‑click pipelines** that “just work”.
- Give power users deep control over **per‑stage configs, randomization, and learning**.
- Scale from a **single PC** to a **cluster of GPUs on a home LAN**, with StableNew acting as the central coordinator.
- Evolve continuously via **user feedback loops** (learning system) rather than brittle hand‑tuned presets.

This roadmap replaces the earlier StableNew_Roadmap_v1.0 and formally pivots the project toward:

- A **modular GUI V2** (panels, stage cards, status bar).
- A **stage‑based pipeline runner** with CancelToken and structured logging.
- A **Hybrid Learning System (L3)** – user can opt into passive rating or active experiment modes.
- A **Queue‑Manager‑based Cluster Scheduler (C3)** – StableNew as orchestrator, multiple worker nodes running workloads.
- A **safer randomizer** that is clearly secondary to learning: learning locks in strong configs, randomizer explores tasteful variation.

---

## 2. Strategic Goals

1. **User Experience**
   - Single “Run Full Pipeline” action with smart defaults.
   - Guided “Learning runs” that show clear comparisons for a single variable at a time.
   - Randomizer tools that feel playful but never chaotic or confusing.
   - Clear, non‑technical feedback language (“Try lowering noise”, not “denoising_strength=0.35”).

2. **Architecture & Maintainability**
   - Strict **layering**: GUI → Controller → Pipeline → API/Utils → External SD WebUI.
   - Testable units at each layer (GUI V2 harness, controller, pipeline runner, learning, randomizer, cluster scheduler).
   - Legacy GUI V1 preserved only as archived tests / reference; V2 is the center of gravity.

3. **Learning & Adaptation**
   - Every meaningful run can produce a **LearningRecord** (config + outputs + user rating).
   - The system can propose **Active Learning experiments** for a single parameter (steps, CFG, sampler, etc.).
   - Over time, each **prompt pack** or style/theme accumulates a profile of “what works well”.

4. **Cluster & Throughput**
   - StableNew becomes a **job dispatcher** that can:
     - Discover LAN nodes and their GPU capabilities.
     - Maintain a **central queue** of work.
     - Assign jobs based on GPU VRAM, current load, and stage type.
   - The same learning & randomizer logic must work identically regardless of whether one or many machines are involved.

5. **Safety & Reliability**
   - “No surprises” around file IO, config mutation, or GUI threading.
   - Strict test coverage for:
     - CancelToken honoring at each stage.
     - Learning record writing and replay.
     - Randomizer parity (preview vs pipeline).
     - Cluster scheduling decisions in dry‑run mode.

---

## 3. Current State (Authoritative Baseline)

As of the **StableNew-MoreSafe-11-21-2025-0818** snapshot:

- **GUI V2**
  - StableNewGUI constructs a **V2 layout**:
    - Sidebar (prompt packs, lists).
    - PipelinePanelV2 with **Txt2ImgStageCard**, **Img2ImgStageCard**, **UpscaleStageCard**.
    - RandomizerPanelV2 (matrix/fanout & variant count).
    - Preview/Status bar panels with progress + ETA.
  - GUI V2 tests exist and are the **only GUI tests run by default**; GUI V1 tests are archived under a legacy folder.

- **Pipeline & Controller**
  - PipelineRunner encapsulates the full stage execution, taking **PipelineConfig + CancelToken**.
  - AppController / PipelineController convert GUI state + config into a runner invocation.
  - Upscale / tiling safety limits exist and are tested.

- **Randomizer**
  - Randomizer is a **utils‑only module**, with matrix parsing and rotation/fanout logic.
  - A **RandomizerAdapter** bridges GUI V2 to the randomizer and ensures plan/preview parity.
  - Import safety protections are in place (no GUI imports from utils).

- **Learning**
  - Learning **plan, runner, adapter, feedback, and record** stubs exist as pure Python modules.
  - PipelineRunner can optionally emit **LearningRecords**.
  - No user‑visible “Learning mode” yet in the GUI – hooks and stubs only.

- **Tests**
  - GUI V2 harness verifies layout skeleton, button wiring, pipeline config roundtrips, randomizer integration, and status bar progress/ETA.
  - Safety tests ensure utils/randomizer remain GUI‑free.
  - Learning tests verify dataclasses, record serialization, and runner/controller hooks.

- **Cluster**
  - Cluster vision is defined conceptually only; there is **no cluster scheduler implementation yet**.

---

## 4. Major Workstreams

### 4.1 GUI V2 Completion

- Finish stage cards with all relevant fields (including ADetailer, Refiner, Hires fix where appropriate).
- Group Run / Stop / Queue mode controls into a dedicated pipeline command bar within the V2 layout.
- Add an **Advanced Prompt Editor** entry point so long-form prompts can be edited in a focused overlay without changing pipeline semantics.
- Add **Learning mode toggles** (Off / Passive / Active) at the GUI level.
- Add **Randomizer UX** enhancements (clear labels, “How many variants?”, safety hints).
- Implement **preset & profile management** within GUI V2.

### 4.2 Pipeline & Stage Sequencer

- Finalize stage sequencing rules:
  - txt2img → optional img2img → optional adetailer → optional upscale → optional post‑processors.
- Ensure every stage:
  - Reads config from the shared **PipelineConfig**.
  - Reports progress with stage‑scoped progress information.
  - Honors CancelToken and failure propagation into the GUI.

### 4.3 Learning System (L3 Hybrid)

- Embed **passive learning**:
  - User can rate each run (e.g., 1–5 stars, tags like “too noisy”, “too smooth”, “nailed it”).
  - Ratings create **LearningRecords** keyed by (prompt pack, style, pipeline config, outputs).

- Embed **active learning**:
  - User can trigger a **Learning Run** where a single parameter is systematically varied:
    - Example: steps = [15, 20, 25, 30, 35] while keeping everything else fixed.
  - Runs may produce 1–3 images per variant.
  - Afterward, the user rates each variant; results are captured as a single LearningPlan + LearningRunResult.

- Hybrid (L3) behavior:
  - Default: passive learning on any run (if enabled in settings).
  - Advanced: user can opt into targeted, per‑parameter Learning Runs.

### 4.4 Randomizer System

- Keep randomizer **secondary to learning**:
  - Learning defines strong “base configs” per style/pack.
  - Randomizer applies **tasteful variation** on top (matrix for styles, LoRAs, embeddings, color grades, etc.).

- Ensure parity:
  - Variant count preview must **always** match actual pipeline runs.
  - Matrix “rotate” and “sequential” modes must behave deterministically.

### 4.5 Cluster Scheduler (C3)

- Introduce a **central queue manager** inside StableNew:
  - Job model: (prompt pack, config, learning/randomizer metadata).
  - Stage assignments: jobs can be full‑pipeline or per‑stage on a node.

- Worker agents:
  - Lightweight agents run on each node, advertising:
    - GPU VRAM, device count, approximate throughput.
    - Current utilization / busy state.
  - Agents accept jobs, run SD WebUI or an equivalent backend, and report results + metrics back.

- Scheduler behavior (C3):
  - Uses **capability + load** to pick nodes:
    - Heavier jobs (large images, many steps) go to nodes with more VRAM.
    - Backfills smaller jobs into idle nodes.
  - Integrates with learning system:
    - Nightly/batch learning runs are distributed across the cluster.
    - Daytime “interactive” work may be constrained to a single machine to avoid latency.

---

## 5. Phased Roadmap

### Phase 1 – Solidify V2 Single‑Node Experience

- Lock V2 layout and stage cards (txt2img, img2img, upscale, adetailer/refiner where applicable).
- Surface prompt pack browsing/apply in the GUI V2 sidebar without changing pack formats.
- Complete pipeline stage sequencing and CancelToken handling.
- Add passive learning hooks for every run (LearningRecord writing).
- Finalize randomizer preview/pipeline parity and UI clarity.
- CI: GUI V2 + learning + randomizer tests must be green by default.

### Phase 2 – Learning & Guided Exploration

- Implement “Learning Run” workflows in the GUI (per‑parameter experiments).
- Provide a minimal “Insights” view (e.g., “For this pack, 30–35 steps tends to score higher than 15–20.”).
- Add tools to **export** a bundle of LearningRecords for external LLM analysis.
- Introduce recommended config presets per prompt pack based on accumulated records.

### Phase 3 – Cluster‑Ready Controller

- Implement the queue manager and node registry.
- Build local “loopback” integration (single machine uses the same queue mechanism).
- Implement basic schedulers (first C3 version): capability + load aware.
- Ensure learning and randomizer logic are **backend‑agnostic** (single vs multiple nodes).

### Phase 4 – Distributed Learning & Batch Production

- Support **overnight batch jobs**:
  - Many prompt packs with randomizer turned on.
  - Learning turned on so the next morning the user can rate outputs.
- Add higher‑level reports (“Which styles are performing well?”, “Which LoRAs underperform?”).
- Optional integration hooks for external LLMs to generate or refine presets automatically (AI‑assisted config builder).

---

## 6. Risks and Non‑Goals

- **Non‑Goals**
  - Not trying to become a full replacement for SD WebUI’s internal UI.
  - Not a general distributed compute framework – focus is SD‑style imaging pipelines.
  - Not a public multi‑tenant service; design is optimized for **home lab / single operator** use.

- **Key Risks**
  - Over‑complexity in learning UI – addressed by keeping Learning Runs focused on **one variable at a time**.
  - Cluster orchestration scope creep – controlled by a strong queue model and clear Stage/Pipeline abstractions.
  - Configuration explosion – mitigated by learning‑driven presets and a strong separation between **“base configs”** and **“randomized overlays”**.

---

## 7. How to Use This Roadmap

- Treat this as the **single source of truth** for direction and priorities.
- Every PR should reference at least one section from:
  - This roadmap
  - The Architecture v2 document
  - The relevant subsystem spec (Learning, Randomizer, Cluster).
- When deviations are needed, update this roadmap first – then implement.
