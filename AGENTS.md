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
- MVP execution is same-process and single-node. Native SVD XT is the only MVP
  video backend.
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
scope. Every authored PR or bounded work package records an
**Execution Profile + Model/Reasoning Recommendation**, a Controller Surface
Assessment when controller/coordinator code may be touched, and a
Token-Efficient Validation Plan.

## 4. Ownership, determinism, and runtime safety

Use `docs/CODEX_MAP.md` to locate the relevant task surface, then inspect only
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
coherent work package; preserve unrelated user changes, PromptPacks, generated
outputs, and untracked user data. Never reset, overwrite, or delete them.
Do not push, merge, rewrite history, delete remote state, publish, deploy, or
mutate secrets without explicit owner authorization.

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
repository policy requires it, and treat required GitHub Python 3.11/3.12 CI as
the compatibility verdict. Never weaken tests, skip failures, or change
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

`docs/AGENT_OPERATING_MODEL.md` defines delivery roles, worktree ownership,
checkpoint/stop discipline, evidence reuse, security/release triggers, and
PR-ready criteria. Provider bridges such as `CLAUDE.md` and
`.github/copilot-instructions.md` may point to this root contract; they do not
replace it. Provider-specific orchestration is an implementation detail, not a
repository authority.
