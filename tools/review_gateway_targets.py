"""The gateways the operator tools may address (PHONE-CORE PS-1): a closed set, ``production`` and ``staging``.

Production's settings are the ones StableNew's Phone review gateway dialog saved. Staging's are in a separate DPAPI
file that only the tools read, with the phone page's address beside it (also DPAPI). A target is only ever a word from
``TARGETS``: never a path, an address, a ref or a shell string (threat T12). Staging settings that share production's
address, certificate or secret are refused, so a staging command cannot reach production (threat T11).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from src.app import review_gateway_store as gateway_store
from src.app.review_gateway_client import GatewayClient, PinnedHttpsTransport
from src.app.review_gateway_store import GatewaySettings, GatewaySettingsStore
from src.app.site_phone_credentials import protect_for_current_user, unprotect_for_current_user
from src.utils.atomic_io import atomic_write_bytes

PRODUCTION = "production"
STAGING = "staging"
TARGETS = (PRODUCTION, STAGING)
CONFIGURE_HINT = "python -m tools.review_gateway_deploy --target staging configure"
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
_URL_LIMIT = 4096


class NoSettings(Exception):
    """The target has not been configured for this Windows user."""


class TargetMixup(Exception):
    """Staging settings that would reach production, or that cannot be shown not to."""


def parse_phone_url(text: str) -> str:
    """``https://host[:port]`` and nothing else; plain ``http`` only for a gateway on this PC (tests)."""

    value = text.strip().rstrip("/")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        parts, port = urlsplit(""), None
    host = parts.hostname or ""
    secure = parts.scheme == "https" or (parts.scheme == "http" and host in _LOOPBACK)
    plain = not (parts.path or parts.query or parts.fragment or "@" in parts.netloc)
    if not (secure and host and plain and port != 0 and not any(c.isspace() for c in value)):
        raise ValueError("Enter the phone address as https://<name>.<tailnet>.ts.net (no path).")
    return value


class StagingPhoneStore:
    """The staging phone page's address, DPAPI-protected: a tailnet name is not for the repository or a log."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        protect: Callable[[bytes], bytes] = protect_for_current_user,
        unprotect: Callable[[bytes], bytes] = unprotect_for_current_user,
    ) -> None:
        self._path = path
        self._protect = protect
        self._unprotect = unprotect

    @property
    def path(self) -> Path:
        if self._path is not None:
            return self._path
        return GatewaySettingsStore(name=STAGING).path.with_name("staging-phone.dpapi")

    def load(self) -> str | None:
        try:
            with self.path.open("rb") as source:
                encrypted = source.read(_URL_LIMIT)
        except FileNotFoundError:
            return None
        return parse_phone_url(self._unprotect(encrypted).decode("utf-8"))

    def save(self, url: str) -> None:
        atomic_write_bytes(self.path, self._protect(parse_phone_url(url).encode("utf-8")))


def check_separate(
    staging: GatewaySettings, production: gateway_store.GatewaySettingsStore
) -> None:
    """Refuse staging values that are production's. Without production settings there is nothing to confuse."""

    try:
        live = production.load()
    except (OSError, ValueError) as error:
        raise TargetMixup(
            "Production's settings cannot be read, so staging cannot be shown to be a different gateway."
        ) from error
    if live is None:
        return
    shared = [
        what
        for what, same in (
            ("address", staging.host.lower() == live.host.lower()),
            ("certificate fingerprint", staging.fingerprint == live.fingerprint),
            ("sync secret", staging.secret == live.secret),
        )
        if same
    ]
    if shared:
        raise TargetMixup(
            f"Refused: the staging {' and '.join(shared)} is production's. Staging is its own gateway."
        )


def staging_settings(
    store: GatewaySettingsStore | None = None, production: GatewaySettingsStore | None = None
) -> GatewaySettings:
    settings = (store or GatewaySettingsStore(name=STAGING)).load()
    if settings is None:
        raise NoSettings
    check_separate(settings, production or GatewaySettingsStore())
    return settings


def staging_client(
    store: GatewaySettingsStore | None = None, production: GatewaySettingsStore | None = None
) -> GatewayClient:
    settings = staging_settings(store, production)
    return GatewayClient(PinnedHttpsTransport(settings), settings.secret)
