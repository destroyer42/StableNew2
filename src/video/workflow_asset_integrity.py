"""Read-only verification of catalog-pinned assets in the configured Comfy model folders.

No install, download, subprocess or Comfy import. Ambiguous search paths are accepted only
when every matching file has the same pinned bytes. Existing workflows opt in explicitly.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.video.motion_source_preparation import sha256_file


def model_folders(command: Sequence[str], working_dir: str | None) -> dict[str, list[Path]]:
    """Read Comfy's standard local roots and explicit extra-model-path files, without executing them."""
    if not working_dir:
        raise ValueError(
            "Managed Comfy source directory is unknown; local model identity cannot be verified."
        )
    import yaml

    source = Path(working_dir).expanduser().resolve()
    model_base = source
    if "--base-directory" in command:
        index = command.index("--base-directory")
        if index + 1 == len(command):
            raise ValueError("Comfy --base-directory is incomplete")
        model_base = Path(command[index + 1]).expanduser()
        if not model_base.is_absolute():
            model_base = source / model_base
    if any(
        part.startswith(("--base-directory=", "--extra-model-paths-config=")) for part in command
    ):
        raise ValueError(
            "Use separate arguments for Comfy model-path flags so model identity can be verified."
        )
    roots = {
        key: [model_base / "models" / key] for key in ("diffusion_models", "text_encoders", "vae")
    }
    roots["diffusion_models"].append(model_base / "models" / "unet")
    roots["text_encoders"].append(model_base / "models" / "clip")
    configs = [source / "extra_model_paths.yaml"]
    for index, part in enumerate(command):
        if part == "--extra-model-paths-config":
            for value in command[index + 1 :]:
                if value.startswith("--"):
                    break
                candidate = Path(value).expanduser()
                configs.append(candidate if candidate.is_absolute() else source / candidate)
    for config in dict.fromkeys(configs):
        if not config.is_file():
            continue
        if config.stat().st_size > 1024 * 1024:
            raise ValueError(f"Comfy model-path configuration is too large: {config}")
        try:
            data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Comfy model-path configuration is invalid: {config}") from exc
        if not isinstance(data, Mapping):
            raise ValueError(f"Comfy model-path configuration is invalid: {config}")
        for entry in data.values():
            if not isinstance(entry, Mapping):
                continue
            base = Path(str(entry.get("base_path") or config.parent)).expanduser()
            if not base.is_absolute():
                base = config.parent / base
            for key, values in roots.items():
                aliases = {"text_encoders": (key, "clip"), "diffusion_models": (key, "unet")}.get(
                    key, (key,)
                )
                for alias in aliases:
                    for raw in str(entry.get(alias) or "").splitlines():
                        if raw.strip():
                            path = Path(raw.strip()).expanduser()
                            values.append(path if path.is_absolute() else base / path)
    return roots


def verify_assets(spec: Any, folders: Mapping[str, Sequence[Path]]) -> tuple[str, ...]:
    """Return precise missing/size/digest/identity failures; stream hashes, never load weights."""
    policy = spec.backend_defaults.get("asset_integrity")
    if not policy:
        return ()
    # Catalog versions own immutable provenance; no 'main'/unknown revision or ad hoc replacement.
    provenance = spec.backend_defaults.get("provenance") or {}
    revision = str(policy.get("revision") or "")
    if (
        len(revision) != 40
        or any(c not in "0123456789abcdef" for c in revision)
        or revision != provenance.get("upstream_revision")
        or policy.get("repository") != provenance.get("upstream_repo")
    ):
        return ("Model asset upstream revision is unknown or differs from the pinned workflow.",)
    issues: list[str] = []
    for filename, asset in policy["files"].items():
        if Path(filename).name != filename or asset["sha256"] != provenance.get("files", {}).get(
            filename
        ):
            issues.append(f"Model manifest identity mismatch: {filename}")
            continue
        candidates = [root / filename for root in folders.get(asset["folder"], ())]
        found = list(dict.fromkeys(path for path in candidates if path.is_file()))
        if not found:
            issues.append(
                f"Model missing: {filename} (Comfy models/{asset['folder']}; no automatic download)"
            )
        for path in found:
            try:
                if path.stat().st_size != asset["size"]:
                    issues.append(f"Model size mismatch (truncated or different file): {path}")
                elif sha256_file(path) != asset["sha256"]:
                    issues.append(f"Model SHA-256 mismatch: {path}")
            except OSError as exc:
                issues.append(f"Model could not be verified: {path}: {exc}")
    return tuple(issues)


def configured_asset_issues(spec: Any, config: Any) -> tuple[str, ...]:
    if not spec.backend_defaults.get("asset_integrity"):
        return ()
    try:
        folders = model_folders(
            tuple(getattr(config, "command", ()) or ()), getattr(config, "working_dir", None)
        )
        return verify_assets(spec, folders)
    except (OSError, ValueError) as exc:
        return (f"Local model identity cannot be verified: {exc}",)
