"""Contained child that runs one Ideogram 4 NF4 job through Diffusers (PR-IMG-120).

Started only by ``DiffusersImageBackend`` through the repository's bounded-process helper:
``python -I diffusers_ideogram4_worker.py <job dir>``. The job directory holds ``request.json`` and receives
``progress.json`` (replaced atomically at each step), one PNG per seed and ``result.json``. The parent forces offline
Hugging Face settings, so the child loads only the pinned local snapshot and never reaches the network. It owns no
queue, NJR, history or GUI state, caches nothing between jobs and exits when its single job is done; its exit releases
every byte of GPU memory it held. Cancellation and timeouts are a kill of the whole contained tree by the parent.

Importing this module imports nothing heavy: torch, Diffusers and Transformers load inside ``run_job``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

if (
    __name__ == "__main__"
):  # isolated mode (-I) puts neither the script directory nor the repository on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.image_backends.diffusers_ideogram4_profile import IDEOGRAM4_PROFILE_V1  # noqa: E402
from src.image_backends.diffusers_residency import (  # noqa: E402
    CODE_CAPTION_INVALID,
    CODE_FAILED,
    CODE_OUT_OF_MEMORY,
    CODE_REQUEST_INVALID,
    CODE_RUNTIME_MISSING,
    GenerationSettings,
    LoaderClasses,
    ResidencyRefusal,
    StagedSwapResidency,
    guidance_matches_steps,
    is_out_of_memory,
)
from src.image_backends.ideogram4_caption import verify_caption_text  # noqa: E402
from src.utils.atomic_io import atomic_write_json  # noqa: E402

REQUEST_FILE = "request.json"
RESULT_FILE = "result.json"
PROGRESS_FILE = "progress.json"
REQUEST_SCHEMA = "stablenew.ideogram4_job.v1"
EXIT_OK, EXIT_REFUSED, EXIT_FAILED = 0, 2, 3

LoaderFactory = Callable[[], tuple[Any, LoaderClasses]]


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    atomic_write_json(path, dict(document), ensure_ascii=False)


def _missing_runtime() -> list[str]:
    return [
        name
        for name in IDEOGRAM4_PROFILE_V1.runtime_packages
        if importlib.util.find_spec(name) is None
    ]


def default_loader() -> tuple[Any, LoaderClasses]:
    import torch
    from diffusers import Ideogram4Pipeline, Ideogram4Transformer2DModel
    from transformers import Qwen3VLModel

    return torch, LoaderClasses(Ideogram4Pipeline, Ideogram4Transformer2DModel, Qwen3VLModel)


def _settings(request: Mapping[str, Any]) -> GenerationSettings:
    if request.get("schema") != REQUEST_SCHEMA:
        raise ResidencyRefusal(CODE_REQUEST_INVALID, "Unknown job request schema")
    if (
        request.get("repo_id") != IDEOGRAM4_PROFILE_V1.repo_id
        or request.get("revision") != IDEOGRAM4_PROFILE_V1.revision
    ):
        raise ResidencyRefusal(
            CODE_REQUEST_INVALID, "The job names a model other than the pinned Ideogram 4 snapshot"
        )
    caption = str(request.get("caption_json") or "")
    findings = verify_caption_text(caption)
    if findings:
        raise ResidencyRefusal(
            CODE_CAPTION_INVALID, "The caption failed verification: " + "; ".join(findings[:8])
        )
    if hashlib.sha256(caption.encode("utf-8")).hexdigest() != request.get("caption_sha256"):
        raise ResidencyRefusal(
            CODE_REQUEST_INVALID, "The caption does not match its recorded SHA-256"
        )
    width, height, steps = request.get("width"), request.get("height"), request.get("steps")
    if type(width) is not int or type(height) is not int or type(steps) is not int:
        raise ResidencyRefusal(CODE_REQUEST_INVALID, "width, height and steps must be integers")
    if (width, height) not in IDEOGRAM4_PROFILE_V1.geometries:
        raise ResidencyRefusal(
            CODE_REQUEST_INVALID, f"Size {width}x{height} is outside the tested sizes"
        )
    preset = IDEOGRAM4_PROFILE_V1.preset_for_steps(steps)
    schedule = tuple(float(value) for value in request.get("guidance_schedule") or ())
    if not guidance_matches_steps(schedule, int(steps)) or schedule != preset.diffusers_guidance():
        raise ResidencyRefusal(
            CODE_REQUEST_INVALID, "The guidance schedule does not match the official preset"
        )
    if (request.get("mu"), request.get("std")) != (preset.mu, preset.std):
        raise ResidencyRefusal(CODE_REQUEST_INVALID, "mu/std do not match the official preset")
    seeds = tuple(int(seed) for seed in request.get("seeds") or ())
    if not 1 <= len(seeds) <= IDEOGRAM4_PROFILE_V1.max_images or not all(
        0 <= s < 2**32 for s in seeds
    ):
        raise ResidencyRefusal(CODE_REQUEST_INVALID, "Invalid seed list")
    return GenerationSettings(
        caption, int(width), int(height), int(steps), schedule, preset.mu, preset.std, seeds
    )


def run_job(
    job_dir: Path,
    loader: LoaderFactory = default_loader,
    missing_runtime: Callable[[], list[str]] = _missing_runtime,
) -> int:
    """Execute the single job in ``job_dir``; returns the process exit code (a result is always written)."""

    try:
        request = json.loads((job_dir / REQUEST_FILE).read_text(encoding="utf-8"))
        settings = _settings(request)
    except ResidencyRefusal as exc:
        _write_json(job_dir / RESULT_FILE, {"ok": False, "code": exc.code, "message": str(exc)})
        return EXIT_REFUSED
    except (OSError, ValueError, TypeError) as exc:
        _write_json(
            job_dir / RESULT_FILE,
            {"ok": False, "code": CODE_REQUEST_INVALID, "message": str(exc)[:500]},
        )
        return EXIT_REFUSED
    missing = missing_runtime()
    if missing:
        _write_json(
            job_dir / RESULT_FILE,
            {
                "ok": False,
                "code": CODE_RUNTIME_MISSING,
                "message": "Missing Python packages: " + ", ".join(missing),
            },
        )
        return EXIT_REFUSED

    def progress(event: dict[str, Any]) -> None:
        try:
            _write_json(job_dir / PROGRESS_FILE, event)
        except OSError:
            pass  # progress is observational; generation continues

    torch: Any = None
    residency: StagedSwapResidency | None = None
    try:
        torch, classes = loader()
        residency = StagedSwapResidency(
            torch=torch,
            classes=classes,
            repo_id=IDEOGRAM4_PROFILE_V1.repo_id,
            revision=IDEOGRAM4_PROFILE_V1.revision,
            policy=IDEOGRAM4_PROFILE_V1.residency,
            progress=progress,
        )
        torch.cuda.reset_peak_memory_stats()
        images = residency.run(settings)
        outputs = []
        for index, (seed, image) in enumerate(zip(settings.seeds, images, strict=True)):
            name = f"image_{index:02d}.png"
            image.save(job_dir / name)
            digest = hashlib.sha256((job_dir / name).read_bytes()).hexdigest()
            outputs.append(
                {
                    "file": name,
                    "seed": seed,
                    "sha256": digest,
                    "width": settings.width,
                    "height": settings.height,
                }
            )
        _write_json(
            job_dir / RESULT_FILE,
            {
                "ok": True,
                "code": "ok",
                "images": outputs,
                "token_count": residency.token_count,
                "allocator_cap": residency.cap.to_dict() if residency.cap else None,
                "timings": dict(residency.log.timings),
                "swaps": residency.log.swaps,
                "swap_seconds": residency.log.swap_seconds,
                "max_resident_transformers": max(residency.log.resident_at_forward, default=0),
                "memory": residency.peak_memory(),
                "runtime": _runtime_versions(),
            },
        )
        return EXIT_OK
    except ResidencyRefusal as exc:
        _write_json(job_dir / RESULT_FILE, {"ok": False, "code": exc.code, "message": str(exc)})
        return EXIT_REFUSED
    except Exception as exc:  # noqa: BLE001 - the parent needs a typed result for any failure
        code = (
            CODE_OUT_OF_MEMORY
            if torch is not None and is_out_of_memory(torch, exc)
            else CODE_FAILED
        )
        memory = residency.peak_memory() if residency is not None else {}
        _write_json(
            job_dir / RESULT_FILE,
            {
                "ok": False,
                "code": code,
                "message": f"{type(exc).__name__}: {exc}"[:2000],
                "memory": memory,
            },
        )
        return EXIT_FAILED


def _runtime_versions() -> dict[str, str]:
    from importlib import metadata

    versions: dict[str, str] = {"python": sys.version.split()[0]}
    for name in IDEOGRAM4_PROFILE_V1.runtime_packages:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "missing"
    return versions


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: diffusers_ideogram4_worker.py <job dir>", file=sys.stderr)
        return EXIT_REFUSED
    return run_job(Path(argv[1]))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
