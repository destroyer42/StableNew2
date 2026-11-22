# DIAG-GPU-160 — PCIe Gen4 device-loss resolution

## Status

**RESOLVED BY OWNER PLATFORM CHANGE (owner-accepted 2026-11-22).**

The owner reported that the GPU display crashed “somewhat randomly but periodically.”
They changed the motherboard UEFI PCIe link speed from **Auto to forced Gen4** and
reported no further display crash after “hours upon hours” of image and video generation.
The owner considers the issue resolved and cleared it as a standing blocker.

## Platform change and evidence

On the ASRock Z690-C/D5, the PNY RTX 4070 Ti sits in the CPU-attached x16 slot
(`PCIE1`). [DIAG-GPU-150](DIAG-GPU-150_Three_Losses_in_11_Hours_and_the_Hang_Recorder.md) proposed
forcing Gen3. The owner instead forced Gen4. The symptom stopped after leaving
Auto while using Gen4, which is
consistent with a problem in automatic link-speed negotiation. The owner-observed
multi-hour stress run provides the basis for closure. There is no recorder trace
or controlled comparison to establish a root cause, and no physical qualification
verdict follows from this observation.

## Recurrence and qualification

The device-loss quarantine and per-run qualification stop conditions remain in effect.
The [GPU hang recorder](../../../tools/diagnostics/gpu_hang_recorder.py) is available
for optional diagnostics. Any new device loss stops the affected run and reopens
this record for the owner to reinstate the standing hold. Each physical
qualification run still requires fresh explicit owner authorization of its exact plan
([SYSTEM-840 runbook, section 2](../../runbooks/qual_system_840.md)).
