# DIAG-GPU-100 — Hard-Crash Correlation and Survivor Telemetry

## Status

**Evidence record and observation-only telemetry: COMPLETE.** This is not a
root-cause verdict and does not authorize a BIOS, driver, power, memory,
process-lifecycle, or GPU-workload change.

## Execution profile

- Classification: Standard local diagnostic/hardening work.
- Model/reasoning recommendation: GPT-5.6 Luna — High. The work couples local
  Windows evidence, mutable user runtime state, and a narrow source seam; a
  lower nominal-cost model materially increases evidence-correlation and
  lifecycle-boundary retry risk.
- Controller surface assessment: not applicable. No controller/coordinator was
  changed; `PipelineRunner` only starts and stops an observation-only helper.
- Token-efficient validation: deterministic recorder/correlation tests, changed
  file Ruff, and the controller ratchet. No GPU workload, stress test, A1111
  restart, Comfy restart, or production process action is part of validation.

## Machine baseline observed 2026-09-21

| Surface | Observed state | Interpretation |
|---|---|---|
| OS | Windows 11 Home, build 26100; booted 2026-09-21 08:20 ET | Recorded baseline only. |
| CPU / board / BIOS | Intel Core i9-13900K; ASRock Z690-C/D5; BIOS 16.01, release date 2025-10-22 | Windows reports microcode revision bytes consistent with `0x147`; the active BIOS power profile cannot be proved from Windows. |
| RAM | 2 x 16 GiB Micron CP16G60C36U5B.M8D1; module speed field 5600 MT/s; configured 6000 MT/s at 1.35 V | The configured memory rate is above Intel's published DDR5-5600 maximum for the i9-13900K. This is a confounder, not proof of fault. |
| GPU | RTX 4070 Ti, 12,282 MiB; driver 616.92 / Windows 32.0.16.1692; VBIOS 95.04.3c.80.52; PCIe Gen4 x16 | At collection: 39 C, 34.23 W of 285 W limit, 1,508 MiB used. This idle snapshot is not a crash snapshot. |
| OS settings | High Performance plan; HAGS registry value not configured | HAGS effective state is unknown without the Windows graphics UI. |
| Unknown hardware facts | PSU model/rating, cable topology, GPU seating, and BIOS Intel Default/Baseline selection | Not observable safely from this session. |

Intel's current guidance for affected 13th/14th-generation desktop processors
is Intel Default Settings and BIOS microcode `0x12F` or later. ASRock documents
both BIOS Default and Baseline Mode profiles for Intel 600/700-series boards.
The observed Windows microcode is later than that threshold, but the actual
BIOS power profile remains unverified. Intel also lists DDR5-5600 as the
i9-13900K maximum supported memory type.

## Incident correlation

Times below are local ET. `KP41` means a Kernel-Power 41 restart record with
an accompanying unexpected-shutdown record. It is a restart marker, not a
cause. The machine-readable record is ignored runtime output:
`reports/diagnostics/diag_gpu_100_incident_timeline.json`.

| Incident | OS/GPU evidence | Durable StableNew state | A1111 capture near incident | Classification |
|---|---|---|---|---|
| 2026-09-07 17:39:43 | KP41 | No active SQLite job; no nearby lifecycle row | Progress capture | Open/no proven generation |
| 2026-09-07 18:54:37 | KP41 | No active SQLite job; no nearby lifecycle row | Progress plus CUDA unknown-error responses | Open/no proven generation |
| 2026-09-07 19:34:25 | KP41 | No active SQLite job; no nearby lifecycle row | Progress plus CUDA unknown-error responses | Open/no proven generation |
| 2026-09-09 05:04:19 | KP41 | No active SQLite job; no nearby lifecycle row | No retained window | Evidence unavailable |
| 2026-09-09 05:48:04 | KP41; later BugCheck `0x133` record | No active SQLite job; no nearby lifecycle row | Progress capture | Open/no proven generation |
| 2026-09-13 18:57:58 | KP41 | No active SQLite job; no nearby lifecycle row | Progress plus CUDA unknown-error responses | Open/no proven generation |
| 2026-09-14 07:44:09 | KP41; later BugCheck `0x133` record | No active SQLite job; no nearby lifecycle row | Progress capture | Open/no proven generation |
| 2026-09-15 19:12:45 | KP41 | No active SQLite job; no nearby lifecycle row | Files written after restart only | Evidence unavailable |
| 2026-09-16 06:20:25 | KP41; `WATCHDOG` and `WATCHDOG4401` dumps timestamped 06:20:25 | No active SQLite job; no nearby lifecycle row | Generation stopped at 37/47; CUDA unknown errors; new capture begins 06:26 | Open/no proven generation |
| 2026-09-16 08:07:04 | KP41; `WATCHDOG` and `WATCHDOG4401` dumps timestamped 08:07:03 | No active SQLite job; no nearby lifecycle row | Generation stopped at 12/30; CUDA unknown errors | Open/no proven generation |
| 2026-09-18 05:30:39 | KP41 | No active SQLite job; no nearby lifecycle row | No retained window | Evidence unavailable |
| 2026-09-18 20:47:41 | KP41 | No active SQLite job; no nearby lifecycle row | Progress plus CUDA unknown-error responses | Open/no proven generation |
| 2026-09-19 14:17:52 | KP41 | No active SQLite job; 8 nearby jobs all started after incident (+474-594 s) | Progress plus CUDA unknown-error responses | Nearby lifecycle; no proven active generation |
| 2026-09-19 17:15:50 | KP41 | No active SQLite job; no nearby lifecycle row | Progress plus CUDA unknown-error responses | Open/no proven generation |
| 2026-09-21 08:19:03 | KP41 | No active SQLite job; no nearby lifecycle row | No retained window | Evidence unavailable |

There were no WHEA records in the reviewed interval. `nvlddmkm` Event 153
(`GPUID: 100`) occurred repeatedly in the same period, but was not present at
every shutdown timestamp. WER contains repeated LiveKernelEvent 141/1A8/1B8
records; its reporting times can be delayed and duplicate, so dump timestamps
and reboot records are the primary timeline anchors. Windows reports two
`0x133` bugchecks (2026-09-09 and 2026-09-14). The named minidumps are access
restricted and no installed debugger was available, so no dump stack analysis
is claimed.

The A1111 text reports `CUDA error: unknown error`; generic diagnostic text in
those responses must not be read as a confirmed illegal-memory-access finding.
The capture identifies an interrupted CUDA/A1111 workload, but cannot identify
the request origin. No StableNew SQLite job was active at exact recorded
shutdown timestamps. Nearby lifecycle correlation must be considered separately;
exact-time absence alone does not establish earlier StableNew execution could not
have participated in the failure sequence. In the regenerated September record,
the only nearby jobs were eight jobs that started after the 2026-09-19 14:17:52
incident; no nearby terminal-before-incident job was observed.

## Ranked hypotheses

1. **GPU/display-driver/device reset under CUDA workload — high confidence as
   the failure domain, not a component-level root cause.** Repeated GPU
   LiveKernel signatures, `nvlddmkm` Event 153, black-screen symptom, watchdog
   dump pairs, and interrupted A1111 CUDA calls converge here. Driver updates
   have not eliminated it. Counterevidence: no per-second pre-crash telemetry
   existed, and successful heavy SVD runs show utilization alone is insufficient.
2. **Platform stability / memory or CPU operating baseline — medium confidence
   as a confounder.** DDR5 is configured at 6000 MT/s while the CPU's published
   maximum is 5600; Intel Default/Baseline selection is unverified. Counterevidence:
   no WHEA event was found and the observed microcode is later than Intel's
   stated minimum, neither of which rules this class out.
3. **GPU power delivery, board slot/cabling, or GPU hardware — medium-low
   confidence, unresolved.** Fan-max/black-screen behavior and GPU reset signs
   fit, but PSU/cabling/physical state were not observable and no sensor trace
   exists for a crash. No physical intervention was performed.
4. **StableNew queue/orphan-thread execution defect — low confidence as the
   immediate crash cause.** Every incident has zero exact-time active SQLite
   jobs; one incident also has nearby jobs, all starting after the incident,
   while eleven have A1111 activity without job provenance. This does not rule
   out a separate residency/process issue. Exact-time absence alone is not a
   causal conclusion.

## Delivered observation boundary

`GpuSurvivorTelemetry` begins only for a GPU-capable NJR inside
`PipelineRunner.run_njr` (including train-LoRA). It records immediate job/stage
events and approximately one-second samples with UTC and monotonic timestamps,
job/run/backend/stage/workflow identity, resolved video backend/workflow identity,
GPU utilization/memory/temperature/
power/clocks/P-state/PCIe data, host available memory, and cheap process-risk
presence at boundaries. Each small JSONL record is appended and fsynced; files
rotate with a bounded retained history. Prior data is never deleted merely
because a later process starts.

The observer emits `backend_resolved`, `generation_dispatched` immediately before
the selected image backend or resolver-returned video backend executes,
`publication_boundary` only after successful output/checkpoint publication, and a
terminal `job_finished` outcome. Neutral Comfy/Wan records `comfy` plus its
workflow id/version; native SVD records `svd_native`; legacy video bridge work
uses the same resolver-returned identity. Cancellation is recorded as
`cancelled`, not as a successful runner finish.

The recorder cannot alter an NJR, SQLite, queue state, retry/cancel outcome,
GPU setting, A1111/Comfy/SVD process, or runtime ownership. A recorder failure
is contained. `tools/diagnostics/correlate_gpu_incidents.py` reads SQLite in
read-only mode and reports exact active overlap separately from nearby lifecycle
rows (`completed_before_incident`, `failed_before_incident`,
`started_after_incident`, or `active_at_incident`). It preserves unknown and
unavailable coverage rather than treating it as absence of StableNew.

## Next isolation experiment — requires owner approval

Do not run a synthetic stress test. The smallest useful change is one
reversible BIOS-baseline experiment: capture the current BIOS pages, select
ASRock **Baseline Mode** (Intel Baseline), disable XMP if that profile does not
already return memory to the module/CPU-supported 5600 MT/s rate, reboot, and
verify the resulting frequency/profile. Then use only ordinary workloads while
the survivor recorder collects evidence. Do not combine this with a driver,
HAGS, power-limit, VBIOS, cable, or GPU-clock change. A recurrence with the
new trace determines the next isolation; no recurrence is not a root-cause
verdict.

## Validation

- `15 passed`: survivor recorder, pipeline observer boundary, cancellation,
  resolver identity, and synthetic correlation coverage tests.
- Changed-file Ruff passed.
- Controller surface ratchet passed; no controller source changed.
- Existing `test_pipeline_runner_njr_diagnostics.py` was attempted but is
  ambient-runtime dependent in this workstation state: its fake runner reached
  the live external/ambiguous Comfy transition guard before its fake stage.
  This is neither a telemetry assertion failure nor a source regression.
- Source commit `21ebc891dca02206a21c40144f0646b8bf628b51` passed GitHub Actions
  run 35679785268 required Python 3.11 and 3.12 jobs. Its informational
  full-suite jobs failed in the established broader-suite debt surface; the
  workflow's required conclusion was success and DIAG-GPU-100 does not repair
  unrelated suite failures.
- No GPU, A1111, Comfy, SVD, process, driver, BIOS, registry, power, or stress
  operation was performed for DIAG-GPU-100 validation.
