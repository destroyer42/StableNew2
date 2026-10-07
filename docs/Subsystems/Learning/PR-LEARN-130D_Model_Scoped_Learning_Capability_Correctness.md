# PR-LEARN-130D - Model-scoped Learning capability correctness

State: model-scoped Learning implemented and published as PR #63. The earlier
**HOLD**, import-boundary repair and hosted-failure repair history are preserved
below. Integration requires separate owner authorization.

## Execution Profile + Model/Reasoning Recommendation

Standard, known architecture, one primary session. Codex: GPT-6.1 Sol High.
Claude Code: Sonnet 5.5 High. The original package prefers Claude Code Local/Desktop
with 130A/130B context; the current Codex session retains its acquired context.
This tier fits the interacting Tk, frozen-state, compiler and recommendation seams;
a cheaper narrow-work tier risks extra discovery and repair cost.

## Controller Surface Assessment

`src/gui/controllers/learning_controller.py` delegates policy validation,
frozen-definition restoration, compile verification and recommendation preflight
to Learning-owned helpers. Its existing NJR builder and batch admission remain.
`main_window_v2` only connects the existing policy observer and cache-only Prompt
snapshot. No controller ownership moves, no ratcheted `src/controller` source or
ceiling changes, and no new compiler, family detector, LoRA resolver, queue,
history, runner or process authority.

LearningController is 3,960 physical lines (-11 from the 3,971-line base; -29
from the earlier 3,989-line checkpoint). Policy and stage-target logic are
extracted. Contrary to the package's ratchet description, this
GUI controller is not listed in the current checked-in ceiling file, which
governs four `src/controller` modules. No ceiling is raised.

## Contract and implementation

Learning applicability is the intersection of stage metadata and canonical
`ModelPolicy`, including exact profile and stage-local control/feature facts.
`model_capabilities.py` returns an immutable projection with available display
variables, internal recommendation parameters, unavailable reason codes,
admitted LoRA candidates, target guidance and canonical JSON context.
Variable names come from `variable_metadata.py`.

The canonical policy adds generic stage control overrides and feature stage
applicability. The qualified profile supplies fixed edit denoise; v2 LoRA
support applies to txt2img alone. Existing 130A/130B consumers retain their
global control/feature lookup semantics.

The active Experiment Design panel observes `ModelPolicyPanelProjection`.
It changes only transient Learning choices, guidance and button availability.
Invalid restored definitions remain inspectable, with explicit incompatibility;
their persisted or executed records are never migrated or rewritten. A switch
does not select a backend, edit prompts or stage-card models, or resolve assets.

Preview independently validates the effective model, stage, variable and every
candidate. Run validates again from the frozen definition and policy contract
before immutable NJR construction. The snapshot includes path-free model
identity, policy id, family/evidence, profile id/version, stage and applicable
control/feature contract. Live stage-card changes do not reinterpret it.
Model comparisons require the same evidenced policy envelope; unknown evidence
and a different exact profile cannot establish one-variable causality.

The existing generic `apply_model_compile_policy` seam runs after validation
and the requested override. Learning rejects a normalized tested parameter or
changed frozen profile rather than labeling it controlled. Allowed Klein
txt2img LoRA NJRs receive the exact v2 profile and fixed executable values.
All variants compile before one existing `JobService.submit_njrs` batch.

LoRA checks reuse `assess_lora_selection` and the PR-IMG-117 evaluator with
`RegistryLoraResolver(cache_only=True)`. Current prompt/style selection and
max-count conflicts are accounted for; pending style evidence cannot qualify
an exact experiment. Ordinary SDXL keeps its existing supported workflow.
Unverified/conflicting models keep configurable scalar controls but optional
unverified features cannot become Learning-qualified.

Image recommendations are filtered through the target projection. Exact
targets require compatible frozen profile evidence before evidence-tier or
automation eligibility calculation. Older evidence without that proof stays
readable but is inapplicable to exact targets. Video recommendation behavior
remains under its existing contract. Recommendation application preflights the
entire patch against the current target before Tk mutation, and rolls back a
failed application. Manual and automatic paths share this guard.

## Token-Efficient Validation Plan

Use injected canonical policy resolvers and exact/cached LoRA evidence. Reproduce
unsafe programmatic CFG preview, injected CFG apply and cross-model fixed-control
recommendations before production edits. Cover the pure intersection, future and
unknown policies, compatible Model candidates, frozen NJRs, LoRA admission,
normalization rejection, exact evidence scoping, atomic apply and Tk round trips.

Run the affected Learning, 130A/130B, PR-IMG-117 and experiment-design suites,
including PR-LEARN-300 freezing/coherence/admission/LoRA tests. Exercise deliberate
negative mutations against the principal guards, then run the local PR gate
once and `git diff --check`. Reuse unchanged physical/backend evidence; no real
generation, GPU, WebUI, runtime lifecycle or environment installation is needed.
Hosted Python 3.14 CI validates the exact published head.

## Boundaries

No prompt translation, PromptPack redesign, statistical redesign, new backend,
profile registry or capability qualification. Klein edit+LoRA, ADetailer and
upscale remain unqualified. No machine-local registry state is frozen into the
policy context. Historical ratings, experiments and executed NJRs are retained.

## Earlier local verification and HOLD finding

Three pre-edit deterministic reproductions failed as expected: Klein CFG
preview was accepted, injected CFG application mutated the card, and fixed
recommendations were returned from incompatible evidence. These checks now pass.

- Affected regression set: **594 passed** (Learning, 130A/130B, PR-IMG-117,
  PR-LEARN-300 and experiment-design Tk coverage).
- Final changed-surface subset: **147 passed**, including manual/automatic
  rejection and frozen definition stability.
- Nine intentional mutations detected: bypass stage intersection, allow fixed
  CFG, allow edit denoise, promote unverified LoRA, omit exact evidence scoping,
  permit stale apply, remove compile entry, silently erase the tested value,
  and scan assets on model refresh. Each source was restored from original bytes.
- Repository completeness after staging: PASS, 501 tracked Python modules.
- Controller ratchet: PASS; four existing ceilings unchanged.
- Repository Ruff and ten-target mypy smoke: PASS.
- `git diff --check`: PASS.
- The prescribed PR-gate invocation stopped at completeness because the new
  modules had not yet been staged. After staging, completeness and the remaining
  gate steps were checked individually; no full-gate PASS is claimed.
- Isolated collection found **5,638 tests**, but its wrapper failed because the
  final test file was edited during its fingerprint window. This attempt is
  invalid as isolation evidence and needs an unchanged-input rerun.
- Required smoke: **FAIL, 177 passed / 1 failed**, at
  `tests/tools/test_operator_journey_harness.py::test_importing_the_journey_does_not_import_state_capturing_app_modules`.

The required-smoke failure is package-caused: the new eager recommendation
imports reach `model_policy_service` / `model_capabilities`, then canonical
model policy, `forge_klein_profile`, `image_backend_types`, and
`src.pipeline.artifact_contract`. Journey import must not load any pipeline or
GUI/controller application modules before workspace redirection. A read-only
in-memory comparison using the baseline recommender imports no forbidden
modules; the current recommender imports `src.pipeline` and its artifact
contract. No execution, network or GPU behavior is implicated by this result.

Earlier validation needed two distinct adjustments: ordinary-SDXL LoRA fixtures
needed explicit model evidence, and the image filter had reached the independent
video recommendation surface. Both are repaired. The import-boundary failure is
the third distinct class, so implementation stopped at that checkpoint rather
than extending repairs. Its HOLD called for owner-scoped import-boundary repair,
clean isolated collection and required smoke, and affected evidence rechecks.
The bounded continuation below resolves those pre-publication blockers.

The optional Black formatter is unavailable; the existing Ruff formatter was
used for new modules. No environment was installed or changed. Hosted Python
3.14 CI and physical generation were not run.

## Bounded import-boundary continuation

The owner authorized one bounded repair pass on
`learn/model-scoped-capabilities-130d`, starting from local checkpoint
`4ca074b43866816f96ad8fdc668e33678d9fd020`. Fetched `origin/main` and the merge-base
remain `79ddcc92401d44871d5bd30d00878ff0e5b20f9b`; the required worktree is
`C:/Users/rob/projects/StableNew-main`. This continuation retains the Standard
execution profile and GPT-6.1 Sol High / Sonnet 5.5 High recommendations, with the
current Codex session preferred to retain branch and evidence context.

The exact existing import-safety test failed before edits. A `builtins.__import__`
trace proved the first new edge:

`learning_lora_strength -> recommendation_engine -> model_capabilities`.

`model_capabilities` requests canonical `src.image_backends.model_policy`, but
Python first initializes `src.image_backends`. Its initializer imports
`a1111_webui_backend -> image_backend_types -> src.pipeline.artifact_contract`.
This package-initializer route reaches the prohibited pipeline modules before
the requested policy module finishes loading. `model_policy_service` is another
new eager dependency from the recommender. In-memory substitution of the exact
`origin/main` recommender produced no prohibited modules; the checkpoint loaded
`src.pipeline` and `src.pipeline.artifact_contract`. The first new edge is in the
recommender, not in the already-import-light operator journey.

Repair: keep RecommendationEngine import and construction light, retain the
optional injected resolver without invoking it, and defer model-capability and
model-policy-service imports plus default resolver selection to `recommend()`.
Filtering, exact evidence scoping, admission and runtime semantics are unchanged.
The existing harness contract is neither changed nor whitelisted. No controller,
model policy, backend type, artifact contract or journey implementation is edited.

Focused post-repair evidence: the exact failed test passes; a new deterministic
subprocess regression proves engine import and both default/injected construction
load no production policy/backend/pipeline modules and do not invoke a resolver.
The journey harness plus affected capability, recommendation, apply, frozen/LoRA
and Tk suites pass: **156 tests**. Intentional eager-policy-import restoration
fails both import regressions; bypassing exact-profile evidence fails its scoped
recommendation regression. Restored source passes all three targeted checks.
The eight unaffected earlier guard mutations retain their unchanged-source
evidence; the ninth (exact-profile scope) was rerun after this repair.

Final verification ran sequentially with the entire repository unchanged during
each command, including documentation. Only closeout documentation changed after
both commands completed; production/test source retains the verified bytes.

- Standalone required smoke: **PASS, 352 passed in 33.64s**; the wrapper confirmed
  repository unchanged (55.1s total).
- Canonical `python tools/ci/run_pr_gate.py`: **PR gate OK**, exit 0. Completeness
  passed with 501 tracked Python source files; four controller ratchets passed
  with no ceiling change; Ruff passed; mypy passed for ten source targets.
- Gate isolated collection: **PASS, 5,639 tests collected in 3.09s**, repository
  unchanged (24.5s total). This is collection evidence, not 5,639 executed tests.
  The new subprocess regression accounts for the one-test increase. The earlier
  5,638-test attempt remains invalid isolation evidence.
- Gate required smoke: **PASS, 352 passed in 35.07s**, repository unchanged
  (57.3s total).
- Final scoped and aggregate whitespace checks: **PASS**. No unresolved blocking
  in-scope finding remains; original 130D guards and authority boundaries remain.

The continuation changes exactly four files: this report, `STATUS.md`,
`src/learning/recommendation_engine.py`, and
`tests/learning_v2/test_model_capabilities_130d.py`. The complete package still
changes the sixteen files listed below. LearningController remains 3,989 physical
lines (+18 from base), with no continuation controller edit or ceiling increase.
At that pre-publication checkpoint, hosted Python 3.14 CI had not run. Physical generation
was not required or run; the optional Black-tooling limitation remains non-blocking
because the existing Ruff formatter and canonical checks passed.

At that closeout, the branch was `learn/model-scoped-capabilities-130d`, with HEAD
`eeeb896ade118f8b695fa068eb6f47213c28337b` and parent
`4ca074b43866816f96ad8fdc668e33678d9fd020`. The owner subsequently authorized its
publication as PR #63; no integration was authorized or performed.

## Bounded repair of hosted failures on PR #63

Starting head: `eeeb896ade118f8b695fa068eb6f47213c28337b`. Fetched `origin/main`
and merge-base remain `79ddcc92401d44871d5bd30d00878ff0e5b20f9b`, with the same
branch and worktree. Hosted run 37564017584 passed required CI but its affected
lane reported 4,276 passed, 19 skipped and six failures. Four journey assertions
share the unevidenced-model fixture root cause; GP10 and review/reprocess apply
share the incomplete stage-card fixture/targeting class. The owner authorized
these two classes, normal publication of the repair, and automatic hosted CI.

Execution remains Standard, GPT-6.1 Sol High / Sonnet 5.5 High, retaining the
current Codex session. Controller surface: delegate stage mapping and complete
target preparation to the toolkit-neutral helper, with no authority movement
or ceiling increase. Token-efficient validation: reproduce first; run target,
affected Learning and canonical journey coverage; reuse unchanged 130B/policy
evidence; freeze files for one canonical local gate; publish normally and obtain
new-head hosted Python 3.14 evidence. No old workflow is manually rerun.

Pre-edit reproduction failed all three selected targets: fake canonical journey,
GP10 and review/reprocess application. The fixture repair persists declared SDXL
embedded metadata using the existing AssetRegistry v2 cache schema, after
workspace activation and before app/model-policy construction. Synthetic content
identity is fixture data, not a real model hash. Existing checkpoint extensions
are preserved. A process-local fixture WebUI root satisfies cache lookup's root
requirement and is restored by OperatorWorkspace. No file discovery, model hashing
or real registry writes occur. Fake mode declares its known fixture; the loopback
real-path test explicitly selects `--fixture-sdxl`. Ordinary real mode seeds no
family claim, so genuinely unclassified optional capabilities remain unavailable.
The journey's direct recommendation query supplies its evidenced target model.

Targeting follows current config/executor authority. ADetailer serializes its
checkpoint override as `adetailer_checkpoint_model`; its detector remains
`adetailer_model`. The executor prioritizes that checkpoint override and uses the
NJR-selected VAE, so VAE application uses Base Generation's aliased txt2img VAE.
Img2img has local CFG/steps/sampler/denoise controls but no scheduler selector;
its inherited scheduler/checkpoint/VAE and upscale checkpoint/VAE use Base
Generation. Upscale Factor uses the upscale control. A complete target/old-value
plan is built before any setter runs; missing/unrepresentable controls reject
the whole patch. Runtime setter failures retain the existing rollback path.
The GP10/review doubles now include the real scalar control contract and assert
every recommended value was applied, rather than weakening atomicity.

Focused evidence:

- Target/cache/GP10/review focused checks passed; real ADetailer serialization
  verifies checkpoint, detector preservation, denoise and inherited VAE.
- Affected Learning/130D, harness, target, GP10/review, 130A and PR-IMG-117 set:
  **533 passed**. Final fixture suffix/unset-root and target checks: **13 passed**.
- All four formerly failing journey tests: **4 passed in 137.46s**. Fake and
  loopback cases each execute three independently persisted jobs through real
  Tk, Learning, JobService, SQLite and runner; full review/rating/recommendation/
  analytics succeeds. Seed-loss still produces the intended invalid-evidence
  failure. Journey guards record no isolation violation or captured error.
- Scoped Ruff: PASS. No canonical model-policy, backend, compiler, queue,
  repository or runner production source changed during this repair.

Final canonical local gate: **PR gate OK**, exit 0, after one invocation with all
files frozen. Completeness passed with 502 tracked Python modules; all four
controller ratchets, Ruff and ten-target mypy passed. Isolated collection:
**5,652 collected in 4.09s**, repository unchanged (35.8s wrapper). Required smoke:
**352 passed in 43.21s**, repository unchanged (75.5s wrapper). Collection is not
a full-suite execution. Final scoped/aggregate whitespace checks pass. Only this
closeout report changed after the gate; production/test source retains its
verified bytes. New-head hosted CI is automatic after the authorized fast-forward
push; its final result and exact repair HEAD are recorded in the completion
report. Earlier HOLD/failed and invalid isolation attempts above remain historical
evidence, not current passing verdicts.

Exact repair scope: `STATUS.md`, `docs/CODEX_MAP.md`, this report,
`Learning_System_Spec_v2.6.md`, `src/gui/controllers/learning_controller.py`,
`src/gui_v2/recommendation_targets.py`, `src/learning/model_policy_service.py`,
`tests/gui_v2/test_recommendation_targets_130d.py`,
`tests/integration/test_golden_path_suite_v2_6.py`,
`tests/integration/test_learning_review_recommendation_e2e.py`,
`tests/tools/test_operator_journey_gui.py`,
`tests/tools/test_operator_journey_model_evidence.py`, and
`tools/operator_journey/{cli.py,fixtures.py,workspace.py,journeys/learning_lora_strength.py}`.

## Original sixteen-file package scope

- `STATUS.md`
- `docs/CODEX_MAP.md`
- `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md`
- `docs/Subsystems/Learning/PR-LEARN-130D_Model_Scoped_Learning_Capability_Correctness.md`
- `src/gui/controllers/learning_controller.py`
- `src/gui/main_window_v2.py`
- `src/gui/views/experiment_design_panel.py`
- `src/image_backends/model_policy.py`
- `src/learning/model_capabilities.py`
- `src/learning/model_policy_service.py`
- `src/learning/recommendation_engine.py`
- `tests/gui_v2/test_learning_model_policy_130d.py`
- `tests/learning/test_recommendation_engine_v2.py`
- `tests/learning_v2/test_model_capabilities_130d.py`
- `tests/learning_v2/test_pr_learn_300_lora_strength.py`
- `tests/learning_v2/test_recommendation_structured_values.py`
