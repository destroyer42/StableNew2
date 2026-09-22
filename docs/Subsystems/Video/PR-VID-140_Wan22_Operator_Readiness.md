# PR-VID-140 â€” Wan2.2 Operator Readiness

Status: **COMPLETE / ACCEPTED / INTEGRATED**. This package adds no backend, queue, lifecycle,
scheduler, or runtime-ownership authority.

## Execution profile and validation plan

- Execution class: Standard; Local/Desktop; GPT-5.6 Terra High.
- Local execution was necessary because acceptance depended on the configured Comfy process, GPU
  telemetry, SQLite history, and one target-machine generation.
- Controller Surface Assessment: `VideoWorkflowController` remains admission-only. It creates no
  graph, selects no backend, and starts no runtime; the controller ratchet did not increase.
  `VideoExecutionResolver` remains the sole backend-selection authority.
- Token-Efficient Validation Plan: reuse unchanged VID-140 deterministic evidence, test the
  manager/harness repairs directly, use one startup-only check before one allowed generation, then
  use required GitHub CI as the Python-version verdict.

## Accepted operator contract

- `ltx_multiframe_anchor_v1` and `ltx_multiframe_anchor_v1_conditioned` are retained catalog
  metadata but **disabled**. Required `StableNewLTXAnchorBridge` / `StableNewLTXDepthControlBridge`
  implementations and accepted real evidence are absent, so they are neither offerable nor runnable.
- Wan `wan22_ti2v_5b_i2v_v1` v1.0.0 remains experimental and per-job opt-in. It accepts source
  image, prompt, negative prompt, and seed only; unsupported motion, anchor, camera, depth, and
  control inputs are not submitted.
- Blank/`Random` seed is frozen before queue admission; an explicit valid seed is preserved.
  Replay keeps that seed and creates a new identity with parent lineage.
- Catalog-declared preparation applies EXIF transpose, RGB conversion, cover-resize, and
  center-crop. Portrait/square use 480x832 and landscape uses 832x480. The original/prepared
  paths, dimensions, policy, and orientation rule are frozen into the immutable NJR.

## Managed-Comfy readiness repair

The first real invocation failed before readiness, model loading, Comfy prompt dispatch, or
generation. Existing evidence retained an owned launch and refused `127.0.0.1:8000/system_stats`,
but no PID, return code, output tail, or port history. Its supported classification is
**`insufficient_existing_evidence`**, not a Wan execution failure.

The source defect was exact: settings mapped `comfy_health_total_timeout_seconds=30.0` to
`ComfyProcessConfig.startup_timeout_seconds`, but `ComfyProcessManager.check_health()` used a
hard-coded 15 seconds and one-second poll. It now passes the configured timeout and poll interval
to `wait_for_comfy_ready`; it adds no retry, extension, discovery, adoption, or new manager.
For an owned managed-start failure, bounded available diagnostics now include PID, alive/exited
state and return code, endpoint, timeout, and final stdout/stderr tails. Unowned processes remain
untouched.

Startup-only verification used a free configured endpoint and manager-owned PID 34228. It became
healthy in 12.8 seconds under the configured 30-second timeout, was alive before teardown, then was
stopped by its owner. A bounded stderr database-initialization warning was non-fatal because the
server reached readiness; no environment, package, model, or configuration was changed.

## Real acceptance evidence

One authorized landscape run entered Video Workflow -> immutable NJR -> JobService -> SQLite ->
`PipelineRunner.run_njr` -> `VideoExecutionResolver` -> Comfy. Job
`a50eb994bc2840eaba84c835316bfff5` used `backend_id=comfy`, workflow
`wan22_ti2v_5b_i2v_v1` v1.0.0, explicit opt-in, and frozen seed `1733123036`.

| Evidence | Observed result |
|---|---|
| Geometry | Source 1024x576 -> prepared 832x480 landscape PNG; compiled graph used 832x480 |
| Output | Valid 615,096-byte MP4; 49 frames, 24 fps, 832x480, 2.0417 s |
| Duration | 92.6 s wall time |
| GPU | 1,127 MiB baseline; 11,635 MiB peak; 71 C peak; 234.62 W peak; no GPU loss/reset |
| Host RAM | 0.01 GB minimum available during known narrow-headroom loading; no stability or root-cause claim |
| History/replay | Canonical manifest persisted. Queued replay `c87894b48d3a4180a41a4f05cb3e1790` has parent `a50eb994bc2840eaba84c835316bfff5` and identical `video_execution`. |
| Visual smoke | A decodable contact sheet shows coherent frames and temporal movement; it is not a new quality or identity claim. |

The acceptance harness previously selected the first queued replay in a reused scratch database,
which could report an older parent despite creating the correct replay. It now selects the queued
job whose immutable NJR parent is the completed acceptance job. Direct SQLite evidence above
confirms the actual replay; no second generation was run.

The manager-owned Comfy process was released after completion and GPU telemetry returned to idle.
This is one successful post-baseline DIAG-GPU-120 exposure with no black-screen/max-fan/GPU-loss
recurrence, not a PASS/FAIL or root-cause conclusion.

## Architecture and lifetime review

- `PipelineRunner` has no Wan, LTX, model, or workflow-name routing. It resolves video only through
  `VideoExecutionResolver`. Runtime reads NJR-derived config and does not mutate an NJR.
- GUI projects catalog/operator state only; raw Comfy graph templates remain catalog/adapter-private.
  `ComfyWorkflowVideoBackend` preserves frozen preparation provenance only in result metadata.
- Prepared source PNGs are deterministic, bounded input/provenance evidence below the ordinary
  output root. They are referenced by immutable NJR, replay, and manifest; they are not result
  artifacts or a second history/lifecycle authority. No generic deletion authority was introduced.
- External Comfy/A1111 ownership is unchanged. The harness stopped only its own manager-owned
  process.

## Validation

- Focused deterministic suite: **81 passed, 2 skipped**. Skips are the existing local Tcl/Tk
  installation condition, not source-test failures.
- Ruff on all touched source/tests/tools: pass. Controller ratchet: pass (four ratcheted
  controllers; new-controller limit 600). `git diff --check`: pass.
- Local `python tools/ci/run_pr_gate.py` was attempted once and is a tooling blocker because local
  `mypy` is unavailable, not a source/test failure.
- GitHub Actions run [35729678881](https://github.com/destroyer42/StableNew2/actions/runs/35729678881)
  for source SHA `2d1b2ff4bff4204b4120c74d23f421510d09dc68`: required Python 3.11 and 3.12 passed.
  Informational full-suite 3.11/3.12 jobs failed in their `xvfb-run` environment path and remain
  non-blocking debt.

## Explicit exclusions

No main integration, LTX bridge implementation, Comfy installation or environment repair, timeout
increase, automatic retry, runtime adoption, GPU/system setting change, or second Wan generation.
