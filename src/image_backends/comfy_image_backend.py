"""The Comfy still-image backend (PR-IMG-COMFY-100): Qwen-Image 2.1 txt2img on StableNew's managed ComfyUI.

One backend behind the existing ``ImageBackendRegistry`` (PR-IMG-100 COA B); the runner, queue, NJR, history and
cancellation authorities are the existing ones, and Comfy's own queue and history stay private to this adapter.
``execute`` runs a fixed, fail-closed sequence:

1. **validate** the frozen intent again (profile, envelope, plan) - pure;
2. **assets**: every pinned file is installed at its exact size and SHA-256 (nothing is downloaded or moved);
3. **lease** the GPU: ``RuntimeTransitionCoordinator.prepare_for("comfy")`` releases StableNew's own WebUI-family
   runtime and the SVD cache through their owners; an external occupant refuses the job;
4. **runtime**: a StableNew-owned managed ComfyUI launched with the managed flags; an external ComfyUI is refused;
5. **probe** ``object_info`` (node classes, file names, encoder type) and the **floors** from ``system_stats``;
6. **dispatch once**: one frozen graph, one prompt, a caller-chosen prompt id; an ambiguous POST is never replayed;
7. **observe** the prompt's history; cancellation interrupts or dequeues this prompt only;
8. **artifacts**: the one PNG is fetched into the run directory, re-saved with StableNew's embedded metadata and given
   a manifest with full provenance;
9. **release** the owned ComfyUI on every exit path (the graph's runtime policy).

Nothing is retried and nothing falls back to another backend. No ``src/video`` behaviour is changed: the managed
runtime, transport and the pure prompt-observation predicates are reused as they are.
"""

from __future__ import annotations

import logging
import random
import re
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.image_backends.comfy_image_graphs import (
    SAVE_NODE_ID,
    ComfyImageGraph,
    canonical_sha256,
    graph_for_profile,
)
from src.image_backends.comfy_image_readiness import (
    ComfyInstallationStatus,
    check_installation,
    evaluate_floors,
    probe_object_info,
)
from src.image_backends.comfy_qwen_image_profile import (
    QwenImagePlan,
    QwenImageProfile,
    QwenImageProfileError,
    qwen_image_profile_for_model,
    resolve_qwen_image_plan,
    validate_qwen_image_config,
    validate_qwen_image_njr,
)
from src.image_backends.image_backend_types import (
    COMFY_IMAGE_BACKEND_ID,
    RUNTIME_FAMILY_COMFY,
    ImageBackendCapabilities,
    ImageExecutionRequest,
    ImageExecutionResult,
)
from src.services.runtime_transition_service import (
    RUNTIME_COMFY,
    RuntimeTransitionCoordinator,
    RuntimeTransitionError,
)

logger = logging.getLogger(__name__)

#: Launch flags the image slice requires of the owned ComfyUI (the managed installation adds its own contract flags).
#: Requiring a flag makes ``ComfyProcessManager.ensure_running`` succeed only for a process StableNew launched and owns.
REQUIRED_LAUNCH_FLAGS: tuple[str, ...] = ("--disable-pinned-memory",)
HISTORY_POLL_SECONDS = 0.5
LIVENESS_REPORT_SECONDS = 5.0
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")


class ComfyImageUnavailable(QwenImageProfileError):
    """The profile cannot run here: weights missing or different, or the runtime lacks a node, file or encoder type."""


class ComfyImageExecutionError(RuntimeError):
    """The one dispatched prompt did not produce a valid result (``code`` says why)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _cancelled(token: Any) -> bool:
    checker = getattr(token, "is_cancelled", None)
    try:
        return bool(checker()) if callable(checker) else False
    except Exception:  # noqa: BLE001 - a broken token must not abort a healthy generation
        return False


def _raise_cancelled(message: str) -> None:
    from src.controller.runtime_state import CancellationError

    raise CancellationError(message)


def _safe_component(value: Any, fallback: str) -> str:
    text = _SAFE_NAME.sub("_", str(value or "")).strip("_")
    return text[:64] or fallback


class ComfyImageBackend:
    backend_id = COMFY_IMAGE_BACKEND_ID
    capabilities = ImageBackendCapabilities(
        backend_id=COMFY_IMAGE_BACKEND_ID,
        stage_types=("txt2img",),
        supports_negative_prompt=False,
        supports_hypernetworks=False,
        runtime_family=RUNTIME_FAMILY_COMFY,
    )
    transition_target = RUNTIME_COMFY

    def __init__(
        self,
        *,
        transition: RuntimeTransitionCoordinator | None = None,
        process_manager: Any = None,
        client_factory: Callable[[str], Any] | None = None,
        installation: Callable[[QwenImageProfile], ComfyInstallationStatus] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        temp_root: str | None = None,
        poll_seconds: float = HISTORY_POLL_SECONDS,
    ) -> None:
        self._transition = transition or RuntimeTransitionCoordinator()
        self._process_manager = process_manager
        self._client_factory = client_factory
        self._installation = installation or (
            lambda profile: check_installation(profile, verify_sha256=True)
        )
        self._clock = clock
        self._sleep = sleep
        self._rng = rng
        self._temp_root = temp_root
        self._poll_seconds = max(0.0, poll_seconds)

    # -- admission ---------------------------------------------------------------------------------------------

    @staticmethod
    def _require_profile(backend_options: Any, model_name: Any) -> QwenImageProfile:
        from src.image_backends.exact_model_profile import resolve_model_profile

        frozen = resolve_model_profile(backend_options)
        if frozen is not None and not isinstance(frozen, QwenImageProfile):
            raise QwenImageProfileError(
                f"{frozen.display_name} (profile v{frozen.version}) requires the '{frozen.backend_id}' backend; this "
                f"work targets '{COMFY_IMAGE_BACKEND_ID}'. StableNew never switches or falls back between backends."
            )
        if frozen is None:
            raise QwenImageProfileError(
                f"The '{COMFY_IMAGE_BACKEND_ID}' image backend runs only the frozen Qwen-Image 2.1 profiles; this work "
                "selects an ordinary checkpoint. StableNew never switches or falls back between backends."
            )
        if qwen_image_profile_for_model(model_name) is not frozen:
            raise QwenImageProfileError(f"{frozen.display_name} requires its exact model selection")
        return frozen

    def validate_njr_intent(self, njr: Any, stage_names: list[str]) -> None:
        """Reject work this backend cannot run before the runner dispatches any stage (pure)."""

        self._require_profile(
            getattr(njr, "backend_options", None), getattr(njr, "base_model", None)
        )
        validate_qwen_image_njr(njr, list(stage_names))

    def _validate_request(
        self, request: ImageExecutionRequest
    ) -> tuple[QwenImageProfile, ComfyImageGraph, QwenImagePlan]:
        profile = self._require_profile(request.backend_options, request.selected_model)
        if request.stage_name != "txt2img":
            raise QwenImageProfileError(f"{profile.display_name} supports only txt2img")
        if request.input_image_path is not None:
            raise QwenImageProfileError(f"{profile.display_name} takes no input image")
        if not str(request.prompt or "").strip():
            raise QwenImageProfileError(f"{profile.display_name} needs a prompt")
        validate_qwen_image_config(profile, request.stage_config, negative=request.negative_prompt)
        validate_qwen_image_config(
            profile,
            {
                "steps": request.steps,
                "cfg_scale": request.cfg_scale,
                "width": request.width,
                "height": request.height,
            },
        )
        plan = resolve_qwen_image_plan(
            profile,
            width=request.width,
            height=request.height,
            seed=request.seed,
            images=request.image_count,
            rng=self._rng,
        )
        return profile, graph_for_profile(profile), plan

    # -- execution ---------------------------------------------------------------------------------------------

    def execute(self, pipeline: Any, request: ImageExecutionRequest) -> ImageExecutionResult | None:
        profile, graph, plan = self._validate_request(request)
        if _cancelled(request.cancel_token):
            _raise_cancelled(f"Cancelled before {profile.display_name} started")
        installation = self._installation(profile)
        if not installation.ready:
            raise ComfyImageUnavailable(
                f"{profile.display_name} is not installed: {installation.summary}"
            )
        transition = self._transition.prepare_for(self.transition_target)
        if not transition.ready:
            raise RuntimeTransitionError(transition)
        evidence: dict[str, Any] = {
            "installation": {
                "paths": dict(installation.paths),
                "sha256_verified": installation.sha256_verified,
            },
            "lease": transition.to_dict(),
        }
        # Runtime policy: once this job may have touched the managed runtime, the process StableNew owns is released
        # on every exit path; an external or unowned ComfyUI is never stopped. The original error always propagates.
        try:
            result = self._execute_on_runtime(pipeline, request, profile, graph, plan, evidence)
        except BaseException:
            self._release_owned_runtime()
            raise
        release = self._release_owned_runtime()
        result.backend_metadata["runtime_release"] = dict(release)
        result.diagnostic_payload["runtime_release"] = dict(release)
        return result

    def _execute_on_runtime(
        self,
        pipeline: Any,
        request: ImageExecutionRequest,
        profile: QwenImageProfile,
        graph: ComfyImageGraph,
        plan: QwenImagePlan,
        evidence: dict[str, Any],
    ) -> ImageExecutionResult:
        from src.video.comfy_workflow_backend import _actual_runtime_identity

        base_url = self._ensure_owned_runtime()
        client = self._client(base_url)
        problems = probe_object_info(graph, client.get_object_info())
        if problems:
            raise ComfyImageUnavailable(
                f"{profile.display_name} cannot run on this ComfyUI: " + "; ".join(problems)
            )
        system_stats = client.get_system_stats()
        evidence["floors"] = evaluate_floors(profile, system_stats)
        evidence["actual_runtime"] = _actual_runtime_identity(system_stats)
        job_part = _safe_component(request.job_id, "job")
        name_part = _safe_component(request.image_name, "txt2img")
        prompt_graph = graph.build(
            prompt=str(request.prompt),
            seed=plan.seed,
            width=plan.width,
            height=plan.height,
            filename_prefix=f"stablenew/{job_part}/{name_part}",
        )
        prompt_id = str(uuid.uuid4())
        payload = {
            "prompt": prompt_graph,
            "prompt_id": prompt_id,
            "client_id": f"stablenew-{job_part}",
            "extra_data": {"backend_id": self.backend_id, **graph.reference()},
        }
        if _cancelled(request.cancel_token):
            _raise_cancelled(f"Cancelled before {profile.display_name} was queued")
        # Not retried: a DispatchOutcomeUnknown here means ComfyUI may already be running this prompt.
        response = client.queue_prompt(payload)
        returned_id = str((response or {}).get("prompt_id") or "").strip()
        if not returned_id:
            raise ComfyImageExecutionError(
                "no_prompt_id", "ComfyUI accepted the graph but returned no prompt id"
            )
        entry = self._wait_for_history(pipeline, request, client, returned_id, profile)
        job_dir = Path(tempfile.mkdtemp(prefix="stablenew-comfy-image-", dir=self._temp_root))
        try:
            source = self._fetch_output(client, entry, job_dir)
            return self._publish(
                pipeline,
                request,
                profile,
                graph,
                plan,
                source,
                {
                    **evidence,
                    "prompt_id": returned_id,
                    "requested_prompt_id": prompt_id,
                    "submitted_graph_sha256": canonical_sha256(prompt_graph),
                },
            )
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

    def _client(self, base_url: str) -> Any:
        if self._client_factory is not None:
            return self._client_factory(base_url)
        from src.video.comfy_api_client import ComfyApiClient

        return ComfyApiClient(base_url=base_url)

    # -- runtime ownership --------------------------------------------------------------------------------------

    def _resolve_process_manager(self) -> Any:
        if self._process_manager is not None:
            return self._process_manager
        from src.video.comfy_process_manager import (
            ComfyProcessManager,
            build_default_comfy_process_config,
            get_global_comfy_process_manager,
        )

        manager = get_global_comfy_process_manager()
        if manager is None:
            config = build_default_comfy_process_config()
            if config is None:
                raise ComfyImageUnavailable(
                    "Qwen-Image needs a StableNew-managed ComfyUI launch configuration (Settings: ComfyUI)"
                )
            manager = ComfyProcessManager(config)
        # Keep the owner across release/relaunch cycles, as the video backend does.
        self._process_manager = manager
        return manager

    def _ensure_owned_runtime(self) -> str:
        from src.video.comfy_process_manager import ComfyStartupError

        manager = self._resolve_process_manager()
        config = getattr(manager, "config", None)
        if (
            config is not None
            and not getattr(config, "autostart_enabled", False)
            and not manager.is_running()
        ):
            raise ComfyStartupError(
                "Qwen-Image requires a StableNew-owned ComfyUI, but automatic ComfyUI start is off"
            )
        # A required flag makes ensure_running refuse to adopt an external ComfyUI on the configured endpoint.
        if not manager.ensure_running(required_flags=REQUIRED_LAUNCH_FLAGS):
            raise ComfyStartupError("The StableNew-owned ComfyUI did not become healthy")
        if not getattr(manager, "owns_process", False):
            raise ComfyStartupError(
                "Qwen-Image runs only on a ComfyUI that StableNew launched and owns; an external ComfyUI is never used"
            )
        return str(getattr(config, "base_url", "") or "http://127.0.0.1:8188").rstrip("/")

    def _release_owned_runtime(self) -> dict[str, Any]:
        """Stop the managed ComfyUI only when StableNew owns its process; report what happened. Never raises."""

        manager = self._process_manager
        report: dict[str, Any] = {"policy": "release_owned_runtime_after_job"}
        if manager is None:
            return {**report, "ownership": "none", "released": False}
        try:
            owned, pid = bool(manager.owns_process), manager.pid
        except Exception as exc:  # noqa: BLE001 - an unreadable owner is never stopped
            return {
                **report,
                "ownership": "unknown",
                "released": False,
                "error": f"{type(exc).__name__}: {exc}"[:300],
            }
        if not owned:
            return {**report, "ownership": "not_owned", "released": False}
        try:
            manager.stop()
            released = not bool(manager.is_running())
        except Exception as exc:  # noqa: BLE001 - report; never escalate to other processes
            return {**report, "ownership": "owned", "pid": pid, "released": False,
                    "error": f"{type(exc).__name__}: {exc}"[:300]}  # fmt: skip
        return {**report, "ownership": "owned", "pid": pid, "released": released}

    # -- observation and cancellation ------------------------------------------------------------------------------

    def _wait_for_history(
        self,
        pipeline: Any,
        request: ImageExecutionRequest,
        client: Any,
        prompt_id: str,
        profile: QwenImageProfile,
    ) -> dict[str, Any]:
        from src.video.comfy_workflow_backend import (
            _history_entry_from_payload,
            _history_failed,
            _history_failure_detail,
            _history_nonterminal,
            _history_ready,
            _queue_membership,
        )

        started = self._clock()
        deadline = started + profile.resources.history_timeout_seconds
        last_report: float | None = None
        while self._clock() < deadline:
            if _cancelled(request.cancel_token):
                self._cancel_prompt(client, prompt_id)
                _raise_cancelled(f"{profile.display_name} cancelled (prompt_id '{prompt_id}')")
            entry = _history_entry_from_payload(
                dict(client.get_history(prompt_id) or {}), prompt_id
            )
            if entry is not None and _history_failed(entry):
                detail = _history_failure_detail(entry)
                raise ComfyImageExecutionError(
                    "execution_error",
                    f"ComfyUI failed {profile.display_name} (prompt_id '{prompt_id}')"
                    + (f": {detail}" if detail else ""),
                )
            if entry is not None and _history_ready(entry):
                return entry
            now = self._clock()
            if last_report is None or now - last_report >= LIVENESS_REPORT_SECONDS:
                live = entry is not None and _history_nonterminal(entry)
                if not live:
                    try:
                        live = _queue_membership(client.get_queue(), prompt_id) is not None
                    except Exception:  # noqa: BLE001 - an unreadable queue is not evidence of liveness
                        live = False
                if live:
                    last_report = now
                    self._emit_liveness(pipeline, request, profile, now - started)
            self._sleep(self._poll_seconds)
        self._cancel_prompt(client, prompt_id)
        raise ComfyImageExecutionError(
            "timeout",
            f"{profile.display_name} took longer than {profile.resources.history_timeout_seconds:.0f} s; its prompt "
            "was stopped",
        )

    @staticmethod
    def _cancel_prompt(client: Any, prompt_id: str) -> None:
        """Best-effort, bounded stop of the one prompt this job queued; never raises, never touches another prompt."""

        from src.video.comfy_workflow_backend import _queue_membership

        try:
            state = _queue_membership(client.get_queue(), prompt_id)
            if state == "running":
                client.interrupt(prompt_id)
            elif state == "pending":
                client.delete_from_queue([prompt_id])
        except Exception as exc:  # noqa: BLE001 - cancellation must proceed even if ComfyUI is unreachable
            logger.warning("Could not ask ComfyUI to stop prompt %s: %s", prompt_id, exc)

    @staticmethod
    def _emit_liveness(
        pipeline: Any, request: ImageExecutionRequest, profile: QwenImageProfile, elapsed: float
    ) -> None:
        """Execution liveness through the runner's status path; no step count or percentage is invented."""

        emit = getattr(pipeline, "_emit_status_update", None)
        if not callable(emit) or not request.job_id:
            return
        try:
            emit(
                {
                    "job_id": request.job_id,
                    "current_stage": "txt2img",
                    "stage_detail": f"{profile.display_name}: executing ({int(elapsed)}s)",
                }
            )
        except Exception:  # noqa: BLE001 - observability must never abort the wait
            logger.debug("Qwen-Image liveness emit failed", exc_info=True)

    # -- outputs ----------------------------------------------------------------------------------------------

    @staticmethod
    def _fetch_output(client: Any, entry: Mapping[str, Any], job_dir: Path) -> Path:
        from src.video.comfy_workflow_backend import _is_generated_output

        outputs = entry.get("outputs")
        node = outputs.get(SAVE_NODE_ID) if isinstance(outputs, Mapping) else None
        images = node.get("images") if isinstance(node, Mapping) else None
        generated = [
            item for item in images or () if isinstance(item, Mapping) and item.get("filename")
            and _is_generated_output(item)
        ]  # fmt: skip
        if len(generated) != 1:
            raise ComfyImageExecutionError(
                "wrong_output_count",
                f"ComfyUI returned {len(generated)} generated images; exactly one was expected",
            )
        descriptor = generated[0]
        name = Path(str(descriptor["filename"])).name
        if not name.lower().endswith(".png"):
            raise ComfyImageExecutionError(
                "unexpected_output", f"ComfyUI returned an unexpected output file: {name}"
            )
        return Path(
            client.download_view(
                name,
                job_dir / name,
                subfolder=str(descriptor.get("subfolder") or ""),
                file_type=str(descriptor.get("type") or "output"),
            )
        )

    def _publish(
        self,
        pipeline: Any,
        request: ImageExecutionRequest,
        profile: QwenImageProfile,
        graph: ComfyImageGraph,
        plan: QwenImagePlan,
        source: Path,
        evidence: Mapping[str, Any],
    ) -> ImageExecutionResult:
        from PIL import Image

        from src.pipeline.artifact_contract import artifact_manifest_payload
        from src.utils.atomic_io import atomic_write_json
        from src.utils.file_io import get_unique_output_path

        try:
            with Image.open(source) as image:
                size = image.size
        except Exception as exc:  # noqa: BLE001 - an unreadable file is a failed job, not a partial success
            raise ComfyImageExecutionError(
                "unreadable_output", f"ComfyUI's output image is unreadable: {exc}"
            ) from exc
        if size != (plan.width, plan.height):
            raise ComfyImageExecutionError(
                "wrong_output_size",
                f"ComfyUI returned a {size[0]}x{size[1]} image; {plan.width}x{plan.height} was requested",
            )
        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_dir = output_dir / "manifests"
        base_name = str(request.image_name or "txt2img")
        run_dir = output_dir.parent if output_dir.name in {"txt2img"} else output_dir
        target = get_unique_output_path(output_dir / f"{base_name}.png")
        manifest_path = manifest_dir / f"{target.stem}.json"
        metadata: dict[str, Any] = {
            "name": target.stem,
            "stage": "txt2img",
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "job_id": request.job_id,
            "image_backend_id": self.backend_id,
            "model": profile.model_name,
            "model_profile": profile.reference(),
            "model_identity": {
                "repo_id": profile.repo_id,
                "revision": profile.revision,
                "files": {asset.filename: asset.sha256 for asset in profile.assets},
            },
            "original_prompt": request.prompt,
            "final_prompt": request.prompt,
            "original_negative_prompt": "",
            "final_negative_prompt": "",
            "path": str(target),
            "output_path": str(target),
            "seed": plan.seed,
            "actual_seed": plan.seed,
            "requested_seed": plan.requested_seed if plan.requested_seed is not None else -1,
            "all_seeds": [plan.seed],
            "qwen_image": {
                "graph": graph.reference(),
                "licence": profile.licence,
                "steps": profile.steps,
                "width": plan.width,
                "height": plan.height,
                **dict(evidence),
            },
            "config": {
                "model": profile.model_name,
                "steps": profile.steps,
                "width": plan.width,
                "height": plan.height,
                "sampler_name": profile.sampler,
                "scheduler": profile.scheduler,
                "cfg_scale": profile.cfg_scale,
                "seed": plan.seed,
            },
            "expected_images": 1,
            "returned_images": 1,
            "saved_images": 1,
            "partial_success": False,
        }
        self._save_png(source, target, run_dir, metadata, request)
        metadata["artifact"] = artifact_manifest_payload(
            stage="txt2img",
            image_or_output_path=target,
            manifest_path=manifest_path,
            output_paths=[str(target)],
            job_id=request.job_id,
        )
        manifest_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(manifest_path, metadata, indent=2, ensure_ascii=False)
        result = {
            **metadata,
            "name": base_name,
            "all_paths": [str(target)],
            "manifest_path": str(manifest_path),
        }
        return ImageExecutionResult.from_stage_result(
            backend_id=self.backend_id,
            stage_name="txt2img",
            result=result,
            backend_metadata={
                "backend_id": self.backend_id,
                "executor": "comfy_image_backend",
                "model_profile": profile.reference(),
                "graph": graph.reference(),
                "prompt_id": evidence.get("prompt_id"),
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
        """Re-save ComfyUI's PNG with StableNew's embedded metadata contract (pixels unchanged; Comfy's own text
        chunks, which carry the full graph, are not copied)."""

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
    "REQUIRED_LAUNCH_FLAGS",
    "ComfyImageBackend",
    "ComfyImageExecutionError",
    "ComfyImageUnavailable",
]
