# PR-IMG-PHOTO-222 — Scope-aware Single/Batch Photo Optimize

Execution Profile + Model/Reasoning Recommendation: Standard/substantial, existing architecture.
Codex GPT-6.1 Sol High / Claude Code Sonnet 5.5 High, Local/Desktop for real Windows Tk and
filesystem acceptance. High effort targets total successful-work cost across UI intent, persisted
aliases and frozen submission parity. No persistence or execution authority expansion is needed.

Controller Surface Assessment: AppController delegates photo preparation and admission through
`src/controller/photo_optimize_submission.py`, retaining its existing public submission method.
Physical lines decrease from 7421 to 7414; the checked-in ceiling decreases accordingly.
The photo tab decreases from 2001 to 1181 lines. Cohesive layout, editing widgets and scope/worker
coordination move to three view modules; toolkit-neutral draft/diff logic lives in
`src/photo_optimize/editing.py`. The extracted helper has no lifecycle or persistence state.

Token-Efficient Validation Plan: first reproduce on three disposable photos; reuse unchanged
settings/migration/compiler coverage. Run focused photo, controller, reprocess and real Tk tests,
then one canonical PR gate near closeout. Use fake JobService and temporary image/sidecar roots.
Inspect aggregate diff and whitespace; Security Review covers untrusted draft data/filesystem writes.
No live runtime, generation or operator asset validation. Hosted CI awaits publication authorization.

## Scope and draft contract

One tab and asset library retain an active photo independently of the selected set. Switching
Single Photo / Batch Edit changes presentation only. Single Photo autosaves only the active draft.
Batch Edit projects Same/Mixed values; checked fields apply, unchecked fields remain unchanged.
Explicit masks include stage flags, model/VAE, stage configuration and saved positive/negative
prompt transformations. Pending checked fields survive selection/scope projection.

Before a batch edit or Pipeline copy, decode/validate every input and serialize every prospective
sidecar without writing. Show every asset and changed field's before/after values in a scrollable
confirmation; cancellation writes nothing. Sidecar fingerprints refuse stale reviews before the
first write and check again per asset. Persistence uses the existing store's atomic sidecar replacement,
not a multi-asset transaction. Results list successful, failed and unconfirmed IDs, including a
readback check when a save raises after replacement. A later failure can leave earlier saves applied;
the operator must inspect unconfirmed state before retry. Concurrent external writers are not locked
by a new authority; fingerprints bound stale-intent detection rather than promising serializability.

Only masked fields and their consumed aliases change. Preserve other config, zero/False values,
unmasked prompts, notes/tags, archive state, history and baseline snapshots. Auto geometry stays
per-photo decoded geometry. Width/height masks require explicit Custom policy; switching Auto photos
to Custom also requires both dimensions. Explicit Auto restores decoded dimensions.

## Pipeline, prompts and preview

Pipeline Copy captures a deep live snapshot of existing stage-card serializers and stage toggles.
Groups select individual field checkboxes; users can preserve any field. Normalized fallback fields
are distinguished from exported controls and omitted from configuration copy choices. Geometry is
a separate explicit Custom override. Missing Pipeline settings refuse without writes. Copy targets
the active photo in Single Photo or selected IDs in Batch Edit, then uses the same confirmed diff.

Saved positive/negative prompts belong to the active baseline. Batch saved-prompt transformations
use `ReviewWorkflowAdapter.apply_prompt_delta` append/replace/modify semantics, including empty-text
behavior. Shared run-only text survives active-photo changes; the effective prompt preview combines
each baseline with that transformation and never saves it. Queue review shows every effective target.
The img2img scheduler dropdown projects resources, loads/saves aliases and reaches the frozen NJR.

Show Image Previews is persisted with editing scope and selected IDs in existing UI state.
Hiding clears thumbnails without modifying assets. Content visibility still applies: the selected
history output is independently classified using effective prompts, output identity, snapshot and
deltas, so a safe current baseline cannot authorize a flagged historical image. History selection
survives preview toggling. Classification uses the existing text resolver, not image recognition.

## Queue boundary

Maximum photos per compatible job is a cap, not repetition. Selected targets are the selected set
in either editing workspace; All Visible uses unarchived visible IDs. Selecting archived photos
refuses submission until restored. Existing `prepare_photo_plan` and ReprocessJobBuilder retain
per-photo stage/config/model/prompt grouping and whole-request compatibility preflight. A complete
scrollable review lists frozen per-photo settings and IDs before Queue. Confirmation passes that
same prepared plan to the existing `_submit_reprocess_njrs` boundary exactly once. No new NJR,
queue, runner, history or batching authority; existing queued snapshots are untouched.

## Evidence and limits

Base: `5cab2431a523a2520124011e39d15665ce9c5a3c`. Before production edits, new regressions
reported 6 failures / 2 passes: the missing batch service and img2img scheduler roundtrip failed;
active-only stage edits and live Pipeline serializer capture passed. No displayed-value divergence
was reproduced for the exercised Pipeline controls. Discovery instead proved normalized defaults
were indistinguishable from captured source fields. The img2img Pipeline card does not export a
scheduler; copy does not pretend its normalized scheduler fallback is an exported control.

Focused acceptance: 125 passed, including three-photo Batch → Single refinement → Review →
one fake queue admission, all prompt transformation modes, exact scoped field copy, stale/invalid
whole-selection refusal, injected partial/post-replacement failures, archive/selection persistence,
preview toggle/restart and historical-content checks, scheduler NJR parity and unchanged grouping.
Logs: `C:/Users/rob/qual/photo222-baseline.log` and `C:/Users/rob/qual/photo222-focused.log`.
Canonical PR gate passed: completeness, lowered controller ratchet, repository-wide Ruff,
ten-file mypy smoke, 9700-test isolated collection and 386 required smoke/contract tests.
Log: `C:/Users/rob/qual/photo222-pr-gate.log`. Security re-review passed after independently
gating historical thumbnails; aggregate diff and whitespace checks passed. No visual-quality or physical
backend claim follows from deterministic Tk tests. Draft writes remain per-asset; confirmation does
not make them a transaction. No additional product decision is required for this bounded outcome.
