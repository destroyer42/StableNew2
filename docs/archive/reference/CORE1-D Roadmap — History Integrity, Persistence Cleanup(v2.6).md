CORE1-D Roadmap — History Integrity, Persistence Cleanup(v2.6).md

The D-phase focuses on:

Eliminating all pre-NJR persistence formats

Repairing, migrating, or compacting historical entries

Ensuring perfect forward/backward compatibility of run records

Making job replay deterministic, NJR-only, and architecture-compliant

Flattening the last remaining DTO sprawl connected to persistence

Guaranteeing that nothing in StableNew can break when old jobs are loaded

This is the final phase before the “E” series (full modernization), and must be completed in strict order.

🔵 CORE1-D1 — Legacy History Conversion to NJR Snapshots
Intent

Unify the entire history layer to NJR snapshots, converting any legacy JSONL history entry that contains:

pipeline_config

legacy job dicts

partial draft-related metadata

missing run metadata fields

Key Work

Extend / utilize legacy_njr_adapter to hydrate all history entries into full NormalizedJobRecord snapshots.

Rewrite JobHistoryStore load path to:

Detect old entries

Convert them deterministically to NJR

Ensure diff stability (unchanged output if converted twice)

Ensure all run records (including pre-C-series ones) are valid NJR snapshots.

Required Tests

Load legacy history with mixed-era entries → produce stable NJR-only record set.

Round-trip test:

load → convert → save → load → identical


Replay a legacy entry → runner receives NJR payload.

Acceptance

No history entry anywhere in the repo contains pipeline_config.

No history entry lacks any required NJR fields.

History loading is pure NjR snapshot hydration.

🔵 CORE1-D2 — History Compaction / Migration (Schema v2.6)
Intent

Clean old fields, add missing fields, remove deprecated ones.
Guarantee that history schema matches exactly the architecture spec.

Key Work

Compact multi-entry job histories (e.g., earlier entries with inconsistent fields).

Normalize:

timestamp formats

run_id / job_id consistency

model fields

prompt/negative prompt routing

stage metadata completeness

Introduce history_version: "2.6" or similar field in each entry.

Tests

Migration produces identical history when re-run.

Compacted history matches a canonical fixture.

Acceptance

All history entries conform to v2.6 schema.

No history entry contains unused fields.

🔵 CORE1-D3 — Unified Job Replay Engine (NJR → RunPlan → Runner)
Intent

Make replay independent of legacy or GUI paths, ensuring that:

Replaying any job (new or legacy-migrated) uses the exact same NJR → RunPlan → Runner pipeline.

Key Work

Add a dedicated replay_job(njr: NormalizedJobRecord) entrypoint.

Ensure JobExecutionController and PipelineController both use this replay path.

Remove all replay functions that decode deprecated shapes.

Strengthen RunPlan creation for replay:

stage integrity

sampling params

model selections

seed rules

Tests

Replay a job from 2023, 2024, 2025 → identical behavior.

Replay a current job → matches direct execution path.

Replay rejects invalid NJRs.

Acceptance

Single unified replay path.

No replay code references legacy fields.

🔵 CORE1-D4 — Job Model Unification (Kill Remaining DTO Sprawl)
Intent

Architectural requirement: StableNew v2.6 must have one job model:

NormalizedJobRecord for:

Display

Persistence

Replay

Diagnostics

Queue operations

And then a few derived view DTOs for UI.

Key Work

Remove intermediate DTOs:

JobUiSummary (merge into NJR snapshot serializer)

any “job preview” DTO duplicating NJR fields

config-snapshot derivatives

Force all display helpers to consume NJR snapshots directly.

Tests

Preview → NJR snapshot

Queue item → NJR snapshot

History item → NJR snapshot

No display code requires job.model_x, job.prompt_x (all come from snapshot).

Acceptance

DTOs exist only as thin presentation wrappers.

No model duplication.

🔵 CORE1-D5 — Normalize Queue Persistence & Remove Transitional Keys
Intent

Ensure queue persistence (if used) is NJR-pure and schema-aligned.

Key Work

Remove transitional fields like:

_normalized_record (now can be replaced by direct NJR storage)

legacy_config_blob

Guarantee queue items store:

NJR snapshot

queue metadata

scheduling metadata

retry/cancellation flags

Tests

Load old queue → auto-migrate to NJR-only items.

Save queue → stable deterministic ordering and schema.

Acceptance

Queue I/O is consistent with history I/O.

🔵 CORE1-D6 — File I/O Cleanup (JSONL Writer & Reader Consistency)
Intent

Fully unify the file I/O stack across:

history store

queue store

replay cache

diagnostics store

last-run store

Key Work

Factor out a canonical JSONL reader/writer.

Add schema version headers (v2.6).

Add strict checksum format for run log lines (optional but recommended).

Tests

All read/write paths round-trip cleanly.

Corrupt-line tolerance + warnings function correctly.

Version-skew tests pass.

Acceptance

All JSONL operations follow one codec.

No file format fragmentation.

🔵 CORE1-D7 — Run-Result Unification (Runner → NJR → Result DTO)
Intent

Standardize how runner results:

enter history

get returned to controller

get returned to GUI

get serialized

get replayed

The architecture demands a single result shape:

RunResult:
    njr: NormalizedJobRecord
    images: List[ImageRef]
    metadata: Dict
    timing: ...
    status: SUCCESS/FAILED/CANCELED

Key Work

Remove old ad-hoc result DTOs.

Replace with the unified RunResult shape.

Ensure PipelineRunner run_njr() returns explicit results in this schema.

Ensure JobExecutionController handles failures consistently.

Tests

Compare run_result from:

direct run

queue run

replay run

All must produce the same result structure.

Acceptance

Run result is fully unified.

🔵 CORE1-D8 — History/Queue/Replay Multi-Version Compatibility Suite
Intent

Ensure StableNew can read & upgrade:

pre-1.0 jobs

1.0–1.3 jobs

2.x jobs with partial metadata

early 2025 jobs

NJR jobs from the new era

Key Work

Create version fixtures for every historical schema.

Unit tests for:

load

migrate

replay

re-save (compact)

Validate behavior matches the architecture’s compatibility matrix.

Acceptance

Multi-version compatibility suite is green.

All migrations deterministic and idempotent.

🔵 CORE1-D9 — Documentation Update & Final Architecture Lock for CORE1
Intent

After all D-phase PRs, update:

ARCHITECTURE_v2.6.md

StableNew_Coding_and_Testing_v2.6.md

Builder Pipeline Deep-Dive_v2.6.md

ARCHITECTURAL_DEBT_ANALYSIS.md

Roadmap_v2.6.md

Required Updates

History migration strategy documented.

Replay engine is NJR-only.

Job model unification is complete.

No pipeline_config references anywhere.

No draft-bundle references.

No reflection anywhere in the system.

Controller chain consolidated.

Persistence schema v2.6 locked.

Acceptance

All docs reflect actual architecture and forbid reintroduction of removed pathways.

CORE1 milestone marked as complete.

🟩 CORE1-D Phase Summary (PR List)
PR ID	Name	Purpose
CORE1-D1	Legacy History → NJR Conversion	Migrate all old history into NJR-only format
CORE1-D2	History Compaction & Schema v2.6	Normalize, flatten, remove obsolete fields
CORE1-D3	Unified Replay Engine	One replay path for all jobs, NJR-only
CORE1-D4	Job Model Unification	Remove redundant DTOs; NJR is the only model
CORE1-D5	Queue Persistence Cleanup	Remove transitional keys; NJR-only queue state
CORE1-D6	File I/O Normalization	Unified JSONL codec and persistence rules
CORE1-D7	RunResult Unification	Single structure for run outcomes
CORE1-D8	Multi-Version Compatibility Suite	Ensure compatibility with all historical data
CORE1-D9	Documentation Finalization	Close out CORE1 and lock the architecture