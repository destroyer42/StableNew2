# StableNew Builder and Compiler Pipeline Deep-Dive v2.6

Status: Canonical, Binding
Updated: 2026-09-05

## 0. Scope

This document defines how typed user/system intent becomes the immutable NJR
execution envelope. It replaces the assumption that every job must pass through
a PromptPack-shaped request.

## 1. Canonical compiler model

`Typed Intent DTO -> Intent Validator -> Source Compiler -> Shared Normalizers -> Deterministic Expansion -> NJR Builder -> NJR Validation`

There may be multiple source compilers. There is one NJR contract.

Supported compiler families are:

- PromptPack image generation;
- image edit and reprocess;
- history replay;
- learning-generated work;
- video workflow;
- CLI;
- training.

A compiler is an application boundary, not a runner or persistence boundary.

## 2. Responsibility split

### 2.1 Intent DTO

Carries source-specific draft input and explicit user choices. It must not carry
queue status, execution results, backend client objects, or GUI widgets.

### 2.2 Source compiler

Validates source identity, resolves source defaults, calls shared normalizers,
performs deterministic expansion, and supplies typed workload/stage data to the
NJR builder.

### 2.3 Shared normalizers

Resolve model references, stage settings, output intent, seeds, and common
configuration into typed values. They do not enqueue, persist, or execute.

### 2.4 NJR builder

Constructs and validates the eight-part NJR core defined by
`ARCHITECTURE_v2.6.md`. It rejects source/workload mismatches and does not add
mutable runtime fields.

### 2.5 JobService

Accepts a valid NJR and small submission policy. It creates the mutable job
execution record through `JobRepository`, enqueues it, and optionally requests
immediate start. `Run Now` is policy, not an execution mode stored in NJR.

## 3. PromptPack compiler

For PromptPack work only:

`PromptPack JSON -> Validation -> Variable/Randomizer Resolution -> Matrix and Sweep Expansion -> Image Normalization -> NJR list`

The compiler records a typed PromptPack source descriptor. Given identical pack
revision, explicit overrides, environment-independent model registry inputs,
and seed material, it must produce structurally identical NJRs apart from
explicitly excluded generated identity fields.

## 4. Other compilers

Non-PromptPack compilers provide their own source descriptors and must not forge
pack identity to satisfy validation. Video workflow types may contain
video-specific authoring data and compile it into an NJR video workload. They do
not become alternate executable records.

Replay either validates a persisted NJR under the current supported schema or
migrates it at the repository boundary before submitting a new NJR with parent
lineage. Runner-side compatibility reconstruction is forbidden.

## 5. Expansion and determinism

All fan-out occurs before submission. The compiler must:

- define stable expansion order;
- enforce a configured expansion limit;
- persist selected/randomized values in provenance;
- assign one job identity per execution;
- report invalid combinations before partial queue submission unless an
  explicitly approved atomic-batch policy says otherwise.

The runner never makes authoring choices.

## 6. Output and errors

Successful compilation returns NJRs. Validation returns structured source-level
errors. Queue identifiers, status, timestamps, progress, output paths, and
runtime errors are not compiler output and are not NJR fields.

## 7. Migration boundary

The existing `PipelineRunRequest` is pack-shaped and may be used only by the
legacy PromptPack intake while `PR-MVP-030` migrates callers. It may not be
extended into a union of every intent type. The migration order is:

1. land the reduced NJR contract and validators;
2. add typed compiler/application interfaces;
3. migrate one source family at a time;
4. remove obsolete pack-shaped generic branches in the same sequence;
5. enforce import and architecture guards.

At no point may a source bypass NJR or the queue.

## 8. Test contract

Each compiler requires tests for:

- valid source-to-NJR compilation;
- invalid source identity and workload mismatch;
- deterministic expansion and limits;
- complete NJR serialization round-trip;
- conditional PromptPack identity;
- absence of mutable execution fields;
- queue submission through `JobService` only;
- no runner or persistence side effects during compilation.

## 9. Forbidden patterns

- one generic DTO with PromptPack-required fields for every source;
- dictionaries passed across compiler, service, and runner boundaries;
- GUI construction of normalized workloads or stage configs;
- compiler-owned queue writes;
- runner-owned source resolution or randomization;
- `DIRECT` or implied direct modes;
- adapters retained without a named deletion step;
- partial serialization of an otherwise accepted NJR.

## 10. Implementation status

`PR-MVP-020` closed the NJR-core half of this contract on 2026-09-07. The
repository now has one frozen eight-part NJR, typed image/video/training
workloads, complete canonical serialization, conditional PromptPack identity,
and an explicit one-way legacy reader. Current builders emit that core and the
runner returns artifacts without writing them back into NJR.

The remaining gap is the compiler/application boundary: callers still use the
pack-shaped `PipelineRunRequest` and callback-heavy submission adapter.
`PR-MVP-030` owns that atomic cutover and deletion of superseded generic paths.
