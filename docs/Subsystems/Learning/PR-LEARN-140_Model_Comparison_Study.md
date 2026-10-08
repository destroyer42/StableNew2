# PR-LEARN-140 — Explicit Model Comparison Study

## Execution Profile + Model/Reasoning Recommendation

Standard, difficult bounded Learning/compiler/provenance/Tk work. Codex:
GPT-6.1 Sol XHigh; Claude Code: Sonnet 5.5 XHigh. Prefer the current Codex
Local/Desktop session for the exact worktree, persisted AssetRegistry and Tk
fixtures. The interacting freeze, policy, adaptation and evidence contracts
justify this tier by total successful-work cost, including likely retries.
New runtime ownership or qualification decisions require owner review.

## Controller Surface Assessment

`LearningController` collects design intent, delegates preview planning and
frozen-arm materialization to `src/learning/model_comparison.py`, stores the
existing execution snapshot, coordinates ordinary atomic admission, and
classifies ratings through the helper. Candidate eligibility, geometry/backend
gates, adaptation and semantic consistency stay in the helper. The controller
also forwards existing executor final positive/negative readback into rating
evidence. No global merge or prompt interpretation belongs in the controller. No
`src/controller/*` surface or controller ceiling changes.

## Study meaning and mode isolation

`controlled_variable` is the backward-compatible default, including snapshots
without `study_type`. Ordinary Variable Under Test = Model still requires the
same compatible evidenced envelope through `compatible_context()`. Registry
SDXL peers may qualify; ordinary SDXL/Klein sweeps remain rejected.

`model_comparison` explicitly compares preference/performance of selected
models under their frozen, model-specific qualified target envelopes for one
source intent. Its persisted interpretation is:

```json
{"study_type":"model_comparison","comparison_claim":"target_envelope_preference","causal_one_variable":false}
```

Equal requested integer seeds do not imply identical latent/noise semantics
across architectures. Geometry, sample count and requested seed/subseed policy
are shared; policy-required settings and effective prompt features may differ.
Review conclusions describe preference under the frozen target envelope and
make no statistical significance or model-only causality claim.

## Bounded design and admission

Experiment Design defaults to Controlled Variable. Model Comparison presents
the existing model resource checklist, fixes Target Stage to `txt2img` and
Prompt Source to PromptPack, and requires at least two distinct candidates.
Switching back restores ordinary stage/variable/source controls. Selection
changes do not mutate stage cards or PromptPacks. Resume restores study mode
and candidate selection from the existing persisted experiment.

Each candidate independently resolves through canonical `ModelPolicy`: an
exact qualified profile or registry-evidenced SDXL is required. Unknown,
conflicting and unqualified families fail closed. Candidate identity in policy
evidence uses the existing path-free conventions.

The configured image backend must satisfy every candidate's required/allowed
backend contract. The baseline width/height must be valid for every candidate;
an invalid shared geometry produces qualified choices and rebuild guidance.
Neither backend nor geometry is automatically changed. Initial studies are
txt2img-only; unsupported hires, refiner, ControlNet or other execution features
are rejected instead of silently removed. Backend validation remains final
authority before dispatch.

Custom/current prompts, cross-family img2img, ADetailer, upscale, reprocess,
video, unknown/unqualified targets, automatic runtime switching, geometry
normalization and new model qualification are outside this contract.

## Build Preview is the semantic freeze

The selected PromptPack row is loaded during Build Preview. Learning preserves
its existing first canonical Matrix vector policy. Structured source creation
uses `resolve_pack_intent`, followed by the pure, versioned
`pack_prompt_intent_to_dict` serializer. No rendered string is parsed to
recover authored roles. The source digest is SHA256 of canonical serialized
structured intent, independent of file path or mutable PromptPack bytes.

The source retains authored positive/negative prose, embedding declarations,
ordered LoRAs, structurally owned triggers when present, Matrix-expanded text,
and global-negative intent/participation. PromptPack identity, row index,
Matrix vector and freeze policy stay in the existing source snapshot.

One bounded `CompileEvidence` context is reused across candidate arms. It
provides one lazy AssetRegistry instance, cached policy lookups and cached
distinct LoRA lookups using persisted evidence. Preview performs no registry
refresh, filesystem model scan, model hashing, backend request, network call
or generation.

Each arm starts from the same intent, uses `adapt_pack_intent` and canonical
`adapt_structured_prompt`, renders through `render_pack_intent`, and applies
`apply_model_compile_policy` to an isolated baseline copy. Model-specific
fixed controls come from canonical policy, never a Learning settings table.

Learning requires every adaptation manifest to be both adaptable and complete.
Definitively incompatible LoRAs may be removed; compatible over-limit LoRAs use
canonical omission order. Unverified/conflicting compatibility refuses the
study. Generic PromptPack compilation retains its existing compile-safe
uncertainty behavior. Dropping a row LoRA never substring-deletes authored
prose. Actor/style trigger ownership and manually typed inline tokens retain
PR-PROMPT-140 semantics.

## Frozen execution contract

The existing Learning execution snapshot contains an additive `study_type` and
`model_comparison` block under `learning_model_comparison/1`; no additional
durable experiment store or NJR schema change exists. The block contains the
source intent/contract/digest, shared geometry, interpretation and all arms.
Every arm freezes:

- candidate index and path-free selected identity;
- exact model policy context and profile reference;
- the complete `prompt_adaptation/1` manifest, including its ruleset version;
- target-adapted structured `effective_intent`, `adapted_positive_prompt` and
  `adapted_negative_prompt` evidence, with global-negative participation retained;
- `executor_base_positive_prompt` and `executor_base_negative_prompt`, rendered
  canonically without preapplying executor-owned global terms;
- `executor_global_prompt_policy`, an evidence projection of the frozen config
  texts, enablement flags and `frozen_njr` source marker;
- retained effective embeddings and LoRAs;
- effective executable configuration and backend options;
- shared source digest, geometry, comparison claim and noncausal flag;
- an integrity digest over the frozen arm payload.

Run thaws and validates all arms, exact profile references, candidate mapping,
source/arm digests, geometry, seed request, fixed controls, effective rendered
base prompt/provenance, frozen global policy, backend options and manifest
target/counts. It renders
already-frozen effective structure only to check internal consistency. It
never reopens the PromptPack, recomputes Matrix, reruns adaptation, consults
live registry evidence or substitutes a newer profile/ruleset. Source, model
selector, stage-card, registry or rules changes require a rebuilt preview.
Unknown frozen profile versions fail closed.

Per `docs/ARCHITECTURE_v2.6.md`, the executor applies frozen Global Positive
and Global Negative terms. Preview uses `render_pack_intent` on the adapted
intent with global-negative participation disabled only for the executor base
projection; it does not change the execution apply flags to compensate for
preapplication. SDXL row negative `bad` with enabled frozen `GLOBAL` therefore
dispatches `bad, GLOBAL` once. Qualified Klein compile policy still clears
standard global terms/flags and the negative channel. No mutable global source
is read after Preview, and shared merges/executor behavior are unchanged.

These base strings are not literal final backend prompts. The arm and rating
declare `prompt_semantics="executor_base_before_globals_and_optimizer"`.
Executor globals and Prompt Optimizer may still affect dispatch. Runtime
`final_prompt` / `final_negative_prompt` readback is retained separately in
`runtime_prompt_readback` when supplied, including an empty negative string;
missing readback remains absent rather than inferred from the Preview base.

Materialization creates an ordinary immutable `SourceKind.LEARNING` NJR with
the frozen image workload, stage, output plan and provenance. Only existing
runtime experiment/variant tracking facts are added to the effective config.
Every arm compiles before the existing `ExperimentAdmissionService` and one
`JobService.submit_njrs` call. Any failure admits no arm; queue, repository,
runner, replay and backend ownership remain unchanged.

## Review and recommendation evidence

The existing image-first review and rating flow identifies each model arm and
persists frozen executor inputs and available final runtime readback separately.
Comparison ratings use
`record_kind="learning_model_comparison_rating"`, preserve the explicit claim
and `causal_one_variable=false`, and retain arm/adaptation evidence so review
can explain target settings and prompt differences.

`RecommendationEngine` ignores comparison records, including records whose
frozen snapshot declares comparison mode. These rows cannot become controlled
parameter evidence or automatic Model recommendations. Existing controlled
ratings retain their evidence rules. Recommendation import/construction stays
lightweight; production compiler/backend imports occur at preview/run seams.
Historical sessions/records remain loadable without migration.

## Token-Efficient Validation Plan

Start with the pure comparison/source-freeze tests and representative NJR
audits, then affected Learning persistence/review/recommendation, 130D
capability/import boundaries and Tk mode tests. Reuse unchanged canonical
PR-PROMPT-140 and image 130A/B/C/117 evidence. Finish remaining
PromptPack/Matrix/global-prompt and atomic admission regressions. Loopback
operator-journey fixtures require a local context that permits sockets.

For the bounded global ownership repair, first reproduce duplication through
the real txt2img payload seam, then verify row/global-only/disabled negatives,
positive ownership, Klein policy, frozen Run and persisted runtime readback.
Kill the mutation that preapplies Global Negative while the executor flag
remains enabled. Reuse exact-source evidence for unchanged adaptation rules.

Deliberate mutations exercise mode isolation, unknown target handling, source
reopening/adaptation/ruleset substitution during Run, geometry/backend changes,
incomplete evidence, missing manifests, source-digest disagreement, fixed
controls, unsupported negative/LoRA behavior, arbitrary prose/source mutation,
partial admission, causal classification/recommendations and eager imports.
Restore each mutation byte-for-byte and rerun the restored contract tests.

Close out settled source with scoped Ruff, canonical mypy smoke,
`git diff --check` and one final `tools/ci/run_pr_gate.py`. Hosted required
Python 3.14 CI is the integration verdict after authorized publication.
Physical generation and environment changes are unnecessary.

Primary regression ownership:
`tests/learning_v2/test_model_comparison_140.py`,
`tests/learning_v2/test_model_comparison_global_prompts_140.py`,
`tests/gui_v2/test_model_comparison_design_140.py`, canonical structured/adaptation
tests, `test_model_capabilities_130d.py`, and the existing operator-journey
import-safety and atomic admission tests.
