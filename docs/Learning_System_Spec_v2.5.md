#CANONICAL
# Learning_System_Spec_v2.5.md

---

# Executive Summary (8–10 lines)

The Learning System in StableNew v2.5 is a non-invasive, pipeline-adjacent feature that records metadata from each completed job to enable insights, analytics, and future intelligent behaviors.  
It does not alter pipeline execution, change image generation results, or act as a scoring model; its role is strictly **logging + analysis**, not decision-making.  
All data collection is performed through a simple append-only JSONL writer, keyed by JobSpecV2 and NormalizedJobRecord structures.  
The system is designed to support future learning phases: e.g., prompt evaluation, model preference inference, auto-parameter recommendations, and performance telemetry.  
This document defines the LearningRecord schema, writer interfaces, controller hooks, and requirements for pipeline/queue integration.  
It is the canonical reference for Phase 2 (Learning) in the StableNew Roadmap.  

---

# PR-Relevant Facts (Quick Reference)

- Learning System is **read-only and passive** during generation.  
- No pipeline behavior may change because of learning.  
- Output is **append-only JSONL**; each line = one completed job record.  
- All learning hooks attach at job completion, not job creation.  
- NormalizedJobRecord is the source of truth for metadata.  
- Future learning behavior must remain deterministic and non-invasive.  
- All Learning System code must be outside GUI and outside runner.  

---

============================================================
# 0. TLDR / BLUF — What the Learning System Does
============================================================

### **BLUF:**
The Learning System logs structured data about every completed job into a JSONL file, without affecting pipeline execution.

### **It records:**

- Job ID  
- Prompt (positive + negative)  
- Model, sampler, scheduler, cfg, steps  
- Seed, variant/batch indices  
- Pipeline stage settings (refiner, hires, upscale, etc.)  
- Execution duration & timestamps  
- Output file paths  
- (Future) post-run user ratings or metadata  
- (Future) performance metrics (latency, GPU memory)

### **It does NOT:**

- Influence parameters  
- Modify prompts  
- Change image outputs  
- Adjust job order or queue behavior  
- Interfere with pipeline execution  

This ensures stability and compatibility with all v2.5 subsystems.

---

============================================================
# 1. Purpose & Non-Goals
============================================================

### 1.1 Purpose

The Learning System provides:

- A unified schema for capturing job metadata  
- A JSONL-based storage system for easy analysis, indexing, or ML-based post-processing  
- A safe, isolated extension point for learning-driven features  
- A foundation for future automated suggestions, scoring, or clustering  

### 1.2 Non-Goals (Critical)

The Learning System may **not**:

- Modify pipeline configs  
- Change model inference behavior  
- Introduce randomness  
- Change queue ordering  
- Annotate images or modify outputs  
- Replace or alter ConfigMergerV2, JobBuilderV2, or pipeline semantics  

---

============================================================
# 2. LearningRecord Schema (Stable v2.5)
============================================================

The JSON-serializable dataclass is:

```python
@dataclass
class LearningRecordV2:
    # Identity
    job_id: str
    timestamp_start: float
    timestamp_end: float

    # Prompt data
    prompt_positive: str
    prompt_negative: str

    # Model / config
    model: str
    vae: Optional[str]
    sampler: str
    scheduler: Optional[str]
    cfg_scale: float
    steps: int
    seed: int

    # Variant & batch info
    variant_index: int
    variant_total: int
    batch_index: int
    batch_total: int

    # Stage settings
    refiner_enabled: bool
    refiner_strength: Optional[float]  # if applicable
    hires_enabled: bool
    hires_denoise: Optional[float]
    hires_scale: Optional[float]
    upscale_enabled: bool
    upscale_denoise: Optional[float]
    upscale_scale: Optional[float]
    adetailer_enabled: bool

    # Output info
    output_dir: str
    output_paths: list[str]

    # Performance metrics
    total_runtime_sec: float
    stage_runtimes: dict[str, float]  # e.g., {"txt2img": 0.92, "refiner": 1.12}

    # Optional extensibility
    user_rating: Optional[int] = None
    notes: Optional[str] = None
2.1 Invariants
Every completed job produces exactly one LearningRecordV2.

All fields must be present (except optional ones).

Records must be self-contained and independent of external state.

============================================================

3. Learning Writer API
============================================================

3.1 JSONL Writer
Implementation lives in:

bash
Copy code
src/learning/writer_v2.py
API:

python
Copy code
class LearningWriterV2:
    def __init__(self, path: str):
        self.path = path

    def write(self, record: LearningRecordV2) -> None:
        # append JSON-serialized record + newline
Requirements
Must use UTF-8 append mode.

Must never block pipeline execution longer than necessary.

Must catch & log errors without crashing jobs.

Must not modify record.

Forbidden
No reading/parsing of old records.

No aggregation logic in writer.

No schema inference.

============================================================

4. Controller Integration Semantics
============================================================

Learning hooks attach only at the job completion event.

4.1 PipelineController Requirements
At job completion, gather:

NormalizedJobRecord

Pipeline execution metrics

Output file paths

Convert into a LearningRecordV2.

Append via LearningWriterV2.

4.2 No influence on job lifecycle
Learning System does not affect:

queue order

priority

seeds

model selection

stage enable/disable

4.3 Optional GUI Exposure (Phase 2B)
A “Learning” tab may display:

Recent learning entries

Metrics summaries

Ratings UI (if user wants to annotate output quality)

But GUI must not modify pipeline behavior.

============================================================

5. Integration With Other Subsystems
============================================================

5.1 ConfigMergerV2
No integration. Learning reads merged configs post-run.

5.2 JobBuilderV2
No integration. Variant and batch indices are used when writing records.

5.3 Runner & Executor
Provide final runtime metrics and output file paths.

5.4 Queue and JobService
Provide callbacks at job completion.

5.5 GUI / AppState
Must not hold Learning System state; it is append-only logging.

============================================================

6. Performance & Reliability Requirements
============================================================

Learning writes must be lightweight (<1ms typical).

Writer errors must never interrupt job execution.

Logging must preserve order (append-only).

File locking must be minimal (append-only is safe on most platforms).

Supports both local and network-mounted paths.

============================================================

7. Testing Requirements
============================================================

7.1 Unit Tests
JSONL writer writes valid lines

Record serialization correctness

Missing optional fields handled correctly

7.2 Integration Tests
Learning hook fires exactly once per completed job

Record contains correct merged config values

Variant/batch indices match JobBuilder outputs

Output paths recorded correctly

7.3 Pipeline Simulation Tests
Simulated pipeline run produces LearningRecord lines

Stage runtime aggregation correct

Seeds and prompts preserved

7.4 Negative Tests
Writer failure does not prevent pipeline completion

Missing output paths gracefully handled

============================================================

8. Future Extensions (v2.6+)
============================================================

Planned future capabilities:

Learning-based suggestion engine (“parameter recommendations”)

Prompt embeddings for semantic comparison

Auto-curated prompt pack improvements

Reinforcement signals from user ratings

Cluster-wide learning aggregation (Phase 3)

Visualization dashboards (success rates, runtime distributions, seed uniqueness)

These extensions must remain:

deterministic

non-invasive

opt-in

pipeline-neutral

============================================================

9. Deprecated Behaviors (Archived)
============================================================
#ARCHIVED
(Do not implement; included for historical reference only)

Deprecated:

Embedding “learning hooks” inside runner internals

Mutating configs based on prior runs

In-run auto-tuning

Hidden prompt transformations

Anything that changes seeds or model selection

All replaced by the v2.5 passive-logging Learning System.

End of Learning_System_Spec_v2.5.md