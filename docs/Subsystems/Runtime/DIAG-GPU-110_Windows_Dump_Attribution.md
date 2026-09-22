# DIAG-GPU-110 — Windows Dump Attribution and Driver Stack Analysis

## Status

**DIAG-GPU-110 — COMPLETE / ACCEPTED / INTEGRATED.** The evidence record
establishes strong cross-incident convergence on the Windows
black-screen/display capture domain, without driver- or component-level
attribution. It does not authorize a driver, BIOS, power, memory, cabling,
registry, process, or workload change.

## Execution profile

- Classification: Standard local forensic diagnostic work.
- Model/reasoning recommendation: GPT-5.6 Terra — High. The work requires
  precise local dump/event correlation and disciplined non-attribution from
  incomplete artifacts; a lower-effort pass would create substantial
  misclassification and rework risk.
- Controller surface assessment: not applicable. No StableNew controller,
  coordinator, source, queue, runtime, or diagnostic tool was changed.
- Token-efficient validation plan: inventory the existing dump/WER evidence,
  run the supported debugger commands once per surviving September dump, retain
  raw output outside Git, and validate only the documentation diff. No test,
  GPU, A1111, Comfy, SVD, process, driver, BIOS, registry, power, or stress
  action is part of this work package.

## Artifact inventory and method

At the 2026-09-22 collection, the visible, in-scope surviving artifacts were:

| Artifact | Availability | Disposition |
|---|---|---|
| `C:\Windows\Minidump\090926-11984-01.dmp` | WER names it for the 2026-09-09 `0x133`; direct access is denied | Not analyzed; no protection bypass attempted. |
| `C:\Windows\Minidump\091426-12875-01.dmp` | WER names it for the 2026-09-14 `0x133`; direct access is denied | Not analyzed; no protection bypass attempted. |
| Matching `Kernel_133_*` WER queue directories | Directory names remain visible; contents are access denied | Preserved as an access limitation, not evidence of absence. |
| `C:\Windows\MEMORY.DMP` | Not present | No analysis possible. |
| `WATCHDOG-20260916-0620.dmp`, `WATCHDOG-20260916-0807.dmp` | Readable | Analyzed. |
| `WATCHDOG4401-20260916-0620.dmp`, `WATCHDOG4401-20260916-0807.dmp` | Readable | Analyzed. |

`cdb.exe` 10.0.29617.1000 from Microsoft WinDbg 1.2606.22001.0 was used with
the Microsoft symbol server and cache `C:\Symbols\WinDbg`. For each readable
dump the pass ran `!analyze -v`, `.bugcheck`, `kv`, `lm t n`, the four requested
blackbox commands, and `lmvm nvlddmkm`. Raw command output is retained locally
under ignored `reports/diagnostics/diag_gpu_110_windbg/`; it is intentionally
not source-controlled. The mini-kernel format did not retain useful blackbox
data (`!blackboxntfs` reported none); absence of that data is not exculpatory.

## Cross-dump evidence

Times below are local ET. `0x1A8` and `0x1B8` are live-dump identifiers, not
ordinary stop-code crashes.

| Incident / artifact | Debugger result | What it establishes | What it does not establish |
|---|---|---|---|
| 2026-09-09 05:48:04 restart | WER: `DPC_WATCHDOG_VIOLATION (0x133)`, `Arg1=1`, `Arg2=0x1e00`; named minidump inaccessible | A cumulative DPC/ISR-overrun watchdog occurred. | Which DPC/ISR or driver consumed the time. |
| 2026-09-14 07:44:09 restart | Same WER `0x133`, `Arg1=1`, `Arg2=0x1e00`; named minidump inaccessible | The same generic watchdog class recurred. | Any stack, triage-block, `!dpcs`, or specific-driver attribution. |
| 2026-09-16 06:20:25 `WATCHDOG` | `VIDEO_DXGKRNL_BLACK_SCREEN_LIVEDUMP (0x1A8)`, `Arg1=0xA`; `dwm.exe`; bucket `LKD_0x1A8_10_dxgkrnl!NtGdiDdDDIGetContextInProcessSchedulingPriority` | Windows detected a physical-monitor mode-set failure and captured a display-kernel black-screen state. | A fault inside `nvlddmkm`, a hardware defect, or a StableNew cause. |
| 2026-09-16 06:20:25 `WATCHDOG4401` | Paired `VIDEO_MINIPORT_BLACK_SCREEN_LIVEDUMP (0x1B8)`, `Arg1=0xA`; `dwm.exe`; bucket `LKD_0x1B8_dxgkrnl!NtDxgkUnmapProcessDebugBlob` | The same incident also crossed the display-miniport capture boundary. | That the stack frame names the responsible driver. |
| 2026-09-16 08:07:03/04 `WATCHDOG` | Same `0x1A8`, `Arg1=0xA`, `dwm.exe`, and failure bucket as 06:20 | A reproducible DXGKRNL black-screen signature. | A new, distinct failure class. |
| 2026-09-16 08:07:03/04 `WATCHDOG4401` | Same paired `0x1B8`, `Arg1=0xA`, `dwm.exe`, and failure bucket as 06:20 | A reproducible paired miniport black-screen signature. | Direct NVIDIA driver blame. |

The two readable pairs have the same stack shape:
`watchdog!WdDbgReportCreate` → `dxgkrnl` → `win32kbase!xxxDisplayDiagBlackScreenDetected`
→ `dwm.exe` system-service transition. `nvlddmkm.sys` was loaded in each dump
and has the same module timestamp, 2026-08-20 11:29:33, but it is not on the
captured stack and `!analyze -v` names `dxgkrnl.sys`, not `nvlddmkm.sys`, as the
bucket module. WinDbg's inability to find local third-party image files for
timestamp verification is a normal limitation of these live mini-dumps, not a
driver-corruption finding.

The current Windows PnP inventory reports NVIDIA GeForce RTX 4070 Ti driver
`32.0.16.1692` (driver date 2026-09-03); the dump module timestamp is historical
evidence only and does not prove that the current installation is unchanged.

## Event and StableNew correlation

Bounded System/Application event review found the two `0x133` WER records and
their corresponding Kernel-Power 41/unexpected-shutdown markers. It found no
WHEA, Display, `nvlddmkm`, or NVIDIA event in the reviewed 2026-09-09,
2026-09-14, or 2026-09-16 incident windows. Kernel-Power 41 remains a restart
marker, not a cause.

This refines, but does not overturn, DIAG-GPU-100. That earlier record already
established a GPU/display failure domain from black-screen symptoms, repeated
LiveKernel 141/1A8/1B8 records, interrupted A1111 CUDA calls, and survivor
telemetry limits; it deliberately did not attribute the root cause to
StableNew. The new dump evidence confirms that the two readable September
incidents were Windows display-stack black-screen captures. It does not connect
the event to a StableNew job: DIAG-GPU-100 found no exact-time active SQLite
job for either incident and described the A1111 activity only as interrupted,
not as request-provenance evidence.

## Attribution and decision gate

**Classification: strong cross-incident convergence on the Windows
black-screen/display capture domain, without driver- or component-level
attribution; generic, unresolved `0x133` DPC attribution.** Confidence is high
that the 2026-09-16 artifacts are display black-screen captures; confidence is
low for any individual driver or physical component. The two inaccessible
`0x133` dumps prevent the required triage-block and `!dpcs` inspection, so this
pass cannot elevate NVIDIA, another third-party driver, PCIe/power, StableNew,
or a CUDA workload to a root-cause finding.

The applicable next path is **C — disable XMP and establish DDR5 at the
CPU-supported 5600 MT/s baseline as one variable**, subject to the separately
authorized isolation objective. It is selected because the recurring
`0x133 Arg1=1` records remain generic and unattributed, while the display
captures provide failure-domain correlation but not NVIDIA-driver attribution.
It is a single-variable isolation, not a remedy claim. No part of that
experiment was performed here.

Before that owner-authorized change, preserve/copy the two `0x133` minidumps
through a normal administrator-supported Windows evidence workflow and rerun
the prescribed `!analyze -v`, `.bugcheck`, `kv`, `!dpcs`, module, and triage
block commands. Do not combine the future XMP-off/5600 experiment with CPU
Baseline/Default profile changes, BIOS flashing, NVIDIA-driver changes, HAGS,
Windows power-plan changes, GPU clocks/power changes, or physical GPU/PSU
intervention. No evidence in this record triggers the powered-off
hardware-inspection path.

## Validation and scope boundary

- Raw WinDbg output exists locally for all four readable 2026-09-16 dumps.
- The two `0x133` WER records and their named inaccessible dump paths were
  verified read-only; access control was respected.
- No production source, test, architecture, runtime, queue/history, GPU
  configuration, process ownership, or machine setting changed.
- No source test or CI run is applicable to this documentation/evidence-only
  record.
