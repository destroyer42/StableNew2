# Subsystem: Controller
# Role: Read-only WebUI readiness + runtime-identity proof shared by outage release and the runtime handoff.

"""One fresh, bounded, read-only proof that the configured WebUI endpoint is a usable runtime of a given identity.

It never discovers ports, starts, stops or adopts anything. ``expected`` selects the identity the proof must match: the
configured identity by default, or the frozen backend identity of the job that needs the runtime (a historical A1111
record is never proven against Forge).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProbeResult:
    ready: bool
    reason: str = ""
    endpoint: str = ""
    identity: str = ""
    recovery_allowed: bool = True


def probe_webui_runtime(expected: str | None = None) -> ProbeResult:
    """Read-only, bounded readiness + runtime-identity proof of the configured endpoint (no discovery, no mutation)."""

    from src.api.healthcheck import probe_webui_endpoint
    from src.api.webui_runtime_identity import (
        WebUIRuntimeIdentityMismatch,
        assert_runtime_matches_backend,
        effective_webui_base_url,
        load_backend_settings,
        probe_endpoint_runtime_identity,
        resolve_configured_webui_runtime_identity,
    )

    try:
        base_url = effective_webui_base_url()
        expected = expected or resolve_configured_webui_runtime_identity(load_backend_settings())
    except Exception as exc:  # noqa: BLE001 - an unreadable configuration is "not proven ready"
        return ProbeResult(
            False, f"configuration_unreadable:{type(exc).__name__}", recovery_allowed=False
        )
    state = probe_webui_endpoint(base_url, timeout=1.5)
    if state != "healthy":
        return ProbeResult(False, f"endpoint_{state}", base_url)
    observed = probe_endpoint_runtime_identity(base_url, timeout=2.0)
    evidence = getattr(observed, "evidence", {}) or {}
    if evidence.get("options_readable") is not True:
        return ProbeResult(
            False, "options_unreadable", base_url, str(observed.identity), recovery_allowed=False
        )
    try:
        assert_runtime_matches_backend(expected, observed)
    except WebUIRuntimeIdentityMismatch:
        return ProbeResult(
            False, "identity_mismatch", base_url, str(observed.identity), recovery_allowed=False
        )
    except ValueError:
        return ProbeResult(
            False, "identity_unsupported", base_url, str(observed.identity), recovery_allowed=False
        )
    return ProbeResult(True, "ready", base_url, str(observed.identity))


__all__ = ["ProbeResult", "probe_webui_runtime"]
