"""Local, cryptographic identity of the Klein files the serving Forge will actually load (PR-IMG-116 review repair).

Forge API names (``/sd-models``, ``/sd-modules``, the ``/options`` read-back) say which *names* are selected, never which
*bytes* are behind them, and an external Forge can expose the expected names over different bytes. Qualified Klein v1
therefore requires the StableNew-owned managed Forge: before a dispatch the data directory is taken from the *actual
launch-session command* of the process the existing ``WebUIProcessManager`` owns and that serves the client's endpoint, and
the exact size and SHA-256 of the three files are verified there against the immutable profile. Any link that cannot be
positively established fails closed (no adoption, restart or modification of an external Forge). This restriction is for
the qualified Klein profile only; ordinary Forge support is untouched.

A verified file is remembered keyed by its stat identity (path, size, mtime, ctime, inode, device): the first use is
hashed, any observed change forces a rehash, so ~12.45 GB is not re-read on every job.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.image_backends.forge_klein_profile import KleinAsset, KleinProfile, KleinProfileError

logger = logging.getLogger(__name__)

_DATA_DIR_FLAG = "--data-dir"
_VERIFIED: dict[tuple[Any, ...], str] = {}
_LOCK = threading.Lock()

#: Forge rebuilds ``/sd-models`` and ``/sd-modules`` in place (``sd_models.list_models`` clears the checkpoint list and
#: re-walks every model directory; ``main_entry.refresh_models`` does the same for the module list). That happens when
#: its UI page loads (Forge opens it in a browser on start by default) or on a refresh, so right after a launch a
#: READY Forge can briefly list no checkpoints or only some modules. StableNew's own client also answers ``[]``/``None``
#: while a catalog read is deferred or on cooldown. A pinned file that is not listed yet is therefore re-read within
#: this bound before the exact-profile check refuses; two real matches still refuse at once.
CATALOG_SETTLE_TIMEOUT_S = 20.0
CATALOG_POLL_INTERVAL_S = 1.0
_monotonic: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep


def clear_verified_cache() -> None:
    with _LOCK:
        _VERIFIED.clear()


def data_dir_from_launch_command(command: list[str]) -> Path | None:
    """The managed runtime's ``--data-dir`` from its launch command (``--data-dir X`` or ``--data-dir=X``)."""

    for index, token in enumerate(command):
        if token == _DATA_DIR_FLAG and index + 1 < len(command):
            return Path(command[index + 1])
        if token.startswith(_DATA_DIR_FLAG + "="):
            return Path(token.split("=", 1)[1])
    return None


_MANAGED_ONLY = (
    "Qualified Klein v1 requires the StableNew-owned managed Forge: StableNew must bind the asset provenance "
    "to the files loaded by the serving runtime. Start Forge through StableNew's managed runtime profile "
    "(external Forge remains supported for other models); an external Forge is never adopted, restarted or modified."
)


def _active_manager() -> Any:
    """The current ``WebUIProcessManager`` (the existing lifecycle authority), or ``None``."""

    from src.api.webui_process_manager import get_global_webui_process_manager

    return get_global_webui_process_manager()


def _normalized_endpoint(url: str) -> tuple[str, str, int | None]:
    from urllib.parse import urlparse

    parsed = urlparse(str(url or "").strip().rstrip("/"))
    host = (parsed.hostname or "").lower()
    return parsed.scheme.lower(), "127.0.0.1" if host == "localhost" else host, parsed.port


def resolve_owned_forge_data_dir(endpoint: str, *, manager: Any = None) -> Path:
    """The data directory of the Forge process StableNew itself launched and that serves ``endpoint``.

    Established only through the existing ``WebUIProcessManager`` authority: a current manager with identity
    ``forge_webui`` that currently owns its live launch-session process, whose endpoint is the client's endpoint,
    and whose *actual launch-session command* (not a configured profile, port or filename) names ``--data-dir``.
    Anything else fails closed. Endpoint health, PID existence, port occupancy or a Forge API identity are never
    taken as ownership.
    """

    manager = manager if manager is not None else _active_manager()
    if manager is None:
        raise KleinProfileError("No StableNew WebUI process manager is active. " + _MANAGED_ONLY)
    if getattr(manager, "runtime_identity", "") != "forge_webui":
        raise KleinProfileError(
            f"The active runtime manager is '{getattr(manager, 'runtime_identity', '')}', not forge_webui. " + _MANAGED_ONLY
        )
    if not getattr(manager, "owns_process", False):
        raise KleinProfileError("StableNew does not own the Forge process serving this endpoint. " + _MANAGED_ONLY)
    if not endpoint or _normalized_endpoint(manager.endpoint) != _normalized_endpoint(endpoint):
        raise KleinProfileError(
            f"The managed Forge serves '{getattr(manager, 'endpoint', '')}', not the client endpoint '{endpoint}'. " + _MANAGED_ONLY
        )
    command = manager.launch_session_command
    data_dir = data_dir_from_launch_command(list(command)) if command else None
    if data_dir is None:
        raise KleinProfileError(
            f"The owned Forge launch session declares no {_DATA_DIR_FLAG}, so its model files cannot be located. " + _MANAGED_ONLY
        )
    return data_dir


def _stat_key(path: Path, size: int, stat: os.stat_result) -> tuple[Any, ...]:
    return (str(path), size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino, stat.st_dev)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_one(data_dir: Path, asset: KleinAsset, *, served_path: Path | None = None) -> dict[str, Any]:
    path = served_path if served_path is not None else data_dir / "models" / asset.models_subdir / asset.filename
    if not path.is_file():
        raise KleinProfileError(
            f"The {asset.role} {asset.filename} is not installed in the managed Forge model tree "
            "(install it with scripts/install_forge_klein_assets.ps1)."
        )
    stat = path.stat()
    if stat.st_size != asset.size:
        raise KleinProfileError(f"The installed {asset.filename} has {stat.st_size} bytes, expected {asset.size}.")
    key = _stat_key(path, asset.size, stat)
    with _LOCK:
        cached = _VERIFIED.get(key)
    if cached == asset.sha256:
        return {"name": asset.filename, "size": asset.size, "sha256": cached, "verified": "sha256", "cache": "hit"}
    actual = _sha256(path)
    if actual != asset.sha256:
        raise KleinProfileError(
            f"The installed {asset.filename} has SHA-256 {actual}, expected {asset.sha256}; "
            "refusing to run Klein on files that are not the qualified assets."
        )
    if _stat_key(path, asset.size, path.stat()) != key:
        raise KleinProfileError(f"The served {asset.filename} changed while its bytes were verified")
    with _LOCK:
        _VERIFIED[key] = actual
    return {"name": asset.filename, "size": asset.size, "sha256": actual, "verified": "sha256", "cache": "miss"}


def verify_klein_assets(
    profile: KleinProfile, *, endpoint: str = "", data_dir: Path | None = None
) -> dict[str, Any]:
    """Exact size + SHA-256 of transformer, text encoder and VAE as installed in the OWNED serving Forge's data dir.

    ``endpoint`` is the endpoint the client dispatches to; ``data_dir`` is a test seam that bypasses the manager.
    """

    root = Path(data_dir) if data_dir is not None else resolve_owned_forge_data_dir(endpoint)
    return {asset.role: _verify_one(root, asset) for asset in profile.assets}


def _read_module_catalog(client: Any) -> Any:
    """Forge's module catalog: the tri-state ``get_module_catalog`` when the client has it, else ``get_vae_models``."""

    reader = getattr(client, "get_module_catalog", None)
    if not callable(reader):
        reader = getattr(client, "get_vae_models", None)
    return reader() if callable(reader) else None


def await_listed_catalogs(
    client: Any, pending: Callable[[Any, Any], str | None], *, label: str
) -> tuple[Any, Any]:
    """Read Forge's checkpoint and module catalogs, re-reading (bounded) while a required file is not listed yet.

    ``pending(models, modules)`` names what is still missing (an unreadable catalog, a pinned file with no entry) or
    returns ``None`` once every required file has at least one entry. Two or more entries are never waited for: the
    caller's strict binding refuses them at once. After ``CATALOG_SETTLE_TIMEOUT_S`` the last reads are returned and
    the caller refuses exactly as before. Read-only: no refresh, selection or other write is sent to Forge.
    """

    deadline = _monotonic() + max(float(CATALOG_SETTLE_TIMEOUT_S), 0.0)
    waited = False
    list_models = getattr(client, "get_models", None)
    while True:
        models = list_models() if callable(list_models) else None
        modules = _read_module_catalog(client)
        missing = pending(models, modules)
        if missing is None:
            if waited:
                logger.info("[forge/catalog] %s: Forge's catalogs now list the required files", label)
            return models, modules
        remaining = deadline - _monotonic()
        if remaining <= 0:
            if waited:
                logger.warning(
                    "[forge/catalog] %s: %s after waiting %.0fs for Forge's catalogs",
                    label, missing, CATALOG_SETTLE_TIMEOUT_S,
                )
            return models, modules
        if not waited:
            logger.info(
                "[forge/catalog] %s: %s; Forge may still be listing its models, re-reading for up to %.0fs",
                label, missing, remaining,
            )
            waited = True
        _sleep(min(float(CATALOG_POLL_INTERVAL_S), remaining))


def _matching_paths(entries: Any, name: str) -> set[str]:
    """Distinct served filenames of the catalog entries whose name, title or filename is ``name``."""

    from src.utils.checkpoint_identity import checkpoint_key

    if not isinstance(entries, list):
        return set()
    key = checkpoint_key(name)
    return {
        str(item.get("filename") or "") for item in entries if isinstance(item, dict)
        and key in {checkpoint_key(item.get(k)) for k in ("model_name", "title", "filename")}
    }


def _unlisted(models: Any, modules: Any, model_names: list[str], module_names: list[str]) -> str | None:
    if not isinstance(models, list) or not isinstance(modules, list):
        return "a catalog could not be read"
    missing = [name for name in model_names if not _matching_paths(models, name)]
    missing += [name for name in module_names if not _matching_paths(modules, name)]
    return f"Forge does not list {', '.join(missing)} yet" if missing else None


def verify_zimage_assets(profile: Any, *, client: Any) -> dict[str, Any]:
    """Use the existing owned-runtime, catalog and fingerprint hash authorities for Z-Image.

    Hash the exact paths the endpoint serves, including reference-home files, never a
    same-named installed copy that the runtime might not load. Catalog ambiguity refuses.
    """
    from src.utils.checkpoint_identity import checkpoint_key
    from src.utils.managed_forge_runtime import verify_pinned_launch

    manager = _active_manager()
    root = resolve_owned_forge_data_dir(str(client.base_url), manager=manager)
    pin = verify_pinned_launch(
        manager.launch_session_command, str(getattr(manager._config, "working_dir", "") or ""),
        profile.forge_revision,
    )
    model_names = [a.filename for a in profile.assets if a.role == "transformer"]
    module_names = [a.filename for a in profile.assets if a.role != "transformer"]
    models, modules = await_listed_catalogs(
        client, lambda m, n: _unlisted(m, n, model_names, module_names), label="Z-Image"
    )
    if not isinstance(models, list) or not isinstance(modules, list):
        raise KleinProfileError("Z-Image requires readable Forge checkpoint and module catalogs")
    result: dict[str, Any] = {"forge": pin}
    for asset in profile.assets:
        paths = _matching_paths(models if asset.role == "transformer" else modules, asset.filename)
        if len(paths) != 1 or not next(iter(paths), ""):
            raise KleinProfileError(f"Forge must list one unambiguous served file for {asset.filename}")
        path = Path(next(iter(paths)))
        if not path.is_absolute() or checkpoint_key(path.name) != checkpoint_key(asset.filename):
            raise KleinProfileError(f"Forge's served path does not bind {asset.filename}")
        result[asset.role] = _verify_one(root, asset, served_path=path)
    return result


def _served_path(entries: list[Any], name: str, label: str) -> Path:
    paths = _matching_paths(entries, name)
    if len(paths) != 1 or not next(iter(paths), ""):
        raise KleinProfileError(f"Forge must list one unambiguous served file for {label}")
    path = Path(next(iter(paths)))
    if not path.is_absolute() or not path.is_file():
        raise KleinProfileError(f"Forge's served path for {label} is not a readable local file")
    return path


def _sha256_cached(path: Path) -> str:
    stat = path.stat()
    key = _stat_key(path, stat.st_size, stat)
    with _LOCK:
        cached = _VERIFIED.get(key)
    if cached is not None:
        return cached
    actual = _sha256(path)
    if _stat_key(path, stat.st_size, path.stat()) != key:
        raise KleinProfileError(f"The served {path.name} changed while its bytes were read")
    with _LOCK:
        _VERIFIED[key] = actual
    return actual


def verify_flux1_assets(
    profile: Any,
    *,
    client: Any,
    model_name: str,
    inspect: Any = None,
    verify_launch: Any = None,
) -> dict[str, Any]:
    """FLUX.1 family identity (PR-IMG-FLUX-130): the served transformer by structure, the modules by bytes.

    Requires the StableNew-owned managed Forge at the profile's pinned revision (like Z-Image). The transformer Forge will
    load is located from its own catalog, classified from its bounded header (``inspect``: path -> ``ComponentEvidence``)
    and must match the profile's standalone FLUX.1 layout and precision; its SHA-256 is then recorded, never
    compared against a pin. Each module must be the one served file under its pinned name, with the pinned size and SHA-256.
    ``inspect`` and ``verify_launch`` are test seams.
    """
    from src.assets.component_evidence import inspect_component_file
    from src.assets.flux_variant import classify_flux_variant
    from src.utils.managed_forge_runtime import verify_pinned_launch

    manager = _active_manager()
    root = resolve_owned_forge_data_dir(str(client.base_url), manager=manager)
    pin = (verify_launch or verify_pinned_launch)(
        manager.launch_session_command, str(getattr(manager._config, "working_dir", "") or ""),
        profile.forge_revision,
    )
    module_names = [asset.filename for asset in profile.modules]
    models, modules = await_listed_catalogs(
        client, lambda m, n: _unlisted(m, n, [model_name], module_names), label=profile.display_name
    )
    if not isinstance(models, list) or not isinstance(modules, list):
        raise KleinProfileError(f"{profile.display_name} requires readable Forge checkpoint and module catalogs")
    transformer = _served_path(models, model_name, f"the checkpoint {model_name}")
    variant = classify_flux_variant((inspect or inspect_component_file)(transformer))
    if variant is None or variant.variant != profile.transformer_variant or variant.bundled:
        found = "not a FLUX transformer" if variant is None else variant.label
        raise KleinProfileError(
            f"{profile.display_name} requires its own transformer-only FLUX.1 layout; the served "
            f"{transformer.name} is {found}."
        )
    if variant.precision not in profile.transformer_precisions:
        raise KleinProfileError(
            f"{profile.display_name} admits the precisions {', '.join(profile.transformer_precisions)}; the served "
            f"{transformer.name} is {variant.precision}."
        )
    digest = _sha256_cached(transformer)
    recommended = profile.recommended_transformer
    result: dict[str, Any] = {
        "forge": pin,
        "transformer": {
            "name": transformer.name,
            "size": transformer.stat().st_size,
            "sha256": digest,
            "variant": variant.variant,
            "precision": variant.precision,
            "container": variant.container,
            "identity": "recommended_download" if digest == recommended.sha256 else "derivative_or_other_conversion",
            "verified": "structure",
        },
    }
    for asset in profile.modules:
        path = _served_path(modules, asset.filename, asset.filename)
        result[asset.role] = _verify_one(root, asset, served_path=path)
    return result


__all__ = [
    "await_listed_catalogs",
    "clear_verified_cache",
    "data_dir_from_launch_command",
    "resolve_owned_forge_data_dir",
    "verify_flux1_assets",
    "verify_klein_assets",
]
