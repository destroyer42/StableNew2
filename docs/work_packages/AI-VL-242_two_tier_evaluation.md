# AI-VL-242: two-tier evaluation contract, scorer and gates for real images

Status: **implemented and tested on synthetic fixtures; no model run, no real image evaluated.** Gates proposed, pending owner
approval. `qualified` stays false; nothing is promoted. Contract: `docs/Subsystems/AiAssist/PR-AI-VL-242_Two_Tier_Evaluation_Contract.md`.

## Execution class and model recommendation

- Execution class: **Standard** (an evaluation contract, a scorer and an offline analysis under `tools/`; no architecture,
  production, runtime-ownership or `src/` change).
- Model recommendation: Claude Code Opus 5.5, high effort (statistical design and closed-schema contract work where a wrong gate
  is expensive to reverse); Codex GPT-5.5 high would also fit. Expected usage: about 15M cache-read, 150k output.
- Controller Surface Assessment: none. No controller, coordinator, GUI or `src/` file is touched; `src/review/findings.py` is
  imported read-only for its `Category` taxonomy.
- Token-Efficient Validation Plan: the two new test files, the existing AI-VL-220/222/223/230 tests unmodified (frozen digests),
  then `tests/tools`, the ruff and mypy ratchets and `python tools/ci/run_pr_gate.py` in an isolated worktree.

## Scope

| Area | Files |
|---|---|
| Contract `eval/2` (cases, labels, response schema, evidence, gates) | `tools/qualification/vl220/eval2.py` |
| Converter from `stablenew.vl240.review_export/1` | `tools/qualification/vl220/review_export.py` |
| Scorer | `tools/qualification/vl220/eval2_scoring.py` |
| Statistics, floors, Florence-2 input, paired comparison, escalation, gates, plan, report, CLI | `tools/qualification/vl242/` |
| Tests (synthetic only) | `tests/tools/test_ai_vl242_contract.py`, `tests/tools/test_ai_vl242_two_tier.py`, `tests/tools/vl242_support.py` |
| Documents | the contract above and this work package |

Not touched: `driver.py`, `visual_argv.py`, `staging.py`, `candidates.py`, `diagnostics.py`, `vl220/__main__.py`, `contract.py`,
`scoring.py`, `plan.py`, `synthetic.py`, `src/`, `src/ai_assist/argv.py`, the model registry and runtime manifest. The frozen
identities stay: VL-220 plan `15d7ab2e...db536`, the three built-in synthetic sets, the `eval/1` response schemas (pinned by a
new test), and the Qwen plans, corpus and LFM3 contract (their tests run unmodified).

## Design decisions

1. **Separate files, not edits to `eval/1`.** Keeping `eval/2` in new modules guarantees `contract.py`, `scoring.py` and
   `plan.py` (and every digest derived from them) stay byte-identical.
2. **One taxonomy.** The category enum is `src.review.findings.Category` minus `Prompt adherence` (a real case carries no
   prompt). Regions are a 3 x 3 grid plus `whole_image`, derived from Review's pixel box by area share, because a model cannot
   reliably answer pixel boxes and a coarse zone is still actionable in the mask editor.
3. **Closed answers end to end.** Explicit verdict tied to the findings list by two schema branches; closed refusal codes; no
   string field without an enum. Persistence keeps only these closed answers.
4. **Unanswered counts against the system on both sides**, so failing to answer cannot improve the false-alarm rate.
5. **Balanced accuracy for the floor gate**, because every deterministic floor scores 0.5 on it while F1 rewards always-defect.
6. **Two-tier time is weighted by a plan-bound defect share** (proposed 0.5), because the test set's 60 % share is a design
   choice and the conditional rules' cost depends on it.
7. **Pre-registered conditional rules** (`on_defect`, `on_clean`) for T1; `never`, `always`, `deep_only` are context.

## Acceptance

| Requirement | Evidence |
|---|---|
| `eval/2` beside a byte-identical `eval/1` | `test_eval1_contract_schemas_sets_and_plan_are_unchanged`; existing VL-220/222/223/230 tests unmodified |
| Converter, human labels only, nothing copied | converter tests incl. `test_the_converter_copies_no_export_text` and eleven refusal codes |
| Closed schema in Review's taxonomy | `test_the_response_schema_is_closed`, schema/validator agreement on good answers and 15 near misses |
| Dimensions and the inconclusive / no-benefit rule | scoring tests; `pair_metrics` excludes inconclusive and matches no benefit with no clear difference |
| Intervals and the paired test | Wilson against published values, exact McNemar on hand-computed counts, deterministic stratified bootstrap |
| Floors, Florence-2 limited to subject counts | `test_floors_on_the_planned_set`, `test_florence_answers_only_subject_counts`, `test_florence_input_is_closed_and_needs_the_plan` |
| Every escalation rule on a hand-computed example | `test_every_escalation_rule_on_a_hand_computed_example`, time weighting, unanswered fallback |
| Gate verdicts at, just above and just below thresholds | parametrized gate tests for F1-F5, D1-D6, T1; pilot and insufficient-sample tests |
| Persistence rule | `test_an_evidence_record_never_carries_answer_text`, ten refusal cases, all-strings-closed scan, CLI refuses in-repo writes |
| Plan digest binds contract, gates, case set, candidates, limits | `test_the_plan_binds_every_input_and_no_case_content`, `test_changing_a_gate_value_changes_the_plan`, evidence-binding refusals |

## Evidence boundary

- Implementation: the files above. Demonstration: deterministic tests on synthetic fixtures only. Qualification: none (N/A).
- Not demonstrated: any model answer on a real image; the driver writing `evidence/2`; Gemma's time and memory; the Florence-2
  subject-count derivation; the export format of AI-VL-240 as merged (the converter follows the fields announced for it; any
  spelling difference is a converter change).

## Owner decisions before the paired run

Approve or change: the gate values (contract section 6), the case set (export, counts and digests), each tier's limits
(replacing the placeholders with AI-VL-241's measurements), `operator_defect_share`, Florence-2 in or out of scope, and then the
`plan_sha256` printed by `python -m tools.qualification.vl242 plan`, separately for a pilot and the full run.

## Follow-ups

- **Blocking the planned set:** Review must record a clean confirmation and a subject count per image (AI-VL-240 found it
  cannot today; `src/` work, owner-approved separately). Without it the real set has no confirmed-clean image, and the
  clean false-alarm, floor and multi-subject gates cannot be evaluated.

- Driver integration (owner of `driver.py`): run `image_review` / `pair_review` cases with `eval2.build_response_schema` and
  `eval2.prompt_for`, write `evidence/2` through `eval2.evidence_record`, and bind the `eval/2` plan digest at admission.
- Florence-2 comparator producer: derive the subject-count token from the existing Smart Review object labels, outside Git.
- Align the converter with the merged AI-VL-240 export if its field spellings differ.
