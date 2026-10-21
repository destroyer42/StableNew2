# DIAG-GPU-150 - Three GPU losses in 11 hours, and the hang recorder (2026-10-20 / 2026-10-21)

## Status

**RECURRENCE RECORDED - ROOT CAUSE NOT ATTRIBUTED - EXIT CRITERION NOT MET.**

- The RTX 4070 Ti dropped off the bus three times in 10 hours 47 minutes: 2026-10-20 18:57:15, 20:56:09 and 2026-10-21 05:44:31 (ET). These are the 17th, 18th and 19th NVIDIA Kernel-PnP remove-veto markers since 2026-09-07 (10th of 19 since XMP was turned off); the 60-day export confirms 19.
- Nothing here attributes the failure to StableNew, Forge, NVIDIA, the GPU, power delivery, PCIe, the CPU, RAM or Windows.
- This record continues `DIAG-GPU-100` to `-140`. It does not reopen or close them (`STATUS.md` open decision 3).
- The one code change is `tools/diagnostics/gpu_hang_recorder.py`, an opt-in separate process that is never imported by the application.

## Execution profile

- **Classification:** Standard local forensic diagnostic work plus one read-only diagnostic tool.
- **Model recommendation:** Claude Code Opus 5.5 High; Codex GPT-6 Astra High.
- **Controller Surface Assessment:** not applicable; no controller, runtime, queue or process code changed.
- **Validation:** `tests/tools/test_gpu_hang_recorder.py` (fake provider, injected clock, no GPU or NVML); the real NVML failure path was exercised against the lost device; `python tools/ci/run_pr_gate.py`.
- **Not done:** no reboot, process action, driver, firmware, BIOS, power or hardware change, no GPU workload. Two attempts to launch the elevated evidence copy were cancelled at the UAC prompt (the secure desktop is not visible while the display is dead), so the administrator copy is still outstanding.

## The three losses (ET; job times from the repository, UTC converted)

| # | Windows marker | Job and phase | First failing CUDA call in Forge | Last good sample -> first nvidia-smi timeout |
|---|---|---|---|---|
| 1 | 10-20 18:57:15.687 | `2ee36aef` txt2img, about 1.4-1.9 s in (CLIP load, util 0%, 110 W) | `model.to(offload_device)` (copy) -> `cudaErrorUnknown` | 22:57:12.18Z -> 12.73Z |
| 2 | 10-20 20:56:09.937 | `454ca149` txt2img, about 6.9-7.5 s in (steady sampling, util 99%, 243 W, 77 C) | `F.group_norm` (kernel) -> `cudaErrorUnknown` | 00:56:06.44Z -> 07.00Z |
| 3 | 10-21 05:44:31.635 | `f9a1aae0` txt2img, about 1.3-1.9 s in (model reload, util 0%, 54 W) | `cublasGemmEx` (UNet attn2 `to_v`) -> `CUBLAS_STATUS_INTERNAL_ERROR`, then `cudaErrorUnknown` | 09:44:28.12Z -> 28.69Z |

The Windows marker is always 2.9-3.0 s after the first nvidia-smi timeout, so the hang instant is known to within one 0.55 s telemetry sample.

## What this changes

1. **The trigger is not a model-swap transfer.** The failing CUDA operation differs every time (a copy, a compute kernel, a cuBLAS GEMM); incident 2 was steady-state sampling. The device vanishes asynchronously and the next CUDA call reports it. `DIAG-GPU-140`'s correlation with Forge's per-job model swap stands as exposure (the job-start window is busy) but not as cause.
2. **GPU telemetry is normal before every loss:** 244-262 W of 285 W, 74-81 C, 2805-2835 MHz, P2, PCIe Gen4 x16, VRAM 8.8-11.1 GB of 12.28 GB (job-start peaks reach 91-94% of VRAM). No CUDA error line of any kind exists in the Forge logs of the loss-free sessions.
3. **Still no Display 4101, `nvlddmkm`, WHEA or Kernel-Power 41 at the marker.** Each loss requests WATCHDOG live-kernel dumps within 0.3 s, followed by a burst of LiveKernelEvent 141, 1B8 and 1A8 reports.
4. **A regime shift, not a slow trend.** About 3,000 jobs ran loss-free from 2026-10-17 15:00 to 2026-10-20 08:35 on the same Forge build and driver; three losses followed within 50-84 jobs each after 10-20 18:50. Over six weeks the rate is steady (about 0.4 per day) with bursts: 9 markers 09-07..09-21, 5 in 09-26..10-01, none 10-02..10-11, 5 in 10-12..10-21.
5. **Not common to the three:** host memory pressure (incident 2 had 6.8-8.2 GB free), display-link flapping (monitor re-enumeration events never fall within 10 minutes of any marker).
6. **The Windows evidence that would help is behind administrator ACLs.** `C:\ProgramData\Microsoft\Windows\WER\ReportQueue` holds 52 queued Kernel reports (21 x 141, 22 x 1B8, 5 x 1A8, 2 x 133). The 1B8 dumps carry NVIDIA's own `NV_Blackscreen_Blackbox` driver blob (confirmed in the one readable 1B8 dump). The two readable 10-20 21:50 dumps are user/dwm-initiated black-screen dumps (stack `DxgkEscape -> DxgkCheckDisplayState`, process `dwm.exe`), not the hang dumps.
7. The installed WinDbg (`Microsoft.WinDbg`) ships `cdb.exe`. It cannot be launched from `WindowsApps`; it runs from a copy of that package's `amd64` folder. `nvlddmkm.sys` is built 2026-09-30; NVIDIA does not publish its symbols.

## Platform facts (Windows can answer when nvidia-smi cannot)

- GPU PNY RTX 4070 Ti (subsystem 196E:13B5) on the CPU's own x16 root port (`Intel PCIe RC 010 G5 - A70D`, PCI bus 1). After the loss Windows still reports Status OK, problem code 0, link Gen4 x16.
- Driver 32.0.16.1742 (617.42), driver date 2026-09-29, installed 2026-10-10; Windows updates KB5127647/5127648/5127690 on 2026-10-13. VBIOS 95.04.3c.80.52.
- CPU i9-13900K, microcode 0x12F; ASRock Z690-C/D5, BIOS 16.01 (2025-10-22); 2 x 16 GB DDR5-5600 at 1.10 V (XMP off).
- VBS running with HVCI; Fast Startup on; PCIe Link State Power Management off; High performance plan; HAGS and TDR registry values unset.
- NVIDIA Overlay and several Electron applications (Chrome, ChatGPT, VS Code, Claude) share the GPU with Forge. System commit was about 50.8 of 56.1 GB after the last loss (the Forge process alone held 25.5 GB commit); commit at the instants of loss was not recorded, which is what the recorder now adds.
- Not observable from software: PSU model and rating, 12VHPWR seating, the BIOS PCIe AER setting.

## Hypothesis matrix (changes only)

| Hypothesis | Direction | Why |
|---|---|---|
| Model-swap transfer as trigger | Weakened | Three different failing operations; one at steady load. |
| Host RAM pressure as trigger | Weakened | Absent in incident 2; at the instants of 1 and 3 free RAM was 4.6-8.2 GB. |
| Display-link instability | Weakened | No correlation in 60 days. |
| GPU power delivery / connector | Open | A fixed-time, device-wide disappearance with normal telemetry and no OS error record fits; nothing measured. |
| PCIe link integrity (slot, CPU root port) | Open | Same; the PCIe replay counter has never been recorded. This is what the Gen3 variable and the recorder test. |
| CPU / platform (13900K, root port on the CPU die) | Open, not testable here | Microcode is current; accumulated degradation cannot be excluded or shown from software. |
| Driver 617.42 | Open | Every 2026-10-12+ loss is after its install, but earlier drivers lost too (`DIAG-GPU-110`, `-130`). |
| HVCI / NVIDIA Overlay / other GPU clients | Open | Cheap, separable variables; none tested. |

## The hang recorder

`tools/diagnostics/gpu_hang_recorder.py` is one long-lived process: NVML opened once through ctypes (no package, no CUDA context), 20 Hz by default. It records, per sample: read latency, GPU and memory utilisation, VRAM, power and limit, temperature, fan, graphics/SM/memory/video clocks, P-state, throttle reasons, **PCIe link generation and width, PCIe replay counter** (a growing replay counter is the textbook precursor of a marginal link), energy, PCIe throughput at 2 Hz, and host commit, physical-available and non-paged pool.

- A watchdog thread (no NVML calls) writes `nvml_call_blocked` events naming the call that has not returned, so a hang is timestamped and attributed even though the sampler is stuck inside the driver.
- On a device-lost status it writes `incident_*.json` (the preceding 10 s, host state, trigger), fsyncs it, logs `gpu_lost`, and keeps probing at 1 Hz, logging `gpu_back` if the device returns.
- Output: `reports/diagnostics/gpu_hang_recorder/gpu_hang_recorder_<utc>_<pid>_NNN.jsonl` (flushed every sample, fsynced every 0.25 s, rotated at 64 MB, 12 files kept, about 21 MB per hour). An OS file lock allows one recorder per output directory.
- It is read-only (no NVML setters, no process or runtime action), opt-in, and not imported by `src/`.

```text
python tools/diagnostics/gpu_hang_recorder.py --probe     # one read of every field; exit 0 healthy, 1 some field failed, 2 device lost
python tools/diagnostics/gpu_hang_recorder.py             # record until Ctrl+C (start it before the app)
python tools/diagnostics/gpu_hang_recorder.py --duration-s 600 --interval-ms 50
```

It is a second NVML poller next to the application's survivor telemetry (which spawns `nvidia-smi` about every 0.55 s). That is an explicit owner-chosen instrumentation variable; it is independent of the single platform variable below. The `--probe` exit code on the first boot after this change is the check that the ctypes bindings are right on real hardware (the happy path could not be exercised while the GPU was lost; the lost-device path was).

## Next single platform variable: force the GPU slot to PCIe Gen3 (owner decision, 2026-10-21)

Change exactly this one thing; leave RAM/XMP, power plan, HAGS, driver and everything else alone.

1. Restart and tap **F2** (or **Del**) repeatedly at the ASRock logo to enter UEFI setup. If it opens in EZ mode, press **F6** for Advanced Mode.
2. Open **Advanced -> Chipset Configuration** and find **PCIE1 Link Speed** (the top x16 slot, the CPU-attached slot the GPU is in). On some ASRock firmware the same item is called *PCIe Link Speed* or *PEG0 Link Speed* and sits under **Advanced -> North Bridge Configuration**. Set it to **Gen3** (default *Auto*). The exact menu names for BIOS 16.01 on the Z690-C/D5 could not be confirmed from ASRock's documentation here; if the item is not where described, photograph the Advanced pages and the setting can be located from the photo.
3. **F10**, Enter on *Yes* to save and exit. Keyboard-only: arrow keys move, Enter opens a list, Esc goes back.
4. After Windows is up and the GPU is under load, confirm the result: the recorder's `pcie_gen` should read 3 while generating. At idle the link may downshift further; that is normal and not the setting.

Test protocol after the change (so the result is comparable): cold boot, start the recorder, start the app, run the same PromptPack SDXL batch, record minutes (and jobs) to a loss or to 60 clean minutes, and write down the recorder `pcie_replay` at the start and end. A recurrence at Gen3 removes Gen4 signalling margin as the explanation and moves the next variable to power delivery or the platform; a clean interval does not prove a fix and needs the existing exit criterion (`DIAG-GPU-130`).

## Evidence preservation still owed

Run `collect_gpu_evidence_ADMIN.ps1` (kept in the ignored local evidence folder `reports/diagnostics/gpu-incident_20261021/`) once from an elevated PowerShell. It only copies, writes SHA-256 hashes and exports event logs. It collects the WER ReportQueue and ReportArchive Kernel reports, `LiveKernelReports` and `Minidump`. A recurrence should follow the `DIAG-GPU-130` evidence-preservation protocol plus the recorder's `incident_*.json` and the last `.jsonl`.

## Evidence locations (local, not committed)

`reports/diagnostics/gpu-incident_20261021/`: `FINDINGS.md`, Windows event windows for each loss, `survivor_analysis.txt`, platform snapshots, `pnp_device_management_60d.csv`, the Forge and app logs of the three sessions, a job CSV, the two readable live dumps with `cdb` output, `SHA256SUMS.txt`.
