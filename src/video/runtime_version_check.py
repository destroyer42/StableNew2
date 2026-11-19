"""Warn when an approved Comfy workflow runs on a ComfyUI version it was not qualified on (VID-CLIP-372).

A workflow spec records the ComfyUI version its evidence came from in ``backend_defaults["provenance"]
["comfyui_version"]``.  An approved workflow is a production backend, so running it on a different
runtime (an older managed install, an external ComfyUI) is allowed but is said out loud: nothing here
blocks, starts or changes anything.  Experimental workflows are never warned about; they already
need the job's own opt-in.  Pure functions over plain values; standard library only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.video.workflow_contracts import WORKFLOW_GOVERNANCE_APPROVED


def qualified_comfyui_version(spec: Any) -> str:
    """The ComfyUI version the spec's evidence was produced on, or an empty string if undeclared."""

    provenance = (getattr(spec, "backend_defaults", None) or {}).get("provenance")
    if not isinstance(provenance, Mapping):
        return ""
    return str(provenance.get("comfyui_version") or "").strip()


def runtime_version_warning(spec: Any, actual_version: Any) -> str | None:
    """A one-sentence warning, or ``None`` when the versions match or either side is unknown."""

    if getattr(spec, "governance_state", "") != WORKFLOW_GOVERNANCE_APPROVED:
        return None
    qualified = qualified_comfyui_version(spec)
    actual = str(actual_version or "").strip()
    if not qualified or not actual or actual == qualified:
        return None
    return (
        f"Workflow '{spec.workflow_id}' {spec.workflow_version} was qualified on ComfyUI {qualified}, "
        f"but this runtime reports {actual}. It will run; speed, memory use and output are not covered "
        "by that evidence."
    )


__all__ = ["qualified_comfyui_version", "runtime_version_warning"]
