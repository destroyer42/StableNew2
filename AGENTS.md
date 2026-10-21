# StableNew repository operating contract

## 1. Repository authority

StableNew is a local desktop application for reproducible image and video
generation. Its authoritative remote is
`https://github.com/destroyer42/StableNew2.git`; `main` is the default
long-lived branch, the current release line is v2.6 MVP recovery, and
`STATUS.md` states current priorities.

Current checkout, branch, HEAD, and diff are primary truth and precede
interpretation from repository-local authorities. The durable authority chain
is this file and `STATUS.md`, then the relevant `docs/CODEX_MAP.md`, relevant
architecture/testing authority, and roadmap for sequencing. Historical chats,
old branches, stale planning files, snapshots, archives, and memory never
override current repository evidence; use them only for a specific historical
question.

## 2. Runtime and architecture invariants

The canonical outer path is:

`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

- Fresh work is queued. Run Now enqueues with immediate-start policy; it never
  directly executes work.
- `NormalizedJobRecord` is the immutable, versioned executable envelope.
- `JobService.submit_njrs` is the application submission boundary.
- `PipelineRunner.run_njr` is the sole public production runner entry.
- `JobRepository` backed by SQLite owns immutable NJR snapshots and mutable
  lifecycle state; queue and history are repository projections. Do not create
  a second queue, history, lifecycle, cancellation, or process authority.
- Replay creates a new NJR identity with parent lineage on the same path.
  PromptPack identity exists only for PromptPack-sourced work.
- GUI captures intent and renders projections; it does not build backend
  payloads, mutate queue persistence, or call the runner. Controllers
  coordinate services; pipeline modules compile and execute typed work; backend
  details remain behind adapters.
- MVP execution is same-process and single-node. Production video backends
  are native SVD XT and the Comfy workflows the catalog marks `approved`
  (owner decision D2, 2026-10-20); an `experimental` workflow runs only with
  the job's own recorded opt-in, never a global switch. The approved set is
  stated in `docs/Subsystems/Video/VIDEO_PIPELINE.md` section 1.1.
- Do not add parallel job models, runner entrypoints, live legacy fallbacks, or
  compatibility layers without a named removal condition. Prefer deleting
  proven-obsolete compatibility code.

Material changes require Rob's approval and a coherent architecture update.

## 3. Product-owner and agent authority

Rob owns product intent, priorities, user-visible behavior, and approval of
material architecture or production decisions. Agents determine normal
technical discovery, implementation detail, testing, repair, documentation
impact, and PR preparation within an approved outcome. Stop for a decision
that would materially change behavior, data safety, runtime ownership,
compatibility, security, supported hardware/platform scope, or irreversible
shared external state.

Classify work as Narrow, Standard, or Architectural. If discovery proves a
higher class, stop and recommend escalation instead of silently broadening
scope. Every authored PR or bounded work package records its execution class, a
one-line **Model recommendation** (Claude Code and Codex model + effort per
`docs/AI_MODEL_SELECTION.md`, and a preferred host only when one materially fits
better), a Controller Surface Assessment when controller/coordinator code may be
touched, and a Token-Efficient Validation Plan. Prefer the largest coherent
package that shares one outcome, stays in understood architecture, and validates
together.

Stop for an owner decision when evidence reveals a choice that materially
changes product-visible behavior not resolved by the request, canonical runtime
ownership or an architecture invariant, user-data migration or deletion
semantics, compatibility policy, a security boundary, supported hardware or
platform scope, or irreversible shared state. Do not stop for file selection,
refactoring needed for correctness, test selection, implementation detail, or
repair of failures caused by the authorized change.

## 4. Ownership, determinism, and runtime safety

Use `docs/CODEX_MAP.md` to locate the relevant task surface (and the generated
`docs/CODE_MAP.md` to find any module), then inspect only
the implementation required for the approved outcome. `src/gui/` owns Tk
presentation, `src/gui_v2/` toolkit-neutral adapters/view models,
`src/controller/` coordination/lifecycle adapters, `src/pipeline/` compiler,
NJR, runner, and stages, `src/queue/` and `src/history/` execution-state
projections, `src/video/` typed video adapters, and `src/learning/`
post-execution consumption. `src/state/` remains tracked; `tools/` and
`scripts/` are not application-logic homes.

Keep GUI work non-blocking and marshal widget updates to the GUI thread. Avoid
import-time network, process, GPU/model, GUI-loop, or filesystem side effects.
Keep randomization and compilation deterministic for fixed inputs. Assess
ratcheted controllers instead of increasing a ceiling without explicit
architecture approval; lower the checked-in ceiling when a controller shrinks.

## 5. User-work and external-state protection

Inspect Git state before changing files. Use a short-lived branch and one
coherent work package; once branch/SHA/worktree and scope are verified, the
active coding session may create/switch to the authorized feature branch, edit,
validate, and commit locally without a separate Release session; preserve unrelated user changes, PromptPacks, generated
outputs, and untracked user data. Never reset, overwrite, or delete them.
Do not push, merge, rewrite history, delete remote state, publish, deploy, or
mutate secrets without explicit owner authorization (feature-branch publication
may be authorized in the initial package authorization). Auto Approve / Full
Access changes capability, not the scope of authorization.

**Protected actions** are integration or merge to `main` or another long-lived
target, force-push or history rewrite, tag/release, deployment, destructive
migration, secrets or credentials, and any other irreversible or shared action.
Each needs current explicit owner authorization naming the action and its
target; a repository policy may prescribe procedure or automation but cannot
authorize the action. Immediately before an authorized one, fail closed: the
authorization and target are unambiguous; local and remote refs, ancestry,
worktree and aggregate diff still match the accepted outcome and its
exclusions; required CI and verifier/security findings are still valid; unrelated
user work is preserved. On drift, missing evidence or ambiguity, stop and report.
Never force-push, choose an alternate ref, bypass CI, widen scope, or infer
authority. Feature-branch publication rechecks the exact HEAD and aggregate diff
the same way; an approved outcome authorizes its normal implementation file scope
without an owner file list, and unexpected changes stop publication.

StableNew may control lifecycle only for a process its appropriate process
manager launched and owns. An external A1111/Comfy process may use supported
API, health/progress observation, and A1111 interrupt/cancellation, but is
never adopted, terminated, killed, or restarted automatically; ambiguous
dispatched generation POSTs are never automatically replayed. Do not change
external hardware, GPU, firmware, model, backend, or configuration state unless
the approved work package explicitly authorizes that action.

## 6. Validation authority

`pyproject.toml` is the sole pytest configuration authority. Add deterministic
regression coverage when practical; use temporary state/artifact roots and no
real network, WebUI, model, GPU, or GUI display unless explicitly opt-in.
Start with focused validation, run `python tools/ci/run_pr_gate.py` when the
repository policy requires it, and treat the required GitHub Python 3.14 CI job
as the integration verdict. Never weaken tests, skip failures, or change
acceptance to obtain green results. Informational failures and unrelated debt
do not broaden the work package.

Reuse accepted exact-SHA evidence while relevant source is unchanged; docs-only
work does not invalidate source/runtime evidence. If a prescribed local tool is
missing, report a tooling blocker once rather than rebuilding unrelated
environments. Inspect the final scoped diff and run `git diff --check`.

After accepted implementation and before the next functional phase, verify the
exact SHA/diff and applicable validation/CI, decide whether canonical truth
changed, and update only affected authorities (`STATUS.md`, architecture,
roadmap, code map, testing guidance, or this file). Do not update docs merely
to narrate a commit.

## 7. Agent operating-model pointer

Product/engineering assessments start at [docs/assessments/README.md](docs/assessments/README.md):
Lightweight, Focused, or Comprehensive, with v1.2 critical-control and
method-diverse challenge requirements. Dated reports support decisions; they
do not supersede `STATUS.md` or authorize implementation or publication.

`docs/AGENT_OPERATING_MODEL.md` defines how work is done: the single-lane default
workflow (one primary Claude Code or Codex session; specialists optional),
worktree ownership, context and session policy, the review and repair protocol,
security triggers and PR-ready criteria. It adds procedure and never restates the
rules above. `docs/AI_MODEL_SELECTION.md` owns model/effort selection and the
calibration rule. Provider bridges such as `CLAUDE.md` and
`.github/copilot-instructions.md` point to this root contract; they do not
replace it. Provider-specific orchestration is an implementation detail, not a
repository authority.

## 8. Completion report

Keep it concise: outcome, branch/SHA, evidence, architecture effect, unresolved
risk, and the next decision if one remains, plus one `Model / usage` line (host,
actual model, effort, repair passes, result, and the tokens measured by
`tools/usage_report.py`). Never estimate a missing value or convert tokens to a price.
