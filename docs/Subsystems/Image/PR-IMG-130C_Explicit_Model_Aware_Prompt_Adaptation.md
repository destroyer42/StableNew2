# PR-IMG-130C - Explicit model-aware Prompt adaptation foundation

Result class: **BOUNDED POLICY LOGIC + UX (Standard)**. One pure, deterministic, policy-driven adaptation engine and a read-only
Prompt-tab **Adapt for Target** preview. Automatic adaptation of PromptPacks during execution is **not** part of this package.
The canonical path is untouched:
`Intent -> Compiler -> NJR -> JobService -> SQLite Queue/Repository -> PipelineRunner.run_njr -> Handler/Executor -> Artifacts/History`.
Execution Profile: Claude Code Sonnet 5.5 High.

## Owner outcome

StableNew can explicitly show how the currently authored prompt would be adapted for the selected image model/profile, so an
operator need not maintain separate PromptPacks per model family. The authored PromptPack stays authoritative and unchanged; the
adaptation is a transient projection for one target, and the same pure function is what the later compiler integration will call,
so Prompt-tab preview and PromptPack execution cannot become two interpretation systems.

## Authorities (unchanged)

`ModelPolicy` (PR-IMG-130A) is the capability/operator-policy authority; the exact qualified profile is the executable authority;
`AssetRegistry` is the model/asset evidence authority; `assess_lora_selection` and the PR-IMG-117 exact admission are the LoRA
authority; the PR-IMG-130B syntax patterns are the one recognizer of weighted attention / `BREAK` / non-prose tokens. 130C consumes
them and reproduces none of their rules. There is no new compiler, queue/repository behavior, runner behavior, backend selection,
family detector, asset scanner, LoRA authority, PromptPack migration, replay interpretation or process/runtime change.

## Authored versus projected

* **Authored Prompt State** is the durable PromptPack content (text, negative, template + variables, Matrix, embeddings, slot LoRAs,
  Style Consistency selection, optimizer settings).
* **Target Adaptation** is a transient, deterministic projection of that state for one `ModelPolicy`/exact profile. A model switch
  never changes authored state. Opening the preview never sets the dirty flag, never saves, never scans, and closing it leaves the
  workspace identical. There is deliberately **no** "Use adapted prompt" action: one reusable PromptPack must not become a
  target-specific saved variant.

## Design

`src/prompting/prompt_adaptation.py` (pure: no Tk, filesystem, network, scan, hashing, model/LLM/VLM or process access):

* `PromptAdaptationInput` - the structured authoring components (rendered positive/negative text, positive/negative embeddings,
  slot LoRAs, the applied Style Consistency LoRA + trigger phrase, a pending-style flag, the stored optimizer/global-negative facts).
  It is not 130B's `PromptStateSnapshot` (which keeps counts only).
* `adapt_prompt_for_target(policy, input, lora_resolver=None) -> PromptAdaptationPlan` - immutable, versioned
  (`ADAPTATION_RULESET_VERSION`), with target identity (`policy_id`, `family`, `evidence`, exact `profile_ref`, `prompt_dialect`),
  `adaptable`, `changed`, a stable `reason`, the adapted text/embeddings/LoRAs/style state and an **ordered** tuple of
  `AdaptationOperation(code, scope, effect, details)`. Details are counts/indices/limits only, never prompt text or asset names.
  `to_diagnostics()` is a content-free serialization suitable for logs and for freezing into later experiment evidence.
* `changed` means the adapted prompt material differs from the input; informational `not_applied` notes about stored settings
  (optimizer, global negative) never count.

Operation codes: `weighted_attention_flattened`, `break_separator_normalized`, `negative_prompt_dropped_unsupported`,
`positive_embedding_dropped_unsupported`, `negative_embedding_dropped_unsupported`, `lora_dropped_unsupported`,
`lora_dropped_unverified`, `lora_dropped_rejected`, `lora_dropped_over_limit`, `lora_retained_compatible`, the `style_lora_*`
equivalents plus `style_lora_not_evaluated` and `style_trigger_dropped_with_lora`, `optimizer_not_applied`,
`global_negative_not_applied`, `target_unverified_no_adaptation`. Effects: `rewritten`, `dropped`, `retained`, `not_applied`,
`refused`.

## Rules (v `130c.1`)

* **Unknown / conflicting / unqualified targets** (`target_is_unverified(policy)`, the same predicate 130B uses): adaptation is
  unavailable, every field is the original, the single operation is `target_unverified_no_adaptation`. Nothing is guessed into SDXL
  or any family.
* **Natural-language dialect** (from `ModelPolicy.prompt_dialect`): clear A1111 `(phrase:1.2)` groups are flattened to `phrase`
  (nested groups repeat to a fixpoint; no strength is inferred; ordinary parentheses are untouched); an upper-case `BREAK` (with
  adjacent whitespace and one adjacent comma) becomes one paragraph break `\n\n`; lowercase "break", `[[matrix]]` markers and
  `<...>` extra-network tokens are protected and unchanged. Quality-tag boilerplate is **preserved** (130B's finding stays advisory).
  A weighted-tags dialect (SDXL) is an identity projection.
* **Negative channel**: supported or unverified - retained (text rules also apply when supported); unsupported - the projected
  negative is empty (authored negative untouched). No semantic inversion into the positive prompt.
* **Embeddings** (`ModelPolicy.feature("embeddings")`): supported/unverified - retained; unsupported - omitted from the projection
  with separate positive/negative operations.
* **LoRAs** (`feature("lora", "txt2img")`): unsupported - all omitted; supported - each LoRA is assessed one at a time through
  `assess_lora_selection` (an exact-admission policy decides compatibility; filename/family/"Forge lists it"/operator selection
  never do). Unverified or rejected ones are omitted; compatible ones are kept in **authored slot order**, then the applied Style
  Consistency LoRA, until the policy's finite `limit` is reached; later compatible ones are omitted `..._over_limit`. This ordering is
  adaptation behavior, not a model-quality recommendation, and matches the order in which 130B counts LoRAs.
* **Style Consistency**: only the applied style from the last existing availability evidence is considered; a selected-but-unevaluated
  style is never accepted and never triggers a scan (`style_lora_dropped_unverified` with `reason: not_evaluated` where exact admission
  applies, otherwise informational `style_lora_not_evaluated`). Its trigger phrase is a structured component and is dropped with its LoRA.
* **Prompt Optimizer / global negative**: reported `not_applied` for targets whose policy disables them; stored values are untouched.

## Prompt-tab preview

`PromptTabFrame` gains one thin action: `Adapt for Target...` beside the 130B target banner. Its availability comes from
`PromptTargetProjection.adaptation_available` (derived from `target_is_unverified`) through `PromptTargetPresenter`; the existing 130B
diagnostics and control presentation are unchanged. Clicking snapshots the current authoring state, calls the pure adapter with the
selected `ModelPolicy` and the cache-only LoRA resolver, builds a toolkit-neutral `AdaptationPreviewModel`
(`src/gui_v2/prompt_adaptation_preview.py`) and opens the read-only `PromptAdaptationDialog` (`src/gui/prompt_adaptation_dialog.py`):
target, whether anything changes, original vs adapted positive prompt, negative status, embedding/LoRA counts and ordered
explanations. All transformation and preview-model construction live outside `PromptTabFrame`; there is no `src/controller/` change.

**Content visibility**: hidden positive/negative text is replaced by a placeholder; operation steps derived from hidden text (flatten
counts, `BREAK` counts, negative dropped) are not itemized; asset identities (LoRA, embedding, style names) are never shown in any
mode (counts only).

## Future compiler seam and recorded gap

The later automatic-interpretation package (`PR-PROMPT-140`) should resolve Matrix/source into structured prompt intent, call
`adapt_prompt_for_target` on those structured components, then render the target string and apply the existing model compile
policy. **Not implemented here: automatic production PromptPack adaptation remains deferred to that package.**

Recorded, not hidden: a slot LoRA's trigger phrase is part of the authored text, so the engine cannot drop it with the LoRA (only the
Style Consistency trigger is structured); the preview says so when a LoRA is omitted. Inline `<lora:...>` tokens typed into text are
untouched. Closing it requires adapting structured components before rendering. The `(phrase: 2)` recognizer is the 130B pattern, so
a parenthetical such as "(ratio: 2)" is treated as weighted syntax by both detection and adaptation.

## Not changed / limits

No PromptPack schema or load/save change; no Learning change (`compatible_context()` and the 130D evidence rules are untouched, and a
cross-profile adaptation is not an ordinary one-variable experiment - a later explicit Model Comparison Study can freeze
`to_diagnostics()`); no compiler, queue, runner, backend, GPU or model qualification; no LLM/VLM rewriting.

## Validation

`tests/image_backends/test_prompt_adaptation_130c.py` (pure: determinism, SDXL identity, Klein flattening/BREAK/negative/embeddings/LoRA
admission and limit ordering including Style Consistency, pending style, unknown/conflicting refusal, synthetic future policy without a
family conditional, Matrix/token protection, input immutability, no I/O) and `tests/gui_v2/test_prompt_adaptation_130c.py` (Tk: button
availability follows the projection, SDXL -> Klein -> SDXL, workspace identical and clean after open/close, nothing saved, spy proving the
preview is produced by the pure adapter, hidden content and asset names never disclosed, no style scan, 130B diagnostics intact). Deliberate
mutation checks (unknown-as-SDXL, family conditional, surviving negative/embeddings/unverified LoRA, removed compatible LoRA, ignored limit,
style outside the limit, stripped parentheses, Matrix as prose, dirtied/erased workspace, preview scan, hidden leak, GUI bypass of the
adapter) were each detected. The PR-IMG-130A/130B/117, Prompt-tab and PromptPack suites stay green. No generation, GPU, network or user-data
mutation.
