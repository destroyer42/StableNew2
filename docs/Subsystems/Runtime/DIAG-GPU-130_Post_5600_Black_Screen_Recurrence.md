# DIAG-GPU-130 - Post-DDR5-5600 Black-Screen Recurrence

## Status

**XMP-OFF RECURRENCE - ACTIVE OBSERVATION / EXIT CRITERION NOT MET.** This evidence-only package
records the 2026-09-23 recurrence with proven immediately preceding StableNew/A1111 `txt2img`
work and a further 2026-09-26 post-XMP-OFF recurrence with WER `141`/`1B8` artifacts and an
unexpected restart. The latter retains known immediately preceding PR-VID-184 Arm A
Wan-Animate-2 GPU-loss workload context, about 20 minutes before the Kernel-Power 41/6008
recovery boot, but no continuous survivor telemetry ties the exact `141`/`1B8` interval to that
workload. It is therefore classified as the known display/live-kernel family without workload
attribution. That temporal correlation neither causes the restart nor proves or falsifies
failure-family equivalence. Nothing here attributes either failure to StableNew, A1111, NVIDIA,
the GPU, power delivery, PCIe, RAM, or any other component.

**Amended conclusion (2026-09-24, product-owner direction):** NVIDIA driver-package isolation is
**deprioritized** by cross-version recurrence evidence - the failure family has recurred across
driver versions, so a driver-package change is no longer the recommended next variable. The next
isolation should target the **platform baseline, one variable at a time** (see "Next single
isolation variable"). This amendment changes the recommendation only; it adds no new incident
evidence to this package and attributes no component. The cross-version recurrence evidence is
owner-supplied and is not reproduced in this document.

## Execution profile

- Classification: Standard local forensic diagnostic work.
- Model/reasoning recommendation: GPT-5.6 Terra - High. Cross-source timestamp reconciliation,
  survivor telemetry interpretation, and non-attribution from incomplete dumps require a
  deliberate evidence pass.
- Controller surface assessment: not applicable. No controller, coordinator, runtime, queue,
  telemetry implementation, or diagnostic source changed.
- Token-efficient validation plan: preserve survivor telemetry and retained logs once, collect
  focused Windows evidence, run the existing read-only correlator, inspect only durable fields
  necessary for the factual workload, and validate the documentation-only diff. No GPU workload,
  process action, test, CI, driver, BIOS, power, or hardware action is in scope.

## Evidence preservation and incident window

The ignored local capture contains survivor files and rotations, a final current-log copy,
selected Windows-event JSON, artifact inventory, correlation output, and retained StableNew
WebUI stdout/stderr copies. Its inventories record source timestamps, sizes, and SHA-256 values.
Windows originals were not moved, deleted, or overwritten.

The defensible incident window is **2026-09-23 20:38:11-20:38:30 ET**
(**2026-09-24 00:38:11-00:38:30 UTC**):

| Evidence | Timestamp / finding | Meaning and limit |
|---|---|---|
| Event Log 6008 | 20:38:11 ET unexpected-shutdown time | Best Windows-reported failure marker; it is a boundary, not a component-failure timestamp. |
| Survivor telemetry | 20:38:04 dispatch; valid GPU sample through 20:38:10 | StableNew A1111 GPU work was active immediately before the Windows marker. |
| Survivor telemetry | First `gpu: null` sample at 20:38:30 | GPU telemetry became unavailable while subsequent queued jobs failed. It does not name the failed device layer. |
| Kernel-Power 41 / boot | 20:39:29 ET / OS last boot 20:39:25 ET | Restart markers only, not a cause. |
| WER | 20:39:49 onward, with later delayed repeats | Reporting times, not capture times. |

The pre-reboot telemetry segment ends at 20:38:48 ET. It still records lifecycle events after the
Event 6008 time while the GPU field is unavailable, so the display-loss instant cannot honestly be
reduced below this window.

## Post-XMP-OFF recurrence and current platform state

Read-only observation on 2026-09-27 found both DIMMs still reporting `Speed=5600`,
`ConfiguredClockSpeed=5600`, and `ConfiguredVoltage=1100 mV`, with the same Micron part and serials
recorded above. Windows last booted at 06:23:33 ET on 2026-09-27. The installed NVIDIA display
driver reports `32.0.16.1714`, which differs from the `32.0.16.1692` recorded before this package;
the transition is not attributed here and means post-XMP-OFF exposure is not a clean held-driver
comparison.

The retained Windows evidence shows a second post-XMP-OFF failure boundary:

| Evidence | Timestamp / finding | Meaning and limit |
|---|---|---|
| WER | `WATCHDOG-20260926-2150.dmp`, LiveKernel `141`; `WATCHDOG4400-20260926-2150.dmp`, LiveKernel `1B8` | Same broad display/live-kernel family; the named dumps are not readable in this pass. |
| Event Log 6008 | 22:06:46 ET unexpected shutdown; Event 6008 recorded 22:07:33 ET | Restart boundary, not a component-failure timestamp. |
| Kernel-Power 41 | 22:07:24 ET | Restart marker only, not a cause. |
| Workload / survivor telemetry | Known immediately preceding PR-VID-184 Arm A Wan-Animate-2 GPU-loss workload context; its run was about 20 minutes before the 41/6008 recovery boot | No continuous survivor telemetry ties the exact `141`/`1B8` interval to that workload. GPU-active exposure and workload provenance for the interval are unknown; do not count this as a qualified exposure. |
| Other reviewed events | No new `0x133` record in this incident window; no attribution event was found | Does not clear any component or establish a different family. |

This recurrence means XMP-OFF has not produced a clean exit from the observed failure family. It
also cannot be used to judge whether the failure occurred during GPU-active work. The PR-VID-184
GPU-loss observation remains a separate, explicitly unmerged evidence class: its temporal
proximity neither causes the restart nor proves or falsifies failure-family equivalence.

## Restricted `0x133` dump attempt

Normal read-only access was attempted for `C:\Windows\Minidump\090926-11984-01.dmp` and
`C:\Windows\Minidump\091426-12875-01.dmp`; both returned **Access is denied**. `C:\Windows\MEMORY.DMP`
is absent. No debugger executable was available on the normal PATH. No elevation, ACL change,
ownership change, copy, or debugger run was performed, so no new `0x133` attribution exists.

The minimal operator action for the next evidence window is to use the normal administrator-
supported Windows evidence workflow to copy only those two named minidumps into the ignored local
diagnostic evidence directory, preserving source path, size, timestamp, and SHA-256. Then run the
already prescribed read-only pass once per copy with the installed Microsoft debugger:

```text
!analyze -v
.bugcheck
kv
!dpcs
lm t n
!blackboxntfs
!blackboxpnp
!blackboxbsd
!blackboxwinlogon
lmvm nvlddmkm
```

Retain raw output outside Git. If the normal administrator-supported copy still fails, record the
access denial and stop; do not bypass protection or alter ACLs.

## StableNew and runtime correlation

`tools/diagnostics/correlate_gpu_incidents.py` was run read-only at `2026-09-24T00:38:11Z`.
It classified the incident as `proven_active_stablenew_gpu_work` from survivor telemetry. SQLite
has no exact active interval at that second because the job's durable completion flushed just after
the Event 6008 timestamp; that does not negate the survivor evidence.

| Surface | Durable evidence |
|---|---|
| Job / run | `fd308a906de94a07b386802e7fbdfca7` / `20260923_203426_A_single_det-cyberreali-16fp-none` |
| Source / backend / stage | PromptPack, `a1111_webui`, `txt2img` |
| Timing | Started 20:38:03.854 ET; dispatched 20:38:04.112; completed 20:38:11.293 |
| Checkpoint | `cyberrealisticXL_v90-16fp.safetensors` |
| Base parameters | 576x1024, 30 steps, DPM++ 2M, Karras, CFG 6.1, seed 982480438 |
| Downstream configuration | The NJR declares ADetailer/upscale settings, but the recorded active stage was base `txt2img`; no evidence shows a downstream stage began. |

The affected job published and completed 0.293 seconds after the Windows-reported shutdown
second. The next three queued `txt2img` jobs failed between 20:38:26 and 20:38:48 with the
durable message `No images were generated successfully`; their survivor samples have no GPU
payload. This is post-boundary runtime degradation, not a StableNew root-cause finding.

The retained A1111 stdout/stderr snapshot has no matching CUDA, device-unavailable, OOM,
illegal-memory-access, or traceback evidence for the window. There is no Comfy or native-SVD
evidence, and no external runtime was started, restarted, adopted, or terminated by this package.

## Pre-incident telemetry

The final valid GPU sample before the Windows marker was 20:38:10.319 ET: RTX 4070 Ti at 100%
utilization, 9,089 MiB of 12,282 MiB VRAM used (3,193 MiB free), 80 C, 273.78 W of a 285 W limit,
2,805 MHz graphics clock, 10,251 MHz memory clock, P2, PCIe Gen4 x16, and 10,367.5 MiB host
memory available.

| Window | GPU / VRAM / thermal / power | Clock / host memory | Reading |
|---|---|---|---|
| Final 60 s (48 samples) | 0-100%; 8,951-9,091 MiB; 56-80 C; 50.9-274.0 W | 2,805-2,835 MHz graphics; fixed 10,251 MHz memory; 10,052-10,404 MiB host available | Normal per-image idle/active transitions; no VRAM or host-memory exhaustion signature. |
| Final 10 s (8 samples) | 0-100%; 8,951-9,089 MiB; 58-80 C; 52.4-274.0 W | Same clocks/P2/Gen4 x16; 10,330-10,398 MiB host available | Job-boundary transition followed by sustained work, not progressive resource pressure. |
| Final 3 GPU samples | 99-100%; 9,089 MiB; 79-80 C; 272.6-273.8 W | 2,805 / 10,251 MHz, P2, Gen4 x16; 10,354-10,368 MiB host available | No abrupt clock, P-state, PCIe, VRAM, thermal, or host-memory abnormality before loss of telemetry. |

High utilization and near-limit board power are observations, not causes: earlier images in the
same run completed. Temperature reached 80 C, but no thermal-limit or thermal-shutdown record
survives. The material discontinuity is loss of GPU telemetry after the Windows marker.

## Windows evidence and dump classification

New WER records name these incident-minute artifacts:

- `WATCHDOG-20260923-2038.dmp` with LiveKernel event `141`;
- `WATCHDOG4400-20260923-2038.dmp` with LiveKernel event `1B8`;
- `WATCHDOG4401-20260923-2038.dmp` with LiveKernel event `1B8`.

The WER records were retained locally. At collection, each named LiveKernel path was no longer
present or accessible, `C:\Windows\Minidump` was access denied, and `MEMORY.DMP` was absent. No
protection was bypassed, so no new WinDbg output exists. No `0x133`, `nvlddmkm`, Display, or WHEA
event was found in the incident window.

Classification is **A, partial reproduction of the known display-black-screen signature**: WER
directly records the known `1B8` live-kernel class and a companion `141`, but no readable dump
confirms the prior `0x1A8` pair or stack. This is not NVIDIA-specific stack evidence, WHEA
evidence, or a genuinely new failure class.

## DIAG-GPU-120 conclusion

At the time of that earlier recurrence, Windows reported both DIMMs at 5600 MT/s and 1250 mV; XMP
remained operator-reported enabled. The established failure recurred under that post-DIAG-GPU-120
condition. This is distinct from the current post-XMP-OFF state, which reports 5600 MT/s and 1100
mV. The DDR5-5600 transition was therefore insufficient to eliminate the fault and weakens a simple
"DDR5-6000 alone" explanation. It does not rule out RAM, IMC, CPU, or platform stability because
timings/controller behavior were not observed and component attribution remains unavailable.

## Hypothesis matrix

| Hypothesis class | New evidence | Direction | Critical blocker |
|---|---|---|---|
| GPU/display driver/device-reset path | New `141` plus `1B8`; GPU telemetry disappears shortly afterward. Owner-supplied cross-version recurrence (2026-09-24 amendment). | Strengthened at failure-domain level; a single driver-package version as the cause is weakened by recurrence across versions. | No readable dump stack or reset reason. |
| GPU hardware | Same symptom family recurs. | Unchanged. | No hardware diagnostics or substitution evidence. |
| PSU / GPU power delivery / cabling | 273.8 W is sub-limit; no power event. | Unchanged. | No rail/cable telemetry or inspection evidence. |
| PCIe / slot / motherboard | Gen4 x16 immediately before incident; no WHEA. | Unchanged. | No physical or platform diagnostic evidence. |
| RAM / IMC / CPU/platform stability | Recurrence at observed 5600 MT/s. | DDR5-6000-only theory weakened; class not excluded. | Timings, controller state, and controlled platform test absent. |
| Thermal | 80 C final sample; no thermal-limit record. | Not materially strengthened. | No hotspot/board thermal telemetry. |
| VRAM pressure / specific stage | 3.19 GiB VRAM and about 10 GiB host memory free; base `txt2img` active. | Weakened for exhaustion/downstream stage trigger. | One workload is not a universal exclusion. |
| StableNew lifecycle | Completion then no-image failures; telemetry proves correlation. | Unchanged for causation. | No source-level fault evidence. |
| A1111/runtime defect | Post-boundary jobs fail and GPU telemetry vanishes. | Weakly strengthened as a runtime symptom. | No CUDA/device-loss log evidence. |
| Windows display-stack/HAGS/power policy | Repeated display live-kernel class. | Strengthened as a broad interaction domain. | Effective HAGS/policy state and causal stack unavailable. |

## Next single isolation variable

**Amended recommendation (2026-09-24): isolate the platform baseline, one variable at a time.**
The original recommendation - one owner-authorized NVIDIA driver-package isolation - is
**deprioritized**: the failure family has recurred across driver versions (owner-supplied
cross-version recurrence evidence), so swapping a driver build is unlikely to discriminate the
cause. The next isolation should instead move the platform baseline (for example memory
configuration/profile, firmware/BIOS defaults, PCIe link configuration, or CPU/power settings),
changing exactly **one** variable per isolation while holding everything else - including the
driver, HAGS, Windows power plan, GPU power/clock settings, and physical hardware - unchanged and
recording the platform state before and after. Which variable comes first is an owner decision and
is not selected by this package. **Owner-confirmed intervention (2026-09-25):** the owner removed
the RAM XMP profile before rebooting. This is XMP-OFF isolation in progress / observation only.
The post-change boot is `2026-09-25 07:06:20 ET`; read-only Windows CIM capture at
`2026-09-25 10:32:03 ET` reports `Win32_OperatingSystem.LastBootUpTime` as
`2026-09-25T07:06:20.5000000-04:00` and both 16 GiB DIMMs (`17179869184` bytes; Micron
`CP16G60C36U5B.M8D1`): `Controller0-ChannelA-DIMM1` (serial `EB472282`) and
`Controller1-ChannelA-DIMM1` (serial `EB472250`). Each reports `Speed=5600`,
`ConfiguredClockSpeed=5600`, `ConfiguredVoltage=1100 mV` (`MinVoltage=1100`, `MaxVoltage=1350`),
`SMBIOSMemoryType=34`, and `FormFactor=8`. Windows does not establish
the firmware XMP toggle itself, Intel Baseline/Default, timings, or memory-controller state. This
observation is not a PASS, fix, or root-cause attribution. No crash-free interval beyond this
observation is claimed. The earlier driver-package option is not excluded permanently; it is
deferred behind platform-baseline evidence. Continue ordinary-use observation and report any
recurrence for monitoring; do not deliberately stress-test or combine this with another
configuration or hardware action.

## Operational GPU-active-exposure exit criterion

This is an operational stop rule for active isolation, not statistical root-cause proof, hardware
clearance, or a claim that XMP-OFF caused or prevented the failures. Move Lane B to dormant,
event-driven observation only after all of the following are true under one recorded platform
state:

1. At least 10 ordinary-use GPU-active StableNew sessions are retained with job/backend/stage
   identity and continuous survivor telemetry; the set contains at least 4 cumulative GPU-active
   hours, including at least three sessions with 10 continuous minutes at or above 80% GPU
   utilization when ordinary work naturally provides it.
2. The sessions span at least 14 calendar days and three clean boots, with no deliberate stress,
   replay, retry of ambiguous dispatches, or newly changed platform variable.
3. No `141`, `1A8`, `1B8`, or `0x133` WER/BugCheck recurrence, Kernel-Power 41/6008 boundary, or
   unexplained loss of GPU telemetry occurs during the qualified exposure set.
4. The pre/post platform snapshot remains reproducible: memory state, driver version, HAGS and
   power-plan observations, and the limits of what Windows cannot expose are recorded for the
   qualifying period.

The current count is **zero qualified post-XMP-OFF exposure sessions** in the retained evidence:
the 2026-09-26 recurrence retains known immediately preceding PR-VID-184 Arm A context, but no
continuous survivor telemetry ties the exact `141`/`1B8` incident interval to it; it cannot count
as qualified clean GPU-active exposure. The criterion is consequently not met and the posture remains active observation. A
future recurrence before the threshold resets the exposure count and triggers the protocol below.

## Exact recurrence evidence-preservation protocol

On any recurrence, stop deliberate GPU work and do not automatically replay or retry an ambiguous
generation dispatch. Record, before cleanup or reboot when possible:

- local incident time, timezone, visible symptom, and whether the machine rebooted;
- survivor telemetry copied read-only, including the last valid GPU sample, first unavailable
  sample, rotations, hashes, and coverage limits;
- System, Application, WER-Diag, Kernel-Power, Event 6008, BugCheck, Display, `nvlddmkm`, and
  WHEA events for the bounded pre/post window, preserving raw exports and source timestamps;
- every named WER/LiveKernel/minidump path, file size/timestamp/hash when readable, and the exact
  access-denied result when not; preserve `MEMORY.DMP` status;
- StableNew job id, run id, NJR/source identity, backend/stage, dispatch/completion times, and
  workload parameters if applicable, plus A1111/Comfy/native-SVD process-log copies;
- platform/config snapshot: boot time, DIMM speed/clock/voltage, driver/VBIOS, GPU link/power/
  temperature/utilization telemetry, HAGS/power-plan observations, and any owner-reported change.

Do not change BIOS/XMP, driver, HAGS, power plan, clocks, pagefile, hardware, or process ownership
as part of preservation. Escalate only with the preserved evidence and a separately approved
single-variable decision.

## Additional GPU-loss observation (2026-09-26, PR-VID-184)

During the single owner-authorized, isolated, non-StableNew Wan-Animate-2 Arm A sampling attempt (10th of 10 sampler steps)
recorded in `docs/Subsystems/Video/PR-VID-184_Wan_Animate_2_Reference_Target_Hardware_Integration_Feasibility.md`
(Phase H), the GPU entered a lost-device state (`CUDA_ERROR_UNKNOWN`/sticky CUDA error; `nvidia-smi`
reported the GPU lost and requested a reboot) while Windows system commit was approximately 95–98 %.
A read-only System-log query over the roughly 10 minutes around it found no WHEA, Kernel-Power 41,
unexpected-shutdown 6008 or display-driver-reset 4101 event. This event did not reproduce the
DIAG-GPU-130 Windows-event signature in the inspected window. That is descriptive only: it does not
prove a different cause, does not clear the hardware or the driver, does not prove commit exhaustion,
and is not a stability PASS. Kernel-Power 41 and 6008 occurred at the recovery boot about 20 minutes
after Arm A, outside that inspected window. The retained evidence has no continuous survivor telemetry
tying the exact `141`/`1B8` interval to Arm A; the temporal context neither causes the restart nor
proves or falsifies failure-family equivalence. It is not merged into this diagnosis's root-cause
interpretation; the status above is unchanged.

## Boundaries and validation

- No GPU workload, stress test, replay, retry, queue mutation, process action, driver action,
  BIOS/XMP/HAGS/power change, or hardware intervention was performed by this package.
- No StableNew production source, tests, architecture, controller, runtime, queue/history, or
  diagnostic implementation changed.
- Validation was evidence preservation, read-only Windows/SQLite/log inspection, the supported
  correlator (including WebUI-log inventory), direct memory-state observation, and final
  documentation diff review. Source CI is not applicable.
