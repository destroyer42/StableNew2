# PR-IMG-MODELS-160 - Model Comparison global-positive parity

## Execution Profile + Model/Reasoning Recommendation

Standard, substantial known-architecture repair inside the Learning freeze/compile seam. Codex:
GPT-6.1 Sol High. Claude Code: Sonnet 5.5 High. Preferred host: the existing productive
Claude Code Desktop session. Stop conditions (relaxing an exact model's restrictions, migrating or
reinterpreting frozen studies, a second authority, scope growth, more than two failure classes)
did not occur.

## Controller Surface Assessment

No controller or coordinator change. `LearningController` still collects intent and delegates
Preview/freeze/Run; the ownership decision lives in `src/learning/model_comparison.py` and reads
the canonical model policy's result.

## Defect (reproduced on unchanged source, `main` `44de6872`)

`build_comparison_snapshot()` froze the shared global-positive text and flag, adapted the
PromptPack intent with no global positive, and then let each exact profile's compile policy clear
the executor-global fields. The Z-Image and Klein arms therefore lost an enabled shared global
positive; only SDXL's executor applied it.

| Candidates, shared global positive `studio lighting` enabled | Executable positive before |
|---|---|
| SDXL + Z-Image: SDXL arm / Z-Image arm | executor applies it / **absent** |
| SDXL + Klein: SDXL arm / Klein arm | executor applies it / **absent** |

Frozen-arm validation also asserted `executor_base_positive_prompt == render(effective_intent)`,
so prepending the terms by hand would have been refused without a matching frozen contract.
Disabled-with-stored-text was already correct (never applied) and is kept as a guard.

## Behavior

Each arm starts from the same frozen source intent and shared baseline and is prepared
independently (`prepare_candidate_baseline` + `apply_model_compile_policy`, unchanged). Ownership
is then read from what the canonical policy left in that arm's frozen executor policy
(`global_prompt_policy.frozen_global_positive_policy`: terms + flag as the executor reads them);
there is no model-family table in `model_comparison.py`.

| Shared request | Arm's policy leaves | Mode | Executable positive |
|---|---|---|---|
| enabled + text | executor still applies the terms | `executor_applied` | rendered positive; executor prepends at dispatch |
| enabled + text | executor flag/text cleared | `compiler_composed` | `merge_global_positive(adapted terms, rendered positive)` once |
| disabled, empty, or none | any | `not_requested` | rendered positive; stored terms are never applied |

* `compiler_composed` uses the existing shared adapter (`adapt_pack_intent(global_positive=...)`):
  weighted attention is flattened and `BREAK` normalized for natural-language targets, recorded as
  the existing content-free `weighted_attention_flattened`, `break_separator_normalized` and one
  `global_positive_composed` operation (counts only). Composition is the executor's own merge rule
  (`resolution_layer.compose_global_positive`), so the string is byte-for-byte what an executor-owned
  arm dispatches. The arm's executor flag and text stay neutralized, so nothing applies it twice.
* A disabled request with stored text on a target that cannot hold it records
  `global_positive_not_applied` (same evidence as the PromptPack path); an executor-owned arm
  records nothing.
* Refusals happen at Build Preview, arm-specific, before any queue admission: terms that adapt to
  nothing, or that the exact profile's own validator refuses (inline adapter/embedding tokens,
  bracket syntax). Geometry, backend, stages, image count, LoRA/negative restrictions and exact-profile
  validators are unchanged and never relaxed.
* Klein is included only because its existing exact-profile validation accepts compiler-composed
  natural-language positive content; qualification was not widened.

## Frozen contract (additive)

* Study: `model_comparison.global_positive = {contract, enabled, text}` (the frozen shared request).
* Arm: `global_positive = {contract, mode, requested}` and `effective_global_positive_prompt`
  (the adapted contribution; `""` unless composed). `prompt_semantics` is unchanged: the compiler
  composes before the executor, so the base remains "before executor globals and optimizer".
* `contract` is `learning_model_comparison_global_positive/1`. `CONTRACT`
  (`learning_model_comparison/1`) and NJR schemas are untouched.
* `frozen_arm()` validates the representation against the frozen shared request, the arm's frozen
  executor policy, the stored executable prompt and the adaptation evidence (exactly one
  `global_positive_composed` operation iff composed, `changed` true), including after digests are
  resealed. It never reruns adaptation, so a later ruleset cannot invalidate a frozen study.
* **Legacy rule:** a study without `global_positive` keeps its original meaning (executor base ==
  rendered structured positive, no composition representation allowed). A new study requires the
  block on every arm, so a missing field cannot bypass a check; stripping the study marker or
  grafting a block onto a legacy arm is refused. Old arms are never silently upgraded.
* Trust model is unchanged: digests detect inconsistency, not authenticity. A consistent re-seal
  of both a contribution and its executable prompt is not detectable without re-adapting, which is
  intentionally not done at Run.

## Preview

`preview_summary()` adds a concise content-free per-arm notice (`composed into the prompt`,
`applied at execution`, `disabled (not applied)`) only when terms are stored in a new-contract study;
legacy studies keep their original summary. No prompt text or path is shown. Preview, frozen arm
fields, config copies and the NJR positive prompt are the same string; Run materializes it unchanged.

## Acceptance evidence

* `tests/learning_v2/test_model_comparison_global_positive_160.py` (85 tests): defect guards;
  every candidate order including SDXL/Z-Image/Klein; disabled/enabled-empty/none; weighted + BREAK
  evidence and content-freedom; payload-boundary exactly-once through the real txt2img executor with a
  fake backend (all three candidate types produce the same prompt); freeze -> save -> restore ->
  Run after live PromptPack/global/GUI inputs change with adaptation forbidden; atomic JobService
  admission and exact-profile NJR validation; rating provenance; refusals; resealed tamper matrix
  (prompt, contribution, mode, flags, evidence, shared record, marker); legacy behavior against a real
  snapshot frozen by the pre-160 code (`tests/learning_v2/fixtures/model_comparison_legacy_global_positive_159.json`).
* Three existing assertions in `test_model_comparison_global_prompts_140.py` that encoded the defect
  (Klein dispatching without the global positive) were corrected to the new contract.
* Mutation checks (removing composition, leaving the executor flag on a composed arm, bypassing the
  frozen validation) are each detected; the first two are refused at Build Preview by the arm's own
  frozen validation, the third by the tamper and legacy-upgrade tests.

## Unchanged

Queue, JobService, repository, history and runner authority; replay identities; backend
qualification and runtime lifecycle; Z-Image exact geometry/one-image restriction; Klein LoRA and
negative restrictions; PromptPack and generic builders (PR-159); CLI builder strictness; SDXL global
negative handling; ordinary Learning and controlled-variable studies. No physical generation.

## Remaining limitations

* Pre-160 studies keep their frozen meaning: their exact-profile arms did not carry an enabled
  global positive. Rebuild Preview to obtain parity.
* An inline `<lora:...>` token in the shared global terms is composed like any other prose. Z-Image
  refuses it at Build Preview (its validator rejects adapter syntax); Klein v2, like authored
  PromptPack prose today, is not pre-parsed at Preview and the exact profile's LoRA authority decides
  at backend admission (refused without LoRA evidence, accepted only when compatible). No validator is
  bypassed or widened; the parity is pinned by a test.
* The executable prompt for a composed arm is validated for internal consistency, not recomputed
  from the shared text (see trust model above).
