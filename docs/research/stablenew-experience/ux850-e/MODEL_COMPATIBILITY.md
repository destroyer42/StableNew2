# Models, preferences and PromptPack compatibility

Evidence: E01–E09/E15–E17/E22–E24 in [SOURCE_INDEX.md](SOURCE_INDEX.md); unchanged source at E base. This is a description of current boundaries and conditional extensions, not a new compatibility policy.

## Five concepts that must stay separate

| Concept | Current authority | Consequence |
|---|---|---|
| Backend/runtime | Configured image backend and adapters | Model family cannot choose a new runtime or expand its supported operations |
| Checkpoint bytes / family | AssetRegistry + ModelPolicy | Whole-name resolution plus current cached hash/fingerprint evidence; unknown/conflicting stays so. Local identity is separate from live WebUI availability |
| Exact executable profile | Versioned exact model profile, compiler/backend | Hard execution envelope; an advisory or learned preference cannot override fixed controls or unsupported stages |
| Capability/operator policy | `resolve_model_policy`, `ModelPolicy` | Projects configurable/fixed/unsupported and supported/unverified features. A policy's word “qualified” is not E granting a fresh physical verdict |
| Advisory generation profile | Research/Learning/Custom profile services and store | Partial recommendations with provenance; never a backend, stage enablement, trained model or new executable envelope |

The current SDXL registry-policy allowlist for comparison is explicit; a family with registry evidence but no qualified comparison policy remains labeled yet ineligible. Do not treat a new checkpoint name, filename match, model card or family analogy as authorization to expand this set. Exact Z-Image source support coexists with standing stability/physical evidence limits; E does not resolve them. No installed model inventory, free memory or runtime state was inspected.

## Current preferences and safe extension

`GenerationProfileController.on_model_chosen` applies the favorite, otherwise Research starting profile, to editable working values through the current service. Selecting a profile also plans/applies supported changes. Profiles can omit settings; an unoffered sampler/scheduler is reported, and a VAE does not silently cross model families. Compiler/backend checks still decide execution. Existing PromptPacks, accepted Preview NJRs and submitted work are not rewritten by these selection actions.

Learning publication is a different action: review findings, confirm immutable revision, refresh catalog. It neither selects, applies, favorites nor saves startup defaults. Startup defaults use their own sanitized document and restore validation, excluding job/image/model-file paths and experiment state. A renamed checkpoint with identical verified bytes can match; a same-named changed checkpoint conflicts. Historical snapshots are not backfilled from today's registry to manufacture old identity proof.

A bounded extension can explain per-setting origins and changed/unsupported/unknown values before a native action. Individual locks require G1 decisions on draft/session/per-model/approved-experiment scope, precedence, temporary exceptions, expiry and recovery. Treating an existing frozen study as a generic lock system would introduce false guarantees. AI can explain an existing plan only after privacy/qualification gates; deterministic reasons already provide the essential behavior.

## PromptPack adaptation is a projection

The compiler resolves structured intent, applies target policy, renders effective strings and freezes adaptation evidence into the NJR. The pure adapter preserves authored text and structural ownership. It can flatten explicit weighted syntax for a natural-language dialect, normalize BREAK, omit an unsupported negative channel or unsupported embeddings, and assess ordered LoRAs through the existing resolver. It does not infer a semantic opposite, invent quality prose, discover trigger ownership or call a language model.

Compile mode removes definitively incompatible LoRA contributions; unknown/conflicting evidence is retained and marked incomplete so final admission can refuse it. Dropping a structurally owned actor/style LoRA also drops its owned trigger; arbitrary PromptPack-row prose has no guessed ownership and is retained. This is not a permissive bypass or proof that the effective prompt preserves every semantic intent.

The accepted A addendum's Prompt Load dirty-check gap means universal draft-protection guarantees are unavailable. Broader compatibility UI should expose source/effective differences and preserve native save boundaries; it must not rely on a universal transactional handoff already existing. Neither C diagrams nor E documentation repairs that path.

Semantic AI rewriting belongs before ordinary intent compilation, with explicit Accept into the editing buffer. Current Prompt AI fingerprints full source/context, preserves protected token multisets and closed choices, refuses stale acceptance and excludes template rewrites rather than flattening structured templates. A rewrite's perceived improvement must be measured against deterministic and manual baselines; schema validity alone cannot establish it. Target advice cannot mutate the picker; Prompt has no eligible workflow-choice source today.

## Cross-model comparisons answer a different question

Current Model Comparison freezes exact effective arms, policy, prompt adaptation and checkpoint evidence. Its claim is **target-envelope preference**, with `causal_one_variable=false`; Prompt x Model Matrix and exploratory grid ratings have their own isolated kinds. Their evidence cannot be laundered into ordinary tested-setting publication or automatic default-model selection.

For a future common-task benchmark (C09), propose two explicitly labeled views: a supported standardized objective/baseline and a separately optimized target envelope. Freeze task cases, source/adapted prompts, checkpoint/runtime/backend/profile identities, geometry, seed policy, effective settings, operator rubric and any measured resource methodology. If one target cannot satisfy the same operation or geometry, show non-comparability rather than quietly repairing it. A shared seed number across model families does not prove equivalent latent conditions or pixel reproducibility. Compare descriptive quality/cost tradeoffs within that scope; do not infer a universal winner, causal model superiority or resource cost from image counts alone.

The low-cost route is current manual selection plus frozen target-envelope studies and human review. Any automatic task router would require approved routing limits, fresh admission/readiness, evidence applicability, resource policy and separately accepted quality evidence. No such router is recommended for current enablement.
