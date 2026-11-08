# Evidence, evaluation and scientific validity

The current system has useful evidence mechanics, not a generally validated evaluator. This report leaves existing recommendation tiers, publication rules and statistics intact. G6 and pending 072 own future sufficiency/methodology decisions. Anchors E17–E24/E27–E29/E38–E40 identify current mechanisms.

## Three evidence types

| Type | What it can establish | Required provenance / what it cannot establish |
|---|---|---|
| Human judgment | This operator's saved overall/subscore/pair preference in a stated context | Preserve rater/context/rubric and revision where available. Current records do not prove multiple independent blinded raters, population preference or objective correctness |
| Technical observation | A named measurement/readback under exact model/runtime/settings/artifact conditions | Preserve implementation/version/units/missingness. Requested, compiled, dispatched and backend-reported settings are different facts. Motion/flicker/detail guardrails do not prove intended action, identity or aesthetic quality |
| AI preference/quality prediction | A proposed estimate under a frozen evaluator release and validated scope | Needs model/preprocessor/data/split/label provenance, calibration, uncertainty and independent evaluation. It is neither a human rating nor local execution/compatibility qualification |

Keep source type even when displaying a combined view. An AI caption, segmentation mask or critique cannot be stored as if the operator rated an artifact. Accepting a mask does not validate an evaluator; agreeing with an AI once does not validate personalization. Manual qualitative rubrics and deterministic integrity/readback checks remain useful without a learned scorer.

## Current consumers have different scopes

| Consumer | Current reduction / eligibility | Limit to retain |
|---|---|---|
| RecommendationEngine | Latest revisable kind/experiment/image row; compatible context weighting; highest weighted mean, confidence then count tie-breakers | Its bounded volume/variance/context score is a heuristic, not calibrated probability or a statistical confidence interval. Review/curation are observational; curation events are not globally collapsed |
| Learning profile publication | Latest experiment/job/image row; ordinary controlled txt2img, exact byte/profile/policy proof, actual seeds and executed tested value; per-experiment consistency and shared thresholds | Qualifying cohorts then pool **by setting**, equal contribution per rating. This is not a general across-study comparability/dependence check; a large cohort can dominate. Only tested fields publish |
| Observed preference summary | Publication-controlled samples grouped by setting × frozen prompt context × category; overall and subscores separate, incompatible/unattributed excluded | Can report insufficient, competing, no-clear or observed preference; no general learned prediction. Narrower grouping than publication does not repair publication policy |
| Qualification Compare & Rate | Verified artifact/seed pairs, fixed context and launch boundary; missing/duplicate proof excluded | Follow-up signal only; historical seed-vector position is not artifact pairing proof. Function/module names do not imply a formal qualification verdict |
| Video review / deterministic eval kit | Isolated clip rating revisions by job/artifact hash; physical clip guardrails in their own schema | Not image recommendation training labels or a general quality score; technical flags do not pick a winner |

Numeric current rules are sourced, not new recommendations: `MIN_CONTROLLED_VARIANTS=2`, `MIN_CONTROLLED_RATINGS=3` in E23; observed-preference `MIN_RATINGS_PER_VALUE=3`, `MIN_LEADING_MARGIN=0.5` rating points in E21; screening uses six pairs, at least five wins and mean improvement at least 0.5 in E17. These are existing eligibility/screening rules, **not evidence that those sample sizes establish scientific significance**. No new measured confidence, effect threshold, acceptable evaluator error or sample-size requirement is chosen here.

## Revisions, duplicates and applicability

The log preserves append history; revising a rating is not a new independent sample. An invalid latest rating removes that sample from the applicable revisable reader rather than reviving its prior value. Profile publication uses its own durable key; video review has separate hash/revision semantics. Current identity is not a universal content-level dependence detector: copying/re-encoding an image, assigning a new experiment/job/path, sharing a prompt seed or importing a result can create dependent observations beyond the existing keys.

A future general evidence analysis should retain original sample/experiment/job/artifact identities and a source namespace, rating revision/time/rubric, exact checkpoint bytes/profile/backend/runtime, effective prompt/adaptation and configuration, actual seed/readback, task/category and acquisition/selection process. Treat identical bytes as one provenance-linked observation, and record nonidentical but dependent derivatives/shared datasets rather than assuming hash difference means independence. Missing rater or environment metadata stays unknown; no historical backfill from present configuration.

Before pooling, state the question, compare these dimensions and classify directly comparable, conditionally relevant, adjustment-required or insufficiently comparable. Preserve contradictory cohorts and exclusions. Shared upstream datasets, repeated imports, reratings and multiple outputs from one seed/subject cannot silently increase independent confirmation. Any weighting or dependency model requires a stated estimand and validation, not a hand-chosen “confidence” multiplier. This is a **future methodological proposal**, not an implemented schema or a change to existing publication.

The A addendum's catalog collision and profile pooling findings remain specific static facts: imports change the selected content-addressed revision with imported-ID-wins semantics; previous revision files are retained. No actual operator-loss occurrence or downstream quality impact is measured. E does not silently fix them or recommend consequential synthesis on top of them.

## Evaluator release proposal and falsification

Before qualifying C12–C14, a separate package would need to freeze the evaluator question: technical defect detection, task adherence and personalized liking require different labels and validation. Record exact model weights, license/provenance, runtime, quantization, prompt/rubric, image decoding/preprocessing and evaluator code/data revisions. Retain refusal, corrupt input, timeout and out-of-scope outcomes separately from low quality. A text-rewrite model contract cannot qualify a vision scorer by analogy.

Proposed validation must compare a low-cost deterministic/manual baseline and candidate under blinded, randomized judgments where suitable. Separate fitting, tuning/calibration and a frozen held-out evaluation; group splits by source/near-duplicate family, subject/prompt/seed and operator as required by the intended generalization. This avoids teaching and testing on dependent derivatives or revised versions of the same label. Those dimensions and the acceptance procedure need owner/methodology review; this report claims no statistical guarantee from the proposal.

Use evaluation independent of the data/feedback used to optimize the evaluator. Report rater disagreement, category/subgroup coverage, missingness, false-negative screening costs, selective abstention/coverage and version-specific uncertainty. Check distribution shifts in checkpoints, style, aspect ratio, content, backend and operator taste. Numeric acceptance, representative sampling rates and any probability calibration method remain **future proposals to freeze before evidence acquisition**, not thresholds selected after seeing output.

AI-screened batches should still allow human inspection of representative/random samples, promising cases, uncertain/failed cases and screening disagreements. Preserve unreviewed outputs and selection probabilities/process; otherwise screen-selected labels bias subsequent preference learning. Operators can correct predictions without those corrections automatically training or releasing anything. E does not authorize training or data capture; Offline AI Assist v1 expressly excludes both. A new release should preserve the old evaluator and applicability record, recheck safety/quality and require explicit promotion; rollback changes the selected advisory release, never rewrites original ratings or historical predictions.

Falsifiers include: performance collapsing on grouped held-out data; a simple manual/deterministic route matching the gain; cross-model prompt adaptations explaining the apparent quality effect; reordered blind pairs reversing preference; rerating/duplicate removal changing a claimed leader; a technical metric favoring flicker or sharpening artifacts over task success. Each would narrow or reject the proposed evaluator claim, not justify lowering acceptance after the run.

## Sufficiency and recommendation boundaries

Distinguish enough evidence to **show an observation**, **suggest one next test**, **apply a manual recommendation**, **publish a tested field**, **route work unattended**, and **qualify a model/evaluator**. They are different decisions. Current engine tiers and profile eligibility remain authoritative for their existing actions; no new general confidence label can confer stronger permissions. A safe gap report can state unknown and offer existing controlled research without promising improvement. Consequential imported synthesis, revised recommendations and learned-profile promotion retain separate operator approval under 071/048; accepting E resolves none of these methods.
