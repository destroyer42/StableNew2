# Intelligent image review roadmap

Owner-selected product direction as of 2026-11-14. The [active product roadmap](../../audits/2026-10-26_product_capability_roadmap.md)
sets portfolio priorities. Later packages below are candidate contracts, each subject to its own authorization.

## Operator outcome

Inspect a generated image → identify and confirm a visible issue → choose an eligible corrective action → create an explicit,
editable draft → freeze and preview it through the canonical compiler → confirm queue admission → compare the original and
corrected output → record a human improvement judgment → recommend a controlled follow-up experiment.

An AI suggestion is advisory data and supplies no defect proof, intervention, executable instruction or improvement evidence.
The operator confirms defects and chooses interventions. The compiler validates execution intent, and the operator confirms
admission. The comparison and human judgment provide improvement evidence.

## Baseline on main at `c7e782103df2f0b486917f36b4d4c31a3ecfa6ba`

| Capability | Merged behavior and evidence boundary |
| --- | --- |
| Smart Review | Explicit opt-in with one selected image. An on-demand contained CPU child proposes a bounded binary mask (SAM 2.1 Small, point/box input) or caption and object labels (Florence-2 Base FT). The operator chooses whether to use the output. Verified local catalog resources are required. Real-model operation and mask/caption usefulness remain open for the integrated Review workflow. [Review contract](../GUI/PHOTO_REVIEW_REPROCESS.md) |
| ADetailer | Requested face and hand passes are recorded separately from backend execution acknowledgements, comparable pixel-change evidence and the operator's explicit improvement judgment. The Review feedback record preserves the human outcome. [Control and effectiveness contract](../Image/PR-REFINE-160_ADetailer_Control_Truth_and_Effectiveness_Evidence.md) |
| Review and History | Mask editing and reprocess use source identity, frozen Preview and confirmed queue admission. Compare with Parent shows the direct original/child pair and its frozen settings diff with content visibility and recorded source hash checks. Existing Review feedback provides a place for operator judgments. Physical masked-output acceptance remains open. [Review contract](../GUI/PHOTO_REVIEW_REPROCESS.md) |
| Learning | Controlled experiments and ratings support qualification review with verified pairs, defensible findings and explicit create-only follow-up drafts. Qualification and any later publication require the corresponding evidence and operator action. [Learning contract](../Learning/LEARNING.md) |
| Text AI Assist | Qwen3.5 and LFM3 are registered text candidates. Preview requires a verified local installation, compatible pinned CPU executable in a contained subprocess, executable-bound egress attestation and explicit enablement for the model/build identity. The selector lists compatible, verified imports. Advisory planning and judged Matrix variety are operator-driven. [AI Assist contract](AI_ASSIST.md), [selector #307](https://github.com/destroyer42/StableNew2/pull/307), [Matrix variety #308](https://github.com/destroyer42/StableNew2/pull/308) |
| Visual candidate | VL-220 records LFM3-VL-2B Q4_K_M and the F16 projector in a separate evaluation registry. The artifacts were verified against pinned sizes and SHA-256 in operator staging. The merged evaluation contract, frozen plan, synthetic cases and scorer establish the evaluation method. The candidate is unqualified and unavailable through the text selector. [Visual evaluation contract](PR-AI-VL-220_Visual_Evaluation_Contract.md), [VL-220 #309](https://github.com/destroyer42/StableNew2/pull/309) |
| Selected-model plan advice | AI-211 biases advice to the Pipeline-selected model when it is eligible in the closed target list. An SDXL checkpoint with only `unverified_generic` policy cannot bind a plan target because its capabilities are implicit. The judge refuses unsupported IDs and the operator reads the advice before taking any action. [AI-211 contract](../../work_packages/AI-211_plan_current_model.md), [AI-211 #310](https://github.com/destroyer42/StableNew2/pull/310) |

Merged implementation and deterministic tests establish code behavior. Installed readiness requires verifying the exact local
assets and runtime. Invocation success requires an observed run. Qualification requires an accepted verdict for that identity and
scope. Operator payoff requires human-reviewed comparisons. Staging verification leaves installation readiness open. Earlier text
AI attempts exposed CLI and structured-output problems. They establish neither successful suggestion quality nor qualification.

## Sequence and exit gates

### Priority 0 · AI-VL-221 · Accept the existing visual driver

- **Outcome and state.** Review the active local effort for contained CPU image invocation and its evaluation runtime.
  Its unpublished code and evidence await independent review. This package owns the driver and invocation path.
- **Prerequisites and exit evidence.** Review the exact diff and frozen-plan identity against the approved
  [image invocation contract](PR-AI-VL-220_Image_Invocation_Contract.md). Require deterministic proof of input and artifact
  identity, bounded requests and responses, containment, cancellation and cleanup. Review any claimed supervised run
  against the approved plan scope, licence acknowledgement, executable-bound firewall attestation and operator-selected,
  separately labeled assets. Record execution and qualification dispositions independently.
- **Owner decision and stop.** Use the recorded invocation approval and its narrow supervised-run authorization with its
  gates. Hold on missing provenance, mismatched plan or scope, unverified containment or missing approval. Exclude a
  production Review entry point, a competing registry, GPU invocation and automatic promotion.

### Priority 1A · AI-ROADMAP-400 · Record the product contract

- **Outcome and state.** This documentation package establishes the loop, current evidence, work ownership and sequence.
- **Prerequisites and exit evidence.** Verify merged capability and package boundaries against current main. Review the
  three-file documentation diff, links and exact-head docs/PR checks.
- **Owner decision and stop.** The owner selected this direction. Merge needs a separate decision naming the PR. Stop after
  the merge recommendation. Scope is documentation. Physical generation, GPU inference, model qualification, Forge/SVD
  restart and external WebUI lifecycle actions require separate authorization.

### Priority 1B · IMG-REVIEW-400 · Guide manual defect review

- **Outcome and state.** Active independent package for operator-confirmed findings, editable corrective drafts and human
  outcome evidence in Review. Priorities 1A and 1B are parallel PRs with independent worktrees and disjoint file ownership.
  AI-ROADMAP-400 owns the three roadmap/status documents. IMG-REVIEW-400 owns the operator-facing finding-to-correction
  experience. It reuses Review and the canonical Preview, submission and comparison path.
- **Prerequisites and exit evidence.** Use existing source identity, visibility, revision, eligibility and lineage contracts.
  Show an eligible finding can become a draft, exact Preview and confirmed queued child, then return to a verified original
  comparison with human feedback. Show stale, incompatible or hidden input is rejected and cancellation leaves no queued job.
- **Owner decision and stop.** Apply the separately approved operator workflow. Escalate a gap that requires new runtime
  ownership or a material Review behavior decision. Exclude visual invocation, driver changes and a second visual registry.

### Priority 2 · AI-REVIEW-410 · Offer qualified on-demand multimodal review

- **Outcome and state.** Proposed Review action for an explicitly selected, verified image. Show bounded, closed findings for
  operator confirmation in the existing Review boundary. Reuse the accepted AI-VL-221 driver and visual registry.
- **Prerequisites and exit evidence.** Require accepted AI-VL-221 and IMG-REVIEW-400 boundaries. Where approved, package
  installation and registry integration, explicit operator import and attestation, and model evaluation together. Demonstrate
  identity-bound readiness, visibility and revision checks, closed-schema refusals, resource containment, and controlled
  real-image evaluation with human labels. Require a formal identity-applicable verdict before offering qualified use.
- **Owner decision and stop.** Obtain approval for the installation/evaluation scope, assets, labels, licensing, attestation
  and promotion. Hold if the identity changes, an applicable verdict is absent or evaluation fails. Exclude background scans,
  free-form executable instructions, automatic interventions and GPU inference.

### Priority 3 · AI-LEARN-420 · Learn which interventions help

- **Outcome and state.** Proposed evidence-driven ranking of eligible interventions for comparable confirmed findings.
- **Prerequisites and exit evidence.** Require stable Review outcome records and approved controlled comparisons covering
  matched source, settings, model, intervention and human labels. Demonstrate supported recommendations with traceable evidence,
  uncertainty and abstention when evidence is insufficient. Check for false recommendations on held-out comparisons.
- **Owner decision and stop.** Approve usable outcome cohorts and minimum evidence for recommendations. Hold where ratings
  lack controls or only pixel differences are available. Exclude automatic application, uncontrolled ratings and training.

### Priority 4 · AI-PLAN-430 · Suggest controlled next experiments

- **Outcome and state.** Proposed Learning-aware experimental advice with an explanation of the evidence and remaining uncertainty.
- **Prerequisites and exit evidence.** Require accepted AI-LEARN-420 evidence boundaries and reuse AI-211 and Learning's
  explicit draft/Preview path. Show suggestions use model-scoped evidence, preserve controls and refuse stale or unsupported
  selections. Test the selected policy for SDXL checkpoints tagged `unverified_generic`.
- **Owner decision and stop.** Obtain an explicit decision on allowing advice for `unverified_generic` SDXL and its bounds.
  Hold that slice pending the decision and policy evidence. Exclude implicit capability promotion, automatic enqueue and execution.

### Priority 5 · AI-GPU-440 · Evaluate optional deep review

- **Outcome and state.** Proposed Gemma 4 12B deep-review option and resource-aware GPU mode, contingent on measurable
  advantage over the qualified review baseline.
- **Prerequisites and exit evidence.** First demonstrate added value on controlled, separately labeled comparisons in an
  approved evaluation. For integration, show exact hardware/runtime readiness, bounded memory, contention refusal and
  reliable cancellation and teardown with production queue activity.
- **Owner decision and stop.** Obtain a separate GPU/process/queue architecture decision and explicit qualification scope.
  Hold if the benefit, safety or ownership evidence is incomplete. Exclude default GPU inference, lifecycle changes to
  externally owned engines and a second queue.

### Priority 6 · AI-OPS-450 · Explain operational problems

- **Outcome and state.** Proposed read-only diagnosis of logs and performance evidence with traceable optimization suggestions.
- **Prerequisites and exit evidence.** Reuse existing diagnostic projections and agree on the data visibility boundary.
  Demonstrate findings backed by known incidents or traces, correct handling of absent data and zero writes to operational state.
- **Owner decision and stop.** Approve log fields and visibility limits. Hold if diagnosis needs inaccessible data or write
  authority. Exclude automatic remediation, configuration edits and process control.

### Priority 7 · AI-TRAIN-460 · Test supervised distillation or fine-tuning

- **Outcome and state.** Optional proposal to use explicitly consented evidence to improve a bounded review task.
- **Prerequisites and exit evidence.** Require an accepted baseline, consent and provenance for every training example and
  independent validation on held-out, human-labeled cases. Show a reproducible improvement against the baseline with separate
  hallucination, schema and resource gates.
- **Owner decision and stop.** Approve data consent, retention, training and any later promotion separately. Hold on missing
  consent, leakage or inconclusive benefit. Exclude implicit collection, training on uncontrolled feedback and self-promotion.

## Evaluation and improvement evidence

Use the [VL-220 frozen evaluation plan and scorer](PR-AI-VL-220_Visual_Evaluation_Contract.md) and keep human labels separate
from model output. Synthetic cases exercise wiring. Evaluate real images for prompt adherence, anatomical defect triage,
false positives on clean images, multi-subject consistency, before/after usefulness and hallucination. Report each applicable
dimension and comparator floor. Record schema validity, latency, memory and resource safety separately. Any extension of the
frozen contract needs its own reviewed scope and evidence. An AI-only aesthetic score cannot qualify or promote a model.

Record the human-confirmed defect, proposed correction, observed pixel change and human judgment as distinct facts. Bind the
comparison to the original and corrected identities and the actual intervention. Pixel changes establish that outputs differ.
The operator's judgment records whether the correction helped, had no benefit, made the result worse or was inconclusive.

## Architecture and operator control

`Intent -> Compiler -> immutable NJR -> JobService -> SQLite Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

AI supplies advisory findings and options before Intent. Existing `ModelPolicy` and operation compatibility govern eligible
actions. Preserve image hashes, content visibility, review revisions and parent/child lineage through draft, Preview, admission
and evidence. The existing compiler, queue, history, runner, cancellation and process owners retain authority.

Downloads and imports are explicit, with verified provenance. The application performs no automatic downloads or firewall
changes. The visual candidate remains unqualified until the applicable qualification authority formally promotes its exact
identity and scope. Process ownership, resource contention, refusal and teardown requirements remain in force across phases.
