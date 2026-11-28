# STARTUP-STALL: startup UI stall, WebUI startup window, stall attribution

Status: built 2026-11-28 with deterministic tests; nothing run in the live app, no GPU. Base `origin/main` 841f9b49,
branch `claude/startup-stall-4de886`. Owner picked this work on 2026-11-28. The follow-up STARTUP-STALL-2
(base 85a59f91, branch `claude/startup-stall-2-a56548`) is recorded below; it supersedes the table's state for
groups C, E, H and I.

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

## STARTUP-STALL-2 (built 2026-11-28; deterministic tests and a test harness only, nothing run in the live app)

Execution class: Standard. Model recommendation: Claude Code Sonnet 5.5 at high effort, or Codex equivalent.
Controller surface: `generation_profile_controller.py` splits one projection into a UI-thread read and a worker half; it
is not ratcheted. No change to the canonical execution path.

### Records on the #498 code (starts at 05:57, 06:38 and 08:00 on 2026-11-28)

Startup stalls were still 1.2-4.9 s (before #498: up to 10.2 s). In the longest (4.86 s) the Tk thread used 0.03 s of
CPU while the process used 4.16 s: it was waiting for the interpreter, not computing. Reproduced outside the app: 3,600
small Tk calls take 1 ms alone and about 1.0 s beside one thread busy in pure Python. A startup stall is therefore
roughly (number of Tk calls) x (the wait for each), and layout code shows in the samples because it is where Tk is
calling, not because it is slow by itself.

### Changes

1. **Window-geometry handlers no longer work once per widget** (`main_window_v2.py`). A binding on the Tk root also
   receives every descendant's `<Configure>` and `<Map>`. A descendant's `<Configure>` cannot move the window, so only
   the root's own is captured. A descendant's `<Map>` still re-checks that the window is on screen, as before (a tab
   switch pulls an off-screen window back), but once per idle turn instead of once per widget. This also runs on later
   resizes, tab switches and queue row changes (samples in groups D, G and J show `wm_state`, `deletecommand` and
   `winfo_screenwidth` under these handlers or their `after_idle`; the group D link is inference).

   Test harness (3,003 widgets, isolated state), only `main_window_v2.py` swapped between before and after:

   | | Before | After |
   |---|---|---|
   | Visibility checks, build + first update | 1,121 | 16 |
   | Geometry captures, build + first update | 3,900 | 18 |
   | Tcl `call` + `createcommand`, build + first update | 41,646 | 19,868 |
   | First `update()` wall, three runs | 1.38, 1.62, 1.63 s | 1.50, 1.28, 1.36 s |
   | Visit every tab once, three runs | 3.08, 4.26, 3.61 s | 3.87, 3.27, 3.72 s |

   With no competing thread the wall times show no reliable difference. The gain expected is in Tk calls made while
   other startup threads run, and that is not measured.

   Noticed, unchanged: the on-screen check uses the primary monitor's size, so a window on a second monitor counts as
   off screen and is pulled back on a tab switch or restore.

2. **Generation profile strip** (group I): working values are read on Tk; the profile store, evidence catalog and asset
   registry reads run on a tracked worker, one at a time, newest result only. Behaviour change: the strip redraws a
   moment after the edit instead of inside it. `AssetRegistry._load` now marks itself loaded only after loading.
3. **AI Assist poll** (group H): availability and trust label are read on a worker once a second; a direct refresh
   (an operator action) supersedes a poll still reading.
4. **Completion stalls** (group E, records 15 and 21): still not attributed. What the logs do show:
   - no lock-contention record has ever named the Tk thread, so the UI has not waited 0.5 s or more on
     `job_repository`; no UI-side lock change was made;
   - the 4.3-4.6 s hold of `job_repository.update_progress` occurred seven times and only two had a UI stall, so the
     hold and the stall are probably two effects of one cause (a slow durable commit on a busy disk is the
     hypothesis).
   New instrumentation: a "UI thread stalled" record now carries `held_locks` (long holds seen while it lasted) and
   `io` (disk MB written, disk write ms, this process's MB written); a "Lock contention" hold carries `cpu_s`. On a
   recurrence: low `cpu_s` with high `disk_write_ms` means storage; `tk_cpu_s` near the stall length means Tcl was
   busy; high `process_cpu_s` with low `tk_cpu_s` means interpreter starvation. It does not name a Tcl call site.

## Remaining, in order of size

1. Startup interpreter starvation (the rest of group C). LoRA discovery, the video-eval catalog, the Site output index,
   the review-gateway publish, the GPU telemetry process scan and photo/OpenPose listing all start with the first map.
   Fewer Tk calls shorten the stall; it ends only if these start after the window has settled or cost less CPU. That
   is a startup-sequencing change, not made here. Re-measure in the live log first.
2. Group E, now instrumented; wait for a recurrence.
3. Groups F and G. Group F recurred once on 2026-11-28 06:38 (1.15 s, the storyboard's dirty poll reading the form).
4. File reads still on Tk without a stall record: the Preview's effective-settings profile lines (only while that
   section is shown), the AI Preview dialog's remote status (only while open) and the profile reads inside an operator
   action (choosing a model, saving).
5. `HistoryProjectionRefresh` held `job_repository` for up to 12 s in `list_recent_jobs`, delaying the queue worker's
   claim. Not a UI stall.

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

STARTUP-STALL-2 has no live measurement: how much shorter the real startup freeze is after it is unknown until the
next restarts are read from the log. Nothing ran in the live app: the shorter startup freeze, the CONNECTING status during a real Forge boot, the 300 s
window against a real slow boot and the thumbnail change are shown only by deterministic tests.
