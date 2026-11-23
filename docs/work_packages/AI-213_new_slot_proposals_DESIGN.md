# AI-213 (design for review): propose a new matrix slot and where to put it

Status: **design for owner review. Not authorized. No code is written until the owner approves it and answers the decisions
below.** Dated 2026-11-22. Builds on AI-212 (`AI-212_slot_variety.md`); truth after any merge lives in
`docs/Subsystems/AiAssist/AI_ASSIST.md`.

## Problem

AI-212 only adds values to slots that already exist in the pack's Matrix tab. An operator who asks "give me good lighting
prompts for hyperrealism" on a pack with no lighting slot gets a refusal, because the model has nothing to work with. The more
useful behavior is the one a person would do by hand: decide that the prompt needs a `lighting` slot, pick starting values, and
put `[[lighting]]` in a sensible place in the prompt sentence.

(A small first step, already done on `codex/ai-slot-variety-ux`: the dialog now names the slots a request can use and says it
cannot create new ones, refusals point to the Matrix tab, and "Show runtime detail" works for remote refusals.)

## Proposal

A sixth typed kind, `SLOT_PROPOSAL`, behind its own button **Suggest new slot**. AI-212's contract stays unchanged.

**Request** (all authored text is delimited data, as today): the goal; the pack's positive prompt sentence; the existing slot
names (so the model avoids duplicates); and a **closed list of insertion points computed by code**. An insertion point is a
position between clauses of the sentence, shown to the model with a short snippet of the text around it. Code never offers a
point inside a protected token (`<lora:...>`, `<embedding...>`, `[[slot]]`, `__wildcard__`).

**Response**: 1 to 3 proposals of exactly `{slot_name, values, insertion_point, rationale}`. `insertion_point` is an index from
the closed list, so the model cannot name a position that does not exist. 3 to 6 values per slot, same value rules as AI-212.

**Judge** (deterministic, outside `src/ai_assist`, like AI-212's): the slot name normalizes (`normalize_matrix_slot_name`), is
not empty, not already a slot, and does not collide with another proposal; every value passes the AI-212 value rules; the
insertion index exists; the prompt sentence is byte-identical to the one the request was built from. Anything failing is shown
with its reason and never offered.

**Accept**: one press per proposal, **Add slot and place marker**. Through the Matrix tab's and prompt editor's own edit paths
it (1) adds the slot with its values and (2) inserts `[[slot_name]]` at the chosen point. The pack becomes modified and
unsaved. It is all-or-nothing: if the pack, matrix or sentence changed since the request, nothing happens and the review clears.
Before the press, the dialog shows the new matrix size (see decision 3).

## What changes in the AI-212 promises

AI-212 states: no slot is created and the prompt sentence is never changed. This design relaxes both, **only** for
`SLOT_PROPOSAL`, **only** on an explicit per-proposal press. Still true: nothing is saved, previewed, compiled, queued or
generated; no model, workflow, stage or setting is touched; goal, values and suggestions stay out of logs and persisted state.
The panel notice and `AI_ASSIST.md` are updated to say exactly this.

## Decisions needed from the owner

1. **May AI Assist's accept action edit the prompt sentence?** Today it never does. This is the main policy change.
   Recommendation: yes, only the single `[[slot]]` insertion above, never rewording.
2. **One proposal per press, or accept several at once?** Recommendation: one per press, so each change is reviewable.
3. **Matrix growth.** Every new slot multiplies the number of combinations the matrix expands to. Recommendation: show
   "matrix goes from A to B combinations" before the press and refuse past the existing matrix limit.
4. **Undo.** Whether the editor gives a single undo step for slot plus marker is unverified. Recommendation: confirm during
   implementation; if it cannot, state clearly in the dialog how to revert (delete the slot row and the marker).
5. **Separate button or fold into Suggest variety?** Recommendation: separate button, so the AI-212 contract and its tests do
   not move. A later change could route a "no fitting slot" refusal to the new button.
6. **Quality bar.** Neither Qwen3.5-4B nor LFM3 has been tried on this task. Recommendation: extend the existing contract
   acceptance harness with slot-proposal cases and keep the Preview label; make no quality claim from demos alone.

## Scope and plan if approved

- In: contract kind, framing and schema, strict validator, insertion-point computation, judge, review model, dialog section,
  Matrix and editor accept path, tests (judge, stale/atomic accept, protected tokens, visibility, no-log), docs, `STATUS.md`,
  `CODE_MAP.md`.
- Out: any save/queue/compile path, `src/pipeline/`, `src/queue/`, `argv.py`, `RunLimits`, qualification identities, ratchet
  ceilings; rewording of the prompt; editing or removing existing slots or values.
- Execution class: **Standard**, comparable to AI-212. Local only; no model or GPU run is needed for the unit and journey tests.
- Verification: the AI-212 journey-test pattern plus new tests for atomic accept and unchanged-sentence-except-marker.
