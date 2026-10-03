"""Read-only WebUI-family runtime identity classification (PR-IMG-FORGE-100).

A1111 and Forge occupy ONE WebUI-family runtime slot (one configured endpoint, one
``WebUIProcessManager``) but are distinct StableNew image backend identities. This module is the
small seam that answers "which identity is the connected endpoint?" from **endpoint evidence only**
- never from process names, window titles, or install-folder names.

Evidence (all read-only ``GET``s, no generation, no options writes):

* Forge: ``/sdapi/v1/cmd-flags`` carries Forge's own ``forge_ref_*`` launch-flag keys **and**
  ``/sdapi/v1/sd-modules`` (Forge's VAE/text-encoder listing) returns a list.
* A1111: ``/sdapi/v1/cmd-flags`` carries no ``forge_*`` keys **and** ``/sdapi/v1/sd-vae`` returns a
  list while ``/sdapi/v1/sd-modules`` does not.
* Anything else (unreachable, malformed, a fork with neither signature) is ``unknown``.

Policy (:func:`assert_runtime_matches_backend`): a ``forge_webui`` backend requires a *positively
identified* Forge; an ``a1111_webui`` backend rejects a positively identified Forge but stays
tolerant of an endpoint it cannot classify (A1111-family forks keep working as before). The guard
runs before any generation dispatch. Nothing here performs network or process work at import time.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

A1111_WEBUI_IDENTITY = "a1111_webui"
FORGE_WEBUI_IDENTITY = "forge_webui"
UNKNOWN_WEBUI_IDENTITY = "unknown"

#: Image backend identities that share the single WebUI-family runtime slot.
WEBUI_FAMILY_IDENTITIES = frozenset({A1111_WEBUI_IDENTITY, FORGE_WEBUI_IDENTITY})

CMD_FLAGS_PATH = "/sdapi/v1/cmd-flags"
SD_MODULES_PATH = "/sdapi/v1/sd-modules"
SD_VAE_PATH = "/sdapi/v1/sd-vae"

_FORGE_FLAG_KEY = "forge_ref_a1111_home"

#: ``fetch(path)`` returns the parsed JSON body, or ``None`` for any failure / non-200 response.
JsonFetch = Callable[[str], Any]


@dataclass(frozen=True)
class WebUIRuntimeIdentity:
    """Classification of one connected WebUI-family endpoint."""

    identity: str = UNKNOWN_WEBUI_IDENTITY
    evidence: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_forge(self) -> bool:
        return self.identity == FORGE_WEBUI_IDENTITY

    @property
    def is_a1111(self) -> bool:
        return self.identity == A1111_WEBUI_IDENTITY

    @property
    def is_known(self) -> bool:
        return self.identity in WEBUI_FAMILY_IDENTITIES


UNKNOWN_RUNTIME_IDENTITY = WebUIRuntimeIdentity()


class WebUIRuntimeIdentityMismatch(RuntimeError):
    """The connected endpoint cannot execute the requested image backend identity."""

    def __init__(self, backend_id: str, observed: WebUIRuntimeIdentity) -> None:
        self.backend_id = backend_id
        self.observed = observed
        if backend_id == FORGE_WEBUI_IDENTITY:
            reason = (
                "forge_webui requires a positively identified Forge endpoint, but the connected "
                f"WebUI was classified '{observed.identity}'"
            )
        else:
            reason = (
                f"{backend_id} cannot run on the connected WebUI, which was classified "
                f"'{observed.identity}'"
            )
        super().__init__(
            f"WebUI runtime identity mismatch: {reason}. Generation was not dispatched; no backend "
            "fallback is performed."
        )


def normalize_webui_runtime_identity(value: Any, *, default: str = A1111_WEBUI_IDENTITY) -> str:
    """Return a known WebUI-family identity, or ``default`` for a missing/blank value.

    An explicit but unrecognized value raises ``ValueError`` (never silently coerced).
    """

    text = str(value or "").strip()
    if not text:
        return default
    if text not in WEBUI_FAMILY_IDENTITIES:
        raise ValueError(
            f"Unknown WebUI runtime identity '{text}'; expected one of "
            f"{sorted(WEBUI_FAMILY_IDENTITIES)}"
        )
    return text


def resolve_configured_webui_runtime_identity(settings: Any = None) -> str:
    """Return the WebUI-family identity StableNew is configured to run (default ``a1111_webui``).

    Reads the explicit ``webui_runtime_identity`` setting (``STABLENEW_WEBUI_RUNTIME_IDENTITY`` is
    the environment fallback). The identity is configuration, never inferred from a model name or an
    install folder. An unrecognized value is logged and degrades to the legacy A1111 default; the
    runtime identity guard still rejects any forge_webui job before dispatch, so a typo cannot make
    a Forge job run on A1111 (or vice versa).
    """

    import logging
    import os

    raw: Any = None
    if isinstance(settings, Mapping):
        raw = settings.get("webui_runtime_identity")
    if not str(raw or "").strip():
        raw = os.environ.get("STABLENEW_WEBUI_RUNTIME_IDENTITY")
    try:
        return normalize_webui_runtime_identity(raw)
    except ValueError as exc:
        logging.getLogger(__name__).error("%s; using %s", exc, A1111_WEBUI_IDENTITY)
        return A1111_WEBUI_IDENTITY


def classify_runtime_identity(cmd_flags: Any, sd_modules: Any, sd_vae: Any) -> WebUIRuntimeIdentity:
    """Pure classification of already-fetched read-only responses."""

    flags_ok = isinstance(cmd_flags, Mapping)
    forge_flag = flags_ok and _FORGE_FLAG_KEY in cmd_flags
    any_forge_key = flags_ok and any(str(key).startswith("forge_") for key in cmd_flags)
    modules_ok = isinstance(sd_modules, list)
    vae_ok = isinstance(sd_vae, list)
    evidence = {
        "cmd_flags_readable": flags_ok,
        "forge_flag_present": bool(forge_flag),
        "sd_modules_list": modules_ok,
        "sd_vae_list": vae_ok,
    }
    if forge_flag and modules_ok:
        return WebUIRuntimeIdentity(FORGE_WEBUI_IDENTITY, evidence)
    if flags_ok and not any_forge_key and vae_ok and not modules_ok:
        return WebUIRuntimeIdentity(A1111_WEBUI_IDENTITY, evidence)
    return WebUIRuntimeIdentity(UNKNOWN_WEBUI_IDENTITY, evidence)


def probe_runtime_identity(fetch: JsonFetch) -> WebUIRuntimeIdentity:
    """Classify an endpoint through ``fetch`` using only read-only GETs.

    Never raises: any fetch failure degrades to ``unknown``.
    """

    sd_modules: Any = None
    sd_vae: Any = None
    try:
        cmd_flags = fetch(CMD_FLAGS_PATH)
        if isinstance(cmd_flags, Mapping):
            sd_modules = fetch(SD_MODULES_PATH)
            if _FORGE_FLAG_KEY not in cmd_flags:
                # A1111 evidence: its VAE route answers and Forge's module route does not.
                sd_vae = fetch(SD_VAE_PATH)
    except Exception:  # noqa: BLE001 - classification is best-effort and read-only
        return UNKNOWN_RUNTIME_IDENTITY
    return classify_runtime_identity(cmd_flags, sd_modules, sd_vae)


def probe_endpoint_runtime_identity(
    base_url: str,
    *,
    timeout: float = 2.0,
    http_get: Callable[..., Any] | None = None,
) -> WebUIRuntimeIdentity:
    """Read-only classification of a configured endpoint (no discovery, no mutation)."""

    if http_get is None:
        import requests

        http_get = requests.get
    root = str(base_url or "").rstrip("/")

    def _fetch(path: str) -> Any:
        try:
            response = http_get(f"{root}{path}", timeout=max(float(timeout), 0.01))
        except Exception:  # noqa: BLE001 - unreachable endpoint is simply unclassified
            return None
        if getattr(response, "status_code", None) != 200:
            return None
        try:
            return response.json()
        except Exception:  # noqa: BLE001
            return None

    return probe_runtime_identity(_fetch)


def classify_client_runtime(client: Any) -> WebUIRuntimeIdentity:
    """Classify the endpoint a client is bound to; clients without a probe are ``unknown``."""

    probe = getattr(client, "probe_runtime_identity", None)
    if not callable(probe):
        return UNKNOWN_RUNTIME_IDENTITY
    try:
        observed = probe()
    except Exception:  # noqa: BLE001
        return UNKNOWN_RUNTIME_IDENTITY
    return observed if isinstance(observed, WebUIRuntimeIdentity) else UNKNOWN_RUNTIME_IDENTITY


def assert_runtime_matches_backend(backend_id: str, observed: WebUIRuntimeIdentity) -> None:
    """Reject a backend/endpoint pairing before any generation dispatch."""

    if backend_id == FORGE_WEBUI_IDENTITY:
        if not observed.is_forge:
            raise WebUIRuntimeIdentityMismatch(backend_id, observed)
        return
    if backend_id == A1111_WEBUI_IDENTITY:
        if observed.is_forge:
            raise WebUIRuntimeIdentityMismatch(backend_id, observed)
        return
    raise ValueError(f"'{backend_id}' is not a WebUI-family image backend identity")


__all__ = [
    "A1111_WEBUI_IDENTITY",
    "FORGE_WEBUI_IDENTITY",
    "UNKNOWN_RUNTIME_IDENTITY",
    "UNKNOWN_WEBUI_IDENTITY",
    "WEBUI_FAMILY_IDENTITIES",
    "WebUIRuntimeIdentity",
    "WebUIRuntimeIdentityMismatch",
    "assert_runtime_matches_backend",
    "classify_client_runtime",
    "classify_runtime_identity",
    "normalize_webui_runtime_identity",
    "probe_endpoint_runtime_identity",
    "probe_runtime_identity",
    "resolve_configured_webui_runtime_identity",
]
