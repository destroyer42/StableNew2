"""Hermetic fakes for the Comfy still-image backend (PR-IMG-COMFY-100): no process, socket, model or GPU."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PIL import Image

from src.image_backends.comfy_image_graphs import (
    QWEN_IMAGE_21_T2I,
    QWEN_IMAGE_21_TURBO_T2I,
    SAVE_NODE_ID,
)
from src.image_backends.comfy_qwen_image_profile import QWEN_IMAGE_PROFILES
from src.services.runtime_transition_service import (
    RuntimeOwnershipState,
    RuntimeTransitionResult,
    RuntimeTransitionStatus,
)

GIB = 1024**3


def object_info(
    *, missing_class: str = "", drop_file: str = "", clip_types: Iterable[str] = ("qwen_image",)
) -> dict:
    """``/object_info`` of a pinned v0.38.0 runtime holding both variants' files (legacy combo shapes)."""

    classes = set(QWEN_IMAGE_21_T2I.required_node_classes) | set(
        QWEN_IMAGE_21_TURBO_T2I.required_node_classes
    )
    info: dict[str, Any] = {
        name: {"input": {"required": {}}} for name in classes if name != missing_class
    }
    files = {
        "unet_name": [p.diffusion_model.filename for p in QWEN_IMAGE_PROFILES],
        "clip_name": [QWEN_IMAGE_PROFILES[0].text_encoder.filename],
        "vae_name": [QWEN_IMAGE_PROFILES[0].vae.filename],
    }
    files = {key: [name for name in names if name != drop_file] for key, names in files.items()}
    if "UNETLoader" in info:
        info["UNETLoader"]["input"]["required"] = {
            "unet_name": [files["unet_name"]],
            "weight_dtype": [["default"]],
        }
    if "CLIPLoader" in info:
        info["CLIPLoader"]["input"]["required"] = {
            "clip_name": [files["clip_name"]],
            "type": [["stable_diffusion", *clip_types]],
        }
    if "VAELoader" in info:
        # The COMBO shape newer nodes use, to cover both parsers.
        info["VAELoader"]["input"]["required"] = {
            "vae_name": ["COMBO", {"options": files["vae_name"]}]
        }
    return info


def sdxl_object_info(
    *,
    checkpoints: Iterable[str] = ("juggernaut.safetensors",),
    loras: Iterable[str] = ("detail.safetensors",),
    vaes: Iterable[str] = ("sdxl_vae.safetensors",),
    missing_class: str = "",
) -> dict:
    """``/object_info`` of the pinned runtime for the SDXL graph (PR-IMG-COMFY-381); combos are the legacy shape."""

    from src.image_backends.comfy_image_graphs import SDXL_T2I

    info: dict[str, Any] = {
        name: {"input": {"required": {}}}
        for name in SDXL_T2I.required_node_classes
        if name != missing_class
    }
    combos = {
        "CheckpointLoaderSimple": {"ckpt_name": [list(checkpoints)]},
        "LoraLoader": {"lora_name": [list(loras)]},
        "VAELoader": {"vae_name": [list(vaes)]},
        "KSampler": {
            "sampler_name": [["euler", "euler_ancestral", "dpmpp_2m", "dpmpp_sde"]],
            "scheduler": [["normal", "karras", "simple", "beta"]],
        },
    }
    for node_class, required in combos.items():
        if node_class in info:
            info[node_class]["input"]["required"] = required
    return info


def system_stats(*, vram_free: int = 11 * GIB, ram_free: int = 20 * GIB) -> dict:
    return {
        "system": {
            "comfyui_version": "0.38.0",
            "python_version": "3.13.16 (main)",
            "pytorch_version": "2.14.0+cu130",
            "ram_total": 32 * GIB,
            "ram_free": ram_free,
        },
        "devices": [
            {
                "name": "cuda:0 NVIDIA GeForce RTX 4070 Ti",
                "vram_total": 12 * GIB,
                "vram_free": vram_free,
            }
        ],
    }


def history_done(prompt_id: str, filename: str = "stablenew_00001_.png") -> dict:
    return {
        prompt_id: {
            "status": {"status_str": "success", "completed": True},
            "outputs": {
                SAVE_NODE_ID: {
                    "images": [
                        {"filename": filename, "subfolder": "stablenew/job", "type": "output"}
                    ]
                }
            },
        }
    }


class FakeComfyClient:
    """In-memory ``ComfyApiClient``: records calls; history is scripted per poll."""

    def __init__(
        self,
        *,
        info: dict | None = None,
        stats: dict | None = None,
        history: list[Any] | None = None,
        queue_state: str | None = "running",
        image_size: tuple[int, int] | None = None,
        output_count: int = 1,
        queue_error: Exception | None = None,
        echo_prompt_id: bool = True,
    ) -> None:
        self.info = object_info() if info is None else info
        self.stats = system_stats() if stats is None else stats
        self.history = history
        self.queue_state = queue_state
        self.image_size = image_size
        self.output_count = output_count
        self.queue_error = queue_error
        self.echo_prompt_id = echo_prompt_id
        self.payloads: list[dict[str, Any]] = []
        self.interrupted: list[str] = []
        self.deleted: list[list[str]] = []
        self.downloads: list[tuple[str, str, str]] = []
        self.history_calls = 0

    @property
    def prompt_id(self) -> str:
        return str(self.payloads[-1]["prompt_id"]) if self.payloads else ""

    def get_object_info(self) -> dict:
        return self.info

    def get_system_stats(self) -> dict:
        return self.stats

    def queue_prompt(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        if self.queue_error is not None:
            raise self.queue_error
        return {"prompt_id": payload["prompt_id"] if self.echo_prompt_id else "", "number": 1}

    def get_history(self, prompt_id: str) -> dict:
        self.history_calls += 1
        if self.history is None:
            done = history_done(prompt_id)
            images = done[prompt_id]["outputs"][SAVE_NODE_ID]["images"]
            done[prompt_id]["outputs"][SAVE_NODE_ID]["images"] = (images * self.output_count)[
                : self.output_count
            ]
            return done
        item = self.history.pop(0) if len(self.history) > 1 else self.history[0]
        return item(prompt_id) if callable(item) else item

    def get_queue(self) -> dict:
        entry = [1, self.prompt_id, {}, {}, []]
        if self.queue_state == "running":
            return {"queue_running": [entry], "queue_pending": []}
        if self.queue_state == "pending":
            return {"queue_running": [], "queue_pending": [entry]}
        return {"queue_running": [], "queue_pending": []}

    def interrupt(self, prompt_id: str | None = None) -> None:
        self.interrupted.append(str(prompt_id))

    def delete_from_queue(self, prompt_ids: list[str]) -> None:
        self.deleted.append(list(prompt_ids))

    def download_view(
        self, filename: str, destination: Any, *, subfolder: str = "", file_type: str = "output"
    ) -> Path:
        self.downloads.append((filename, subfolder, file_type))
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.payloads[-1]["prompt"]
        size = self.image_size or (
            payload["6"]["inputs"]["width"],
            payload["6"]["inputs"]["height"],
        )
        Image.new("RGB", size, (40, 80, 120)).save(target)
        return target


class FakeManager:
    """``ComfyProcessManager`` stand-in: owns a process once ``ensure_running`` succeeds."""

    def __init__(
        self, *, autostart: bool = True, external: bool = False, healthy: bool = True
    ) -> None:
        self.config = SimpleNamespace(
            autostart_enabled=autostart, base_url="http://127.0.0.1:8188/"
        )
        self.external = external
        self.healthy = healthy
        self.running = False
        self.stops = 0
        self.starts = 0
        self.required: list[tuple[str, ...]] = []

    @property
    def owns_process(self) -> bool:
        return self.running

    @property
    def pid(self) -> int | None:
        return 4321 if self.running else None

    def is_running(self) -> bool:
        return self.running

    def ensure_running(self, *, required_flags: tuple[str, ...] = ()) -> bool:
        from src.video.comfy_process_manager import ComfyStartupError

        self.required.append(tuple(required_flags))
        if self.external:
            raise ComfyStartupError(
                "Cannot launch managed ComfyUI: a healthy external ComfyUI is already serving; refusing to adopt"
            )
        if not self.running and self.healthy:
            self.starts += 1
        self.running = self.healthy
        return self.healthy

    def stop(self) -> None:
        self.stops += 1
        self.running = False


class FakeTransition:
    def __init__(self, status: RuntimeTransitionStatus = RuntimeTransitionStatus.READY) -> None:
        self.status = status
        self.targets: list[str] = []

    def prepare_for(self, target: str) -> RuntimeTransitionResult:
        self.targets.append(target)
        blocked = self.status is not RuntimeTransitionStatus.READY
        return RuntimeTransitionResult(
            target=target,
            conflicts_observed=("forge_webui",),
            ownership_state={
                "forge_webui": RuntimeOwnershipState.EXTERNAL
                if blocked
                else RuntimeOwnershipState.OWNED
            },
            releases_attempted=("forge_webui",),
            releases_completed=() if blocked else ("forge_webui",),
            status=self.status,
            blockers=("external Forge WebUI on port 7860",) if blocked else (),
        )


class Token:
    def __init__(self, cancelled: bool = False, after_polls: int | None = None) -> None:
        self.cancelled = cancelled
        self.after_polls = after_polls
        self.polls = 0

    def is_cancelled(self) -> bool:
        self.polls += 1
        if self.after_polls is not None and self.polls > self.after_polls:
            return True
        return self.cancelled


class Pipeline:
    def __init__(self) -> None:
        self.statuses: list[dict[str, Any]] = []

    def _emit_status_update(self, status: dict[str, Any]) -> None:
        self.statuses.append(status)


def small_profile(profile: Any) -> Any:
    """The profile with tiny stand-in assets (same names and folders) whose bytes a test can write for real."""

    import hashlib
    from dataclasses import replace

    def small(asset: Any) -> Any:
        content = asset.filename.encode("utf-8")
        return replace(asset, size=len(content), sha256=hashlib.sha256(content).hexdigest())

    return replace(
        profile,
        diffusion_model=small(profile.diffusion_model),
        text_encoder=small(profile.text_encoder),
        vae=small(profile.vae),
    )


def install(
    root: Path, profiles: Iterable[Any], *, corrupt: str = "", truncate: str = ""
) -> dict[str, list[Path]]:
    """Write each (small) profile's assets into temp Comfy model folders; ``corrupt``/``truncate`` name one file."""

    folders = {"diffusion_models": [root / "diffusion_models"], "text_encoders": [root / "text_encoders"],
               "vae": [root / "vae"]}  # fmt: skip
    for profile in profiles:
        for asset in profile.assets:
            path = root / asset.folder / asset.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            content = asset.filename.encode("utf-8")
            if asset.filename == corrupt:
                content = bytes(reversed(content))
            if asset.filename == truncate:
                content = content[:-1]
            path.write_bytes(content)
    return folders
