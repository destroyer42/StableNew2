"""The Diffusers image backend (PR-IMG-120): Ideogram 4 NF4 txt2img in a contained child per job.

One backend behind the existing ``ImageBackendRegistry`` (PR-IMG-100 COA B); the runner, queue, NJR, history and
cancellation authorities are the existing ones. ``execute`` runs a fixed, fail-closed sequence:

1. **validate** the frozen intent again (profile, envelope, caption) - pure, no side effect;
2. **lease** the GPU: ``RuntimeTransitionCoordinator.prepare_for("diffusers")`` releases StableNew's own WebUI-family
   runtime, managed Comfy and the SVD cache through their owners; an external occupant refuses the job;
3. **floors**: installation (packages + pinned snapshot), driver-visible free VRAM and available host RAM;
4. **launch** ``diffusers_ideogram4_worker`` with ``run_bounded``: job-object containment with a verified commit limit,
   a wall-clock timeout, cancellation that kills the whole tree, and recorded ownership evidence;
5. **teardown proof**: the child has exited and the container proves no process of its tree remains, so the driver has
   reclaimed its GPU memory; a post-exit VRAM reading is recorded as an observation;
6. **artifacts**: PNGs with StableNew's embedded metadata and per-image manifests, in the executor's result shape.

The application process never imports torch, Diffusers or Transformers for this backend. Nothing is retried or replayed
and nothing falls back to another backend.
"""

from __future__ import annotations

import json
import logging
import random
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.image_backends.diffusers_ideogram4_profile import (
    IDEOGRAM4_PROFILE_V1,
    Ideogram4Plan,
    Ideogram4Profile,
    Ideogram4ProfileError,
    is_ideogram4_model_name,
    resolve_plan,
    validate_ideogram4_config,
    validate_ideogram4_njr,
)
from src.image_backends.diffusers_readiness import (
    GpuMemory,
    InstallationStatus,
    available_host_ram_bytes,
    check_installation,
    query_gpu_memory,
)
from src.image_backends.ideogram4_caption import CaptionError, CaptionResolution, resolve_caption
from src.image_backends.image_backend_types import (
    DIFFUSERS_IMAGE_BACKEND_ID,
    RUNTIME_FAMILY_DIFFUSERS,
    ImageBackendCapabilities,
    ImageExecutionRequest,
    ImageExecutionResult,
)
from src.services.runtime_transition_service import (
    RUNTIME_DIFFUSERS,
    RuntimeTransitionCoordinator,
    RuntimeTransitionError,
)
from src.utils.managed_process import ProcessOutcome, run_bounded

logger = logging.getLogger(__name__)

WORKER_PATH = Path(__file__).with_name("diffusers_ideogram4_worker.py")
WORKER_STDOUT_CAP = 256 * 1024
MAX_RESULT_BYTES = 4 * 1024 * 1024
PROGRESS_POLL_SECONDS = 1.0
_ENV_ALLOWLIST = (
    "SYSTEMROOT", "SYSTEMDRIVE", "PATH", "PATHEXT", "TEMP", "TMP", "TMPDIR", "USERPROFILE", "LOCALAPPDATA",
    "APPDATA", "HOME", "LANG", "LC_ALL", "VIRTUAL_ENV", "HF_HOME", "HF_HUB_CACHE", "XDG_CACHE_HOME",
    "CUDA_PATH", "CUDA_VISIBLE_DEVICES", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
)  # fmt: skip
_ENV_FORCED = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DIFFUSERS_DISABLE_TELEMETRY": "1",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONDONTWRITEBYTECODE": "1",
}
_FAILURE_MESSAGES = {
    "vram_insufficient": "not enough free GPU memory inside the model process",
    "out_of_memory": "the GPU ran out of memory under the residency cap",
    "caption_too_long": "the caption is too long",
    "caption_invalid": "the caption failed verification",
    "runtime_missing": "a required Python package is missing",
    "request_invalid": "the job request was rejected by the model process",
    "failed": "the model process failed",
}


class Ideogram4Unavailable(Ideogram4ProfileError):
    """Ideogram 4 is not installed (packages or pinned weights missing)."""


class Ideogram4ResourceError(RuntimeError):
    """A fail-closed resource floor (free VRAM, host RAM) is not met; nothing was loaded."""


class Ideogram4ExecutionError(RuntimeError):
    """The contained model process did not produce a valid result (``code`` says why)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


ProcessRunner = Callable[..., ProcessOutcome]


def child_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    import os

    source = os.environ if environ is None else environ
    env = {key: source[key] for key in _ENV_ALLOWLIST if key in source}
    env.update(_ENV_FORCED)
    return env


class _CancelAndProgress:
    """The ``run_bounded`` cancel callback; it also forwards child progress at most once per second (no extra thread)."""

    def __init__(
        self,
        cancel_token: Any,
        progress_path: Path,
        sink: Callable[[dict[str, Any]], None],
        clock: Callable[[], float],
    ) -> None:
        self._token = cancel_token
        self._path = progress_path
        self._sink = sink
        self._clock = clock
        self._next = 0.0
        self._last: str = ""

    def __call__(self) -> bool:
        now = self._clock()
        if now >= self._next:
            self._next = now + PROGRESS_POLL_SECONDS
            self._forward()
        checker = getattr(self._token, "is_cancelled", None)
        return bool(checker()) if callable(checker) else False

    def _forward(self) -> None:
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return
        if text == self._last:
            return
        self._last = text
        try:
            event = json.loads(text)
        except ValueError:
            return
        if isinstance(event, dict):
            try:
                self._sink(event)
            except Exception:  # noqa: BLE001 - progress is observational
                logger.debug("Ideogram 4 progress sink failed", exc_info=True)


class DiffusersImageBackend:
    backend_id = DIFFUSERS_IMAGE_BACKEND_ID
    capabilities = ImageBackendCapabilities(
        backend_id=DIFFUSERS_IMAGE_BACKEND_ID,
        stage_types=("txt2img",),
        supports_negative_prompt=False,
        supports_hypernetworks=False,
        runtime_family=RUNTIME_FAMILY_DIFFUSERS,
    )
    transition_target = RUNTIME_DIFFUSERS

    def __init__(
        self,
        *,
        transition: RuntimeTransitionCoordinator | None = None,
        installation: Callable[[], InstallationStatus] = check_installation,
        gpu_memory: Callable[[], GpuMemory] = query_gpu_memory,
        host_ram_bytes: Callable[[], int] = available_host_ram_bytes,
        process_runner: ProcessRunner = run_bounded,
        interpreter: str = sys.executable,
        temp_root: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self._transition = transition or RuntimeTransitionCoordinator()
        self._installation = installation
        self._gpu_memory = gpu_memory
        self._host_ram = host_ram_bytes
        self._runner = process_runner
        self._interpreter = interpreter
        self._temp_root = temp_root
        self._clock = clock
        self._rng = rng

    # -- admission ---------------------------------------------------------------------------------------------

    @staticmethod
    def _require_profile(backend_options: Any) -> Ideogram4Profile:
        from src.image_backends.exact_model_profile import resolve_model_profile

        profile = resolve_model_profile(backend_options)
        if profile is not None and not isinstance(profile, Ideogram4Profile):
            raise Ideogram4ProfileError(
                f"{profile.display_name} (profile v{profile.version}) requires the '{profile.backend_id}' backend; "
                f"this work targets '{DIFFUSERS_IMAGE_BACKEND_ID}'. StableNew never switches or falls back between "
                "backends."
            )
        if not isinstance(profile, Ideogram4Profile):
            raise Ideogram4ProfileError(
                f"The '{DIFFUSERS_IMAGE_BACKEND_ID}' image backend runs only Ideogram 4 NF4 (profile v1); this work "
                "selects an ordinary checkpoint. StableNew never switches or falls back between backends."
            )
        return profile

    def validate_njr_intent(self, njr: Any, stage_names: list[str]) -> None:
        """Reject work this backend cannot run before the runner dispatches any stage (pure)."""

        self._require_profile(getattr(njr, "backend_options", None))
        if not is_ideogram4_model_name(getattr(njr, "base_model", None)):
            raise Ideogram4ProfileError(
                f"{IDEOGRAM4_PROFILE_V1.display_name} requires its exact model selection"
            )
        validate_ideogram4_njr(njr, list(stage_names))

    def _validate_request(
        self, request: ImageExecutionRequest
    ) -> tuple[CaptionResolution, Ideogram4Plan]:
        if request.stage_name != "txt2img":
            raise Ideogram4ProfileError(
                f"{IDEOGRAM4_PROFILE_V1.display_name} supports only txt2img"
            )
        self._require_profile(request.backend_options)
        if not is_ideogram4_model_name(request.selected_model):
            raise Ideogram4ProfileError(
                f"{IDEOGRAM4_PROFILE_V1.display_name} requires its exact model selection"
            )
        if request.input_image_path is not None:
            raise Ideogram4ProfileError(f"{IDEOGRAM4_PROFILE_V1.display_name} takes no input image")
        validate_ideogram4_config(request.stage_config, negative=request.negative_prompt)
        try:
            caption = resolve_caption(request.prompt)
        except CaptionError as exc:
            raise Ideogram4ProfileError(
                f"{IDEOGRAM4_PROFILE_V1.display_name} cannot run this prompt: {exc}"
            ) from exc
        plan = resolve_plan(
            steps=request.steps,
            width=request.width,
            height=request.height,
            seed=request.seed,
            images=request.image_count,
            rng=self._rng,
        )
        return caption, plan

    # -- preflight ---------------------------------------------------------------------------------------------

    def _check_installation(self) -> InstallationStatus:
        status = self._installation()
        if not status.ready:
            raise Ideogram4Unavailable(
                f"{IDEOGRAM4_PROFILE_V1.display_name} is not installed: {status.summary}"
            )
        return status

    def _check_floors(self) -> dict[str, Any]:
        policy = IDEOGRAM4_PROFILE_V1.residency
        try:
            memory = self._gpu_memory()
        except Exception as exc:  # noqa: BLE001 - an unreadable GPU state cannot authorize a 11 GiB load
            raise Ideogram4ResourceError(
                f"StableNew could not read free GPU memory before loading Ideogram 4 ({exc}); nothing was loaded"
            ) from exc
        if memory.free_mib < policy.min_free_vram_mib:
            raise Ideogram4ResourceError(
                f"Ideogram 4 needs {policy.min_free_vram_mib} MiB of free GPU memory, but only {memory.free_mib} MiB "
                f"of {memory.total_mib} MiB is free. Another application is using the GPU; StableNew released its own "
                "runtimes and does not close other programs. Nothing was loaded."
            )
        host = int(self._host_ram())
        if host < policy.min_available_host_ram_bytes:
            raise Ideogram4ResourceError(
                f"Ideogram 4 needs {policy.min_available_host_ram_bytes / 1024**3:.0f} GiB of available host RAM while "
                f"loading, but only {host / 1024**3:.1f} GiB is available. Close other programs and try again. "
                "Nothing was loaded."
            )
        return {
            "free_vram_mib": memory.free_mib,
            "used_vram_mib": memory.used_mib,
            "total_vram_mib": memory.total_mib,
            "available_host_ram_bytes": host,
        }

    # -- execution ---------------------------------------------------------------------------------------------

    def execute(self, pipeline: Any, request: ImageExecutionRequest) -> ImageExecutionResult | None:
        caption, plan = self._validate_request(request)
        self._raise_if_cancelled(request.cancel_token)
        installation = self._check_installation()
        transition = self._transition.prepare_for(self.transition_target)
        if not transition.ready:
            raise RuntimeTransitionError(transition)
        floors = self._check_floors()
        self._raise_if_cancelled(request.cancel_token)
        job_dir = Path(tempfile.mkdtemp(prefix="stablenew-ideogram4-", dir=self._temp_root))
        try:
            outcome, document = self._run_child(pipeline, request, caption, plan, job_dir)
            teardown = self._teardown_evidence(outcome)
            return self._publish(
                pipeline,
                request,
                caption,
                plan,
                job_dir,
                document,
                {
                    "installation": {"snapshot_dir": str(installation.snapshot_dir or "")},
                    "lease": transition.to_dict(),
                    "floors": floors,
                    "teardown": teardown,
                },
            )
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

    @staticmethod
    def _raise_if_cancelled(token: Any) -> None:
        checker = getattr(token, "is_cancelled", None)
        if callable(checker) and checker():
            from src.controller.runtime_state import CancellationError

            raise CancellationError("Cancelled before Ideogram 4 started")

    def _run_child(
        self,
        pipeline: Any,
        request: ImageExecutionRequest,
        caption: CaptionResolution,
        plan: Ideogram4Plan,
        job_dir: Path,
    ) -> tuple[ProcessOutcome, dict[str, Any]]:
        from src.image_backends.diffusers_ideogram4_worker import (
            PROGRESS_FILE,
            REQUEST_FILE,
            REQUEST_SCHEMA,
            RESULT_FILE,
        )
        from src.utils.atomic_io import atomic_write_json

        profile = IDEOGRAM4_PROFILE_V1
        atomic_write_json(
            job_dir / REQUEST_FILE,
            {
                "schema": REQUEST_SCHEMA,
                "repo_id": profile.repo_id,
                "revision": profile.revision,
                "caption_json": caption.caption_json,
                "caption_sha256": caption.sha256,
                "width": plan.width,
                "height": plan.height,
                "steps": plan.preset.steps,
                "guidance_schedule": list(plan.preset.diffusers_guidance()),
                "mu": plan.preset.mu,
                "std": plan.preset.std,
                "seeds": list(plan.seeds),
            },
            ensure_ascii=False,
        )
        poll = _CancelAndProgress(
            request.cancel_token,
            job_dir / PROGRESS_FILE,
            lambda event: self._emit_progress(pipeline, request, event),
            self._clock,
        )
        outcome = self._runner(
            [self._interpreter, "-I", str(WORKER_PATH), str(job_dir)],
            timeout_seconds=profile.residency.timeout_seconds(plan.preset.steps, len(plan.seeds)),
            max_stdout_bytes=WORKER_STDOUT_CAP,
            cancel=poll,
            env=child_environment(),
            memory_limit_mb=profile.residency.child_memory_limit_mb,
            record_ownership=True,
            keep_output_tail=True,
        )
        if outcome.cancelled:
            from src.controller.runtime_state import CancellationError

            raise CancellationError(
                "Ideogram 4 generation cancelled; its model process was stopped"
            )
        if outcome.launch_error:
            raise Ideogram4ExecutionError(
                "launch_error",
                f"The Ideogram 4 model process could not start: {outcome.launch_error}",
            )
        if outcome.timed_out:
            raise Ideogram4ExecutionError(
                "timeout", "Ideogram 4 took longer than its time limit and was stopped"
            )
        document = self._read_result(job_dir / RESULT_FILE, outcome)
        if outcome.returncode != 0 or not document.get("ok"):
            code = str(document.get("code") or "failed")
            detail = str(document.get("message") or "")[:500]
            summary = _FAILURE_MESSAGES.get(code, "the model process failed")
            raise Ideogram4ExecutionError(
                code, f"Ideogram 4 failed: {summary}" + (f" ({detail})" if detail else "")
            )
        return outcome, document

    @staticmethod
    def _read_result(path: Path, outcome: ProcessOutcome) -> dict[str, Any]:
        try:
            with path.open("rb") as stream:
                data = stream.read(MAX_RESULT_BYTES + 1)
            if len(data) > MAX_RESULT_BYTES:
                raise ValueError("oversized result")
            document = json.loads(data.decode("utf-8"))
        except (OSError, ValueError) as exc:
            tail = outcome.stderr.decode("utf-8", errors="replace")[-800:]
            raise Ideogram4ExecutionError(
                "failed",
                f"The Ideogram 4 model process produced no readable result (exit {outcome.returncode}). {tail}",
            ) from exc
        if not isinstance(document, dict):
            raise Ideogram4ExecutionError(
                "failed", "The Ideogram 4 model process produced an invalid result"
            )
        return document

    def _teardown_evidence(self, outcome: ProcessOutcome) -> dict[str, Any]:
        """The child has exited; prove no process of its tree remains, then observe driver VRAM."""

        evidence: dict[str, Any] = {
            "returncode": outcome.returncode,
            "contained": outcome.contained,
            "memory_limit_enforced": outcome.memory_limit_enforced,
        }
        ownership = outcome.ownership
        if ownership is not None:
            evidence.update(
                ownership_complete=ownership.complete,
                total_processes=ownership.total_processes,
                survivors_at_end=ownership.survivors_at_end,
                active_after_teardown=ownership.active_after_teardown,
                problems=list(ownership.problems)[:8],
            )
            if ownership.active_after_teardown:
                raise Ideogram4ExecutionError(
                    "teardown_unproven",
                    f"{ownership.active_after_teardown} process(es) of the Ideogram 4 model tree were still running after "
                    "teardown; GPU memory may still be held. The job is failed rather than reported clean.",
                )
        else:
            evidence["ownership_complete"] = False
        try:
            memory = self._gpu_memory()
            evidence["post_exit_vram"] = {
                "free_mib": memory.free_mib,
                "used_mib": memory.used_mib,
                "total_mib": memory.total_mib,
            }
        except Exception as exc:  # noqa: BLE001 - observational only
            evidence["post_exit_vram"] = {"error": str(exc)[:200]}
        return evidence

    @staticmethod
    def _emit_progress(
        pipeline: Any, request: ImageExecutionRequest, event: Mapping[str, Any]
    ) -> None:
        emit = getattr(pipeline, "_emit_status_update", None)
        if not callable(emit):
            return
        phase = str(event.get("phase") or "")
        status: dict[str, Any] = {
            "job_id": request.job_id,
            "current_stage": "txt2img",
            "stage_index": int(getattr(pipeline, "_current_stage_index", 0) or 0),
            "total_stages": len(getattr(pipeline, "_current_stage_chain", None) or ["txt2img"]),
        }
        if phase == "denoising":
            step, steps = int(event.get("step") or 0), max(1, int(event.get("steps") or 1))
            image, images = int(event.get("image") or 1), max(1, int(event.get("images") or 1))
            status.update(
                stage_detail=f"Ideogram 4: image {image}/{images}, step {step}/{steps}",
                current_step=step,
                total_steps=steps,
                progress=min(1.0, ((image - 1) * steps + step) / (images * steps)),
            )
        else:
            status.update(stage_detail=f"Ideogram 4: {phase or 'starting'}", progress=0.0)
        emit(status)

    # -- artifacts ---------------------------------------------------------------------------------------------

    def _publish(
        self,
        pipeline: Any,
        request: ImageExecutionRequest,
        caption: CaptionResolution,
        plan: Ideogram4Plan,
        job_dir: Path,
        document: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> ImageExecutionResult:
        from src.pipeline.artifact_contract import artifact_manifest_payload
        from src.utils.atomic_io import atomic_write_json
        from src.utils.file_io import get_unique_output_path

        images = document.get("images")
        if not isinstance(images, list) or len(images) != len(plan.seeds):
            raise Ideogram4ExecutionError(
                "failed", "The Ideogram 4 model process returned the wrong number of images"
            )
        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_dir = output_dir / "manifests"
        base_name = str(request.image_name or "txt2img")
        profile = IDEOGRAM4_PROFILE_V1
        run_dir = output_dir.parent if output_dir.name in {"txt2img"} else output_dir
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        common = {
            "stage": "txt2img",
            "timestamp": timestamp,
            "job_id": request.job_id,
            "image_backend_id": self.backend_id,
            "model": profile.model_name,
            "model_profile": profile.reference(),
            "model_identity": {"repo_id": profile.repo_id, "revision": profile.revision},
            "original_prompt": request.prompt,
            "final_prompt": request.prompt,
            "original_negative_prompt": "",
            "final_negative_prompt": "",
            "requested_seed": plan.requested_seed if plan.requested_seed is not None else -1,
            "all_seeds": list(plan.seeds),
            "ideogram4": {
                **caption.to_manifest(),
                "preset": plan.preset.name,
                "steps": plan.preset.steps,
                "mu": plan.preset.mu,
                "std": plan.preset.std,
                "width": plan.width,
                "height": plan.height,
                "token_count": document.get("token_count"),
                "allocator_cap": document.get("allocator_cap"),
                "timings": document.get("timings"),
                "swaps": document.get("swaps"),
                "max_resident_transformers": document.get("max_resident_transformers"),
                "memory": document.get("memory"),
                "runtime": document.get("runtime"),
                **dict(evidence),
            },
            "config": {
                "model": profile.model_name,
                "steps": plan.preset.steps,
                "width": plan.width,
                "height": plan.height,
                "sampler_name": profile.sampler,
                "scheduler": profile.scheduler,
                "cfg_scale": profile.cfg_scale,
                "seed": plan.seeds[0],
                "preset": plan.preset.name,
            },
        }
        saved: list[Path] = []
        manifests: list[tuple[Path, dict[str, Any]]] = []
        for index, (entry, seed) in enumerate(zip(images, plan.seeds, strict=True)):
            source = job_dir / str(entry.get("file") or "")
            if (
                source.parent != job_dir
                or not source.is_file()
                or int(entry.get("seed", -1)) != seed
            ):
                raise Ideogram4ExecutionError(
                    "failed", "The Ideogram 4 model process returned an unexpected image entry"
                )
            name = (
                base_name
                if len(images) == 1
                else (
                    f"{base_name}_s{index + 1:02d}"
                    if request.learning_sample_names
                    else f"{base_name}_batch{index}"
                )
            )
            target = get_unique_output_path(output_dir / f"{name}.png")
            metadata = {
                **common,
                "name": target.stem,
                "path": str(target),
                "output_path": str(target),
                "seed": seed,
                "actual_seed": seed,
                "image_sha256_from_model_process": entry.get("sha256"),
            }
            self._save_png(source, target, run_dir, metadata, request)
            saved.append(target)
            manifest_path = manifest_dir / f"{target.stem}.json"
            metadata["artifact"] = artifact_manifest_payload(
                stage="txt2img",
                image_or_output_path=target,
                manifest_path=manifest_path,
                output_paths=[str(target)],
                job_id=request.job_id,
            )
            metadata.update(
                expected_images=len(plan.seeds),
                returned_images=len(images),
                saved_images=len(images),
                partial_success=False,
            )
            manifests.append((manifest_path, metadata))
        manifest_dir.mkdir(parents=True, exist_ok=True)
        for manifest_path, metadata in manifests:
            atomic_write_json(manifest_path, metadata, indent=2, ensure_ascii=False)
        primary = saved[0]
        result = {
            **common,
            "name": base_name,
            "path": str(primary),
            "output_path": str(primary),
            "all_paths": [str(path) for path in saved],
            "seed": plan.seeds[0],
            "actual_seed": plan.seeds[0],
            "manifest_path": str(manifests[0][0]),
            "expected_images": len(plan.seeds),
            "returned_images": len(images),
            "saved_images": len(saved),
            "partial_success": False,
        }
        return ImageExecutionResult.from_stage_result(
            backend_id=self.backend_id,
            stage_name="txt2img",
            result=result,
            backend_metadata={
                "backend_id": self.backend_id,
                "executor": "diffusers_ideogram4_worker",
                "model_profile": profile.reference(),
            },
        )

    @staticmethod
    def _save_png(
        source: Path,
        target: Path,
        run_dir: Path,
        metadata: dict[str, Any],
        request: ImageExecutionRequest,
    ) -> None:
        """Re-save the child's PNG with StableNew's embedded metadata contract (the image pixels are unchanged)."""

        from PIL import Image, PngImagePlugin

        from src.utils.image_metadata import build_contract_kv, build_payload_from_manifest

        with Image.open(source) as image:
            image.load()
            payload = build_payload_from_manifest(
                image_path=target,
                run_dir=run_dir,
                stage="txt2img",
                manifest=metadata,
                image_size=image.size,
            )
            payload.setdefault("job_id", request.job_id or "")
            kv = build_contract_kv(
                payload,
                job_id=str(request.job_id or ""),
                run_id=run_dir.name,
                stage="txt2img",
                created_utc=datetime.now(UTC).isoformat(),
            )
            info = PngImagePlugin.PngInfo()
            for key, value in kv.items():
                info.add_itxt(str(key), str(value), zip=False)
            image.save(target, pnginfo=info)


__all__ = [
    "DiffusersImageBackend",
    "Ideogram4ExecutionError",
    "Ideogram4ResourceError",
    "Ideogram4Unavailable",
    "child_environment",
]
