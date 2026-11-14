"""The one activation authority (owner decision D20): point the installation at one imported runtime build and one model.

The admin tool's ``activate`` command and the in-app model selector both call :func:`activate`; ``record_active`` in
``manifests.py`` stays the single writer of ``active.json`` and only this function calls it for an operator action. Nothing
here runs a model or a binary, starts a process, hashes a model, or records an attestation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.ai_assist.manifests import (
    ModelEntry,
    ModelRegistry,
    RuntimeBuild,
    RuntimeManifest,
    Verification,
    hash_file,
    record_active,
    verify_installation,
)
from src.ai_assist.paths import model_dir, runtime_dir


class ActivationRefused(Exception):
    """Activation was refused and ``active.json`` was not touched. ``code`` is a stable string."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Activation:
    build: RuntimeBuild
    entry: ModelEntry
    #: The fast identity check made right after the pointer was written; ``ok`` unless the files changed meanwhile.
    verification: Verification


def is_compatible(entry: ModelEntry, build: RuntimeBuild) -> bool:
    """Whether the reviewed registry lists ``build`` for ``entry``. The list is explicit; an empty one allows nothing."""

    return build.build_id in entry.compatible_builds


def model_import_problem(root: Path, entry: ModelEntry) -> str:
    """Why the model file is not an imported, correctly sized copy of ``entry`` (``""`` when it is).

    A size check only: the bytes were hashed when they were imported and the directory is content-addressed. Re-hashing a
    multi-gigabyte model on every look would freeze the operator's window."""

    path = model_dir(root, entry.sha256) / entry.filename
    try:
        if not path.is_file():
            return "model_not_imported"
        return "" if path.stat().st_size == entry.bytes else "model_size_mismatch"
    except OSError:
        return "model_not_imported"


def runtime_import_problem(root: Path, build: RuntimeBuild, *, deep: bool = True) -> str:
    """Why the unpacked build is not exactly the pinned one (``""`` when it is).

    Every loadable file the manifest lists must exist; with ``deep`` each one is also re-hashed against its pin (a build
    is a few tens of megabytes, so this is cheap)."""

    base = runtime_dir(root, build.build_id)
    try:
        for rel, expected in sorted(build.files.items()):
            path = base / rel
            if not path.is_file():
                return "runtime_not_imported"
            if deep and hash_file(path)[0] != expected:
                return f"runtime_file_hash:{rel}"
    except OSError:
        return "runtime_not_imported"
    return ""


def activate(
    root: Path,
    runtime: RuntimeManifest,
    registry: ModelRegistry,
    *,
    build_id: str,
    model_id: str,
) -> Activation:
    """Activate ``model_id`` on ``build_id`` after proving both are pinned, compatible and imported.

    Raises :class:`ActivationRefused` before anything is written. Afterwards the returned ``verification`` is the usual
    fast identity check (candidates allowed: whether a candidate may then be used is the Preview record's question)."""

    build = runtime.find(build_id)
    entry = next((e for e in registry.entries if e.model_id == model_id), None)
    if build is None or entry is None:
        raise ActivationRefused("unknown_build_or_model")
    if not is_compatible(entry, build):
        raise ActivationRefused("build_incompatible")
    problem = model_import_problem(root, entry) or runtime_import_problem(root, build)
    if problem:
        raise ActivationRefused(problem)
    record_active(root, build, entry)
    verification = verify_installation(root, runtime, registry, allow_candidate=True)
    return Activation(build, entry, verification)


__all__ = [
    "Activation",
    "ActivationRefused",
    "activate",
    "is_compatible",
    "model_import_problem",
    "runtime_import_problem",
]
