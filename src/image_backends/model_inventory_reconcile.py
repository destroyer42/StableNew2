"""Explicit, GET-only reconciliation of the offline inventory with one already-running WebUI endpoint (PR-IMG-MODELS-152).

Invoked only by an operator action (the report tool's ``--forge-url``). It never starts, restarts or probes for a process,
never writes an option, never POSTs a module or model selection and never attributes managed-Forge qualification to an
endpoint it did not verify. The endpoint's *served* state answers "what does this endpoint list", never "what is on disk"
or "is it qualified"; a failed or blocked read is ``unavailable``, never empty (the existing ``get_module_catalog`` and
``get_additional_modules`` tri-state is preserved, and ``get_models`` -- whose legacy contract returns ``[]`` for any
failure -- is therefore treated as unavailable when it is empty).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.api.webui_runtime_identity import classify_client_runtime
from src.image_backends.model_readiness_probe import checkpoint_key


def _safe(call: Any) -> Any:
    try:
        return call()
    except Exception:  # noqa: BLE001 - a failed read is "unavailable", reported as such
        return None


def read_forge_state(client: Any) -> dict[str, Any]:
    """Read-only snapshot of one endpoint's served checkpoints, module catalog and current selection."""

    identity = classify_client_runtime(client)
    state: dict[str, Any] = {
        "status": "observed" if identity.is_forge else "unverified_runtime",
        "runtime_identity": identity.identity,
        "checkpoint_listing": "unavailable",
        "served_files": None,
        "selection": "unavailable",
        "selected_file": None,
        "module_catalog": "unavailable",
        "module_names": None,
        "selected_modules": None,
    }
    if not identity.is_forge:
        return state  # unverified or non-Forge: nothing further is read or attributed

    entries = _safe(getattr(client, "get_models", lambda: None))
    if isinstance(entries, list) and entries:
        state["checkpoint_listing"] = "observed"
        state["served_files"] = [
            str(item["filename"])
            for item in entries
            if isinstance(item, Mapping) and item.get("filename")
        ]
        current = _safe(getattr(client, "get_current_model", lambda: None))
        if isinstance(current, str):
            state["selection"] = "observed"
            wanted = checkpoint_key(current)
            matches = sorted(
                {
                    str(item["filename"])
                    for item in entries
                    if isinstance(item, Mapping)
                    and item.get("filename")
                    and wanted
                    in {
                        checkpoint_key(item.get("title")),
                        checkpoint_key(item.get("model_name")),
                        checkpoint_key(item.get("filename")),
                    }
                }
            )
            state["selected_file"] = matches[0] if len(matches) == 1 else None
    # an empty ``/sd-models`` answer is indistinguishable from a failed read through the legacy client: unavailable

    catalog = _safe(getattr(client, "get_module_catalog", lambda: None))
    if isinstance(catalog, list):
        state["module_catalog"] = "empty" if not catalog else "observed"
        state["module_names"] = sorted(
            str(item.get("model_name"))
            for item in catalog
            if isinstance(item, Mapping) and item.get("model_name")
        )
    selected = _safe(getattr(client, "get_additional_modules", lambda: None))
    if isinstance(selected, list):
        state["selected_modules"] = sorted(str(item) for item in selected)
    return state


__all__ = ["read_forge_state"]
