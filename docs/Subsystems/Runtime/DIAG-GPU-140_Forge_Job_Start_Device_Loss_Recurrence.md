# DIAG-GPU-140 - Forge job-start device-loss recurrence (2026-10-20)

## Status

**RECURRENCE RECORDED - ROOT CAUSE NOT ATTRIBUTED - EXIT CRITERION NOT MET.**

- At 2026-10-20 22:57:15 UTC (18:57:15 ET) the RTX 4070 Ti dropped off the bus during a StableNew Forge txt2img batch. `nvidia-smi` then reported `GPU is lost. Reboot the system to recover this GPU`, and it still did at the time of writing (no reboot yet).
- This is the **17th** NVIDIA Kernel-PnP remove-veto marker since 2026-09-07, and the **8th** since RAM XMP was turned off on 2026-09-25.
- StableNew's GPU-loss containment (PR-QUEUE-GPU-180) worked: one job failed with its original evidence, and the 8 jobs behind it stayed queued under quarantine `gpu-6aff599d`.
- **New in this record:** every repository-attributable loss (2026-10-12, 10-17, 10-20) happened 4-9 seconds into a Forge txt2img job, inside Forge's model swap between GPU and host memory.

This is a correlation, not a cause. Nothing here attributes the failure to StableNew, Forge, NVIDIA, the GPU, power delivery, PCIe, RAM or any other component.

This record continues `DIAG-GPU-100`, `-110`, `-120` and `-130`. It does not reopen or close them (`STATUS.md` open decision 3).

## Execution profile

- **Classification:** Standard local forensic diagnostic work, read-only.
- **Model recommendation:** Claude Code Opus 5.5 High (cross-source timestamp reconciliation and non-attribution); Codex GPT-6 Astra High.
- **Controller Surface Assessment:** not applicable. No controller, runtime, queue or process code changed.
- **Validation plan:**
  - Read Windows events, the SQLite repository (`?mode=ro`), the app log, the Forge logs and the crash bundle once.
  - Run the existing correlator.
  - The only code change is the correlator timestamp fix in this PR, with its regression test.
  - No GPU workload, process action, driver, BIOS, power or hardware action was taken.

## Incident timeline (UTC)

| Time | Source | Event |
|---|---|---|
| 22:50:06 | `state/jobs.sqlite3` | First job of the session starts. A PromptPack batch of SDXL txt2img at about 9 s per image and 100% GPU utilization follows (app log `stage_pressure_warning`: 58-74% VRAM). |
| 22:57:10.785 | repository | Job `004dbacb` completes normally. |
| 22:57:10.794 | repository | Job `2ee36aef` starts: `babesByStableYogiPony_xlV4`, 768x1024, 35 steps, DPM++ 2M Karras, ADetailer off. |
| 22:57:12.474 | app log progress marker | `step=0/35`. Forge begins `setup_conds`, which loads the CLIP model to the GPU. |
| **22:57:15.687** | Windows `Microsoft-Windows-Kernel-PnP/Device Management` event 1000 (record 3538) | Windows requested removal of `PCI\VEN_10DE&DEV_2782&SUBSYS_13B5196E&REV_A1\4&341ca995&0&0008`; vetoed by the device (`IllegalDeviceRequest`). |
| about 22:57:17 | crash bundle `ui_heartbeat_stall` | The Tk GUI thread stops answering. Heartbeat age is 10.8 s at 22:57:27.6, so the desktop stalled with the device. |
| 22:57:27.613 | `reports/diagnostics/stablenew_diagnostics_20261020_225727_ui_heartbeat_stall.zip` | Watchdog bundle written. Host RAM 26.0 / 32.5 GB used (80.1%), 6.5 GB available; Forge RSS 9.1 GB. |
| 22:57:28 | Forge stderr (`logs/webui/webui_stderr_09d73b2e.log`) | `torch.AcceleratorError: CUDA error: unknown error` (`cudaErrorUnknown`). Raised in `memory_management.load_models_gpu -> partially_load -> detach -> unpatch_model -> model.to(offload_device)`: the UNet was being moved off the GPU to make room for CLIP. |
| 22:57:28 | Windows Application log | `MicrosoftSecurityApp.exe` FailFast (`.NET Runtime` 1025, `Application Error` 1000). An unrelated GPU client crashing in the same second is consistent with a device-wide loss. |
| 22:57:28.546 | app log `gpu_device_loss` | `quarantine_established`, incident `gpu-6aff599d`, `evidence_class=confirmed_device_loss`, `accelerator_fault=device_fault`, host probe `nvidia-smi`: `state=device_lost`, `device_count=0`. |
| 22:57:28.567 | repository | Job `2ee36aef` FAILED (`txt2img error: AcceleratorError`). 8 later jobs remain `queued`. |
| 22:57:46 | `C:\Windows\LiveKernelReports\WATCHDOG`, `WATCHDOG4400` | Folder modification times change. No new `.dmp` file was visible to a non-elevated read. |

**No Windows record in the window:**
- no `nvlddmkm` System event;
- no `Display` 4101 (TDR recovered) event;
- no WHEA-Logger event, in the last 60 days either;
- no Kernel-Power 41.

Boot ID 102 is unchanged since 2026-10-17 13:05:36 ET.

## Platform state at the incident

- **GPU and driver:** RTX 4070 Ti, driver 617.42 (`Win32_VideoController.DriverVersion` `32.0.16.1742`, adapter `Status=OK` while `nvidia-smi` reports the GPU lost).
- **Earlier drivers in this failure family:** 616.92 and 617.14 (`DIAG-GPU-110`, `-130`).
- **RAM:** both DIMMs at `Speed=5600`, `ConfiguredClockSpeed=5600`, `ConfiguredVoltage=1100 mV`, the XMP-off baseline recorded in `DIAG-GPU-130` on 2026-09-25.
- **Workload process:**
  - managed Forge `neo-d70373eb` on port 7871: PyTorch 2.13.0+cu130, `VRAM State: NORMAL_VRAM`, total VRAM 12,282 MB, PyTorch cross attention;
  - launch `--uv --api --port 7871 --data-dir ... --forge-ref-a1111-home ... --ad-no-huggingface --skip-install`.
- **No ComfyUI was serving:** the app's startup ComfyUI bootstrap to port 8000 failed, there was no ComfyUI process, and no video job ran in the session.

## Forge model swapping at every job start

Forge's stdout for this session (`webui_stdout_09d73b2e.log`) logs 69 `Moving model(s)` lines across about 40 jobs. On every image:

1. CLIP (2,526 MB) loads with only about 4.4-4.8 GB of VRAM usable.
2. The UNet (4,897 MB) is moved back in, taking about 1.6 s.
3. The VAE (160 MB) loads.

On the first job the UNet loaded only partially (`340.65 MB offloaded ... lowvram`).

So each image moves roughly 7 GB between host and device, at the start of the job, around full-load sampling. The failing call was one of these transfers.

## Recurrence history (Kernel-PnP event 1000 for the NVIDIA device, 60-day query)

All 17 markers are listed below (local ET).

**Before XMP was turned off (2026-09-25):** 09-07 17:27:50, 09-09 00:38:26, 09-13 18:56:29, 09-14 23:05:59, 09-15 19:02:36, 09-16 08:04:16, 09-18 00:44:02, 09-19 17:13:32, 09-21 08:10:32.

**After XMP was turned off:**

| Marker (local ET) | Repository job active at the marker |
|---|---|
| 09-26 21:50:19 | none recorded |
| 09-29 08:42:38 | none recorded |
| 09-29 15:02:36 | none recorded |
| 09-30 06:02:56 | none recorded |
| 10-01 19:42:55 | none at the marker; 220 jobs in the previous hour |
| 10-12 22:28:04 | `2d60937b` Forge txt2img, **9.1 s into the job**, `photoMomentumSDXLNSFW_v20`, 976x1408, 40 steps; 107 jobs in the previous hour |
| 10-17 12:49:24 | `81f4fdc5` Forge txt2img, **4.3 s into the job**, `photoMomentumSDXLNSFW_v20`, 576x1024, 30 steps; 37 jobs in the previous hour |
| 10-20 18:57:15 | `2ee36aef` Forge txt2img, **4.2 s into the job**, `babesByStableYogiPony_xlV4`, 768x1024, 35 steps; 40 jobs in the previous hour |

- All three attributable jobs failed with `txt2img error: AcceleratorError`.
- The markers without a repository job predate the current repository or come from work outside the queue: qualification harnesses, A1111 directly, or other applications. `DIAG-GPU-100` to `-130` record the workloads that are known for them.
- Many markers are followed within minutes by a Kernel-Power 41 / EventLog 6008 pair, a hard restart after the loss. 10-20 has none yet because the machine has not been restarted.

## Correlator defect found and fixed in this PR

`tools/diagnostics/correlate_gpu_incidents.py` attached the machine's **local** zone to naive timestamps. The job repository writes naive `datetime.utcnow()` values, so on this UTC-4 host every repository job was shifted by four hours. This incident was therefore reported as `stablenew_open_no_proven_active_generation` with no active job.

With naive values read as UTC (all of the tool's inputs are UTC by contract), the same command reports `proven_active_stablenew_gpu_work` with job `2ee36aef` active. Earlier correlator outputs that relied on repository jobs should be re-run before they are trusted.

The regression test pins a UTC-4 local zone, so it fails the old behaviour even on a UTC CI runner.

## Hypothesis matrix

| Hypothesis | For | Against / open |
|---|---|---|
| Platform power delivery: PSU transient response, GPU power connector seating or cabling | Device-wide loss with no OS-level error record; recurs across drivers, backends and models; the attributable losses cluster at a load transition (job start: idle-to-burst plus a transfer burst). The PSU model has never been observable from software. | No electrical measurement exists; the connector type and seating have not been inspected and recorded. |
| PCIe link integrity (Gen4 signalling, slot, riser if any) | The failure point in this record is a large host<->device transfer; "fell off the bus" is the classic signature. | No WHEA corrected or uncorrected PCIe errors in 60 days. Link generation and width at the time are unrecorded (`nvidia-smi` cannot answer now). |
| GPU hardware fault | Persistent across the platform changes made so far. | Not separable from the rows above without a swap or a different host. |
| NVIDIA driver | - | Recurs across 616.92, 617.14 and 617.42; driver isolation was deprioritized in `DIAG-GPU-130`. |
| RAM / memory controller | Pinned-memory DMA reads host RAM. | 8 recurrences after XMP-off at 5600 MT/s, 1.1 V; no WHEA memory errors. |
| StableNew or Forge software defect | The trigger is always GPU work that StableNew dispatched (for the attributable three), and Forge's swapping determines when the transfer bursts happen. | Application code cannot remove a PCIe device. The same family occurs under A1111, ComfyUI/Wan and outside the queue. Software shapes the exposure, not the failure. |
| Thermal | - | About 7 minutes of load this time; earlier sessions ran for hours at 80-85 C without a loss. No telemetry for this window. |

## Next single isolation variable (owner decision)

Following `DIAG-GPU-130`, change **one** platform variable at a time and record the before and after state. In order of cost and discriminating power:

1. **Inspect and reseat the GPU power connection and the card.** Record the connector type (16-pin 12VHPWR/12V-2x6 or 8-pin), that it is fully latched, any adapter, cable bend radius near the plug, and the PSU model and rating.
2. **Force the GPU slot to PCIe Gen3 in firmware.** Small cost for this workload; discriminates link integrity.
3. **Lower the GPU power limit** (for example to 80%) to soften load transients. This changes GPU power settings, which `DIAG-GPU-130` holds constant during other isolations.

Optionally, as a separate **software** exposure variable: reduce Forge's per-job model swapping, for example by freeing VRAM held by other GPU applications so CLIP and the UNet stay resident. This lowers the number of transfer bursts; it is not a fix and is not combined with a platform change.

Exit criterion (unchanged): sustained ordinary GPU use comparable to the 10-12 to 10-20 interval (three losses in eight days) without a recurrence after one variable changes.

## Recovery for this incident

1. Reboot; nothing short of that recovers a lost GPU.
2. After restart, StableNew restores quarantine `gpu-6aff599d` from SQLite with the 8 jobs held in order. Release it from the app: this needs operator confirmation plus a fresh healthy host enumeration (`GpuLossCoordinator.release`, PR-QUEUE-GPU-180). A reboot, a healthy WebUI or a recovered GPU alone releases nothing.

## Evidence locations (local, not committed)

A pre-reboot copy of the app log, both Forge logs, the managed ComfyUI log, the 60-day Kernel-PnP 1000 XML, the `nvidia-smi` output and the fixed correlator output is kept in `reports/diagnostics/gpu-6aff599d_20261020/` (ignored by Git). The live files below can rotate.

- Repository: `state/jobs.sqlite3` (jobs `2d60937b...`, `81f4fdc5...`, `2ee36aef...` and the 8 queued jobs).
- App log: `logs/stablenew.log.jsonl` (lines 1440-1497 at capture). Most of its records carry no timestamp, so the timeline above uses the repository, the progress marker, Windows events and file times.
- Forge logs: `logs/webui/webui_stderr_09d73b2e.log`, `webui_stdout_09d73b2e.log`.
- Crash bundle: `reports/diagnostics/stablenew_diagnostics_20261020_225727_ui_heartbeat_stall.zip`.
- Correlator output: `python tools/diagnostics/correlate_gpu_incidents.py --incident 2026-10-20T22:57:28Z --sqlite state/jobs.sqlite3 --webui-log-dir logs/webui --windows-pnp --out <file>`.

## Boundaries and validation

- **Read-only:** Windows event queries, `Win32_*` CIM reads, one `nvidia-smi` query, a read-only SQLite connection, and log and crash-bundle reads.
- **Not done:** no reboot, process action, driver, firmware, power or hardware change, no GPU workload, and no elevation (the WATCHDOG dump folders were not read).
- **Code change (correlator naive-UTC fix plus regression test):** `tests/tools/test_correlate_gpu_incidents.py` and `test_correlate_gpu_incidents_pnp.py` pass (32); `ruff check` passes; the files were already outside the format baseline.
