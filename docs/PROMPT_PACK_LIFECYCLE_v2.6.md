# StableNew PromptPack Lifecycle v2.6

Status: Canonical, Binding
Updated: 2026-09-05

## 0. Scope

This document governs PromptPack-authored image intent. PromptPack is the
primary image authoring surface, but it is not the universal identity or input
format for image edit, reprocess, replay, learning, CLI, video, or training work.

## 1. Canonical representation

A PromptPack is one versioned JSON document. It contains, as applicable:

- schema version and stable pack identity;
- display name and revision;
- prompt slots and negative prompts;
- authoring metadata and variables;
- deterministic matrix/randomizer definitions;
- PromptPack-side defaults;
- provenance needed to migrate or audit the document.

TXT and TSV are import/export interchange formats only. They are not paired
runtime authority, and the absence of a TXT/TSV file does not invalidate a JSON
PromptPack.

Legacy paired TXT/JSON content must be migrated by a backup-first tool. When the
two sides disagree, migration reports the conflict and requires an explicit
resolution; it must not silently overwrite either source.

## 2. Lifecycle

`Author/Import -> Validate -> Store -> Select -> Draft -> Resolve/Expand -> Compile NJR -> Submit -> Queue -> Run -> Artifacts/History -> Learning`

The authoring document is mutable before compilation. The resulting NJR is an
immutable execution snapshot.

## 3. Authoring and validation

PromptPacks may be created in the editor, imported from TXT/TSV, or edited as
schema-valid JSON. Validation covers:

- schema and supported version;
- non-empty stable identity and revision rules;
- slot structure and prompt text;
- matrix/randomizer references and expansion bounds;
- legal PromptPack-side defaults;
- absence of backend-private workflow payloads.

Invalid documents cannot compile new work. Validation errors must identify the
field and corrective action without partially saving a replacement.

## 4. Draft and compilation

Selecting a pack loads authoring data into the application draft. User edits to
the draft do not mutate the stored pack unless the user explicitly saves it.

The PromptPack compiler:

1. validates the selected JSON document;
2. layers explicit user overrides over pack defaults;
3. resolves variables, randomizer choices, matrix products, and config sweeps
   deterministically;
4. validates supported image stages and models;
5. emits one immutable NJR per expanded execution;
6. records `source.kind = "prompt_pack"`, pack identity, revision, and relevant
   provenance in each NJR.

All expansion completes before queue submission. The runner does not reopen the
pack, choose randomizer values, or reconstruct source defaults.

## 5. Runtime ownership

After compilation:

- `JobService` receives NJR plus submission policy;
- repository/queue own status and scheduling;
- runner consumes typed NJR workload/stages;
- history stores execution state and an NJR snapshot or stable reference;
- learning consumes artifacts and provenance without rewriting the pack.

Pack identity is required only for NJRs whose source kind is `prompt_pack`.

## 6. Import, export, and migration

- JSON is the only native save format.
- TXT/TSV export is an explicit interoperability action.
- Import produces a preview and validation report before save.
- Migration preserves originals, reports conflicts, and is idempotent.
- Runtime code never falls back to TXT/TSV when JSON validation or lookup fails.
- Once a legacy pack is migrated and verified, its originals are retained as
  recoverable migration inputs according to the runbook, not live authorities.

## 7. Forbidden behavior

- requiring two same-basename files for a valid pack;
- treating TXT/TSV as execution-time truth;
- requiring `prompt_pack_id` for a non-PromptPack NJR;
- loading or mutating PromptPack files from runner code;
- deferring prompt expansion or randomization until execution;
- storing Comfy or other backend workflow JSON in a PromptPack;
- silently resolving migration conflicts;
- maintaining dual JSON and TXT write paths after cutover.

## 8. Implementation status

The repository already contains unified-JSON authoring behavior, while active
code/tests still carry paired-file and universal pack-identity assumptions.
`PR-MVP-050` performs the atomic storage/loader/test migration. Until it closes,
this document is the target contract and the architecture gap register remains
open.
