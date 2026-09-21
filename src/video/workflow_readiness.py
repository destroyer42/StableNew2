"""Bounded, workflow-specific resource-readiness check (PR-VID-130).

This is deliberately **not** a scheduler, allocator, lease manager or process controller.  It
only *observes* the reachable Comfy runtime and the host and answers one question before a queue
dispatch: "does this workflow's declared, qualification-derived floor look satisfiable right now?"
It never terminates, adopts, restarts or reconfigures any process (A1111, Comfy, or otherwise) and
never retries or replays a job; a failing check simply fails the job with what is blocking.

A workflow opts in by declaring ``backend_defaults["resource_readiness"]``; workflows without the
declaration are not checked (so approved workflows such as the LTX pair are unaffected).

Thresholds for ``wan22_ti2v_5b`` come from the PR-VID-110 measurements on the RTX 4070 Ti 12 GB
(12,282 MiB): the operator-media run peaked at 11,690 MiB whole-GPU with 2,120 MiB already used
outside the run, i.e. a 9,570 MiB footprint, and the earlier studio runs peaked at 11.1-11.6 GiB
whole-GPU. Headroom is therefore narrow by measurement, not comfortable.

* **VRAM available to Comfy** = driver-free VRAM + the VRAM Comfy's own allocator already holds
  (``torch_vram_total``). Memory Comfy holds itself (for example a Wan model that is already
  loaded) is reusable by Comfy, so a warm, valid state is not rejected; memory held by *other*
  processes (A1111, desktop apps) is what lowers the number. The floor is 10,000 MiB (the
  9,570 MiB measured footprint plus ~430 MiB margin). The measure is slightly conservative: the
  CUDA context Comfy itself owns is counted as outside use.
* **Available host RAM** floor 16 GB. The three models are 18.1 GB on disk and are memory-mapped
  on a cold load; qualification runs started with 20.8-27 GB available and still dipped to
  0.01-0.05 GB free transiently. Windows counts standby cache as available, so a warm load is not
  penalised. Below the floor a cold load is likely to thrash the pagefile.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

_MIB = 1024 * 1024


def _host_available_ram_gb() -> float:
    import psutil

    return float(psutil.virtual_memory().available) / 1e9


@dataclass(frozen=True, slots=True)
class ResourceReadinessResult:
    ready: bool
    blocking: tuple[str, ...] = ()
    observations: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": bool(self.ready),
            "blocking": list(self.blocking),
            "observations": dict(self.observations),
        }

    @property
    def message(self) -> str:
        return "; ".join(self.blocking)


class WorkflowResourceReadiness:
    def __init__(self, *, ram_probe: Callable[[], float] | None = None) -> None:
        self._ram_probe = ram_probe or _host_available_ram_gb

    @staticmethod
    def policy_for(spec: Any) -> Mapping[str, Any] | None:
        policy = (getattr(spec, "backend_defaults", None) or {}).get("resource_readiness")
        return policy if isinstance(policy, Mapping) and policy else None

    def evaluate(self, spec: Any, *, system_stats: Mapping[str, Any]) -> ResourceReadinessResult:
        policy = self.policy_for(spec)
        if policy is None:
            return ResourceReadinessResult(ready=True, observations={"policy": None})
        blocking: list[str] = []
        observations: dict[str, Any] = {"policy": policy.get("policy")}

        vram_floor = float(policy.get("min_available_to_comfy_vram_mib") or 0)
        if vram_floor:
            devices = [
                device
                for device in (system_stats.get("devices") or [])
                if isinstance(device, Mapping) and str(device.get("type") or "").lower() == "cuda"
            ]
            if not devices:
                blocking.append(
                    "ComfyUI reports no CUDA device, so GPU memory readiness cannot be verified"
                )
            else:
                device = devices[0]
                total = float(device.get("vram_total") or 0) / _MIB
                free = float(device.get("vram_free") or 0) / _MIB
                held_by_comfy = float(device.get("torch_vram_total") or 0) / _MIB
                available = free + held_by_comfy
                observations.update(
                    vram_total_mib=round(total),
                    vram_free_mib=round(free),
                    vram_held_by_comfy_mib=round(held_by_comfy),
                    vram_available_to_comfy_mib=round(available),
                    vram_floor_mib=round(vram_floor),
                )
                if available < vram_floor:
                    blocking.append(
                        f"only {available:.0f} MiB of GPU memory is available to ComfyUI "
                        f"(needs {vram_floor:.0f} MiB; {total - available:.0f} MiB of {total:.0f} "
                        "MiB is in use by other processes). Close other GPU applications "
                        "(for example A1111); StableNew will not stop them for you"
                    )

        ram_floor = float(policy.get("min_available_ram_gb") or 0)
        if ram_floor:
            available_ram = float(self._ram_probe())
            observations.update(
                ram_available_gb=round(available_ram, 1), ram_floor_gb=round(ram_floor, 1)
            )
            if available_ram < ram_floor:
                blocking.append(
                    f"only {available_ram:.1f} GB of system RAM is available (needs "
                    f"{ram_floor:.1f} GB for a cold Wan2.2 model load). Close memory-heavy "
                    "applications and retry"
                )
        return ResourceReadinessResult(
            ready=not blocking, blocking=tuple(blocking), observations=observations
        )


__all__ = ["ResourceReadinessResult", "WorkflowResourceReadiness"]
