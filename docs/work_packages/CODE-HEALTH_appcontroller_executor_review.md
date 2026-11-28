# CODE-HEALTH: AppController and executor design review

Status: design review merged (PR #516, 2026-11-28). The owner approved slices 1-6 now and 7-8 later, and decided
roadmap decisions 12 and 14 (section 12). The section 8 defects are fixed by the CODE-HEALTH bug-fix package
(section 13). No refactor slice is implemented yet.

Execution class: Architectural assessment (read-only). Model: Claude Code, Opus 5.5, high effort, with two read-only
search subagents for caller and test mapping. This is a single-model assessment with explicit self-critique
(section 9). It is not an independent second-model review.

Canonical path, unchanged by every slice below:
`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`.

## 1. Start state and evidence limits

- Repository: StableNew. Worktree `claude/distracted-swanson-ee2f7e` at `85a59f91` (= `origin/main` at task start,
  2026-11-28T09:00-05:00). Clean tree.
- Sizes at that SHA: `src/controller/app_controller.py` is 4,749 physical lines, exactly its ceiling in
  `tools/ci/controller_surface_baseline.json` (`STATUS.md` still says about 5,010; the ceiling has since come down).
  The file has about 287 methods. `src/pipeline/executor.py` is 6,004 lines, and no size ratchet covers it.
- Last 30 days: the controller lost about 2,070 net lines (+252 / -2,319, 23 commits) and the executor lost about 540
  (+475 / -1,016, 16 commits). Both are shrinking. This plan speeds that up; it does not reverse a trend.
- Method: an outline of both files, grep for callers and tests (counts are file counts and are approximate where names
  collide; `PipelineController` defines many of the same names), and direct reads of the hot spots. I spot-checked every
  claim marked "verified". Line numbers are at `85a59f91`.
- Not done: no tests were run (read-only review), no runtime tracing, no coverage measurement. "Dead" means no caller
  in `src/` was found by grep, including `getattr` strings. A dynamic caller I could not see would show up when the
  slice's tests run.

## 2. The decision

Decide whether and how to split the two largest objects without breaking the canonical path, and give the order. The
criteria are, in order: no change in behaviour; risk that the characterization tests can contain; operator value (fewer
silent defects, cheaper new model families); then line-count ratchet movement.

## 3. AppController: what it holds today

`AppController` is the Tk host's facade. GUI views, `src/gui/presentation_actions.py`, `src/app_factory.py:65` (its
only construction site) and the shutdown coordinator call it. It already delegates most of its logic to
`src/controller/app_controller_services/*`, `PipelineController`, `JobService` and the video controllers. Much of the
file is forwarding shims and leftovers.

| # | Cluster | Lines | Main outside callers | Tests (files) | Verdict |
|---|---|---|---|---|---|
| A1 | Module types: `LifecycleState`, `RunMode`, `RunSource`, `RunConfig`, `DeprecatedPipelineConfigSnapshot`, `AppState`, `CancelToken` | 190-320 | `CancelToken` only (TYPE_CHECKING import, `pipeline_runner.py:77`) | 7 | `CancelToken` duplicates `src/controller/runtime_state.py:32`. `require_stop_to_finish` / `needs_stop_to_finish` have no caller. Dead or duplicated |
| A2 | `__init__`, which sets 83 attributes | 362-707 | `app_factory.py:65` | ~108 import the class | Builds about 14 collaborators. It does not build `JobService`, which comes from `PipelineController` via `assemble_runtime_stack` (`pipeline_controller.py:679`). But it patches `queue._history_store` (662-673) and private `PipelineController` flags (564-566). Stays, and shrinks as clusters leave |
| A3 | UI dispatch and debounce (`_ui_dispatch`, `_run_in_gui_thread`, `_mark_ui_dirty`) | 711-906 | 5 GUI/controller modules call the private `_ui_dispatch`; 3 call `_run_in_gui_thread` | 28 | Real and central. `_wrap_ui_callback` has a second inline copy at 2364. Belongs in a small `UiDispatcher` port |
| A4 | Runtime status throttle and cache | 907-1121 | `pipeline_controller`, `watchdog_system_v2` | 4 | Publishing already lives in `RuntimeProjectionCoordinator`; the throttle could join it |
| A5 | Resource lists, profiles, learning hooks, watchdog | 1122-1276 | stage cards, `app_factory`, `main_window_v2` | ~43 | Forwards to `WebUIResourceService`, `GenerationProfileController`, `learning_completion_router`. Leave alone |
| A6 | Run submission and preview queue | 1277-1670 | `preview_panel_v2`, `site_connection_dialog`, `run_submission_service.py` (calls back into private methods) | 28 | Mostly shims over `QueueRunSubmissionService`. `_build_stage_plan_config_for_tests` (1329-1403, verified) runs in production on every run through `_capture_stage_plan_for_tests` (1405-1415, 1437, 1546) and swallows all errors: a test seam in the run path. `on_run_job_now_v2` (1552-1571) uses `__func__` identity checks to detect test overrides |
| A7 | Reprocess, review, photo optimize, image edits | 1671-2264 | review tab, guided reprocess, photo optimize, history replay. Six GUI/learning modules call the **private** `_build_reprocess_config` and `_extract_reprocess_baseline_from_image` | 35 | `_build_reprocess_config` (2108-2263, about 155 lines, two near-identical branches, hard-coded ADetailer prompts) has no home elsewhere. It belongs beside `src/pipeline/reprocess_builder.py` as a pure function. `on_submit_image_edits` and `on_optimize_photo_assets` have no `src` caller |
| A8 | GUI attach, queue callbacks, queue projection, history | 2265-2639 | `app_factory`, `shutdown_coordinator`, `runtime_projection_coordinator` | 25 | Handlers are 1-5 line forwards. Both controllers register queue callbacks on the same `JobService` (here at 2351; `PipelineController` at 1012, gated by "managed externally" flags) |
| A9 | Queue commands (move, remove, clear, pause, resume, cancel, auto-run, send) | 2640-2836 | `queue_panel_v2`, `running_job_panel_v2`, `main_window_v2` | 20 | **Duplicated in `PipelineController` (about 1200-1299).** Pause, resume and send already forward to it (2746, 2750, 2812); the rest reimplement it |
| A10 | Settings, lifecycle, status, log, diagnostics, error handlers | 2837-3140 | `main_window_v2`, `presentation_actions`, debug hub | ~56 | `_validate_pipeline_config` (DEPRECATED) and `_set_validation_feedback` are used only by `on_run_clicked`. The rest forwards to the diagnostics services |
| A11 | Legacy run path, last-run restore, stage visibility | 3141-3344 | `main_window_v2` (`on_run_clicked`), sidebar, `generation_profile_controller` | 16 | **`_run_pipeline_via_runner_only` (3141-3156) is dead (verified: no caller; it always raises).** `_get_pipeline_tab_*` are test-only |
| A12 | Stop, help, refresh, shutdown hooks | 3345-3445 | header buttons (`main_window_v2.py:1377`), `shutdown_coordinator` | 12 | **`on_stop_clicked` does nothing in production (verified: it returns unless `state.lifecycle == RUNNING`, and nothing in `src` sets RUNNING).** The header Stop button only logs "not running". This is a defect, not dead code; see section 8 |
| A13 | Packs, config, resource dropdowns, stage cards, ADetailer/randomizer/LoRA | 3446-4338 (about 890 lines) | `sidebar_panel_v2`, `randomizer_panel_v2`, `base_generation_panel_v2`, `pipeline_tab_frame_v2`, 8 learning/model-evidence modules call `get_current_global_prompt_policy` | 57 | The largest cluster and the most Tk-coupled: it reads widgets through `_get_sidebar_panel`, and `lb.curselection()` at 3453. It belongs behind a view contract. Dead or test-only: `load_packs`, `_update_gui_dropdowns`, `update_config`, `get_available_models`, `_build_pipeline_config` with `DeprecatedPipelineConfigSnapshot`, `_get_active_prompt_text`, `_resolve_prompt_from_pack` |
| A14 | Thin queue aliases (`on_add_job_to_queue`, `on_run_job_now`, `on_pause_queue`...) | 4339-4410 | only `on_cancel/pause/resume_current_job` (`running_job_panel_v2.py:493-511`) | 5 | Four aliases have no `src` caller; `on_run_queue_now_clicked` has none at all. `on_add_job_to_queue` builds a non-NJR `Job(payload=...)` (4059). `on_pause_current_job` pauses the queue, not the job |
| A15 | Video, SVD, movie clips, character training | 4411-4749 (about 340 lines) | SVD, video workflow, movie clips, character training tabs, job history, storyboard | 44 | Mostly forwards to `SVDController`, `svd_submission_service`, `VideoWorkflowController`, `MovieClipsSubmissionService`. `submit_character_training_job` (4477-4511) compiles the training job inline. Belongs in a video actions facade |

Likely bugs found along the way (all verified by reading; none is in scope for a refactor slice; see section 8):

- 3647 logs `{field}` (the imported `dataclasses.field`) instead of `field_name`.
- 3653 passes `getattr(self, "config_manager", None)`, but the attribute is `_config_manager` (455). So
  `read_current_policy` never falls back to the saved global prompt policy when the sidebar returns nothing.
- 4426 reads `getattr(self, "output_dir", None)`, which is never set. Movie clips always use `"output"` and ignore the
  configured output folder (the pack path uses `_config_manager.get_setting("output_dir", ...)` at 4158).

## 4. Executor: what it holds today

`Pipeline` is the WebUI-family stage executor. The only way in from the runner is `PipelineRunner._execute_image_backend`
(`pipeline_runner.py:1613`) -> `backend.execute(self._pipeline, request)` (1684) -> `WebUIFamilyImageBackend.execute`
(`src/image_backends/webui_family_backend.py:275`) -> `run_txt2img_stage` / `run_img2img_stage` / `run_adetailer_stage`
/ `run_upscale_stage` (298-345). SVD comes through `SVDNativeBackend.execute` -> `run_svd_native_stage`
(`svd_native_backend.py:42`). Comfy and Diffusers bypass the executor; they borrow only `_emit_status_update`. 79 test
files import the executor, 14 of them `tests/pipeline/test_executor_*.py`.

| # | Cluster | Lines | Outside callers | Tests (files) | Verdict |
|---|---|---|---|---|---|
| E1 | Module helpers (payload sanitize/validate, HTTP-500 signature, WebUI tail) | 121-286 | none | 2-3 | Stays. `PipelineStageError` has no `src` importer |
| E2 | `__init__` and run metrics | 288-407 | runner (`_begin_run_metrics`, `get_run_efficiency_metrics`, `take_*`); `forge_webui_backend.py:719` calls private `_record_vae_switch` | 9 | Stays. `_model_discovery_attempted` is never read again |
| E3 | Prompt optimizer, stage policy, sidecars | 408-582 | none | 2-5 | A thin wrapper over `src/prompting`; the optimizer construction is copied twice (408, 498). Low value to move |
| E4 | Manifest, metadata, provenance, naming | 583-871 | — | 2-5 | **Duplicated.** The manifest/metadata/collision-safe-name/stage-history block repeats in every stage body (metadata builder at 3944, 4107, 4697, 5173, 5857; manifest at 3998, 4756, 4860, 5203, 5877; collision names at 3855, 3995, 4667, 5113, 5200, 5726, 5874, all verified). `comfy_image_backend.py:1014-1075` and `diffusers_backend.py:512-621` reimplement it again. Belongs in a shared stage artifact writer |
| E5 | Progress and status emission | 872-963 | `_emit_status_update` via `getattr` from the Comfy, Diffusers and Comfy video backends | 3 | Stays. `set_progress_controller` is reached only through `CoreController.set_pipeline`, which nothing in `src` calls, so the `progress_controller.report_progress` paths (3742, 4521) are probably dead (unverified) |
| E6 | Model, VAE, modules, hypernetwork, drift | 964-1129, 1820-1925 | the Forge backend reimplements the module-set write and verify (`forge_webui_backend.py:695-722`) | 15-20 | The Forge `additional_modules` (Klein) path at 1002/1037 sits in generic code. `_webui_defaults_applied` claims "once per run" but is once per `Pipeline` lifetime |
| E7 | Runtime pressure, admission, soft recovery, launch policy | 1130-1819 (about 690 lines) | none (`outpaint_canvas.py:103-115` mirrors `_assess_stage_pressure`, guarded by a parity test) | 21 for admission | **A copied preamble.** The same pressure, launch, admission and drift sequence appears four times (ADetailer 3320-3344, txt2img 4179-4195, upscale 5510-5540 and 5665-5700). **img2img (4889) has none.** Family branching: `"sdxl_guarded"` at 1766-1795, the SDXL-class reason at 1157, and three different load formulas (executor 1145, `app_config.py:588-626`, outpaint). Belongs in a runtime-admission collaborator in `src/pipeline` |
| E8 | Cancel, stage events, recovery, WebUI readiness and health | 1926-2296 | `_ensure_not_cancelled` is reimplemented in `pipeline_runner.py:1771`, `svd_runner.py:512`, `svd_service.py:218` | 13-20 | `reset_stage_events` / `get_stage_events` have no `src` caller (test-only, verified). `_record_stage_event` appends on every stage and nothing clears it, so `_stage_events` grows for the life of the process (verified). WebUI restarts come from here (the poll thread) and from `webui_outage_coordinator`: two restart authorities |
| E9 | Generation dispatch, recovery and progress polling | 2297-3061 (`_poll_progress_loop` 2544-2940, about 400 lines) | none | 19-22 | The most thread-heavy code; see section 5. Belongs in a `GenerationDispatcher` class in `src/pipeline` once characterization tests are in place |
| E10 | Aesthetic, sampler, ETA helpers | 3062-3204 | none | 1-3 | **`_format_eta` (3182) is dead (verified).** The live copy is `running_job_panel_v2.py:258` |
| E11 | Stage bodies: `run_adetailer` 3205-4020 (+ **unreachable 4021-4122, verified: a stray "Run upscaling" body after `return None`**); `run_txt2img_stage` 4124-4888; `run_img2img_stage` 4889-5239; `run_svd_native_stage` 5240-5375; `run_upscale_stage` 5376-5933; `run_adetailer_stage` 5933-6004 | the WebUI and SVD backends | 6-33 each | Each body repeats cancel -> status -> model/VAE -> preflight -> payload -> dispatch -> cancel -> artifact write. **Family branches inside generic txt2img:** Z-Image 4211-4231, 4523-4527, 4590-4592; SDXL refiner 4257-4320, 4465-4492; Flux1 wire projection 4523; Forge ControlNet/OpenPose 4531-4537. These are lazy imports from `src/image_backends`, so the dependency runs both ways. **Upscale "single" mode calls `self.client.upscale_image` directly (5705, verified)**, outside `_generate_images_with_progress`; the bug-fix package found this deliberate (section 13) |

Counts at `85a59f91`: `zimage` appears 12 times, `refiner` 45, `sdxl` 8, `svd` 21, `flux` 2, `klein` 1; `.get(` appears
463 times (P4-4's typed-settings target is to halve it).

## 5. Coupling that makes the split hard

AppController:

- **Half-built test controllers.** 34 test files construct `AppController` with `__new__` and skip `__init__`. The file
  defends this with 103 `getattr(self, "...")` lookups and 30 `hasattr(self, ...)` lazy inits (for example 1067-1076).
  Moving a method into a collaborator that `__init__` builds breaks every half-built controller that calls it. This is
  the main reason a naive split fails, and slice 1 deals with it first.
- **Test-override detection by identity.** `on_run_job_now_v2` compares `__func__` against `AppController.on_run_now`
  and `AppController.start_run_v2` (1552-1571). Moving or wrapping those methods silently changes which path runs.
- **Two controllers on one `JobService`.** `PipelineController` receives `app_controller=self`. Both register queue
  callbacks on the same service, gated by private "managed externally" flags that AppController sets on
  `PipelineController` (564-566). A9's queue commands exist in both.
- **Callbacks both ways.** `run_submission_service.py` holds and calls private AppController methods
  (`_submit_preview_jobs_to_queue_async`, `_capture_stage_plan_for_tests`). Six GUI/learning modules call the private
  reprocess builders; five call the private `_ui_dispatch`.
- **Tk without a tkinter import.** `root.after` through `getattr` (766-777), `run_in_main_thread(_later)` (686, 721,
  786), `lb.curselection()` (3453), `notebook.select` (4575), four GUI imports (132, 133, 596, 3882; baseline
  `controller_gui_imports: 4`). Thread-affinity checks with `threading.get_ident` (383, 716, 749, 3651): for example
  `get_current_global_prompt_policy` reads the Tk sidebar only on the UI thread and returns a cached projection
  elsewhere.
- **Threads and locks.** Tracked threads via the registry: RunQueueSubmit (1441), movie clips (4427), the diagnostics
  read model (520), plus one daemon ShutdownWatchdog (3432; baseline `daemon_threads: 1`). `_runtime_status_lock` is a
  leaf lock: nothing is called while it is held (1079-1102, verified). `_last_runtime_status` is read and cleared
  outside it (1002, 1014), which is benign today because only the UI thread writes it. Crash-bundle building borrows
  `_diagnostics_read_model.lock` (3057). AppController never holds its own lock while calling the queue, so it does
  not take part in the queue's `_transition_lock` -> `_lock` order. Keep it that way.

Executor:

- **Per-run state on a long-lived object.** The runner writes `_current_stage_chain`, `_current_stage_index`,
  `_current_job_id`, `_current_njr_sha256`, `_current_pack_block`, `_provenance_incomplete` and `_status_callback`
  directly from outside (`pipeline_runner.py:923-924, 996, 1168, 1310-1314, 1689`). Cross-run caches (`_current_model`,
  `_current_vae`, `_current_modules`, `_current_hypernetwork`, `_true_ready_gated`, `_webui_defaults_applied`,
  `_last_recovery_time`) are never reset per run. Any extracted collaborator has to receive this state explicitly, not
  reach back into `self`.
- **The poll thread.** Each `_generate_images_with_progress` call (2963-2971) creates three Events and a one-worker
  `ThreadPoolExecutor` running `_poll_progress_loop`. Teardown in `finally` (3047-3060) waits up to 1 s, then shuts
  down with `wait=True`. From that worker thread the loop calls `client.get_progress`, `client.interrupt`,
  `manager.restart_webui` (2610: a process restart started off the calling thread) and the status sink. The main path
  reads `_active_managed_stall_escalation` and `_dispatch_cancel_token`, which are assigned just after `submit`
  (2984-2985), so there is a tiny window. `_progress_lock` guards writes of two fields; one is never read and the other
  is read without the lock. It is effectively vestigial, but removing it is a behaviour question, not a refactor.
- **Private access from the backends.** The WebUI backends shape the config, then call `run_*_stage`, and poke
  `_image_performance`, `_record_vae_switch` and `client`. The executor lazily imports Forge profile modules back
  (4211-4537).
- **No Tk.** No tkinter imports; `tests/safety/test_controller_core_no_gui_imports.py:11` pins it.

## 6. Alternatives considered

1. **Minimal: delete and deduplicate only.** Remove the dead code and collapse the copied blocks, keep the two files.
   Cheap and safe, but it leaves the Tk-coupled pack/config cluster and the thread-heavy dispatch in place.
2. **Recommended: staged extraction into existing homes.** Collaborators go where the architecture already wants them
   (`app_controller_services`, a view contract, `src/pipeline` collaborators, `reprocess_builder`), each one PR with
   characterization tests first, and the public method names stay as one-line forwards until their GUI callers move.
3. **Big bang: rewrite AppController as several controllers and move the executor into `image_backends/webui/` now.**
   Rejected: the 34 half-built test controllers, the identity checks and the family branches make one large change
   unreviewable, and the move needs decision 14 (section 10).

## 7. The staged plan

Each slice is one PR, behaviour-preserving, and adds characterization tests before moving anything. Every slice runs
the focused tests named, then the PR gate on the final tree (and `tests/system` plus `tests/tools` when it adds a
`src` module, per the PR-gate census rule). Every slice that shrinks `app_controller.py` lowers its ceiling in
`tools/ci/controller_surface_baseline.json`, which the checker requires. Sizes are estimates.

Ordered by value over risk:

| # | Slice | Move | Size | Risk | Tests that pin it first | Ratchet effect |
|---|---|---|---|---|---|---|
| 1 | **Dead code out, test seams in** | Add one `make_test_app_controller()` fixture so tests stop building half-initialized controllers (migrate the 34 `__new__` sites, or as many as the slice touches). Delete: executor unreachable 4021-4122, `_format_eta`, `_model_discovery_attempted`, `reset/get_stage_events` with the unbounded `_stage_events` list (tests move to the runner's `stage_events`); controller `_run_pipeline_via_runner_only`, `DeprecatedPipelineConfigSnapshot` with `_build_pipeline_config`, `_get_active_prompt_text`, `_resolve_prompt_from_pack`, the unused `CancelToken` methods, `_update_gui_dropdowns`, `on_run_queue_now_clicked`, the four test-only queue aliases (tests retargeted to the `_v2` names). Leave `_capture_stage_plan_for_tests` to slice 3 | -400 controller, -150 executor | Low | Retargeted alias tests; a grep test that the deleted names have no `src` reference; the existing executor suites | Controller ceiling about 4,350 |
| 2 | **One stage artifact writer** | Extract the manifest + metadata builder + collision-safe name + stage history block (E4, repeated in 5 bodies) into `src/pipeline/stage_artifact_writer.py`. The executor calls it; Comfy and Diffusers adopt it in a later PR | -300 executor, +150 new module | Medium (provenance: P3-5 "never lost silently") | Golden snapshots of manifest JSON and PNG metadata per stage with the fake client, taken before the move; `provenance_incomplete` tests | Executor -300 net; consider an executor ceiling (decision 15) |
| 3 | **Queue commands have one owner** | A9 + A14: AppController's queue commands become one-line forwards to `PipelineController`, which already owns pause, resume and send. Move `_build_stage_plan_config_for_tests` out of the production run path into a test helper, keeping the `validate_stage_plan` call | -250 controller | Low-medium (`running_job_panel_v2` tries names in order) | A parity test: each AppController command and its `PipelineController` twin produce the same queue state and saved queue file; `test_app_controller_queue_control_150`, `test_queue_operations_v2` | Controller ceiling about 4,100 |
| 4 | **Reprocess config is a pure builder** | Move `_build_reprocess_config` and `_extract_reprocess_baseline_from_image` (A7) to public functions beside `src/pipeline/reprocess_builder.py`. Point the six GUI/learning callers at them. This feeds `ReprocessJobBuilder`; it is not a second compiler | -300 controller | Medium | Golden config snapshots for a fixture set of images (each branch, each stage combination) taken before the move; `test_review_batch_200`, `test_app_controller_reprocess_review_tab`, `test_photo_220` | Controller ceiling about 3,800 |
| 5 | **Runtime admission collaborator** | Move E7 (pressure, admission, soft recovery, launch policy, about 690 lines) into `src/pipeline/runtime_admission.py`. Collapse the four copied preambles into one call. img2img stays without it and upscale single mode keeps its direct call (behaviour-preserving); both become owner questions (section 8) | -750 executor, +600 new module | Medium-high (21 admission test files) | The existing admission and pressure tests, plus a per-stage "preamble call sequence" characterization test with a recording fake, taken before the move | Executor -150 net and much smaller methods; mypy count for the file should drop |
| 6 | **Video actions facade** | A15 (SVD, video workflow, movie clips, character training, about 340 lines) moves into `app_controller_services/video_actions.py`. AppController keeps one-line forwards until the 8 GUI tabs move to the facade in a follow-up | -250 controller | Low-medium | `test_app_controller_svd`, `test_svd_tab_frame_v2`, `test_history_media_projection`; a forward-parity test | Controller ceiling about 3,550 |
| 7 | **Pack and stage-card state behind a view contract** | A13 (about 890 lines): the logic that reads and writes sidebar, stage-card, ADetailer, randomizer and LoRA state moves into a `src/gui/view_contracts/pipeline_config_contract.py` owned by the GUI, with the controller keeping only pack load/apply orchestration. Removes `lb.curselection()` and the `DropdownLoader` import from the controller | -600 controller | High (57 test files, Tk widgets, UI-thread affinity) | Characterization of pack load -> apply -> fingerprint (`working_settings_fingerprint`) -> queue NJR config for 3 packs, captured before the move; the sidebar and randomizer panel tests | Controller ceiling about 2,950; `controller_gui_imports` 4 -> 3 |
| 8 | **Generation dispatcher** | Move E9 (`_generate_images*`, `_poll_progress_loop`, about 760 lines) into `src/pipeline/generation_dispatcher.py`, which owns the poll worker, the three Events and the stall/cancel state, and receives per-run state explicitly | -760 executor, +700 new module | High (threads, WebUI restart from the worker) | `test_executor_progress_polling`, `test_pr_harden_009_r1d_managed_stall_policy`, the r1a/r2 cancellation tests, `test_adetailer_progress_semantics`, plus a new deterministic fake-clock test of stall -> interrupt -> restart ordering, taken before the move | Executor about 4,150 after slices 1, 2, 5, 8 |

After all eight slices: AppController about 2,950 lines (the roadmap's Phase 4 exit was under 4,000) and the executor
about 4,150 (the exit was under 3,000; the rest needs the family-branch work under decision 14). Moving code does not
shrink the app. The net reduction across the repository is roughly 1,000-1,300 lines (dead code plus the
deduplication in slices 2, 3 and 5). The point of slices 4-8 is ownership and testability, not a smaller line total.

Not in this plan, and gated on decision 14 / P4-5: moving the Z-Image, Flux1, SDXL-refiner and ControlNet branches
out of `run_txt2img_stage` into backend profile hooks.

## 8. Findings to raise as separate packages (not refactors)

These change behaviour, so they are kept out of the refactor slices. Each needs a bug or owner-decision package:

1. **The header Stop button does nothing** (A12). Production never sets `LifecycleState.RUNNING`, so
   `on_stop_clicked` only logs. Operators cancel from the running-job panel. Decide whether Stop should cancel the
   running job, or remove the button.
2. **The global prompt policy fallback never runs** (3653, `config_manager` vs `_config_manager`).
3. **Movie clips ignore the configured output folder** (4426).
4. **img2img has no pressure/admission/drift preamble**, and **upscale single mode skips the generation gate** (5705).
   Either may be deliberate; neither is documented. (Resolved in section 13: img2img was an omission and is fixed;
   upscale single mode is deliberate and now says why.)
5. **`_stage_events` grows for the life of the process** (slice 1 deletes it with its test-only readers; if the owner
   prefers to keep it, it needs clearing in `_begin_run_metrics`).
6. **Two WebUI restart authorities** (the poll thread and `webui_outage_coordinator`).
7. 3647 logs the wrong variable (cosmetic).

## 9. Self-critique

- **Weakest assumption: grep finds every caller.** The file uses `getattr` heavily, and GUI code tries method names in
  order (`running_job_panel_v2.py:493-511`). Mitigation: slice 1 adds a test asserting no `src` string reference to each
  deleted name, and every deletion runs the full GUI test lanes. If a dynamic caller turns up, the method stays.
- **The line estimates may be optimistic.** Forwards and imports add lines back. The ratchet lowers only to the
  measured size, so an optimistic estimate costs nothing.
- **Slice 7 may not be worth its risk.** It is the largest controller win, but the most Tk-coupled. If its
  characterization test cannot be written cheaply, stop after slice 6 and take the controller to about 3,550.
- **The executor may move anyway (decision 14).** Slices 2, 5 and 8 create collaborators in `src/pipeline` that are
  backend-neutral (the artifact writer is also needed by Comfy and Diffusers), so they stay put if the executor moves.

## 10. Roadmap decisions 12 and 14

**Decision 12, a durable CANCELLING status: recommend no; show a non-durable "stopping" state instead.**

- Evidence: a plain cancel commits CANCELLED before the runner is signalled (`job_service_shutdown.py:86-89` calls
  `cancel_job` -> `mark_cancelled`, then `signal_runner`). So the status says CANCELLED while generation may still be
  running. `QUEUE_AND_RUNTIME.md` B10 item (3) records this as the one open part of P3-6.
- But the harm is only in what is displayed. One worker thread claims the next job only after `run_njr` returns
  (`single_node_runner.py:643-656`), so a cancelled job never overlaps the next one on the GPU. Return to queue is
  already gated on dispatch evidence.
- A durable status touches `JobStatus` (five values, `job_model.py:32`), the repository transition table
  (`job_repository.py:71-82`), SQLite history, the batch projection, the phone gateway's sync contract and every
  "terminal status" set. That is a schema and contract change for a display problem.
- Cheaper fix: the runner already exposes `is_cancel_requested()` (`single_node_runner.py:881`). Show the running row
  as "Stopping..." until the worker settles. That is a projection change with no schema change, and it fits P4-7.
  Revisit a durable status only if a second worker or a remote runner is ever authorized.

**Decision 14, moving the executor into `image_backends`: recommend later, after typed stage settings and the family
hooks.**

- Evidence: the adapter boundary is real now. The runner reaches the executor only through
  `WebUIFamilyImageBackend.execute` (`webui_family_backend.py:275-345`). Exact-profile modules already exist
  (`exact_model_profile.py`, `forge_zimage_profile.py`, `forge_flux1_profile.py`, `forge_klein_*`).
- But the executor still imports those profiles back (4211-4537) and holds the family branches. The backends poke its
  private state. Moving it today turns `src/pipeline/executor.py` into `src/image_backends/webui/executor.py` with the
  same 6,000 lines and a two-way dependency inside `image_backends`. That is a rename, and it changes PR-IMG-100
  ownership for nothing.
- Order that makes the move cheap: this plan's slices 2, 5 and 8 (backend-neutral collaborators stay in
  `src/pipeline`); then P4-4 typed stage settings; then P4-5 family hooks on the backend profiles. After that the
  remainder (the five stage bodies and model sync, about 3,000 lines) is WebUI-specific and moves as one mechanical PR.

## 11. What not to do

- Do not create a second queue, runner, history, compiler authority or GUI-to-backend path. Slice 4's builder feeds
  `ReprocessJobBuilder`; it must not construct an NJR itself.
- Do not move the executor wholesale (decision 14) or split it by stage into five copies of the same preamble.
- Do not add a durable CANCELLING status to fix a display problem (decision 12).
- Do not fix the section 8 defects inside a refactor slice. A "behaviour-preserving" PR that also changes Stop or
  img2img admission cannot be reviewed as either.
- Do not move methods out of AppController before the test fixture exists (slice 1). The 34 half-built controllers
  will fail in ways that look like regressions.
- Do not remove the `__func__` identity checks or the `getattr` guards in bulk; remove each with the tests that needed
  it.
- Do not wrap moved methods in compatibility shims that keep the old private names alive for GUI callers. Move the
  callers (slices 4 and 6 do this).
- Do not touch the queue lock order or call into the queue while holding an AppController lock.
- Do not raise any ratchet ceiling to make a slice fit.

## 12. Owner decisions

Decided 2026-11-28, as relayed by the orchestrator session: "PRs 1–6 now, 7–8 later"; decision 12 "No; show
"Stopping...""; decision 14 "Later"; the top-bar Stop "Cancel the running job". Item 4 (an executor line ceiling) is
not yet decided. The recommendations as they were put:

1. Approve this plan, or a subset (recommended: slices 1-6 now; 7 and 8 after 1-6 land and their characterization
   tests prove cheap).
2. Decision 12: no durable CANCELLING; do the "Stopping..." projection as a small separate package (recommended).
3. Decision 14: later, after slices 2, 5, 8, P4-4 and P4-5 (recommended).
4. Decision 15 (in part): add an executor line ceiling after slice 1, so the gains in slices 2, 5 and 8 are locked in
   (recommended).
5. The section 8 defects: open one bug package for items 1-3 (Stop button, prompt-policy fallback, movie clips output
   folder) (recommended), and ask whether img2img and upscale single mode skip admission deliberately.

## 13. Bug-fix package (CODE-HEALTH bug fixes, 2026-11-28)

Branch `fix/code-health-bugfixes` from `origin/main` `7de95a26`. Each fix has a regression test that failed first
(`tests/controller/test_code_health_bugfixes_ch1.py`, `tests/pipeline/test_img2img_runtime_admission_ch1.py`).

- **(a) Top-bar Stop.** `on_stop_clicked` now calls `on_cancel_current_job`, the running-job panel's own method, when
  the runner holds a job or the queue has a RUNNING one, and only logs otherwise. There is no second cancel path. The
  old lifecycle-gated body (reachable only in tests that forced `LifecycleState.RUNNING`) and the now-unused
  `_set_lifecycle` are gone; the rest of the `LifecycleState` leftovers stay for slice 1.
- **(b) "Stopping..." row (decision 12).** `src/controller/app_controller_services/stopping_display.py`. On an operator
  cancel (panel Cancel, Cancel and Return, top-bar Stop) the running row keeps the job, labelled `Stopping...`, until a
  UI-loop check every 250 ms sees the runner's `current_job` change; the queue's CANCELLED announcement no longer clears
  the row while the GPU is busy. Display only: no job status, database, history or sync change. Without a UI loop
  (headless, or a main window whose "later" falls back to running the check at once) the row clears on the
  announcement, as before; `docs/Subsystems/Runtime/QUEUE_AND_RUNTIME.md` B10 records the decision.
- **(c) Global prompt-policy fallback.** `get_current_global_prompt_policy` passes `_config_manager` (the attribute
  that exists), so the saved policy applies when the sidebar has none. The wrong log variable (`field`) is fixed too.
  Now that the fallback is reachable, `global_prompt_policy_service.read_current_policy` treats a settings object
  without the saved-policy getters (the partial stand-ins several controller tests pass) as having no saved policy.
- **(d) Output folder.** The root cause was wider than Movie Clips: `AppController.output_dir` was never defined, and
  Movie Clips, SVD, Video Workflow and the other video submissions all read it, so all of them ignored the saved
  folder. `output_dir` is now a property that returns the saved application-wide `output_dir` (the same rule image jobs
  use, `ConfigManager._apply_application_defaults`) and `None` when none is set, so each caller keeps its default. The
  owner's live setting is `output`, so nothing moves on his install.
- **(e) GPU-ready checks.**
  - img2img: **an omission**, not a design. `IMAGE_PIPELINE.md` already described admission as common to every stage,
    the pressure model has no img2img entry, and no document gives a reason. A reprocess, photo-optimize or Klein-edit
    job that starts with img2img reached Forge with no admission. img2img now runs pressure assessment, pressure
    mitigation and runtime admission before model sync, and records `pressure_assessment`, `runtime_admission` and any
    runtime warning in its manifest like txt2img. The workload launch policy is deliberately not applied: it has no
    img2img profile and a profile restart needs GPU qualification. An unhealthy-but-not-poisoned runtime still runs
    img2img (it is not in the unsafe-pressure refusal set), so only a poisoned runtime that recovery cannot fix, or a
    duplicate process, refuses it.
  - Upscale single mode: **deliberate**. It already runs the full admission preamble and drift check; it bypasses
    `_generate_images_with_progress` only because the extras endpoint is not a sampler generation (no payload
    validator, no `/progress` stall polling), and the client applies `UPSCALE_RETRY_POLICY`. A code comment now says so.
- Not verified on the live app or a GPU.

## Model and effort for the slices

- Slices 1, 3, 6: Claude Code Sonnet 5.5 high, or Codex standard high; about 2-5M cache-read each.
- Slices 2, 4, 5: Claude Code Opus 5.5 high; about 5-10M cache-read each.
- Slices 7, 8: Claude Code Opus 5.5 high (xhigh for the thread work in 8), with an independent `verify-change` pass;
  about 10-20M cache-read each.

## Stop conditions

- A characterization test cannot be written for a slice without changing behaviour: stop that slice and report.
- A deleted name turns out to have a dynamic caller: keep the method and record it.
- A slice needs a schema, NJR or queue-status change: stop; that is an owner decision.
- Any slice would cross into P4-4 or P4-5: stop at the boundary.

## Documentation impact

- `STATUS.md`: the "Known debt" line quotes the old controller size (5,010). Update it when slice 1 lowers the ceiling,
  not in this docs-only commit.
- `docs/Subsystems/Runtime/QUEUE_AND_RUNTIME.md` B10 item (3): link the decision 12 outcome once the owner decides.
- `CODEX_MAP.md`, `AGENTS.md`, architecture: no change from this review.
