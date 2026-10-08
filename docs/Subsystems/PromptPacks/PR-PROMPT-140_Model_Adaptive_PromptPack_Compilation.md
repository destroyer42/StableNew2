# PR-PROMPT-140 - Model-adaptive PromptPack compilation

Result class: **STANDARD - bounded compiler/provenance work**. Fresh PromptPack compilation now adapts the authored prompt to the
selected model target before the executable strings and the immutable NJR exist. The canonical path is unchanged:
`Intent -> Compiler -> immutable NJR -> JobService -> SQLite Queue/Repository -> PipelineRunner.run_njr -> Handler/Executor -> Artifact/History`.
Execution Profile: Claude Code Sonnet 5.5 XHigh.

## Outcome

**One authored PromptPack, many immutable target-specific NJRs.** The PromptPack is authored once and is never copied, saved or
mutated. Compiling it for SDXL gives today's strings byte-for-byte; compiling the same pack for the qualified FLUX.2 Klein profile
omits the unsupported negative channel and embeddings, omits definitively incompatible LoRAs (and the trigger phrases they structurally
own), keeps admitted LoRAs within the target's limit and normalizes the accepted deterministic dialect forms. The exact effective prompt
and the adaptation evidence are frozen into the NJR; replay executes that frozen NJR and never reinterprets anything.

## Ownership: structure -> adapt -> render

| Step | Owner |
|---|---|
| Source config (before model compile policy) and effective config (after `apply_model_compile_policy`) are kept separate | `PromptPackNormalizedJobBuilder._build_jobs_for_entry` |
| Matrix expansion, actor / row / Style Consistency ownership -> immutable `PackPromptIntent` | `src/pipeline/resolution_layer.py::resolve_pack_intent` |
| Target `ModelPolicy` (exact profile first, else persisted registry evidence, else unverified) | `src/image_backends/model_policy.py::resolve_model_policy` (unchanged), via one `CompileEvidence` per build |
| Deterministic compile-safe adaptation (the one rule implementation) | `src/prompting/prompt_adaptation.py::adapt_structured_prompt` (PR-IMG-130C engine) |
| Re-assembly by role | `resolution_layer.adapt_pack_intent` (maps components in and out; no rules) |
| Final strings in the historical order | `resolution_layer.render_pack_intent` |
| Model compile policy on an isolated config copy | `apply_model_compile_policy` (unchanged) |
| Frozen NJR + manifest | builder -> `NJRProvenance.metadata["prompt_adaptation"]` |

`UnifiedPromptResolver.resolve_from_pack` remains as a compatibility wrapper (`resolve_pack_intent` then `render_pack_intent`); the
Learning freeze path still calls it and is unaffected. A 1,088-case grid proves the wrapper is byte-for-byte equal to the pre-140
implementation (actors, shared and LoRA-less triggers, Style Consistency, duplicate LoRA names, embeddings, Matrix values, global/pack/
safety negatives, empty fallback).

## Compile-safe semantics

These generic compile-safe semantics remain the default compiler contract.
Fresh GUI PromptPack submission additionally enables the explicit qualified
Klein selection policy in PR-PROMPT-143: complete evidence preparation, only
positively verified adapters, and operator review for multiple compatible
candidates before NJR creation. That separate versioned selection contract
does not relax Learning's completeness gate or rewrite replayed NJRs. See
`PR-PROMPT-143_Klein_Compatible_LoRA_Selection.md`.

Production adaptation deletes an authored component only on a **definitive** fact:

* the policy says the feature is unsupported (negative channel, embeddings, LoRA);
* the existing PR-IMG-117 evaluator reports the LoRA `incompatible` (surfaced as `LoraAssessment.statuses`, derived directly from that
  evaluator - no new compatibility detector);
* a *compatible* LoRA exceeds the target's finite limit. Order is the production execution order: **actor LoRAs, PromptPack-row LoRAs in
  authored order, then Style Consistency** (not the Prompt-tab preview order).

`unverified`, `conflicting`, stale or absent evidence **never deletes**: the LoRA is preserved, consumes a slot, is recorded as
`lora_retained_unverified` / `lora_retained_conflicting` and the manifest says `complete: false`; the backend's refreshing, fail-closed
admission stays final. Unknown, conflicting or unqualified targets are not adapted at all (`target_unverified_no_adaptation`, `adaptable:
false`, `complete: false`) and are never guessed into SDXL or Klein. The Prompt-tab preview keeps its own stricter read-only LoRA rule
(it omits unverified LoRAs from the projection); text, negative and embedding rules are shared.

Non-prompt features are never adapted: ADetailer, hires, refiner, upscale, ControlNet, reference/edit requirements, stage chains, geometry
and backend requirements remain under `ModelPolicy`, the exact profile and the backend's fail-closed validation.

## Trigger ownership

* **Actor LoRA <-> actor trigger phrase** and **Style LoRA <-> Style trigger phrase** are structural pairs: dropping the LoRA drops its
  trigger (`actor_trigger_dropped_with_lora` / `style_trigger_dropped_with_lora`). A phrase shared by several actors survives while any
  owner survives; a phrase carried by a LoRA-less actor is never LoRA-owned.
* **PromptPack-row LoRAs** have no authoritative trigger metadata, so no authored prose is ever guessed or substring-deleted; the manifest
  records `pack_lora_trigger_not_tracked` when one is dropped. No PromptPack schema migration was made.
* Manually typed inline `<lora:...>` tokens are left exactly as written (and under backend validation); promoting them to structured intent
  is a later, explicit package.

## Dialect safety gate

The shared weighted-attention recognizer (`prompt_compatibility.WEIGHTED_ATTENTION_PATTERN`, used by both 130B detection and the adapter) is
now deliberately conservative because automatic compilation acts on it: the weight must be a **decimal written directly after the colon** and
the phrase may contain no colon. `(red dress:1.2)` and `(a:.5)` are weights; `(ratio: 2)`, `(ratio:2)`, `(note: 5)` and ordinary parentheticals
are preserved. Upper-case `BREAK` -> one paragraph break; lowercase prose, `[[matrix]]` markers and `<...>` tokens are protected; quality-tag
boilerplate stays advisory and is never deleted. No semantic rewriting, no LLM/VLM, no negative-to-positive inversion.

## Evidence and performance

`CompileEvidence` (`src/pipeline/compile_evidence.py`) is created once per `build_jobs()` call: one lazy `AssetRegistry` read of the
**persisted snapshot** (no refresh, scan, hash or network), one policy resolution per distinct model, one LoRA lookup per distinct name
(`LoraEvidenceContext`) however many Matrix variants and LoRAs there are. Tests prove the default path never refreshes and constructs one
registry per build. Each Matrix variant is adapted on its own expanded intent. Controllers are untouched.

## The frozen adaptation manifest

`NJRProvenance.metadata["prompt_adaptation"]` (NJR schema version unchanged) = `{"contract": "prompt_adaptation/1", **PromptAdaptationPlan.
to_diagnostics()}`: engine ruleset version, mode `compile`, target `policy_id` / `family` / `evidence` / exact `profile_ref` / `prompt_dialect`,
`adaptable` / `changed` / `complete` / `reason`, ordered stable operations (code, scope, effect, content-free details) and counts. It contains
no prompt text and no asset names. The effective prompt strings, embeddings and LoRA tags are already first-class NJR fields and describe what the
target receives (workload and executable-config strings, `provenance.positive_embeddings`, `provenance.negative_embeddings`, `provenance.lora_tags`,
the rendered `<lora:...>` tokens). `intent_config`, plan/story metadata and the resolved actor/style metadata keep describing the operator's
*source* intent; the manifest bridges the two. SDXL work carries an identity manifest (`changed: false`).

## Replay and history

Adaptation happens only when fresh PromptPack work is constructed. The queue persists the exact effective NJR; replay (`compile_replay_intent`) is a
pure copy with a new identity and never opens the PromptPack or calls the adapter, and a later `ADAPTATION_RULESET_VERSION` cannot alter an existing
NJR (regression tests patch the adapter, the builder and the ruleset version).

## Not changed / deferred

Learning (it freezes and builds its own NJRs; `compatible_context()` and recommendation evidence untouched; a future Model Comparison Study will
consume this versioned evidence), manual/CLI/Review/reprocess/video/replay prompts, the Prompt-tab preview UX, `PipelineRunner`, queue, repository,
backend routing, controllers, PromptPack schema, Qwen / Z-Image, LoRA substitution.

## Validation

`tests/pipeline/test_pack_prompt_intent_140.py` (legacy-equivalence grid, ownership, ordering), `tests/pipeline/test_prompt_pack_adaptation_140.py`
(SDXL identity, Klein adaptation + real backend admission, trigger ownership, uncertainty, bounded evidence, dialect safety, Matrix, manifest,
source immutability, unknown targets, replay), `tests/image_backends/test_prompt_adaptation_140.py` (compile-safe engine, recognizer, synthetic
future policy, purity, evidence context) plus the unchanged 130A/130B/130C/117 and PromptPack/Matrix/global-prompt/Learning suites. Deliberate
mutation checks cover the failure modes listed in the work package. No physical generation.
