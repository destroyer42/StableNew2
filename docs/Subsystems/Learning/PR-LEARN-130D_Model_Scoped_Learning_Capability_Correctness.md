# PR-LEARN-130D - Model-scoped Learning capability correctness

State: **READY FOR PUBLICATION** after clean local verification. Locally committed
closeout only; publication and integration remain unauthorized. The earlier
**HOLD** checkpoint is preserved below as the trigger for this bounded repair.

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

LearningController grows from 3,971 to 3,989 physical lines (+18); the substantive
policy logic is extracted. Contrary to the package's ratchet description, this
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
Hosted CI is pending separate publication authorization.

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
Hosted Python 3.14 CI awaits separately authorized publication. Physical generation
was not required or run; the optional Black-tooling limitation remains non-blocking
because the existing Ruff formatter and canonical checks passed.

Final branch: `learn/model-scoped-capabilities-130d`. Final HEAD is the local
closeout commit containing this report, titled
`fix(PR-LEARN-130D): defer recommendation policy imports until execution`, whose
parent is `4ca074b43866816f96ad8fdc668e33678d9fd020`. Its exact SHA is supplied in
the completion report and can be resolved with `git log -1 --format=%H --` followed
by this report's path; a commit cannot embed its own hash. Publication is
recommended, but no push, PR creation or integration is authorized or performed.

## Exact changed files

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
