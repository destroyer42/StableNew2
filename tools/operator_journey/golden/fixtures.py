"""Backend + workspace fixtures for simulated golden-path runs (loopback fakes at the HTTP boundary only)."""

from __future__ import annotations

from tools.operator_journey.fake_a1111 import FakeA1111
from tools.operator_journey.fixtures import seed_sdxl_checkpoint_evidence
from tools.operator_journey.journeys.learning_lora_strength import model_base


def make_fake_a1111(**kwargs) -> FakeA1111:
    return FakeA1111(**kwargs)


def seed_declared_sdxl(workspace, fake_a, _fake_c) -> None:
    """Declare the fake's checkpoint SDXL in the isolated AssetRegistry cache (a fixture, never a real model)."""

    if fake_a is not None:
        seed_sdxl_checkpoint_evidence(workspace, model_base(fake_a.title(fake_a.model)))


def seed_declared_checkpoints(
    workspace, architectures: dict[str, str], *, verified: tuple[str, ...] = ()
) -> None:
    """Declare several fixture checkpoints (``{name: modelspec.architecture}``) in the isolated AssetRegistry cache.

    Evidence is synthetic fixture metadata, never a hash of a real model; names supply no family evidence.  A model the
    mapping omits is simply unclassified (the product labels it ``unverified``).  A name listed in ``verified`` also
    gets a tiny placeholder file whose real SHA-256 and size/mtime fingerprint the cache records, which is exactly
    what the registry requires before it treats a checkpoint's identity as verified (it never hashes on its own).
    """

    import hashlib
    import json
    import os
    from pathlib import Path

    from src.state.workspace_paths import workspace_paths

    cache = workspace_paths.asset_registry_cache()
    if cache.parent != workspace.state_dir.resolve():
        raise RuntimeError("Fixture evidence requires the activated isolated workspace")
    os.environ["STABLENEW_WEBUI_ROOT"] = str(workspace.root / "fixture-webui")
    entries = {}
    for name, architecture in architectures.items():
        filename = Path(name).name if Path(name).suffix else f"{Path(name).name}.safetensors"
        path = workspace.root / "fixture-models" / filename
        entry = {
            "sha256": hashlib.sha256(f"operator-journey-fixture|{path.name}".encode()).hexdigest(),
            "kind": "checkpoint",
            "path": str(path),
            "root": str(path.parent),
            "name": path.name,
            "size": 0,
            "metadata": {"modelspec.architecture": architecture},
            "provenance": "operator-journey-declared-fixture",
        }
        if Path(filename).stem in verified or name in verified:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"operator-journey placeholder checkpoint {path.name}".encode())
            stat = path.stat()
            entry.update(
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                path=str(path.resolve()),
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                provenance="operator-journey-verified-fixture",
            )
            entries[str(path.resolve())] = entry
        else:
            entries[str(path)] = entry
    cache.write_text(json.dumps({"version": 2, "entries": entries}), encoding="utf-8")
