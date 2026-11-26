# Controlled Prompt Slot experiments

Outcome: one named positive-prompt slot varies over 2-8 ordered candidates, with
1-3 images each (maximum 24), in existing Learning Design/Preview/Run/Compare/Rate.
Custom templates and native PromptPack rows share canonical token substitution,
structured intent/adaptation and ordinary Learning NJR materialization. All other
settings, prompt components, negative prompt and seed cohort are frozen. Observed
prompt readback is required for a controlled conclusion. No universal optimum claim.

Execution Profile: Standard, difficult cross-file correctness/evidence package;
Windows Local/Desktop, one primary session, no delegation.
Model recommendation: Claude Code Sonnet 5.5 XHigh; Codex GPT-6.1 Sol XHigh.
Frozen prompt, adaptation, materialization and readback proof justify this tier to
minimize expected total successful-work cost. Expected usage: 15M cache-read / 75k output.
Actual host: Codex Desktop, GPT-6.1 Sol High; this is the current single session,
not a Claude session. Session: `codex:01a17495-32aa-7751-a315-a0d5eeeebbf6`.
New work-package boundary recorded before discovery: `2026-10-25T18:06:06.3676546-04:00`.
The exact current-turn `task_started` event is `2026-10-25T18:05:50.171-04:00`,
recovered from this session's log; closeout usage starts there to include initial preparation.

Starting checkout: main at `612deb1e67f0acd3f152b9abf313fda169476aad`, with an
unrelated untracked GUI assessment preserved. PR #213 is merged; live main is
`2b4fde2dd540b33a906bcc676959e2eb263a005d`. Implementation starts at that accepted
integration in `C:/Users/rob/qual/StableNew-learn680`, branch
`learning/learn-prompt-680-controlled-slots`. Local main is not changed.
No matching open Prompt Slot PR or existing implementation was found.

Controller Surface Assessment: LearningController starts at 4,068 lines. Domain
authoring/freeze/parity/readback belongs to toolkit-neutral Learning modules;
controller dispatch stays thin. Existing snapshot, ordinary_njr, JobService,
SQLite, experiment/session and rating stores remain authoritative. No ceiling increase.

Final controller assessment: LearningController 4,068 -> 4,084 physical lines (+16).
Prompt Slot coordination is 306 lines in the existing Learning controller-services
namespace; the toolkit-neutral contract/readback/conclusion module and its Tk authoring
frame remain separate. No ratcheted controller shrank and no ceiling was raised.

Authorities consulted: AGENTS, STATUS, CODEX_MAP and relevant CODE_MAP entries,
work-package template, model selection, architecture, Learning living doc/spec,
PromptPacks/prompting, image pipeline/model profiles, GUI style and testing/CI.

Token-Efficient Validation Plan:

1. Demonstrate missing authoring/compilation behavior with deterministic tests.
2. Validate slots, fixed selections, candidate bounds/directives/order, native/custom
   sources, optimizer refusal and canonical adaptation using temporary data/fakes.
3. Prove frozen Preview/Run parity, common seeds, single atomic submission, restart
   identities, observed prompt evidence, ratings/conclusion and recommendation isolation.
4. Check UI visibility, compact layout, edits invalidating Preview and lifecycle.
5. Run affected regressions sequentially, then the canonical Python 3.14 gate once
   source is stable; no concurrent pytest or edits during repository-stability checks.
6. Review aggregate diff, batch in-scope repairs once, reverify, update affected canonical
   docs/code map, inspect exact state/diff, and commit locally.

Exclusions: physical generation/backends/model loading, PromptPack rewrites, negative
sweeps, cross-model/multi-axis studies, new compiler/job/queue/store authority,
optimizer training, automatic recommendations/profiles, remote publication or merge.
Stop for a material authority/schema/data-safety decision, unprovable target adaptation,
independent feature expansion, more than two material failure classes or exhausted repair budget.

## Focused evidence and review

- 54 new deterministic cases cover authoring bounds/directives/aliases, both sources,
  fixed slots, frozen ordinary NJRs, one admission, source edits/deletion, same seed cohort,
  actual positive/negative readback, launch/seed mismatches, SQLite restart associations,
  saved/draft ratings and local conclusions, setting/profile isolation, visibility, keyboard
  controls, destruction and compact/200% scaling scroll access.
- Broad affected regression: 1,054 passed. One sandboxed attempt hit Windows invalid-handle
  failure during Tk fixture teardown; the identical sequential suite passed under normal
  Windows desktop access. No environment rebuild or application/runtime change was made.
- Aggregate review completed in the primary session. One batched repair kept parity proof
  compact (sealed input/config digests rather than duplicated candidate configurations)
  and added a missing local type annotation. Post-repair focused reverification: 198 passed.
- Strict targeted mypy: no issues in the three new source modules. Ruff and generated
  code-map freshness passed. Canonical gate and final diff/commit evidence follow at closeout.
- The first canonical gate exposed seven added type diagnostics at existing seams.
  Explicit NJR return types, nullable baseline checks and visibility callback annotations
  resolved them; five existing view diagnostics also disappeared. The prescribed mypy
  ratchet update lowered that view from 42 to 37; no baseline increased. All 54 new cases
  passed again after these annotation and guard changes.
- The formatter ratchet then identified three touched files requiring canonical Ruff
  formatting; formatting was applied and the unchanged format/debt baselines passed.

Initial target is registry-verified SDXL txt2img. Exact profiles are explicitly refused
until their prompt adaptation/readback contract is proven. The logical contract is
`learning_prompt_slot/1` inside the existing snapshot schema. Variant IDs A-H keep private
candidate text out of generic labels/filenames; frozen metadata retains the exact text.
No rating, session, PromptPack or NJR schema migration is introduced. Ordinary Matrix freeze,
numeric/resource recommendations and profile-publication rules retain their existing semantics.

## Local acceptance

PASS. The canonical Python 3.14 gate passed after correcting the STATUS line cap in place:
repository completeness (748 modules), controller ratchet, Ruff, mypy smoke, whole-source
mypy/format/architecture ratchets, 13,635 collected tests and 358 required smoke tests
(one warning). Collection and smoke verified repository stability. The full census was
not requested or run; no hosted CI verdict is claimed for this unpublished branch.

Focused evidence remains 1,054 affected regressions, 198 post-review cases and 54 new
cases repeated after typed seam repairs; these overlapping runs are not additive counts.
Both prompt sources, ordinary Matrix compatibility, frozen Preview/Run equivalence,
the 101/102/103 seed cohort, observed prompt/seed/launch validity, saved ratings/local
conclusions, profile/recommendation exclusions and additive legacy/recovery behavior
are covered by these deterministic tests. Runtime evidence tests use fakes; they do
not assert physical backend prompt fidelity. Missing readback remains uncontrolled.

Ownership: `prompt_slot_experiment.py` owns the logical contract, canonical substitution/
adaptation orchestration, prompt evidence checks and local conclusion. Existing
`ordinary_snapshot.py`/`experiment_execution.py` own snapshot persistence; the small
`learning_controller_services/prompt_slot.py` seam calls existing `ordinary_njr.materialize_njr`.
Existing ExperimentAdmissionService compiles all variants, JobService admits once, and
experiment reconciliation combines prompt readback with existing seed/launch evidence.
LearningRecordWriter and the existing session/repository stores retain ratings/jobs.
Prompt Slot stays outside the numeric variable registry; the recommendation engine
explicitly excludes its study and the existing profile gate rejects nonordinary studies.

Aggregate diff: 23 files (12 source, two tests, eight authorities/work-package documents,
one lowered type baseline). Reviewed source immutability, one-variable isolation,
structured components, frozen globals, canonical policy, readback, visibility, admission
and restart compatibility. No current blocking finding remains. One aggregate-review
repair batch was followed by three gate-compliance corrections (typing, formatting,
STATUS line cap); no acceptance criterion, test or ceiling was weakened.

No PromptPack, historical NJR or rating was overwritten; no second queue, runner,
compiler or database was introduced. No physical GPU/backend execution or runtime
restart occurred. The original main checkout remains at `612deb1e...`, including its
unrelated untracked GUI assessment. At this local acceptance boundary, publication,
PR creation and merge were not yet authorized.
The installed usage reporter will measure this single Codex session from the recorded
task-start boundary through closeout; exact tokens/window and the final commit are
reported in the completion response.

## Authorized publication integration

The owner subsequently authorized integration of current main into this feature branch,
overlap resolution, revalidation, push and PR creation. Integration into long-lived main
is not authorized. Pre-integration feature HEAD is `beaa6f5681c41e5d98f06c110d7797ecf26cb940`;
the fetched main is `0318d3f3669535c07b6fcbaa671fd3ad069cf497` (GUI-SEAM-700 and
GUI-QT-001 assessment integration). This is a history-preserving merge into the feature.

No application-source conflict occurred. The generated code map is regenerated with
both inventories. The mypy baseline preserves both independent reductions: 1,475 total,
including the Learning view at 37. STATUS retains both capability/CI descriptions within
150 lines. Feature behavior, architecture ownership and LearningController size are
unchanged. Revalidation covers the existing affected Learning/profile/GUI suite, the
new controller/presentation seam tests and the updated canonical gate including its
controller Tk import-boundary check. No physical qualification or environment rebuild.

Integrated-tree revalidation PASS: 1,120 affected Learning/profile/GUI/controller/code-map
tests; updated canonical gate PASS (749 modules, all ratchets and the controller Tk
import boundary, 13,671 collected tests, 358 required smoke tests with one warning).
Collection and smoke report the repository unchanged. No source repair was necessary.
The reviewed aggregate against integrated main retains the same 23-file package;
no inherited GUI isolation/CI changes are introduced again by the feature PR.
