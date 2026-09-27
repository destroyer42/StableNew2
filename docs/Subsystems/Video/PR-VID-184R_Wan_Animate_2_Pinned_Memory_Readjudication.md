# PR-VID-184R - Wan-Animate-2 Pinned-Memory / HostBuffer Re-adjudication

Status: **`PR-VID-184R — COMPLETE — WAN_ANIMATE_2_LOCAL_EXECUTION_PASS_WITH_PINNED_MEMORY_DISABLED;
PINNED_MEMORY_PATH_MATERIALLY_IMPLICATED; MOTION PARTIAL`**. Qualification and evidence only: no
production `src/` change, no backend, workflow registration, controller, GUI, queue, runner or
process-manager change.

## Question and design

PR-VID-184 (integrated, `main` `876db65`) lost the GPU during sampling step 10 of 10 of the frozen
Wan-Animate-2 Distilled workload, with `hostbuf_file_reader_read failed` in the traceback and Windows
commit at ~95–98 %. Open upstream ComfyUI reports (`#14250`, `#15255`, both still open and unfixed when
checked) describe HostBuffer read failures that reporters say `--disable-pinned-memory` avoids.
They are not StableNew evidence (other hardware, versions, and in `#15255` multi-GPU), so they justify a
controlled re-test, not a conclusion.

One-variable question: **does disabling ComfyUI pinned memory prevent or materially alter the
sampling-stage device loss under an otherwise identical frozen workload?** Arm A is the accepted
PR-VID-184 run (not rerun). Arm B is the same isolated environment and workload with only
`--disable-pinned-memory` added. One GPU submission was authorized and used; no retry.

## Evidence lock

- In the pinned revision (`comfy/cli_args.py`, `model_management.py`, `pinned_memory.py`) the flag
  disables the pinned-memory budget (on Windows 40 % of RAM; Arm A logged `Enabled pinned memory
  13010.0` MiB) and turns `pin_memory`/`get_pin` into no-ops. It does not disable dynamic VRAM, and
  `handle_pin` still performs the file read without a pin, so the flag changes host staging but does not
  necessarily remove the HostBuffer read path. No hidden second behavior change was found in those
  functions; that is source reading, not a runtime measurement.
- Preserved PR-VID-184 environment reused unchanged and re-verified: ComfyUI `v0.37.0`
  (`73c9bad4d21e7addbe1d13bc92eee0f1431b017d`), Python 3.11.9, torch `2.14.0+cu130`, `comfy-aimdo 0.5.5`,
  `comfy-kitchen 0.2.35`, frontend 1.52.7; all four model hashes, both input hashes, and the flattened
  graph (`9ef8dae4…`) match PR-VID-184's records. StableNew-managed Comfy untouched. No Comfy/PyTorch
  upgrade.
- Deterministic manifest diff (`tools/qualification/vid184r/arm_manifest.py`, 7 tests): the only
  differences are the launch flag and arm/evidence metadata; no forbidden second-variable flag in either arm.
- Preflight (dry-run, no submission): gates passed, flag effect verified (no `Enabled pinned memory`
  line), qualification-port listener confirmed as the harness-owned process tree, teardown clean.

## Arm B result

| | Arm A (PR-VID-184) | Arm B (184R, `--disable-pinned-memory`) |
| --- | --- | --- |
| Outcome | GPU device loss at sampler step 10/10, no output | **Completed**, `execution_success`, 10/10 steps, output produced |
| Sampling | ~14.5 s/it (9 steps done) | ~14.6 s/it; `Prompt executed in 163.99 s` |
| Model staging log | dynamic VRAM, same staged sizes | identical (dynamic VRAM still on) |
| HostBuffer / CUDA errors | `hostbuf_file_reader_read failed`, sticky CUDA error | none; 0 tracebacks |
| Commit at start of monitoring | 86.68 % (preflight 57.78 %) | 34.21 % |
| Commit peak / steady | 98.15 % / ~95.1–95.9 % | 57.46 % / ~53.4–53.8 % |
| Min commit headroom / min physical available | not captured | 23.3 GB / 11.83 GB |
| GPU memory used peak | 10,600 MiB (sampled) | 11,881 MiB (during staging) |
| GPU temp / power peak | 77 °C / 253 W | 81 °C / 256 W |
| Post-run GPU | lost, reboot required | healthy (`nvidia-smi` normal), owned process torn down, exit code recorded |

Not captured in Arm B: a valid per-process working set (the harness sampled the venv launcher shim's
PID) and shared-GPU-memory behavior. The harness applied the accepted commit-aware safety stop
(≥97 % commit or <1 GB headroom for 2 consecutive samples); it never triggered. Arm A recorded telemetry
only, so that is a safeguard difference, but it could only have ended Arm B early, not altered a run
that completed.

Output: `vid184_run5_generated_00001_.webm`, sha256 `c669c216…`, VP9, 24 fps, **41 decoded frames**,
geometry **480×848** (the template derives width/height at runtime; PR-VID-184 never reached the point
where this was observable, and earlier text expecting 480×832 is corrected here). Trimmed per the
frozen contract to exactly 39 frames (`420a5b50…`) with no resampling.

## Uncontrolled differences (limits on the comparison)

This is one Arm-B run against one Arm-A run, and the machine state was not identical: Arm B ran ~30 min
after a fresh boot with commit at 28–34 % (Arm A preflight was 57.8 %, physical RAM available 12.1 GB vs
18.7 GB); pagefile usage was 0; and a marginal failure could vary run to run. The commit rise during the
workload was roughly +12.7 GB in Arm B (34.2 → 57.5 %) versus roughly +22.5 GB in Arm A (57.8 → 98.2 %
from preflight), a suggestive difference but not one this design can attribute solely to the flag.
Kernel-Power 41 and 6008 events exist at the recovery boot ~20 minutes after Arm A's run (outside the
10-minute window PR-VID-184 inspected); their cause is not established and they are not attributed to
either arm. Nothing in Arm B's window or after it added any event.

## Classification

- **Execution:** `WAN_ANIMATE_2_LOCAL_EXECUTION_PASS_WITH_PINNED_MEMORY_DISABLED` — for this one
  frozen envelope, one run, on this workstation.
- **Causal:** `PINNED_MEMORY_PATH_MATERIALLY_IMPLICATED`. With the frozen workload unchanged except for
  disabling pinned memory, the workload that previously lost the GPU during step 10/10 completed. This
  materially implicates the pinned-memory/HostBuffer execution path as a contributor, but does not prove
  it was the sole cause, and the system-state differences above are not excluded. Not established: the
  mechanism, whether commit pressure or the HostBuffer read was the proximate cause, that the failure
  is reproducible in Arm A, or anything about the historical DIAG-GPU-130 black screens.
- **PR-VID-184 is not wrong:** it accurately records the behavior of its tested configuration
  (`GPU_DEVICE_LOSS_DURING_SAMPLING`). This result narrows its *configuration-specific* local-hardware
  NO-GO: the "hardware-only" reading is weakened; that configuration's failure appears to depend on a
  ComfyUI runtime setting (n=1 vs n=1). The old run is not rewritten.

## Frozen capability metrics (thresholds unchanged, contract hash `30608f7a…`)

On the 39-frame output: `primary_subject_continuity` 1.00 (pass); `ghost_actor_persistence` 0 (pass);
`root_translation_fraction` 0.623 (pass, subject centroid x 71→370 of 480); `motion_curve_correlation`
**0.151 (below the 0.30 gate**, above the ~0.10 noise floor). Corroborating only:
`identity_hist_mean` 0.949 (palette-dominated), camera drift ~0, motion-area 0.274.

Agent visual inspection of the full contact sheet (not the owner's verdict): a single figure matching the
reference (navy V-neck tee, navy leggings, white/teal sneakers, pale lavender/green backdrop) performs a
high-knee drill and travels left to right; no second figure; hair changes from the reference's pulled-back
style, some background blotching and banding, mostly plausible anatomy. Clean left/right leg alternation
cannot be confirmed from stills.

**Motion-quality classification: PARTIAL.** Three of four frozen gates pass and the qualitative picture is
the first in this line of a reference-looking subject carrying the driving motion without a ghost, but the
timing-correlation gate is not met, this is one seed and one 1.625 s case, and the human verdict gate has
not been run. Resource-path PASS is kept separate from this and does not imply a capability PASS. Model
capability is no longer untested for this case; it is PARTIAL and unadjudicated.

## Architecture, validation, boundaries

No production change; the canonical `Intent → … → PipelineRunner.run_njr → VideoExecutionResolver →
backend` path is untouched and the isolated qualification Comfy remains disposable evidence
infrastructure. Validation: `tests/tools/test_vid184r_arm_manifest.py` (7) plus the PR-VID-184 tool tests,
Ruff, `git diff --check`, no `src/` diff, managed Comfy unmodified; required GitHub CI is the integration
verdict. Not a GPU stability test: DIAG-GPU-130 is not resolved by this result and its interpretation is
unchanged. No further GPU run is authorized.

## Next owner decision

Not selected here. Reasonable branches: record a human visual verdict on the output; decide whether a
replicate/second-seed adjudication or the paid remote baseline from PR-VID-184 is worth its cost; or
decide whether a future experimental `backend_id=comfy` package (with pinned memory disabled recorded as
a required launch condition) is warranted. All require separate authorization.
