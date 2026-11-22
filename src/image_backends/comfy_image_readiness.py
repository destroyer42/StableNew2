"""PR-IMG-COMFY-100: readiness of the Comfy still-image profiles (read-only; never downloads, moves or loads weights).

Three layers, from cheapest to live:

* ``check_installation``: every pinned file is in a configured Comfy model folder at its exact size; with
  ``verify_sha256`` also its exact SHA-256, hashed once per (path, size, mtime) per process. Used for the GUI offer
  (size only) and before dispatch (with the hash).
* ``probe_object_info``: the running StableNew-owned Comfy offers every node class of the frozen graph, the three file
  names in its loader options and the ``qwen_image`` encoder type.
* ``evaluate_floors``: the free VRAM and free host RAM Comfy itself reports meet the profile's floors.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from src.assets.component_evidence import (
    ARCH_QWEN_IMAGE_VAE,
    inspect_component_file,
    is_qwen_image_20b_fp8,
)
from src.image_backends.comfy_image_graphs import ComfyImageGraph
from src.image_backends.comfy_qwen_image_profile import (
    ComfyModelAsset,
    QwenImageProfile,
    qwen_transformer_loader_name,
)

ModelFolders = Mapping[str, Sequence[Path]]

_HASH_CACHE: dict[tuple[str, int, int], str] = {}
_HASH_LOCK = threading.Lock()
_HASH_CHUNK = 8 * 1024 * 1024


class ComfyImageResourceError(RuntimeError):
    """A fail-closed resource floor is not met (free VRAM or host RAM); nothing was queued."""


@dataclass(frozen=True, slots=True)
class ComfyInstallationStatus:
    ready: bool
    problems: tuple[str, ...] = ()
    #: Pinned filename -> the local file that satisfied it.
    paths: Mapping[str, str] = field(default_factory=dict)
    sha256_verified: bool = False
    loader_names: Mapping[str, str] = field(default_factory=dict)
    sha256: Mapping[str, str] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        return "installed" if self.ready else "; ".join(self.problems)


def comfy_model_folders(
    extra_kinds: Sequence[str] = (), *, use_registered_launcher: bool = True
) -> dict[str, list[Path]]:
    """The model folders of StableNew's managed Comfy launch configuration (reads settings, never runs Comfy).

    ``extra_kinds`` (``checkpoints``, ``loras``) adds the SDXL leg's folders; the default is the Qwen-Image set."""

    from src.video.comfy_process_manager import (
        build_default_comfy_process_config,
        get_global_comfy_process_manager,
    )
    from src.video.workflow_asset_integrity import model_folders

    manager = get_global_comfy_process_manager() if use_registered_launcher else None
    config = getattr(manager, "config", None) if manager is not None else None
    config = config or build_default_comfy_process_config()
    if config is None:
        raise ValueError("no StableNew-managed ComfyUI launch configuration is set")
    command, working_dir = (
        tuple(getattr(config, "command", ()) or ()),
        getattr(config, "working_dir", None),
    )
    if extra_kinds:
        return model_folders(command, working_dir, extra_kinds=tuple(extra_kinds))
    return model_folders(command, working_dir)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def cached_sha256(path: Path, *, hasher: Callable[[Path], str] = _sha256) -> str:
    """SHA-256 of ``path``, hashed again only when its size or modification time changes."""

    stat = path.stat()
    key = (str(path.resolve()), int(stat.st_size), int(stat.st_mtime_ns))
    with _HASH_LOCK:
        cached = _HASH_CACHE.get(key)
    if cached is not None:
        return cached
    value = hasher(path)
    with _HASH_LOCK:
        _HASH_CACHE[key] = value
    return value


def clear_hash_cache() -> None:
    with _HASH_LOCK:
        _HASH_CACHE.clear()


def _check_asset(
    asset: ComfyModelAsset,
    folders: ModelFolders,
    verify_sha256: bool,
    hasher: Callable[[Path], str],
) -> tuple[str | None, list[str]]:
    candidates = [Path(root) / asset.filename for root in folders.get(asset.folder, ())]
    found = list(dict.fromkeys(path for path in candidates if path.is_file()))
    if not found:
        return None, [
            f"Model missing: {asset.filename} (Comfy models/{asset.folder}; StableNew never downloads it)"
        ]
    problems: list[str] = []
    for path in found:
        try:
            if path.stat().st_size != asset.size:
                problems.append(f"Model size mismatch (truncated or different file): {path}")
            elif verify_sha256 and cached_sha256(path, hasher=hasher) != asset.sha256:
                problems.append(f"Model SHA-256 mismatch: {path}")
        except OSError as exc:
            problems.append(f"Model could not be verified: {path}: {exc}")
    return str(found[0]), problems


def _diffusion_files(model_name: str, folders: ModelFolders) -> tuple[tuple[str, Path], ...]:
    loader_name = qwen_transformer_loader_name(model_name)
    if not loader_name:
        return ()
    relative = Path(loader_name)
    return tuple(
        dict.fromkeys(
            (str(relative), path.resolve())
            for root in folders.get("diffusion_models", ())
            if (path := root / relative).is_file()
        )
    )


def has_structural_qwen_checkpoint(model_name: str) -> bool:
    """Inspect just the selected checkpoint in the configured Comfy diffusion folders."""

    try:
        candidates = _diffusion_files(
            model_name, comfy_model_folders(use_registered_launcher=False)
        )
        return len(candidates) == 1 and is_qwen_image_20b_fp8(
            inspect_component_file(candidates[0][1])
        )
    except (OSError, ValueError):
        return False


def _check_structural_install(
    profile: QwenImageProfile,
    model_name: str,
    folders: ModelFolders,
    verify: bool,
    hasher: Callable[[Path], str],
) -> ComfyInstallationStatus:
    encoder = profile.text_encoder
    encoder_path, problems = _check_asset(encoder, folders, verify, hasher)
    if encoder_path is None:
        problems = [
            "Qwen-Image needs the Qwen2.5-VL-7B text encoder "
            f"({encoder.filename}, 9.38 GB) in models/text_encoders."
        ]

    paths: dict[str, str] = {}
    names: dict[str, str] = {}
    digests: dict[str, str] = {}
    if encoder_path is not None:
        paths[encoder.filename] = encoder_path

    diffusion = _diffusion_files(model_name, folders)
    if len(diffusion) != 1:
        problems.append(
            f"ComfyUI needs one unambiguous {model_name!r} in models/diffusion_models. "
            "Add its existing checkpoint folder to diffusion_models in the managed Comfy extra_model_paths.yaml."
        )
    else:
        loader_name, path = diffusion[0]
        if not is_qwen_image_20b_fp8(inspect_component_file(path)):
            problems.append(
                f"{loader_name} does not match the standalone Qwen-Image 20B E4M3 FP8 layout."
            )
        else:
            names["diffusion_model"] = loader_name
            paths[loader_name] = str(path)

    vae = profile.vae
    vae_path, vae_problems = _check_asset(vae, folders, verify, hasher)
    if vae_path is None:
        aliases = {
            candidate.resolve(): candidate.name
            for root in folders.get("vae", ())
            if root.is_dir()
            for candidate in root.glob("*.safetensors")
            if candidate.is_file()
            and candidate.stat().st_size == vae.size
            and inspect_component_file(candidate).architecture == ARCH_QWEN_IMAGE_VAE
        }
        if len(aliases) == 1:
            loader_name = next(iter(aliases.values()))
            vae_path, vae_problems = _check_asset(
                replace(vae, filename=loader_name), folders, verify, hasher
            )
            names["vae"] = loader_name
    problems.extend(vae_problems)
    if vae_path is not None:
        paths[names.setdefault("vae", vae.filename)] = vae_path

    if verify and not problems:
        digests = {name: cached_sha256(Path(path), hasher=hasher) for name, path in paths.items()}
    return ComfyInstallationStatus(
        not problems, tuple(problems), paths, verify and not problems, names, digests
    )


def check_installation(
    profile: QwenImageProfile,
    *,
    folders: ModelFolders | None = None,
    model_name: str | None = None,
    verify_sha256: bool = False,
    hasher: Callable[[Path], str] = _sha256,
) -> ComfyInstallationStatus:
    """Check pinned assets and any structural selection without loading weights. Never raises."""

    try:
        resolved = comfy_model_folders() if folders is None else folders
        if profile.structural_transformer:
            return _check_structural_install(
                profile, model_name or profile.model_name, resolved, verify_sha256, hasher
            )
    except (OSError, ValueError) as exc:
        return ComfyInstallationStatus(False, (f"Local model identity cannot be verified: {exc}",))
    problems: list[str] = []
    paths: dict[str, str] = {}
    for asset in profile.assets:
        path, asset_problems = _check_asset(asset, resolved, verify_sha256, hasher)
        problems.extend(asset_problems)
        if path is not None:
            paths[asset.filename] = path
    ready = not problems
    return ComfyInstallationStatus(
        ready, tuple(problems), paths, sha256_verified=ready and verify_sha256
    )


def _input_options(object_info: Mapping[str, Any], node_class: str, input_name: str) -> list[str]:
    """The combo options Comfy's ``/object_info`` lists for one input (legacy and ``COMBO`` shapes)."""

    node = object_info.get(node_class)
    inputs = node.get("input") if isinstance(node, Mapping) else None
    if not isinstance(inputs, Mapping):
        return []
    for group in ("required", "optional"):
        spec = inputs.get(group)
        value = spec.get(input_name) if isinstance(spec, Mapping) else None
        if not isinstance(value, (list, tuple)) or not value:
            continue
        head = value[0]
        if isinstance(head, (list, tuple)):
            return [str(item) for item in head]
        if head == "COMBO" and len(value) > 1 and isinstance(value[1], Mapping):
            return [str(item) for item in value[1].get("options") or ()]
    return []


def probe_object_info(
    graph: ComfyImageGraph, object_info: Any, *, loader_names: Mapping[str, str] | None = None
) -> tuple[str, ...]:
    """Problems that stop the frozen graph from running on this Comfy; empty when it can be queued."""

    if not isinstance(object_info, Mapping) or not object_info:
        return ("ComfyUI returned no node information",)
    profile = graph.profile
    names = loader_names or {}
    problems = [
        f"ComfyUI has no '{node_class}' node (the pinned v0.38.0 runtime provides it)"
        for node_class in graph.required_node_classes
        if node_class not in object_info
    ]
    checks: tuple[tuple[str, str, str], ...] = (
        ("UNETLoader", "unet_name", names.get("diffusion_model", profile.model_name)),
        ("CLIPLoader", "clip_name", profile.text_encoder.filename),
        ("VAELoader", "vae_name", names.get("vae", profile.vae.filename)),
        ("CLIPLoader", "type", graph.clip_type),
    )
    if profile.structural_transformer:
        checks += (("UNETLoader", "weight_dtype", "fp8_e4m3fn"),)
    for node_class, input_name, expected in checks:
        if node_class in object_info and expected not in _input_options(
            object_info, node_class, input_name
        ):
            problems.append(f"ComfyUI does not list '{expected}' for {node_class}.{input_name}")
    return tuple(problems)


def listed_option(
    object_info: Mapping[str, Any], node_class: str, input_name: str, value: str
) -> str | None:
    """The spelling ``/object_info`` lists for ``value`` (path separators compared as ``/``), or ``None`` if unlisted."""

    wanted = str(value).replace("\\", "/")
    for item in _input_options(object_info, node_class, input_name):
        if str(item).replace("\\", "/") == wanted:
            return str(item)
    return None


def _combo_has(
    object_info: Mapping[str, Any], node_class: str, input_name: str, value: str
) -> bool:
    return listed_option(object_info, node_class, input_name, value) is not None


def probe_sdxl_graph(
    prompt_graph: Mapping[str, Any], required_classes: Sequence[str], object_info: Any
) -> tuple[str, ...]:
    """Problems that stop the built SDXL graph from running on this Comfy; empty when it can be queued.

    Checks every node class the frozen graph can contain, then that each loader file and the sampler and scheduler names
    of THIS job are values the running ComfyUI lists (``/object_info``). Nothing is repaired or substituted.
    """

    if not isinstance(object_info, Mapping) or not object_info:
        return ("ComfyUI returned no node information",)
    problems = [
        f"ComfyUI has no '{node_class}' node (the pinned v0.38.0 runtime provides it)"
        for node_class in required_classes
        if node_class not in object_info
    ]
    checks = {
        "CheckpointLoaderSimple": ("ckpt_name",),
        "LoraLoader": ("lora_name",),
        "VAELoader": ("vae_name",),
        "KSampler": ("sampler_name", "scheduler"),
    }
    for node in prompt_graph.values():
        node_class = str(node.get("class_type"))
        for input_name in checks.get(node_class, ()):
            value = node.get("inputs", {}).get(input_name)
            if node_class in object_info and not _combo_has(
                object_info, node_class, input_name, str(value)
            ):
                problems.append(f"ComfyUI does not list '{value}' for {node_class}.{input_name}")
    return tuple(dict.fromkeys(problems))


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def evaluate_floors(profile: Any, system_stats: Any) -> dict[str, Any]:
    """Check Comfy's own free VRAM and host RAM against the profile floors; returns the readings or raises."""

    stats = system_stats if isinstance(system_stats, Mapping) else {}
    raw_system = stats.get("system")
    system: Mapping[str, Any] = raw_system if isinstance(raw_system, Mapping) else {}
    raw_devices = stats.get("devices")
    devices: list[Any] = raw_devices if isinstance(raw_devices, list) else []
    device = devices[0] if devices and isinstance(devices[0], Mapping) else {}
    vram_free, vram_total = _int(device.get("vram_free")), _int(device.get("vram_total"))
    ram_free, ram_total = _int(system.get("ram_free")), _int(system.get("ram_total"))
    if vram_free is None or ram_free is None:
        raise ComfyImageResourceError(
            f"ComfyUI did not report free GPU memory and host RAM, so {profile.display_name} cannot be admitted; "
            "nothing was queued"
        )
    floors = profile.resources
    gib = 1024**3
    if vram_free < floors.min_free_vram_bytes:
        raise ComfyImageResourceError(
            f"{profile.display_name} needs {floors.min_free_vram_bytes / gib:.0f} GiB of free GPU memory, but ComfyUI "
            f"reports {vram_free / gib:.1f} GiB free. StableNew released its own runtimes; another program is using "
            "the GPU. Nothing was queued."
        )
    if ram_free < floors.min_free_ram_bytes:
        raise ComfyImageResourceError(
            f"{profile.display_name} needs {floors.min_free_ram_bytes / gib:.0f} GiB of free host RAM, but ComfyUI "
            f"reports {ram_free / gib:.1f} GiB free. Close other programs and try again. Nothing was queued."
        )
    return {
        "vram_free_bytes": vram_free,
        "vram_total_bytes": vram_total,
        "ram_free_bytes": ram_free,
        "ram_total_bytes": ram_total,
        "device_name": str(device.get("name") or ""),
    }


__all__ = [
    "ComfyImageResourceError",
    "ComfyInstallationStatus",
    "cached_sha256",
    "check_installation",
    "clear_hash_cache",
    "comfy_model_folders",
    "evaluate_floors",
    "listed_option",
    "probe_object_info",
    "probe_sdxl_graph",
]
