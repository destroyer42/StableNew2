"""Read-only WebUI-family runtime identity classification (PR-IMG-FORGE-100).

A1111 and Forge occupy ONE WebUI-family runtime slot (one configured endpoint, one
``WebUIProcessManager``) but are distinct StableNew image backend identities. This module is the
small seam that answers "which identity is the connected endpoint?" from **endpoint evidence only**
- never from process names, window titles, or install-folder names.

Evidence (all read-only ``GET``s, no generation, no options writes):

* Forge: ``/sdapi/v1/options`` contains explicit Forge-only options **and**
  ``/sdapi/v1/sd-modules`` returns a list, without a conflicting A1111 VAE signature.
* A1111: readable options carry no ``forge_*`` keys, ``/sdapi/v1/sd-vae`` returns a list,
  and ``/sdapi/v1/sd-modules`` is unavailable.
* ``/sdapi/v1/cmd-flags`` is optional corroboration: Neo can return HTTP 500 for real flags.
* Anything else (unreachable, malformed, a fork with neither signature) is ``unknown``.

Policy (:func:`assert_runtime_matches_backend`): a ``forge_webui`` backend requires a *positively
identified* Forge; an ``a1111_webui`` backend rejects a positively identified Forge but stays
tolerant of an endpoint it cannot classify (A1111-family forks keep working as before). The guard
runs before any generation dispatch. Nothing here performs network or process work at import time.

Configured identity (PR-IMG-FORGE-120): an unset ``webui_runtime_identity`` is the product default, managed Forge;
an explicit ``a1111_webui`` is the supported rollback; an unrecognized value fails closed. The default endpoint is
identity-aware (Forge ``127.0.0.1:7871``, A1111 ``127.0.0.1:7860``). There is no fallback between the two.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

A1111_WEBUI_IDENTITY = "a1111_webui"
FORGE_WEBUI_IDENTITY = "forge_webui"
UNKNOWN_WEBUI_IDENTITY = "unknown"

#: The runtime identity of NEW production work when nothing is configured (PR-IMG-FORGE-120): managed Forge.
#: A1111 stays supported, but only as an explicit ``webui_runtime_identity`` rollback.
DEFAULT_WEBUI_RUNTIME_IDENTITY = FORGE_WEBUI_IDENTITY

#: A1111's default endpoint and the flat default every settings file written before the Forge promotion persisted.
A1111_DEFAULT_BASE_URL = "http://127.0.0.1:7860"

#: Image backend identities that share the single WebUI-family runtime slot.
WEBUI_FAMILY_IDENTITIES = frozenset({A1111_WEBUI_IDENTITY, FORGE_WEBUI_IDENTITY})

CMD_FLAGS_PATH = "/sdapi/v1/cmd-flags"
OPTIONS_PATH = "/sdapi/v1/options"
SD_MODULES_PATH = "/sdapi/v1/sd-modules"
SD_VAE_PATH = "/sdapi/v1/sd-vae"

_FORGE_FLAG_KEY = "forge_ref_a1111_home"
_FORGE_OPTION_KEYS = frozenset({
    "forge_additional_modules", "forge_preset", "forge_unet_storage_dtype",
})

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


class WebUIRuntimeConfigurationError(ValueError):
    """The configured WebUI runtime identity is unusable; configuration fails closed (never a silent A1111/Forge swap)."""


class WebUIRuntimeIdentityMismatch(RuntimeError):
    """The connected endpoint cannot execute the requested image backend identity."""

    def __init__(self, backend_id: str, observed: WebUIRuntimeIdentity, *, detail: str = "") -> None:
        self.backend_id = backend_id
        self.observed = observed
        self.detail = detail
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
            if backend_id == A1111_WEBUI_IDENTITY and observed.is_forge:
                reason += (
                    " (ACTION REQUIRED: StableNew is configured for managed Forge, the product default. To run "
                    "this A1111 job, such as a replay of work created before the Forge default, select the A1111 "
                    "rollback explicitly with webui_runtime_identity = a1111_webui and restart StableNew)"
                )
        super().__init__(
            f"WebUI runtime identity mismatch: {reason}. Generation was not dispatched; no backend "
            "fallback is performed."
            + (f" [identity: {detail}]" if detail else "")
        )


def normalize_webui_runtime_identity(value: Any, *, default: str = DEFAULT_WEBUI_RUNTIME_IDENTITY) -> str:
    """Return a known WebUI-family identity, or ``default`` for a missing/blank value.

    An explicit but unrecognized value raises :class:`WebUIRuntimeConfigurationError` (never silently coerced).
    """

    text = str(value or "").strip()
    if not text:
        return default
    if text not in WEBUI_FAMILY_IDENTITIES:
        raise WebUIRuntimeConfigurationError(
            f"Unknown WebUI runtime identity '{text}'; expected one of {sorted(WEBUI_FAMILY_IDENTITIES)}. "
            "Fix webui_runtime_identity (or STABLENEW_WEBUI_RUNTIME_IDENTITY); no backend fallback is performed."
        )
    return text


def resolve_configured_webui_runtime_identity(settings: Any = None) -> str:
    """Return the WebUI-family identity StableNew is configured to run (default ``forge_webui``).

    Reads the explicit ``webui_runtime_identity`` setting (``STABLENEW_WEBUI_RUNTIME_IDENTITY`` is the
    environment fallback). A missing/blank value selects the product default, managed Forge; an explicit
    ``a1111_webui`` is the supported rollback and is never rewritten. The identity is configuration, never
    inferred from a model name or an install folder. An unrecognized value raises
    :class:`WebUIRuntimeConfigurationError`: configuration fails closed, there is no silent degradation to either
    backend.
    """

    import os

    raw: Any = None
    if isinstance(settings, Mapping):
        raw = settings.get("webui_runtime_identity")
    if not str(raw or "").strip():
        raw = os.environ.get("STABLENEW_WEBUI_RUNTIME_IDENTITY")
    return normalize_webui_runtime_identity(raw)


def load_backend_settings(config_manager: Any = None) -> Mapping[str, Any]:
    """The settings backend/runtime selection reads, failing closed when they cannot be read.

    ``ConfigManager.load_settings`` tolerates a corrupt ``settings.json`` (it logs and uses defaults) because most
    settings are cosmetic. Backend selection is not: silently reading defaults could drop an explicit
    ``webui_runtime_identity = a1111_webui`` rollback and run on Forge, or the reverse. An unreadable file or manager
    therefore raises :class:`WebUIRuntimeConfigurationError`; nothing is selected and no generation is attempted.
    """

    try:
        if config_manager is None:
            from src.utils.config import ConfigManager

            config_manager = ConfigManager()
        settings = config_manager.load_settings()
    except WebUIRuntimeConfigurationError:
        raise
    except Exception as exc:  # noqa: BLE001 - any read failure is a configuration error here
        raise WebUIRuntimeConfigurationError(
            f"The StableNew settings could not be read ({exc}); the WebUI runtime was not selected and no backend "
            "fallback is performed. Fix or remove the settings file."
        ) from exc
    load_error = getattr(config_manager, "settings_load_error", None)
    if isinstance(load_error, str) and load_error:
        raise WebUIRuntimeConfigurationError(
            f"The StableNew settings file is unreadable ({load_error}); the WebUI runtime was not selected and no "
            "backend fallback is performed. Fix or remove presets/settings.json."
        )
    return settings if isinstance(settings, Mapping) else {}


def default_webui_base_url(identity: str) -> str:
    """The identity-aware default endpoint: managed Forge ``127.0.0.1:7871`` (from its manifest), A1111 ``:7860``."""

    if identity == FORGE_WEBUI_IDENTITY:
        from src.utils.managed_forge_runtime import default_endpoint

        return default_endpoint()
    return A1111_DEFAULT_BASE_URL


def explicit_webui_base_url(settings: Any = None, *, identity: str | None = None) -> str | None:
    """The endpoint the operator explicitly chose for this identity, or ``None`` (use the identity default).

    Precedence is unchanged: ``webui_base_url`` setting, then ``STABLENEW_WEBUI_BASE_URL``. For Forge, the A1111
    default ``http://127.0.0.1:7860`` is not an explicit Forge endpoint: every settings file written before the
    promotion persisted it as the flat default, so it carries no operator intent for Forge and resolves to the
    Forge default. A genuinely different URL stays authoritative (and is validated against the managed runtime).
    """

    import os

    resolved = identity or resolve_configured_webui_runtime_identity(settings)
    value = ""
    if isinstance(settings, Mapping):
        value = str(settings.get("webui_base_url") or "").strip()
    if resolved == FORGE_WEBUI_IDENTITY and value.rstrip("/") == A1111_DEFAULT_BASE_URL:
        value = ""
    if not value:
        value = os.environ.get("STABLENEW_WEBUI_BASE_URL", "").strip()
    return value or None


def resolve_effective_webui_base_url(settings: Any = None, *, identity: str | None = None) -> str:
    """The endpoint of the configured WebUI-family runtime: the explicit choice, else the identity default."""

    resolved = identity or resolve_configured_webui_runtime_identity(settings)
    return explicit_webui_base_url(settings, identity=resolved) or default_webui_base_url(resolved)


def effective_webui_base_url() -> str:
    """:func:`resolve_effective_webui_base_url` for callers that hold no settings (reads them strictly)."""

    return resolve_effective_webui_base_url(load_backend_settings())


def _endpoint_state(value: Any, well_formed: bool) -> str:
    if value is None:
        return "unavailable"
    return "ok" if well_formed else "malformed"


def classify_runtime_identity(
    cmd_flags: Any, sd_modules: Any, sd_vae: Any, *, options: Any = None,
) -> WebUIRuntimeIdentity:
    """Pure classification of already-fetched read-only responses."""

    flags_ok = isinstance(cmd_flags, Mapping)
    forge_flag = flags_ok and _FORGE_FLAG_KEY in cmd_flags
    any_forge_key = flags_ok and any(str(key).startswith("forge_") for key in cmd_flags)
    options_ok = isinstance(options, Mapping)
    forge_options = sorted(_FORGE_OPTION_KEYS.intersection(options)) if options_ok else []
    any_forge_option = options_ok and any(str(key).startswith("forge_") for key in options)
    modules_ok = isinstance(sd_modules, list)
    vae_ok = isinstance(sd_vae, list)
    evidence = {
        "cmd_flags_readable": flags_ok,
        "forge_flag_present": bool(forge_flag),
        "options_readable": options_ok,
        "forge_option_keys": forge_options,
        "any_forge_option": any_forge_option,
        "sd_modules_list": modules_ok,
        "sd_vae_list": vae_ok,
        # Per endpoint: readable ("ok"), no usable response ("unavailable"), or a response of the wrong shape
        # ("malformed"). Facts only, never raw payloads (an options body can carry paths and tokens).
        "endpoint_state": {
            "cmd_flags": _endpoint_state(cmd_flags, flags_ok),
            "options": _endpoint_state(options, options_ok),
            "sd_modules": _endpoint_state(sd_modules, modules_ok),
            "sd_vae": _endpoint_state(sd_vae, vae_ok),
        },
    }
    if options_ok and forge_options and modules_ok and sd_vae is None:
        return WebUIRuntimeIdentity(FORGE_WEBUI_IDENTITY, evidence)
    if options_ok and not any_forge_option and not any_forge_key and vae_ok and sd_modules is None:
        return WebUIRuntimeIdentity(A1111_WEBUI_IDENTITY, evidence)
    return WebUIRuntimeIdentity(UNKNOWN_WEBUI_IDENTITY, evidence)


def probe_runtime_identity(fetch: JsonFetch) -> WebUIRuntimeIdentity:
    """Classify an endpoint through ``fetch`` using only read-only GETs.

    Never raises. Each failed probe is unavailable evidence; optional flags cannot
    prevent independent positive options/module evidence from being evaluated.
    """

    responses = {}
    for path in (CMD_FLAGS_PATH, OPTIONS_PATH, SD_MODULES_PATH, SD_VAE_PATH):
        try:
            responses[path] = fetch(path)
        except Exception:  # noqa: BLE001 - each probe is best-effort and read-only
            responses[path] = None
    if all(value is None for value in responses.values()):
        return UNKNOWN_RUNTIME_IDENTITY
    return classify_runtime_identity(
        responses[CMD_FLAGS_PATH], responses[SD_MODULES_PATH], responses[SD_VAE_PATH],
        options=responses[OPTIONS_PATH],
    )


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
    "A1111_DEFAULT_BASE_URL",
    "A1111_WEBUI_IDENTITY",
    "DEFAULT_WEBUI_RUNTIME_IDENTITY",
    "FORGE_WEBUI_IDENTITY",
    "UNKNOWN_RUNTIME_IDENTITY",
    "UNKNOWN_WEBUI_IDENTITY",
    "WEBUI_FAMILY_IDENTITIES",
    "WebUIRuntimeConfigurationError",
    "WebUIRuntimeIdentity",
    "WebUIRuntimeIdentityMismatch",
    "assert_runtime_matches_backend",
    "classify_client_runtime",
    "classify_runtime_identity",
    "default_webui_base_url",
    "effective_webui_base_url",
    "explicit_webui_base_url",
    "load_backend_settings",
    "normalize_webui_runtime_identity",
    "probe_endpoint_runtime_identity",
    "probe_runtime_identity",
    "resolve_configured_webui_runtime_identity",
    "resolve_effective_webui_base_url",
]
