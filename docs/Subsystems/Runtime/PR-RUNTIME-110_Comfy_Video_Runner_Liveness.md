# PR-RUNTIME-110 — Comfy Video Runner Liveness / Watchdog Correctness

Status: **implemented on PR #23; integration gated by required GitHub CI and review.** No new queue, runner,
watchdog, progress store, lifecycle or process authority: the fix uses the existing
`Pipeline._emit_status_update` -> `AppController` runtime-status merge -> `SystemWatchdogV2` path.
The outer execution path
(`Intent -> Compiler -> NJR -> JobService -> SQLite -> PipelineRunner.run_njr -> backend ->
artifact/history`), Comfy process ownership, cancellation and PR-VID-190/191 behavior are unchanged.

## Semantics: long backend execution is not a queue-runner stall

`SystemWatchdogV2` declares `queue_runner_stall` when the runner-owned job shows no runner activity
and no meaningful `RuntimeJobStatus` change for `RUNNER_STALL_S` (90 s; native SVD has its own
stage-specific thresholds). Three different things must not be conflated:

| Signal | Meaning | Source | Counts toward the watchdog? |
|---|---|---|---|
| Real generation progress | A percentage / step count supplied by the backend | WebUI and native SVD executors | Yes (meaningful change) |
| Backend state change | Stage / `stage_detail` transitions | Executors, SVD post-process | Yes (meaningful change) |
| Bounded execution liveness | The Comfy server lists the queued prompt as running/pending, or its history explicitly marks the prompt nonterminal | `ComfyWorkflowVideoBackend` wait loop | Yes, for the runner-owned job, only inside the workflow-declared execution bound |

A healthy Comfy video job blocks the queue thread inside `_wait_for_history_entry` for the whole
generation. Before this package that loop reported nothing, so runner activity and runtime status
went stale and the watchdog declared a stall at ~90 s of a perfectly healthy job.

## Behavior

While waiting for the prompt, at most every 5 s (`_LIVENESS_REPORT_INTERVAL_S`, well under 90 s) the
backend confirms with Comfy that the prompt is still alive — it is in the server's `/queue`
running/pending lists (`_prompt_is_live`), or its history explicitly says running/pending/queued/
executing with `completed: false` — and only then
emits `{job_id, current_stage, stage_detail: "comfy executing (<elapsed>s)"}` for **`request.job_id`**
(the runner-owned job, `Pipeline._current_job_id`). The runtime-status merge keeps the last real
progress, step and ETA values: **no percentage or step count is invented**, and the operator sees
only the elapsed time of a prompt the server confirms is running. The watchdog already ignores any
status whose `job_id` is not the runner's current job, so a heartbeat cannot be borrowed from the
next queued job or a stale prior job.

Bounds preserved:

- **Unreachable/unresponsive Comfy** (`/queue` errors or times out): no liveness is emitted, so the
  watchdog stalls at 90 s exactly as before, and the backend still fails at its execution bound.
- **Responsive Comfy that does not know the prompt** (in neither queue nor history): no liveness;
  same result.
- **Comfy that reports the prompt running forever:** liveness continues only until the backend's
  own `history_timeout` (120 s default; TI2V-5B `@1.1.0` declares 600 s and Animate-2 declares
  1200 s), which raises `TimeoutError`.
  Liveness is never a substitute for that bound.
- **Terminal failed Comfy history:** the backend raises a failure promptly and emits no further
  liveness, even if a stale queue response still lists the prompt. A history entry without an
  explicit nonterminal status does not itself count as liveness.
- WebUI/A1111 no-progress semantics, native SVD thresholds, the once-per-episode cooldown, process
  ownership and cancellation are untouched. `RUNNER_STALL_S` is not raised.

No WebSocket or new transport is used; only the existing `ComfyApiClient` `/queue` and `/history`
HTTP surfaces.

## Reproduction evidence (2026-09-29, owner runtime)

Two successful Comfy video jobs each produced a spurious `queue_runner_stall` bundle about 90 s in:
one completed in ~94 s (bundle at the ~90 s boundary), a longer 81-frame job completed in ~221 s.
Both reached `completed` with one output artifact, and StableNew-owned Comfy was released afterward.
This is watchdog/observability evidence only; it says nothing about Animate-2 quality. Deterministic
reproduction (fake clock, real merge and watchdog): without liveness the first stall is reported at
92 s for both 94 s and 221 s jobs; with it, no stall for 94 s, 221 s and 600 s jobs.

## Validation

`tests/video/test_pr_runtime_110_comfy_liveness.py` covers: healthy 94/221/600 s runs are not stalls
under the actual TI2V-5B/Animate-2 workflow timeout declarations;
liveness is bounded, job-scoped and invents no progress; a foreign job's heartbeat does not count;
unreachable and prompt-unknown Comfy still stall at ~92 s and fail at the bound; endless "running"
responses end at the backend bound; the reporter is inert without a job or status path; and
`_prompt_is_live` requires the server to list the prompt. Terminal failed history emits no
liveness; explicit nonterminal history can emit it; ambiguous history without queue membership
remains stall-detectable. The existing watchdog/runtime suites
(`test_pr_harden_008`, `test_pr_harden_009`, `test_watchdog_ui_stall`) guard the SVD, WebUI and
cooldown semantics.

## Not in this package

A1111 intentional termination logged as `exit_code=1` at ERROR severity; startup
`ui_heartbeat_stall` bundles; Engine Settings / tracked `presets/settings.json` ownership;
`STABLENEW_COMFY_BASE_URL` precedence; Animate-2 product quality; output-route behavior.
