# DIAG-GPU-120 — DDR5-5600 XMP Isolation

## Status

**OBSERVATION IN PROGRESS.** This is an initial post-change checkpoint, not a PASS, FAIL, root-cause, or stability verdict. Ordinary StableNew use is the only authorized exposure source; no workload was created for this diagnostic.

## Execution profile

- Classification: Standard local diagnostic observation.
- Model/reasoning recommendation: GPT-5.6 Terra — Medium. This bounded, read-only comparison of local Windows and accepted repository evidence must avoid presenting an XMP-profile change as a frequency-only or causal test.
- Controller surface assessment: not applicable. No StableNew source, controller, runtime, queue/history, telemetry, or diagnostic utility changed.
- Token-efficient validation plan: inspect the integrated telemetry seam and historical tail, capture the OS-visible platform state once, review the transition/event boundary, then validate the documentation-only diff. No source test, CI, GPU workload, synthetic stress, process action, or machine setting action is part of this checkpoint.

## Intervention and transition boundary

The operator changed the BIOS XMP profile from **DDR5-6000 to DDR5-5600**. XMP remains enabled. This is not XMP-off/JEDEC memory, motherboard defaults, or Intel Baseline/Default mode.

The exact time of the BIOS edit is not directly evidenced. The defensible configuration-transition boundary is the clean Event Log shutdown at **2026-09-22 07:39:34 ET** (Event 6006) and the following Windows boot at **2026-09-22 07:42:38 ET** (`Win32_OperatingSystem.LastBootUpTime`; Event 6005 at 07:42:50 ET). The profile transition occurred at or before that boot, but its exact BIOS-screen timestamp is unknown.

## Memory comparison

| Surface | Pre-change accepted evidence | Post-change directly observed 2026-09-22 | Interpretation |
|---|---|---|---|
| XMP profile | DDR5-6000 XMP | Operator reports DDR5-5600 XMP remains enabled | Operator-confirmed intervention; Windows does not expose the XMP enablement field here. |
| Configured clock | 6000 MT/s | 5600 MT/s on both DIMMs | Primary acceptance question: **yes**, Windows now shows approximately DDR5-5600 rather than DDR5-6000. |
| Module-reported speed | 5600 MT/s | 5600 MT/s on both DIMMs | No observed change in this SMBIOS field. |
| Configured voltage | Approximately 1350 mV | 1250 mV on both DIMMs | Observable difference; no claim about BIOS timing or controller behavior follows. |
| Timings / controller parameters | Not retained | Not exposed by this read-only Windows capture | Unknown. |

| Slot | Manufacturer / part / serial | Capacity | `Speed` | `ConfiguredClockSpeed` | `ConfiguredVoltage` |
|---|---|---:|---:|---:|---:|
| `Controller0-ChannelA-DIMM1` | Micron Technology `CP16G60C36U5B.M8D1`, `EB472282` | 16 GiB | 5600 MT/s | 5600 MT/s | 1250 mV |
| `Controller1-ChannelA-DIMM1` | Micron Technology `CP16G60C36U5B.M8D1`, `EB472250` | 16 GiB | 5600 MT/s | 5600 MT/s | 1250 mV |

Windows reports 33,307,708 KiB total visible memory (approximately 32 GiB). The intended experimental variable is the lower XMP profile, not a proven frequency-only change: the observed voltage difference and unobserved timings, memory-controller behavior, and other XMP-derived parameters are material evidence limitations.

## Platform and held-constant evidence

| Surface | Current direct observation | Comparison with accepted baseline |
|---|---|---|
| CPU | 13th Gen Intel Core i9-13900K, 24 cores / 32 logical processors | Same CPU class. |
| Board / BIOS | ASRock Z690-C/D5; AMI BIOS 16.01, release date 2025-10-22 | Same as DIAG-GPU-100 record. |
| GPU | RTX 4070 Ti; driver 616.92; VBIOS `95.04.3c.80.52`; 285 W limit | Same GPU, driver, and VBIOS recorded by DIAG-GPU-100. |
| Windows / power plan | Windows 11 Home build 26100; High performance | Same accepted OS line and power plan. |
| HAGS registry field | `HwSchMode` not configured | Same registry observation as DIAG-GPU-100; effective HAGS state remains unverified. |
| CPU microcode evidence | Current registry `Update Revision` raw value `2F010000` | The prior record's `0x147` notation was not reproduced by the same documented method, so microcode constancy cannot be claimed from this checkpoint. |
| BIOS profile / CPU limits | Not exposed safely from Windows | Operator reports no intentional Intel Baseline/Default or CPU change; independent verification is unavailable. |
| GPU clocks / power settings | No configuration comparison mechanism used | Operator reports no intentional change; current telemetry/power limit is not a setting-history proof. |
| StableNew source/runtime | `main` baseline `f5dfe1533f1489e3559ae4fc1e27ae8e0e03f180`; no diagnostic source change | No source/runtime change is associated with the machine experiment. |

## Post-change crash and telemetry baseline

At the checkpoint there are no retained post-boot Kernel-Power 41, Event 6008, BugCheck, WHEA, Display, `nvlddmkm`, NVIDIA, or LiveKernelReport artifacts. The latest retained unexpected-shutdown markers remain Kernel-Power 41 at 2026-09-21 08:20:20 ET and Event 6008 at 08:20:30 ET, describing the 2026-09-21 08:19:03 ET shutdown. The latest retained `nvlddmkm` Event 153 is 2026-09-21 10:26:05 ET. The latest BugCheck record remains the inaccessible 2026-09-14 `0x133 Arg1=1` record. No WHEA record was returned from the retained System log.

The current LiveKernelReports inventory contains only historical September 16 WATCHDOG/WATCHDOG4401 artifacts plus an out-of-scope March dump; it contains no new post-transition artifact.

DIAG-GPU-100 survivor telemetry remains integrated in `src/utils/gpu_survivor_telemetry.py` and is started from `PipelineRunner`. The historical tail ends at **2026-09-22 07:38:41 ET**, before the transition boot, with a recorded completed A1111 `txt2img` job. It provides no post-change samples: post-change GPU-capable StableNew job count and exposure are therefore **zero at this checkpoint**. The mechanism and retained output path are available for ordinary-use observation.

## Observation rules

Future ordinary StableNew GPU jobs are the exposure source. Record job count, backend/stage, duration, completion/failure, and the integrated telemetry's GPU memory, temperature, power, and uptime context where available. Do not create load solely to accumulate evidence.

If the established black-screen/max-fan/GPU-loss failure recurs, stop deliberate GPU work, do not automatically retry the failed job, preserve survivor telemetry and Windows/WER/LiveKernel evidence, and correlate it against DIAG-GPU-100/110 before another variable changes. Recurrence would show that this DDR5-5600 XMP transition was insufficient to eliminate the failure; it would not prove memory uninvolved. Conversely, no immediate recurrence is not a PASS or proof that DDR5-6000 caused prior failures.

## Boundaries and validation

- Other than the prior operator-performed XMP DDR5-6000 to DDR5-5600 transition, no machine setting was changed by this checkpoint. In particular, XMP was not disabled and no manual frequency, timing, voltage, CPU profile/limit, BIOS, NVIDIA, HAGS, Windows power-plan, GPU clock/power, or physical hardware change was made.
- No StableNew production source, test, queue/history authority, or runtime process was modified; StableNew was not launched and no image/video was generated for DIAG-GPU-120.
- Direct post-change configuration capture, transition-boundary review, historical/post-change separation, telemetry readiness inspection, final documentation diff review, and `git diff --check` are the applicable validation. Source CI is not applicable.
