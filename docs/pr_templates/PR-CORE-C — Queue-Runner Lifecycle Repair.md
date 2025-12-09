PR-CORE-C — Queue-Runner Lifecycle Repair.md

Version: v2.6-CORE
Tier: Tier 3 (Queue/Runner subsystem)
Author: ChatGPT (Planner), approved by Rob
Date: 2025-12-08
Discovery Reference: D-23
Depends on:

PR-CORE-A — UnifiedJobSummary + PromptPack-Only invariant

PR-CORE-B — Deterministic builder chain (ConfigMerger → PromptResolver → ConfigResolver → RandomizerEngine → JobBuilder producing full NormalizedJobRecords)

1. Summary

PR-CORE-C repairs and stabilizes the entire Queue → Runner lifecycle, making it predictable, architecture-compliant, and fully aware of the new PromptPack-only job model.

This PR guarantees:

The queue accepts only fully-normalized jobs (NormalizedJobRecord).

Job lifecycle transitions are deterministic and serially consistent.

The Runner receives the exact resolved configuration (prompts, stage chain, seed, matrix metadata, etc.).

GUI (Queue Panel, Running Job Panel), History, and Learning all display correct lifecycle states derived from these normalized records.

Debug Hub receives complete structured lifecycle events.

The architecture after PR-CORE-C:
PromptPack → (PR-CORE-B Builder) → NormalizedJobRecord
      → JobService.submit(job_records)
      → JobQueueV2.enqueue()
      → JobRunnerDriver.execute(record)
      → History.write(record, status)
      → GUI + DebugHub receive lifecycle events


This PR forms the execution backbone for StableNew v2.6.

2. Motivation / Problem Statement

Prior issues (before PR-CORE-A/B):

Queue received partial jobs (missing stage configs, missing prompts, inconsistent seeds).

RUNNING jobs sometimes never completed because lifecycle transitions were not atomic.

Debug Hub could not reliably “Explain Job” due to inconsistent job fields.

GUI showed stale entries or incorrect transitions.

History contained incomplete or mismatched job payloads.

Free-text prompts and GUI-generated job objects led to nondeterministic failures.

With the update:

We now have deterministic, complete NormalizedJobRecord objects produced by PR-CORE-B.

This PR ensures the Queue & Runner treat those records as the only valid unit of execution, enforcing strict input validation and stable lifecycle semantics.

3. Scope
In Scope

Job submission path

Queue insertion logic

Lifecycle transitions

Background worker loop (RunnerDriver)

UnifiedJobSummary generation for running jobs

History write operations

Debug Hub lifecycle event emission

Enforcement of PromptPack-only invariant at the JobService boundary

Not In Scope

Job construction (handled by PR-CORE-B)

UI view behavior (handled by PR-CORE-D)

Learning metadata details (already defined in Learning Spec)

Executor internals (pipeline_runner/executor.py is explicitly forbidden)

4. High-Level Behavior Changes (Before → After)
Subsystem	Before	After
JobService	accepted partial configs; sometimes mutated input	accepts only full NormalizedJobRecord; never mutates it
Queue	stored mixed job types, could hold stale objects	stores immutable NormalizedJobRecords only
Runner	sometimes invoked without complete stage configs	always receives fully resolved record
Lifecycle	inconsistent transitions; RUNNING stuck	strict finite-state machine (FSM)
History	incomplete metadata, missing prompt provenance	writes full job metadata including PromptPack ID and matrix slots
Debug Hub	ambiguous lifecycle logs	receives structured events for SUBMITTED → COMPLETED
5. Architectural Alignment
Based on ARCHITECTURE_v2.5.md (patched)

This PR implements the correct execution flow:

Controller → JobService → JobQueueV2 → RunnerDriver → History → Summary outputs

PromptPack-Only Enforcement

JobService must reject any submission where:

prompt_pack_id is missing

any required NormalizedJobRecord field is missing (positive_prompt, stage chain, etc.)

builder was bypassed

Queue and Runner never accept or modify “draft” jobs.

6. Updated Data Contracts
6.1 Input Contract

JobService.submit_jobs(jobs: list[NormalizedJobRecord])

Every job MUST satisfy the full PR-CORE-A record schema:

prompt_pack_id (required)

prompt_pack_row_index

positive_prompt, negative_prompt

positive_embeddings, negative_embeddings, lora_tags

matrix_slot_values

stage chain (list[StageConfig])

global fields (seed, cfg_scale, width, height, sampler, scheduler, clip_skip, base_model, vae)

pipeline semantics (loop_type, loop_count, images_per_prompt, variant_index, batch_index)

randomization metadata

run_mode + queue_source (supplied by controller)

Queue assumes this object is immutable and complete.

7. Step-by-Step Implementation Plan
A. JobService Enforcement Layer
A1 — Validate input type

Reject anything not a NormalizedJobRecord.

A2 — Validate mandatory fields (PromptPack-only)

Reject job if:

prompt_pack_id is None

positive_prompt or negative_prompt empty

stage_chain empty or malformed

any StageConfig missing required values (enabled, step params for enabled stages)

missing seeds, sampler, cfg, or matrix metadata

On failure:
Return structured error to controller → surface UI message.

B. Queue Insertion (JobQueueV2)
B1 — Queue stores jobs immutably

No mutation of the normalized record.

B2 — Insert all jobs FIFO

Each job gets:

QUEUED timestamp

SUBMITTED lifecycle event emitted immediately

B3 — Enforcement rule:

Queue does not build, merge, or resolve prompts.
All resolution must have already happened in PR-CORE-B.

C. Background Worker / RunnerDriver
C1 — Worker loop

Pseudo-code:

while running:
    job = queue.dequeue()
    update(job, status=RUNNING)
    emit_event("RUNNING", job)

    try:
        runner_driver.execute(job)
        update(job, status=COMPLETED)
        history.write(job)
        emit_event("COMPLETED", job)
    except Exception as e:
        update(job, status=FAILED, error=str(e))
        history.write(job)
        emit_event("FAILED", job)

C2 — RunnerDriver responsibilities

Convert NormalizedJobRecord → payload for executor

Pass stage_chain, prompts, seeds, cfg, model, VAE, matrix metadata

No computation or merging of prompts/config

Never modify the job record

C3 — Mark completion deterministically

On success → COMPLETED

On exception → FAILED

On cancellation → CANCELLED (job must be removed from queue before RUNNING)

D. Lifecycle State Machine

Allowed transitions:

SUBMITTED → QUEUED → RUNNING → COMPLETED
                                 ↘ FAILED
                                 ↘ CANCELLED


Illegal transitions must raise an internal warning and be logged to Debug Hub.

E. History Recording

History stores:

full NormalizedJobRecord (copy)

status

created_at, completed_at

output_paths (populated by runner)

error_message if FAILED

History must be append-only.

F. Debug Hub Integration

Emit structured events:

{ event_type: "SUBMITTED", job_id: ..., summary_fields... }
{ event_type: "QUEUED",    job_id: ..., ... }
{ event_type: "RUNNING",   job_id: ..., ... }
{ event_type: "COMPLETED", job_id: ..., ... }
{ event_type: "FAILED",    job_id: ..., error: ... }


Debug Hub “Explain Job” uses UnifiedJobSummary and NormalizedJobRecord fields.

8. Test Plan (Updated for PromptPack-Only)
T1 — Reject job without prompt_pack_id

Expected: JobService throws validation error; no queue insertion.

T2 — Submit a PromptPack-based job

Build NormalizedJobRecord using PR-CORE-B fixtures

Submit

Verify: SUBMITTED → QUEUED → RUNNING → COMPLETED transitions

Verify History contains correct fields

T3 — Multi-job FIFO order

Queue A then B then C → ensure RUNNING order matches FIFO.

T4 — Failure path

Runner throws an exception → FAILED
History contains error; lifecycle events visible in Debug Hub.

T5 — Batch × Variant fanout

Submit a list of N NormalizedJobRecords from PR-CORE-B; ensure:

all enter queue

all run

records maintain indexes (variant_index, batch_index)

T6 — UI behavioral tests (coordinated with PR-CORE-D)

Pipeline Tab run button disabled unless Prompt Pack selected

Running Job panel uses UnifiedJobSummary from lifecycle events

Queue panel updates correctly on each job state event

Debug Hub logs all transitions

T7 — No intermediate mutation

Assert that the job objects in queue and job objects in history are bit-for-bit equal (except timestamps / status).

9. Acceptance Criteria

Queue only accepts NormalizedJobRecord objects from PR-CORE-B.

No free-text, partial, or GUI-constructed job enters queue.

Lifecycle transitions are deterministic and correct.

Runner receives complete resolved configurations.

Debug Hub shows correct events for every state.

History contains immutable, reconstructable job entries including PromptPack provenance.

All tests pass including PromptPack-only validation tests.

GUI (PR-CORE-D) reflects the updated lifecycle semantics.

10. Documentation Impact Assessment
Update required in:

ARCHITECTURE_v2.5.md

Add explicit statement: Queue accepts only fully constructed NormalizedJobRecord (PromptPack-only).

Roadmap_v2.5.md

Mark Phase C: "Queue/Runner Lifecycle Repair with PromptPack-only enforcement".

DEBUG_HUB_v2.5.md

Add structured lifecycle event examples.

StableNew_Coding_and_Testing_v2.5.md

Update queue testing section with PromptPack-required rule.

CHANGELOG.md

11. CHANGELOG Entry Template
## [PR-CORE-C] - 2025-12-08
Queue/Runner Lifecycle Repair (PromptPack-only)
- Enforced that JobService accepts only full NormalizedJobRecords derived from Prompt Packs.
- Implemented strict lifecycle FSM for SUBMITTED → QUEUED → RUNNING → COMPLETED/FAILED.
- Added immutable job storage in JobQueueV2.
- Updated RunnerDriver to consume only canonical job records.
- Added structured lifecycle events for Debug Hub.
- Updated History subsystem to store full normalized records.
- Updated tests to assume PromptPack-only job construction.

12. Rollback Plan
If rollback necessary:

Restore prior queue behavior (mixed job types).

Remove PromptPack-only validation.

Revert lifecycle FSM enforcement.

Revert Debug Hub structured event layer.

Restore older History write behavior.

Rollback does not break builder (PR-CORE-B) but will re-introduce architectural drift, so should be avoided unless critical.