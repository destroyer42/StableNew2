# VID-RES-350 — Advisory memory pressure at Video Workflow admission

## Execution Profile + Model/Reasoning Recommendation

- **Class:** Standard; local, bounded readiness-policy change in the existing Comfy Video Workflow path.
- **Model recommendation:** Codex GPT-6.1 Sol High / Claude Code Sonnet 5.5 High; known architecture with interacting admission,
  execution and GUI contracts warrants enough effort to avoid safety-check and retry regressions. Keep the current host and
  acquired context. Expected usage: about 2M cached-input and 20k output tokens. No delegation needed.
- Start: clean `main` at `d68b477ba89ae6c5b88fe2e985defed35fcc9196`; remote `main` independently verified at the same SHA.
- Worktree: `C:/Users/rob/qual/StableNew-vidres350`; branch `codex/vid-res-350-advisory-memory`.
- Session: `codex:01a18f9e-df55-7ae1-b265-aef94dd3b5bd`. Session metadata starts at
  `2026-10-30T21:41:56.265-04:00`. A separate pre-discovery measurement boundary was not recorded, so closeout usage is
  labelled as a session window rather than claiming a compliant exact package total. End boundary is reported at closeout.
- Authorities: `AGENTS.md`, `STATUS.md`, `docs/CODEX_MAP.md`, `docs/AI_MODEL_SELECTION.md`, `docs/AGENT_OPERATING_MODEL.md`,
  `docs/CODEX_WORK_PACKAGE_TEMPLATE.md`, Video pipeline sections 1.1/4/7.1, and Testing/CI guidance.

## Controller Surface Assessment

No controller code or controller ceiling changes. The existing Video preflight mixin and GUI queue gate consume the same
preflight contract; the new advisory state never enters `WorkflowPreflight.blocking`. The runtime transition coordinator has
only a corrected policy comment. Its process ownership, handoff and release behavior are unchanged. The large GUI controller
does not grow. No lifecycle, queue, scheduler, executable-envelope or architecture invariant changes.

## Outcome and scope

- RAM is measured against the unchanged published qualification threshold, with a serialized advisory when low. It gates
  neither admission nor cold/warm execution. The 1.5 GB admission startup deduction is removed.
- Preflight GPU pressure/unreadable-driver evidence is advisory. The existing driver-based GPU check still fails closed
  after runtime handoff and Comfy startup, before prompt dispatch. Queueing reserves no memory.
- Setup, dependency and per-job governance requirements stay enforced. Existing runtime managers alone release owned
  conflicting processes; external processes stay untouched.
- Readiness observations/advisories are logged before allocation and retained in successful execution diagnostics. Comfy
  history exception type/message is retained in failed-job reporting. No retry, fallback or ambiguous prompt replay.
- Published specs, pinned graphs/hashes, frozen NJRs and replay identity stay unchanged. All admission paths use the existing
  builders and `JobService.submit_njrs`.
- Exclusions: physical GPU/model work, runtime launches/restarts/qualification, installation, workflow changes, push, PR or merge.

## Token-Efficient Validation Plan

1. Fake RAM/GPU probes cover 0.5/4/8/15 GB, warm/cold loads, low/unreadable driver figures and misleading Comfy estimates.
2. Real coordinator with fake runtime managers proves owned Forge release, post-start measurement and external-runtime refusal.
3. GUI/session tests prove visible advisories, enabled Queue and submission feedback; SQLite integration proves all four
   admission pathways and allocation failures without duplicate prompt dispatch. Existing pinned-version/replay tests cover
   unchanged historical identity; dependency, launch-flag, governance, lifecycle and transport tests guard the retained refusals.
4. Run focused/adjacent tests, then `python tools/ci/run_pr_gate.py` once near closeout. Use the existing Python 3.14 repository
   environment and writable temporary roots; do not rebuild an unrelated environment. Review aggregate diff and `git diff --check`.
5. Required hosted Python 3.14 CI remains the integration verdict; no hosted verdict for an unpublished local commit is implied.

The initial interpreter lacked pytest; the existing repository `.venv` supplies the pinned tools. The first test setup was
blocked by sandbox numbered-temp-directory permissions; an explicit writable `--basetemp` resolved it. The initial focused
run exposed a missing motion prompt in the new GUI test and an existing default-probe test reading ambient launch/host facts;
the fixture now supplies the prompt and fakes those facts. No acceptance assertion or production safety guard was weakened.

## Documentation and stop conditions

`VIDEO_PIPELINE.md` changes because resource interpretation and operator feedback changed. `STATUS.md`, roadmap, code map,
testing authority and repository rules need no narrative update. Stop for an unexpected lifecycle/architecture decision,
scope or safety-boundary expansion, or more than two independent source failure classes. One batched repair/reverification
cycle for confirmed in-scope findings; unrelated failures do not expand the package. Publication remains separately authorized.

## Validation and review evidence

- Focused run: **127 passed**. Extended adjacent run: **425 passed, 2 skipped**, plus one older lifecycle test still
  asserting that low RAM must refuse the second/third resident-runtime jobs. Updated that assertion for this package's
  authorized behavior; the complete affected lifecycle/frame-count module then passed **37 tests**. All adjacent test
  nodes now have passing evidence. The skips are host symlink permission and the opt-in external qualification graph.
- `run_pr_gate.py` was invoked once. Completeness, controller surface, Ruff, mypy smoke/ratchet, Ruff/architecture ratchets
  and controller Tk boundary passed. Collection's pollution guard correctly caught the lifecycle-test edit made while it
  was running. With the files held stable, collection passed: **14,894 tests collected**, repository unchanged.
- The remaining required smoke first hit sandbox `WinError 10013` at a test-owned fake HTTP socket. Re-running that step
  with sandbox escalation passed: **358 passed, 1 non-failing warning**, repository unchanged. No real runtime or GPU was used.
- Final aggregate review and `git diff --check` passed. Controllers did not grow; coordinator behavior is byte-for-byte
  unchanged apart from its docstring. Published catalog/spec files and NJR builders have no diff. No unresolved in-scope
  correctness finding. This is local component evidence; hosted Python 3.14 CI and the full census were not run.
- Logs: `C:/Users/rob/qual/vidres350-focused.log`, `vidres350-adjacent.log`, `vidres350-reverification.log`,
  `vidres350-pr-gate.log`, `vidres350-collection.log`, `vidres350-required-smoke-unsandboxed.log` (all in the same qual folder).
- Closeout remote `main` remains `d68b477ba89ae6c5b88fe2e985defed35fcc9196`. Main worktree is clean and unchanged.

## Changed files

- Readiness: `src/video/workflow_readiness.py`, `src/video/workflow_preflight.py`.
- Feedback/diagnostics: `src/gui/view_contracts/video_runtime_readiness_contract.py`,
  `src/gui/views/video_workflow_runtime_strip_v2.py`, `src/video/comfy_workflow_backend.py`.
- Coordinator policy comment only: `src/services/runtime_transition_service.py`.
- New coverage: `tests/video/test_pr_vid_res_350_memory_policy.py`,
  `tests/integration/test_pr_vid_res_350_failure_reporting.py`.
- Updated acceptance: `tests/video/test_pr_vid_ux_311_preflight.py`, `tests/video/test_pr_vid_ux_340_comfy_setup.py`,
  `tests/video/test_wan22_experimental_workflow.py`, `tests/video/test_pr_vid_seq_330_backend.py`,
  `tests/video/test_pr_vid_190_comfy_lifecycle_frame_count.py`, `tests/gui_v2/test_pr_vid_ux_311_runtime_strip.py`,
  `tests/gui_v2/test_pr_vid_ux_340_comfy_setup_ui.py`.
- Documentation: `docs/Subsystems/Video/VIDEO_PIPELINE.md` and this bounded package record.
