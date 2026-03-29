# WebUI Restart and Lost Connection Investigation 2026-03-20

Status: Initial investigation
Date: 2026-03-20
Scope: First-pass evidence review of recurring restarts, lost-connection symptoms, and pipeline slowdowns in the StableNew WebUI-backed image pipeline.

This document is an active diagnostic reference. It does not supersede the canonical architecture documents, the Debug Hub, or the operational runbooks. Its purpose is to capture what is currently evidenced, what is only suspected, and what a second targeted pass should prove or disprove.

## Questions This Investigation Tried To Answer

1. What are the most likely root causes of the frequent restart and lost-connection behavior?
2. Which code paths should a second investigation inspect first?
3. Which earlier theories are still current, and which ones are already mitigated in the current branch?
4. What targeted tests or manual experiments would distinguish the failure classes cleanly?

## Evidence Reviewed

### Runtime logs

- `tmp/latest_diagnostic/logs/stablenew.log.jsonl`
- `tmp/latest_diagnostic/logs/stablenew.log.jsonl.2`
- `tmp/latest_diagnostic/logs/stablenew.log.jsonl.5`
- `tmp/diag_check2/logs/stablenew.log.jsonl.2`
- `tmp/diag_check2/logs/stablenew.log.jsonl.5`

### Current code inspected

- `src/api/client.py`
- `src/api/webui_process_manager.py`
- `src/pipeline/executor.py`
- `src/pipeline/pipeline_runner.py`
- `src/utils/retry_policy_v2.py`
- `src/main.py`
- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/controller/process_auto_scanner_service.py`
- `src/cli.py`
- `src/prompting/sdxl_prompt_optimizer.py`

### Historical context reviewed

- `docs/runbooks/ZOMBIE_PROCESS_RECOVERY.md`
- `docs/PR_Backlog/HistoricalRoot/PR-HARDEN-006-ADetailer-Fail-Fast-Retry-Policy.md`
- `docs/PR_Backlog/HistoricalRoot/PR-HARDEN-007-Post-Recovery-Health-Check-Timeout.md`
- `docs/PR_Backlog/HistoricalRoot/PR-HARDEN-008-Per-Job-Pipeline-Timeout-Ceiling.md`

## Scope And Confidence Limits

This report is evidence-backed, but it is not a final root-cause proof.

Known limits:

- The log set mixes older rotated logs with current branch source. Some historical logs clearly reflect older timeout and retry behavior than the current code.
- This pass did not run a live WebUI under a debugger or capture GPU telemetry at the moment of failure.
- The repo contains active worktree changes in runtime files. Those changes were not modified in this investigation, but they do raise the chance that some historical logs came from a slightly different branch state.
- No new runtime code or tests were added in this pass. This is a reporting and scoping pass only.

## Executive Summary

The strongest current model is that there are two recurring failure classes, not one:

1. Hard WebUI exits. In these incidents the WebUI process actually dies with exit code 1, and the later "lost connection", connection reset, and WinError 10061 messages are follow-on symptoms after the server is already gone.
2. Hung-but-alive request failures. In these incidents the WebUI process remains alive, but a stage request stops returning and eventually times out.

The evidence suggests that memory-heavy finishing stages, especially upscale and in some archived cases tiled upscale, are the strongest current hotspot for the hard-exit class.

The evidence does not support blaming the prompt optimizer. `src/prompting/sdxl_prompt_optimizer.py` is not on a credible process, transport, or recovery boundary.

Two historically plausible theories are now weaker for the current branch because the mitigations are already present in source:

- ADetailer now has its own fail-fast retry policy.
- The post-recovery health probe now uses an extended timeout during the grace window.

One important nuance in the current logs is SafeMode. SafeMode reduces the chance that repeated `/options` writes are destabilizing WebUI during the active run. At the same time, SafeMode also blocks StableNew from applying its conservative upscale safety defaults at runtime, which leaves the active WebUI tile and cache settings unmanaged.

## Recurrence Snapshot

The following counts were derived from a PowerShell count pass across the archived diagnostic logs during this investigation:

| Log file | `code=1` exits | `read timeout=300.0` hits | large orphan-launch kills |
| --- | ---: | ---: | ---: |
| `tmp/diag_check2/logs/stablenew.log.jsonl.5` | 42 | 454 | 31 |
| `tmp/latest_diagnostic/logs/stablenew.log.jsonl` | 33 | 454 | 25 |
| `tmp/latest_diagnostic/logs/stablenew.log.jsonl.5` | 2 | 1 | 2 |

These counts do not by themselves prove cause, but they do establish that both crash and long-timeout behavior are recurrent across multiple rotated logs.

## Detailed Findings

### 1. Failure Class A: WebUI Actually Exits

Representative sequence from `tmp/diag_check2/logs/stablenew.log.jsonl.2`:

- `:470` - cleanup kills a `launch.py` process using about 18.4 GB of RSS.
- `:477` - request attempt fails with `ConnectionResetError(10054)`.
- `:489` - StableNew logs `WebUI process exited (code=1)` and the stderr tail includes tiled-upscale progress.
- `:502-506` - the retry fails with WinError 10061 (`actively refused it`) and the stage reports WebUI unavailable.

Recent run example from `tmp/latest_diagnostic/logs/stablenew.log.jsonl.5`:

- `:579` - cleanup kills a `launch.py` process using about 7.9 GB.
- `:590` - a request fails with `ConnectionResetError(10054)`.
- `:599` - StableNew logs `WebUI process exited (code=1)`.

Interpretation:

- In this class, "lost connection" is not the first failure. It is the consequence of the server disappearing mid-request.
- The important timeline is process death first, client socket failure second.

Code areas that matter:

- `src/api/webui_process_manager.py:933-1048` - process match heuristics and kill path for orphaned WebUI Python and shell processes.
- `src/api/webui_process_manager.py:1067-1095` - crash-tail logging (`WebUI process exited (code=%s)`).
- `src/api/webui_process_manager.py:1407-1455` - blocked-port discovery and forced kill path.
- `src/pipeline/executor.py:1343-1398` - executor error envelope captures `webui_running`, PID, and stdout/stderr tails for downstream diagnosis.

What a second pass should prove:

1. Whether the large orphaned `launch.py` processes are a cause of later crashes, or just residue left behind after the real failure already happened.
2. Whether the underlying exit is GPU OOM, WebUI extension failure, a model-specific crash, or an external kill.
3. Whether the process manager is sometimes cleaning up a still-recoverable process too aggressively after a partial failure.

### 2. Failure Class B: Request Hangs While WebUI Stays Alive

Representative sequence from `tmp/latest_diagnostic/logs/stablenew.log.jsonl.2:4372-4377`:

- two img2img attempts hit `Read timed out. (read timeout=300.0)`;
- the executor envelope records `webui_running: true` and a live PID;
- no crash tail is attached.

Interpretation:

- This is not the same failure class as the hard exits.
- The server is still present, but a request is not returning within the client timeout budget.

Code areas that matter:

- `src/api/client.py:66-70` - default read/generation timeout constants.
- `src/api/client.py:118-140` - client constructor default `timeout=DEFAULT_GENERATION_TIMEOUT`.
- `src/api/client.py:275-291` - `_resolve_timeout()` normalizes the request into a `(connect, read)` tuple.
- `src/api/client.py:904-989` - `txt2img()` and `img2img()` call `_request_context()` without their own timeout override.
- `src/api/client.py:1072-1087` - `upscale()` also uses the shared request timeout path and only changes retry policy.
- `src/api/client.py:1208-1224` - stage router for `txt2img`, `img2img`, `adetailer`, and `upscale`.

What a second pass should prove:

1. Whether the active GUI/runtime path is actually using the current 120-second default, or whether some code path still supplies 300 seconds.
2. Whether hangs correlate with a specific stage, payload size, sampler, or post-processing choice.
3. Whether the WebUI is still making internal progress during the hang, or whether it has effectively stalled.

### 3. Upscale Is The Strongest Current Hotspot

Why this is the leading hotspot:

- In archived crash-heavy logs, the crash tail very often includes tiled-upscale progress. `tmp/diag_check2/logs/stablenew.log.jsonl.2:489` is the clearest example.
- In the latest diagnostic logs, the active route logs repeated batch-upscale activity such as `tmp/latest_diagnostic/logs/stablenew.log.jsonl.5:1664-1673`.
- The batch pipeline route is `src/pipeline/pipeline_runner.py:1344-1405`, which logs `Processing upscale for image ...` and dispatches to `run_upscale_stage()`.
- The active upscale implementation is `src/pipeline/executor.py:4065-4158`, which logs the received upscale config and performs pre-upscale memory checks.

Important nuance:

- `src/pipeline/executor.py:4128-4130` explicitly documents that one earlier `ensure_safe_upscale_defaults()` behavior was removed because it interfered with `tile_size=0`-style user settings.
- Meanwhile, `src/api/client.py:708-762` and `src/api/client.py:772-807` still contain two mechanisms for clamping or setting conservative WebUI upscale defaults.
- `src/pipeline/executor.py:736-751` still applies `apply_upscale_performance_defaults()` once per run if the client exposes it.

Interpretation:

- Upscale safety behavior is spread across more than one layer.
- The active path is not simply "defaults on" or "defaults off"; it depends on which call site runs and whether SafeMode blocks option writes.

What a second pass should prove:

1. Which concrete WebUI `/options` values are active immediately before each failing upscale.
2. Whether the crash rate changes materially when only keeper images are upscaled versus every generated image.
3. Whether tile, overlap, cache, and image megapixel ceilings are being left in an aggressive state because SafeMode blocks StableNew's normal safety writes.

### 4. SafeMode Is A Double-Edged Diagnostic Detail

Evidence:

- Current logs repeatedly emit `WebUI options writes disabled (SafeMode)`, for example `tmp/latest_diagnostic/logs/stablenew.log.jsonl.5:3`, `:523`, `:623`, and many later repeats.
- The client logs the same state in `src/api/client.py:164-170` and `_options_can_send()` returns `safe_mode` from `src/api/client.py:659-667`.
- Both `ensure_safe_upscale_defaults()` and `apply_upscale_performance_defaults()` bail out if `_options_can_send()` returns false. See `src/api/client.py:755-762` and `src/api/client.py:791-807`.

Interpretation:

- SafeMode makes it less likely that the current run is crashing because StableNew is churning `/options` writes.
- SafeMode also prevents StableNew from applying the conservative tile/cache/image-size defaults that were intended to keep upscale memory use under control.

What a second pass should prove:

1. The actual WebUI option values during the failing runs.
2. Whether turning SafeMode off in a controlled repro reduces or increases instability.
3. Whether SafeMode-on runs should proactively log the live `/options` state so operators can tell what settings are really in effect.

### 5. Current Source Already Contains Two Important Historical Mitigations

These are already present in the current branch and should not be treated as the most likely active root cause unless the secondary pass proves otherwise:

1. ADetailer fail-fast retry policy.
   - `src/utils/retry_policy_v2.py:37-64`
   - `src/api/client.py:1208-1224`
   - `src/pipeline/executor.py:2348-2364`

2. Extended post-recovery health probe.
   - `src/pipeline/executor.py:86-87`
   - `src/pipeline/executor.py:1137-1168`

Interpretation:

- Historical logs that show ADetailer going through the generic img2img retry loop are still useful as history, but they are weaker evidence for the current branch.
- Historical logs that support the old short post-recovery probe theory are similarly weaker because the mitigation is already in current source.

### 6. Timeout Mismatch Between Current Source And Archived Logs Is Real And Unresolved

Current source says:

- `src/api/client.py:70` - default generation timeout is 120 seconds.
- `src/api/client.py:128` - the client constructor default uses that 120-second value.

Archived logs still show:

- repeated `timeout: [3.0, 300.0]` envelopes;
- repeated `Read timed out. (read timeout=300.0)` entries, for example `tmp/latest_diagnostic/logs/stablenew.log.jsonl.2:4372-4377`.

Instantiation paths inspected:

- GUI/controller default path: `src/controller/app_controller.py:400-408` and `src/controller/app_controller.py:933-939` construct `SDWebUIClient` without explicit timeout overrides.
- Pipeline controller path: `src/controller/pipeline_controller.py:1397-1403` does the same.
- CLI path: `src/cli.py:124-132` is the main explicit timeout override path found in current source.
- `src/main.py:240-256` confirms `STABLENEW_WEBUI_TIMEOUT` only overrides WebUI startup timeout, not API request timeout.

Interpretation:

- The 300-second timeout behavior in archived logs is either from older branch state, a non-default construction path, or runtime configuration outside the path inspected here.
- This mismatch must be resolved in the second pass because it affects whether long stalls are being detected early enough.

What a second pass should prove:

1. The actual `self.timeout` value on the client used by the GUI runtime.
2. Whether any config/bootstrap path still supplies 300 seconds indirectly.
3. Whether the relevant logs were produced before the 120-second change landed.

### 7. A Separate WebUI Or Model Compatibility Failure Exists

This investigation also found a different, non-restart error class in `tmp/diag_check2/logs/stablenew.log.jsonl.2:48581-48589`:

- `500 Server Error` on `/sdapi/v1/txt2img`
- WebUI stderr includes `AttributeError: 'DiffusionEngine' object has no attribute 'cond_stage_model_empty_prompt'`

Interpretation:

- This does not look like the main cause of the restart/lost-connection pattern.
- It is still a meaningful failure mode that should be tracked separately because it can poison requests and muddy incident analysis.

Code areas that matter:

- `src/api/client.py:430-565` - HTTP failure logging and retry behavior.
- `src/pipeline/executor.py:1343-1398` - error envelope capture and diagnostics bundle trigger.

### 8. There Is Stale Or Unreachable Upscale Code In `executor.py`

This matters because it can mislead code search during future debugging.

- `src/pipeline/executor.py:2475-2524` contains an apparent retained upscale block after `return None`, including an old `ensure_safe_upscale_defaults()` call.
- The active batch route for the failures in the current logs is instead `src/pipeline/pipeline_runner.py:1344-1405` -> `src/pipeline/executor.py:4065-4158`.

Interpretation:

- The stale block is not the best explanation for the active failures.
- It is still a worthwhile cleanup target because it can cause investigators to attribute behavior to the wrong path.

### 9. Lower-Confidence Side Path: Auto-Scanner / Watchdog Interference

This was not a primary focus of the pass, but it should be explicitly logged as a lower-confidence branch of investigation rather than ignored.

Evidence:

- `tmp/latest_diagnostic/logs/stablenew.log.jsonl.5:1-2`, `:58-59` contain `AUTO_SCANNER_TERMINATE` entries for repo-local Python processes.
- Current code for the scanner lives in `src/controller/process_auto_scanner_service.py:20-34` and `src/controller/process_auto_scanner_service.py:184-210`.
- The current code uses 300-second idle and 2048 MB thresholds, while the cited log entries still show older 120-second and 1024 MB thresholds.
- `tmp/latest_diagnostic/logs/stablenew.log.jsonl.5:21954-21974` also contains watchdog memory-violation envelopes.

Interpretation:

- These logs reinforce the general warning that archived logs do not map cleanly onto the current branch.
- Based on the paths and CWDs observed, this does not currently look like the primary cause of the WebUI crash pattern.
- It is still worth checking in a second pass if the main investigation stalls.

## Code Map For A Targeted Second Pass

| Area | Code to inspect first | Why it matters | Key question |
| --- | --- | --- | --- |
| shared timeout budget | `src/api/client.py:66-70`, `:118-140`, `:275-291` | defines the effective request timeout | what timeout is the GUI runtime actually using? |
| stage request call sites | `src/api/client.py:904-989`, `:1072-1087`, `:1208-1224` | txt2img/img2img/upscale all route through shared request handling | which stage is most likely to hang or die? |
| SafeMode and `/options` writes | `src/api/client.py:659-667`, `:708-762`, `:772-807` | blocks or applies protective WebUI defaults | are conservative defaults active in the failing runs? |
| GUI/controller client construction | `src/controller/app_controller.py:400-408`, `:933-939`; `src/controller/pipeline_controller.py:1397-1403` | likely active runtime construction path | is there any hidden timeout override here? |
| startup timeout only | `src/main.py:240-256` | proves `STABLENEW_WEBUI_TIMEOUT` is not request timeout | are operators assuming it affects API calls when it does not? |
| CLI-only timeout override | `src/cli.py:124-132` | explicit timeout override path exists here | were any archived logs produced through CLI or CLI-driven tests? |
| ADetailer fail-fast | `src/utils/retry_policy_v2.py:37-64`; `src/api/client.py:1208-1224`; `src/pipeline/executor.py:2348-2364` | historical theory already mitigated | are current incidents still being blamed on already-fixed behavior? |
| post-recovery health probe | `src/pipeline/executor.py:86-87`, `:1137-1168` | historical theory already mitigated | are recoveries failing somewhere else now? |
| diagnostics envelope | `src/pipeline/executor.py:1343-1398` | captures whether WebUI was still running | can incident classification be made automatic? |
| active batch upscale route | `src/pipeline/pipeline_runner.py:1344-1405`; `src/pipeline/executor.py:4065-4158` | path most clearly associated with the active logs | what exact config and memory state precede a crash? |
| stale upscale block | `src/pipeline/executor.py:2475-2524` | likely dead code that can mislead grep-based debugging | should this be removed after the investigation? |
| orphan kill heuristics | `src/api/webui_process_manager.py:105-152`, `:933-1048`, `:1407-1455` | decides what counts as a WebUI orphan and kills it | are we cleaning up correctly, too broadly, or too late? |
| crash-tail logging | `src/api/webui_process_manager.py:1067-1095` | sole code path that emits the code=1 crash tail | can we expand the tail with memory or extension state? |
| lower-confidence process cleaner | `src/controller/process_auto_scanner_service.py:20-34`, `:184-210` | repo-local Python cleaner with its own kill thresholds | could it ever interfere with live runtime investigation? |

## Recommended Second-Pass Investigation Plan

### A. Instrumentation to add before another real repro

1. Log the resolved request timeout tuple for every stage request from `_request_context()` or `_perform_request()`.
2. Log the concrete client construction path once at startup, including whether the client timeout came from a default or override.
3. Before every upscale, log the live WebUI `/options` values relevant to memory pressure:
   - `img_max_size_mp`
   - `ESRGAN_tile`
   - `ESRGAN_tile_overlap`
   - `DAT_tile`
   - `DAT_tile_overlap`
   - `upscaling_max_images_in_cache`
4. On every executor error envelope, include stage-level metadata such as current upscaler, resize factor, and whether SafeMode blocked default application.
5. At process-exit time, record whatever memory and GPU telemetry is cheaply available so code=1 exits can be separated into OOM-like and non-OOM-like buckets.

### B. Manual reproduction matrix with a real WebUI

Use the same prompt, seed, model, and base dimensions for a small matrix:

1. txt2img only
2. txt2img + ADetailer only
3. txt2img + upscale only
4. txt2img + ADetailer + upscale
5. repeat (3) and (4) with SafeMode off
6. repeat (3) and (4) with conservative manual tile/cache settings applied directly in WebUI

For each run, capture:

- stage durations
- resolved request timeout tuple
- WebUI PID continuity
- RSS of `launch.py`
- live `/options` snapshot before upscale
- whether stderr tail shows tiled-upscale progress at crash time

This matrix should very quickly reveal whether upscale is the dominant destabilizer, whether SafeMode is masking or worsening the issue, and whether ADetailer materially changes the crash rate in the current branch.

### C. Deterministic automated tests that do not need a real WebUI

Because the repo test rules forbid live WebUI dependencies, the next pass should rely on mocked clients and fake process-manager state.

Suggested tests:

1. `tests/api/test_client_timeout_resolution.py`
   - prove the default client timeout is 120 seconds;
   - prove `_resolve_timeout()` returns the expected tuple;
   - prove `STABLENEW_WEBUI_TIMEOUT` does not alter request timeout.

2. `tests/controller/test_app_controller_webui_client_config.py`
   - prove GUI/controller construction paths do not silently override request timeout.

3. `tests/api/test_client_safe_mode_option_writes.py`
   - prove SafeMode blocks both `ensure_safe_upscale_defaults()` and `apply_upscale_performance_defaults()`.

4. `tests/pipeline/test_upscale_stage_active_path.py`
   - prove batch upscale flows through `run_upscale_stage()`;
   - assert the active path emits the expected config log;
   - isolate the stale block as non-authoritative for current behavior.

5. `tests/pipeline/test_executor_webui_failure_envelope.py`
   - simulate a connection-reset-after-exit case and a timeout-while-running case;
   - assert the envelope correctly distinguishes `webui_running=True` vs `False` and preserves the tail.

6. `tests/api/test_webui_process_manager_match_reasons.py`
   - prove `_get_webui_python_match_reasons()` and `_get_webui_shell_match_reasons()` do not over-match unrelated processes.

7. `tests/api/test_webui_crash_tail_bundle_trigger.py`
   - simulate a crash-suspected exception and assert the diagnostics bundle path is scheduled once with the expected context.

### D. Low-priority but worthwhile cleanup after the investigation

1. Remove or quarantine the stale upscale block in `src/pipeline/executor.py:2475-2524` so future debugging is less error-prone.
2. Consider centralizing upscale-safety behavior so there is one authoritative place for clamping and one authoritative place for honoring user tile settings.
3. If the timeout mismatch is confirmed, make the runtime emit one startup log line that states the effective request timeout budget.

## Preliminary Conclusions

Current best explanation, ranked by confidence:

1. High confidence: many lost-connection incidents are downstream symptoms after a real WebUI exit.
2. High confidence: a second class of failures consists of requests hanging while the WebUI process remains alive.
3. Medium to high confidence: upscale, and in some archived incidents tiled upscale specifically, is the most credible active crash hotspot.
4. Medium confidence: SafeMode is reducing one possible instability source while also disabling the automatic conservative WebUI settings that would otherwise protect upscale.
5. Medium confidence: the ADetailer retry-loop and short post-recovery-probe theories are now mostly historical for the current branch because the mitigations are already present.
6. Low to medium confidence: auto-scanner or watchdog side channels may matter in some logs, but they are not currently the strongest explanation for the observed WebUI crash pattern.

The second pass should be designed to prove or disprove these hypotheses with targeted instrumentation, not more broad log reading.
