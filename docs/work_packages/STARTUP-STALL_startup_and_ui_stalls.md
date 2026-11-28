# STARTUP-STALL: startup UI stall, WebUI startup window, stall attribution

Status: built 2026-11-28 with deterministic tests; nothing run in the live app, no GPU. Base `origin/main` 841f9b49,
branch `claude/startup-stall-4de886`. Owner picked this work on 2026-11-28.

Execution class: Standard. Model recommendation: Claude Code Sonnet 5.5 at high effort, or Codex equivalent.
Controller surface: `webui_connection_controller.py` gains one read-only state projection and the service
`application_runtime_coordinator.py` moves one call to a worker; `app_controller.py` is unchanged and no ratcheted
controller grows. No change to the canonical execution path, queue, history or submission authority.
Validation: characterization tests, then new tests per change, the touched `tests/gui_v2` files, `tests/system`,
ratchets, code map and the PR gate.

## Changes

1. **PromptPack catalog off the Tk thread** (`site_connection_dialog.py`). `SitePackCatalog` resolved every pack on
   the Tk thread at startup (and on Refresh): 3.7-6.3 s, six times in the log. App state is now snapshotted on the UI
   thread, a tracked worker builds the catalog, and `_ui_dispatch` publishes it. The newest request wins; a result for
   a revoked session or a closing app is dropped.
   - Behaviour change: until the catalog arrives (seconds after start) the Site gets `promptpacks_not_shared`; the
     pairing window says "Preparing the visible PromptPacks…". The listing is not faster, only off Tk.
   - Inference for why it was slow (90 packs, the largest 31 KB): in the newer records the Tk thread used
     0.06-0.3 s CPU over 3.3-5.8 s while process CPU matched wall time, so each file-system call waited to get the
     interpreter back from other startup threads.
   - Digests: building the catalog computes none. The one-pack digest checks at Preview preparation and Queue admission
     stay synchronous on purpose: they read one file (4 MiB cap), have no stall record, and moving them would open a
     gap between the check and the admission.
2. **Managed Forge startup window 180 s -> 300 s** (`managed_forge_runtime.STARTUP_TIMEOUT_SECONDS`). Evidence, Forge's
   own `Startup time` in `logs/webui` for 11 launches: 32.6, 35.4, 36.9, 38.2, 42.1, 42.1, 42.1, 46.7, 48.8, 52.9 and
   171.0 s. The 171 s boot (2026-11-27 19:36) answered 176 s after launch, 4 s inside the window. Still bounded; a
   process that exits ends the wait at once. A1111 and explicit launch profiles keep their own values.
3. **Booting is not an error.** The status read ERROR for the whole Forge boot (the readiness probes set it). While the
   owned process is inside its window the connection now reads CONNECTING.
4. **Gui-ready readiness check off Tk** (`application_runtime_coordinator.py`). It ran socket and HTTP probes on the
   Tk thread (0.3-0.6 s in the starts timed; one sample in a 2.91 s record).
5. **Motion Library thumbnails decoded off Tk** (`video_workflow_motion_library_panel_v2.py`).

## Stall inventory: all 46 records from 2026-11-26 to 2026-11-28 04:56 UTC

Source: `logs/stablenew.log.jsonl`, `.1` and `.2` of the live checkout, read only. Numbers are the order in time.
Durations are the longest heartbeat age sampled, in seconds. One site per record is the dominant one; short records
with one sample show where the Tk thread was, which is not proof of what held it.

| Group | Site | Records (duration) | State |
|---|---|---|---|
| A. GPU telemetry process scan on Tk | `gpu_survivor_telemetry.start` -> `process_inspector_v2.py:77` | 1 (6.7), 3 (8.3), 11 (7.2), 13 (5.7), 22 (4.1) | Fixed earlier by DESK-QUICK (#464) |
| B. PromptPack catalog on Tk | `site_pack_catalog.py:49-50` via `site_connection_dialog._share_packs` | 26 (4.0), 29 (3.7), 31 (6.3), 37 (4.8), 39 (4.2), 42 (4.9) | Fixed here |
| C. Startup window map and layout | Tk `mainloop`, `pipeline_tab_frame_v2` `_layout_fits` / `_set_presentation`, `main_window_v2` geometry and map handlers, `flow_row_v2`, `responsive_wrap_v2` | 2 (2.6), 4 (6.2), 12 (7.7), 14 (2.0), 23 (2.3), 27 (2.3), 30 (4.5), 32 (10.2), 33 (2.2), 34 (2.7), 35 (1.2), 38 (2.9), 40 (2.4), 43 (2.0), 45 (4.9), 46 (1.9) | Open, see below |
| D. Job start | Tk `mainloop` (one `deletecommand`) | 5 (1.3), 9 (1.0), 10 (1.2), 19 (1.2) | Queue projection; fixed earlier by RUN-LEAN |
| E. Job completion | Tk `mainloop`, then layout | 15 (4.7), 16 (2.9), 21 (5.1) | Not attributed to a Tk site, see below |
| F. Video Workflow form read | `video_workflow_tab_frame_v2.get_video_workflow_state` | 6 (1.4), 17 (1.0), 18 (1.0) | Open, single samples |
| G. Other single samples | `gui_invoker._schedule_pump`, `storyboard_panel_actions._poll_dirty`, `running_job_panel_v2._set_widget_text` | 7 (1.2), 8 (1.3), 20 (1.2) | Open, single samples |
| H. AI Assist settings read on Tk | `ai_assist/remote_preview.py:133` from the Prompt tab's poll | 24 (2.2) | Open |
| I. Generation profile strip file reads on Tk | `generation_profiles/store.py:174`, `assets/registry.py:396` | 25 (1.4), 36 (1.2), 41 (1.5) | Open |
| J. Mixed | readiness probe on Tk, reflow, registry | 28 (2.9) | Probe fixed here |
| K. Motion Library thumbnails | `video_workflow_motion_library_panel_v2._thumb` | 44 (1.8); also the last sample of 32 | Fixed here |

## The ten records that had no attributed cause

DESK-QUICK (#464) left ten stalls with no Python frame above `mainloop`:

- **Three at job start (5, 9, 10).** Attributed, by correlation: each sits among `Queue projection timing` records of
  400-840 ms over about 1,800 queued jobs, plus a 1.1-1.2 s `job_repository` contention for 5 and 9. That projection
  converted every NJR on each job start and held the interpreter; RUN-LEAN (e3d3e217) now converts each once. Record 19
  matches the same pattern (about 200 ms projections over 949 jobs). Not re-observed since: no queue that large has
  run on the fixed code in these logs, so the fix is unproven in the live app.
- **Two at txt2img completion (15: 4.7 s; 21: 5.1 s).** Not attributed. Each coincides exactly with a 4.5-4.8 s hold of
  `job_repository` (`job_repository.update_progress`) and `job_queue_transition` (`job_queue.record_progress`) on the
  `progress_poll` thread. The Tk thread showed no Python frame, so it was not waiting on that Python lock in Python
  code. For 15 the watchdog thread was starved too (a process- or machine-wide hold); for 21 it sampled on time. A slow
  synchronous commit (disk) is a hypothesis only. A recurrence now records `tk_cpu_s` and `other_threads`.
- **Five at startup (2, 4, 12, 14, 23).** Attributed to the first window map and compact-layout fit (group C), by
  inference: the same records sample `_apply_responsive_layout` -> `_set_presentation` / `_layout_fits` in
  `update_idletasks`, and the `mainloop` samples are Tcl geometry work with no Python frame. Newer records of the same
  shape add that Tk CPU is only 2-70 % of the observed time while process CPU is often above it, so other startup
  threads share the blame.

## Remaining, in order of size

1. Group C, the startup map and layout fit (up to 10 s). Needs a design change to the compact fit and to how much work
   starts together; not a small safe fix.
2. The generation profile strip reads its store and hashes the asset registry path on Tk (group I).
3. The AI Assist poll reads its settings file on Tk (group H).
4. Groups F and G need more than one sample before changing anything.

## Related findings, not changed

- `main._async_bootstrap_webui` and `openpose_picker_panel` call `root.after` from worker threads. Each blocks until
  Tk is free, so the Forge launch waits out the startup stall (`WebUI launch profile resolved` appears right after it).
- Each 5 s slice of `wait_for_managed_startup` logs a WARNING "did not become ready" during a normal boot (about 150 in
  the logs).
- The 30 s startup probe grace (`main.py`) ends before a typical 33-53 s boot is ready.
- Stall records keep the label "Refreshing preview from state" long after that operation; read the stacks, not it.
- 2026-11-27 10:29: the bootstrap gave up after 180 s with nothing listening and no launch logged. Cause unverified;
  the longer window only delays that report.

## Not demonstrated

Nothing ran in the live app: the shorter startup freeze, the CONNECTING status during a real Forge boot, the 300 s
window against a real slow boot and the thumbnail change are shown only by deterministic tests.
