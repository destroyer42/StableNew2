"""PR-IMG-COMFY-381: SDXL txt2img on the ComfyUI still-image backend, end to end against in-memory fakes.

Covers asset resolution by registry SHA, the graph the fake ComfyUI receives, artifacts, release on every exit and the
canonical ``run_njr`` route with ``image_backend_default = comfyui`` (no network, process, model or GPU).
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from src.assets import AssetKind
from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.image_backends import ImageBackendRegistry, ImageExecutionRequest, model_policy
from src.image_backends import image_backend_types as backend_types
from src.image_backends.comfy_image_backend import ComfyImageBackend, ComfyImageUnavailable
from src.image_backends.comfy_sdxl_assets import SdxlAssetError, SdxlAssetResolver
from src.image_backends.comfy_sdxl_profile import SdxlComfyError
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.pipeline_runner import PipelineRunner
from tests.helpers.comfy_image_fakes import (
    FakeComfyClient,
    FakeManager,
    FakeTransition,
    Pipeline,
    Token,
    sdxl_object_info,
)

CKPT, LORA, VAE = "juggernaut.safetensors", "detail.safetensors", "sdxl_vae.safetensors"
SDXL_LOOKUP = Mock(
    return_value=CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ())
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeRegistry:
    """The ``AssetRegistry`` surface the resolver reads: persisted records by kind, never a scan."""

    def __init__(self, entries: dict[AssetKind, list[tuple[Path, str]]]) -> None:
        self._entries = entries

    def cached_snapshot(self) -> FakeRegistry:
        return self

    def records_for(self, kind: AssetKind) -> tuple[Any, ...]:
        return tuple(
            SimpleNamespace(sha256=sha, locations=(SimpleNamespace(path=path, kind=kind),))
            for path, sha in self._entries.get(kind, ())
        )

    def verified_sha256(self, path: Path) -> str | None:
        return None


class Models:
    """Registry-scanned (Forge) files plus the ComfyUI folders that may or may not see them."""

    def __init__(
        self, tmp_path: Path, *, comfy_sees: bool = True, comfy_differs: bool = False
    ) -> None:
        self.forge = tmp_path / "forge"
        self.comfy = tmp_path / "comfy"
        self.contents = {
            "checkpoints": (CKPT, b"ckpt-bytes"),
            "loras": (LORA, b"lora-bytes"),
            "vae": (VAE, b"vae-bytes"),
        }
        entries: dict[AssetKind, list[tuple[Path, str]]] = {}
        for folder, kind in (
            ("checkpoints", AssetKind.CHECKPOINT),
            ("loras", AssetKind.LORA),
            ("vae", AssetKind.VAE),
        ):
            name, data = self.contents[folder]
            source = self.forge / folder / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(data)
            entries[kind] = [(source, _sha(data))]
            if comfy_sees:
                visible = self.comfy / folder / name
                visible.parent.mkdir(parents=True, exist_ok=True)
                visible.write_bytes(data + b"-different" if comfy_differs else data)
        self.registry = FakeRegistry(entries)

    def resolver(self) -> SdxlAssetResolver:
        folders = {kind: [self.comfy / kind] for kind in self.contents}
        return SdxlAssetResolver(
            registry=self.registry,
            folders=lambda: folders,
            hasher=lambda path: _sha(path.read_bytes()),
        )


def make_backend(
    tmp_path: Path, models: Models | None = None, client: FakeComfyClient | None = None, **kw: Any
):
    models = models or Models(tmp_path)
    client = client or FakeComfyClient(info=sdxl_object_info())
    manager, transition = FakeManager(), FakeTransition()
    ticks = iter(range(0, 1_000_000))
    jobs = tmp_path / "jobs"
    jobs.mkdir(exist_ok=True)
    backend = ComfyImageBackend(
        transition=transition,
        process_manager=manager,
        client_factory=lambda base_url: client,
        clock=lambda: float(next(ticks)),
        sleep=lambda seconds: None,
        rng=random.Random(5),
        temp_root=str(jobs),
        poll_seconds=0,
        family_lookup=SDXL_LOOKUP,
        sdxl_assets=models.resolver(),
        **kw,
    )
    return backend, client, manager, transition


def request(tmp_path: Path, **changes: Any) -> ImageExecutionRequest:
    values: dict[str, Any] = {
        "backend_id": "comfyui",
        "stage_name": "txt2img",
        "stage_config": {"model": CKPT, "clip_skip": 2},
        "output_dir": tmp_path / "run" / "txt2img",
        "image_name": "txt2img_p01",
        "prompt": "a castle on a hill <lora:detail:0.8>",
        "negative_prompt": "blurry, lowres",
        "selected_model": CKPT,
        "sampler": "Euler a",
        "scheduler": "Karras",
        "steps": 24,
        "cfg_scale": 6.5,
        "width": 1024,
        "height": 768,
        "seed": 1234,
        "image_count": 1,
        "job_id": "job-s1",
        "backend_options": {"image": {"backend_id": "comfyui"}},
        "cancel_token": Token(),
        "selected_vae": VAE,
    }
    values.update(changes)
    return ImageExecutionRequest(**values)


def test_sdxl_txt2img_runs_end_to_end_with_the_mapped_graph_and_full_provenance(
    tmp_path: Path,
) -> None:
    backend, client, manager, transition = make_backend(tmp_path)

    result = backend.execute(Pipeline(), request(tmp_path))

    assert result is not None and Path(result.output_paths[0]).is_file()
    assert transition.targets == ["comfy"] and manager.stops == 1
    graph = client.payloads[0]["prompt"]
    assert graph["1"]["inputs"]["ckpt_name"] == CKPT
    assert graph["20"]["inputs"] == {
        "model": ["1", 0], "clip": ["1", 1], "lora_name": LORA, "strength_model": 0.8, "strength_clip": 0.8,
    }  # fmt: skip
    assert graph["3"]["inputs"]["stop_at_clip_layer"] == -2
    assert graph["4"]["inputs"]["text"] == "a castle on a hill"
    assert graph["5"]["inputs"]["text"] == "blurry, lowres"
    assert graph["7"]["inputs"] | {"model": None, "positive": None, "negative": None, "latent_image": None} == {
        "model": None, "seed": 1234, "steps": 24, "cfg": 6.5, "sampler_name": "euler_ancestral",
        "scheduler": "karras", "positive": None, "negative": None, "latent_image": None, "denoise": 1.0,
    }  # fmt: skip
    assert graph["6"]["inputs"] == {"width": 1024, "height": 768, "batch_size": 1}
    assert graph["30"]["inputs"]["vae_name"] == VAE
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assets = manifest["comfy_sdxl"]["assets"]
    assert assets["checkpoint"]["sha256"] == _sha(b"ckpt-bytes")
    assert assets["loras"][0]["weight"] == 0.8 and assets["vae"]["sha256"] == _sha(b"vae-bytes")
    assert manifest["comfy_sdxl"]["graph"]["graph_id"] == "sdxl_t2i"
    assert any("Karras" in item for item in manifest["comfy_sdxl"]["approximations"])
    assert (
        manifest["final_negative_prompt"] == "blurry, lowres"
        and manifest["config"]["sampler_name"] == "Euler a"
    )
    assert result.backend_metadata["runtime_release"]["released"] is True


def test_the_owned_comfy_is_released_when_the_dispatch_fails(tmp_path: Path) -> None:
    backend, client, manager, _ = make_backend(
        tmp_path, client=FakeComfyClient(info=sdxl_object_info(), queue_error=RuntimeError("boom"))
    )

    with pytest.raises(RuntimeError, match="boom"):
        backend.execute(Pipeline(), request(tmp_path))

    assert manager.stops == 1 and len(client.payloads) == 1


def test_a_file_comfy_cannot_see_is_refused_before_the_gpu_lease_with_configuration_guidance(
    tmp_path: Path,
) -> None:
    backend, client, manager, transition = make_backend(
        tmp_path, Models(tmp_path, comfy_sees=False)
    )

    with pytest.raises(SdxlAssetError, match="extra_model_paths.yaml"):
        backend.execute(Pipeline(), request(tmp_path))

    assert transition.targets == [] and manager.running is False and client.payloads == []


def test_a_comfy_file_with_a_different_sha_is_never_used(tmp_path: Path) -> None:
    backend, client, _, _ = make_backend(tmp_path, Models(tmp_path, comfy_differs=True))

    with pytest.raises(SdxlAssetError, match="different SHA-256"):
        backend.execute(Pipeline(), request(tmp_path))

    assert client.payloads == []


def test_a_model_the_registry_does_not_know_is_refused(tmp_path: Path) -> None:
    models = Models(tmp_path)
    models.registry = FakeRegistry({})
    backend, client, *_ = make_backend(tmp_path, models)

    with pytest.raises(SdxlAssetError, match="not in the asset registry"):
        backend.execute(Pipeline(), request(tmp_path))

    assert client.payloads == []


def test_a_file_the_running_comfy_does_not_list_is_unavailable_and_nothing_is_queued(
    tmp_path: Path,
) -> None:
    backend, client, manager, _ = make_backend(
        tmp_path, client=FakeComfyClient(info=sdxl_object_info(checkpoints=["other.safetensors"]))
    )

    with pytest.raises(ComfyImageUnavailable, match=f"does not list '{CKPT}'"):
        backend.execute(Pipeline(), request(tmp_path))

    assert client.payloads == [] and manager.stops == 1


def test_a_non_sdxl_model_is_refused_with_switch_guidance_and_never_falls_back(
    tmp_path: Path,
) -> None:
    backend, client, *_ = make_backend(tmp_path)
    backend._family_lookup = Mock(
        return_value=CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SD1, ())
    )

    with pytest.raises(SdxlComfyError, match="switch the Image backend to Forge"):
        backend.execute(Pipeline(), request(tmp_path))

    assert client.payloads == []


def test_cancellation_before_dispatch_queues_nothing(tmp_path: Path) -> None:
    from src.controller.runtime_state import CancellationError

    backend, client, *_ = make_backend(tmp_path)

    with pytest.raises(CancellationError):
        backend.execute(Pipeline(), request(tmp_path, cancel_token=Token(cancelled=True)))

    assert client.payloads == []


def test_the_negative_prompt_capability_is_declared() -> None:
    assert ComfyImageBackend.capabilities.supports_negative_prompt is True


# -- the canonical route ------------------------------------------------------------------------------------------------


class _NoWebUIPipeline:
    def __init__(self) -> None:
        self.client = None

    def _begin_run_metrics(self) -> None:
        return None

    def get_run_efficiency_metrics(self, _variant_count: int) -> dict[str, object]:
        return {}


@pytest.fixture
def comfy_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend_types, "configured_image_backend_id", lambda: "comfyui")
    monkeypatch.setattr(model_policy, "RegistryFamilyLookup", lambda *a, **k: SDXL_LOOKUP)


def _config(**changes: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "model": CKPT, "prompt": "a lighthouse at dusk", "negative_prompt": "blurry", "seed": 5, "width": 1024,
        "height": 1024, "steps": 20, "cfg_scale": 6.0, "sampler_name": "Euler", "scheduler": "Automatic",
        "prompt_optimizer": {"enabled": False},
    }  # fmt: skip
    config.update(changes)
    return config


def test_with_the_comfy_default_an_sdxl_job_compiles_for_comfyui_and_runs_through_run_njr(
    tmp_path: Path, comfy_default: None
) -> None:
    record = JobBuilderV2(time_fn=lambda: 1, id_fn=lambda: "sdxl-e2e").build_jobs(
        base_config=_config()
    )[0]
    assert record.backend_options["image"]["backend_id"] == "comfyui"
    assert "model_profile" not in record.backend_options["image"]

    backend, client, manager, _ = make_backend(tmp_path)
    registry = ImageBackendRegistry()
    registry.register(backend)
    webui = Mock()
    runner = PipelineRunner(
        webui, Mock(), runs_base_dir=str(tmp_path / "runs"), image_backend_registry=registry
    )
    runner._pipeline = _NoWebUIPipeline()

    result = runner.run_njr(record)

    assert result.success is True, result.error
    assert result.metadata["image_backend_id"] == "comfyui"
    graph = client.payloads[0]["prompt"]
    assert graph["7"]["inputs"]["seed"] == 5 and graph["7"]["inputs"]["sampler_name"] == "euler"
    assert (
        graph["7"]["inputs"]["scheduler"] == "normal" and graph["5"]["inputs"]["text"] == "blurry"
    )
    assert webui.method_calls == [] and manager.stops == 1


@pytest.mark.parametrize(
    ("changes", "message"),
    [({"enable_hr": True}, "enable_hr is unsupported"), ({"sampler_name": "Mystery"}, "Mystery")],
)
def test_unsupported_work_is_refused_at_compile_time_with_the_comfy_default(
    comfy_default: None, changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(SdxlComfyError, match=message):
        JobBuilderV2(time_fn=lambda: 1, id_fn=lambda: "refused").build_jobs(
            base_config=_config(**changes)
        )


def test_a_model_the_registry_cannot_classify_is_refused_at_compile_time_with_the_comfy_default(
    comfy_default: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        model_policy, "RegistryFamilyLookup", lambda *a, **k: Mock(return_value=None)
    )
    with pytest.raises(SdxlComfyError, match="not a registry-classified SDXL checkpoint"):
        JobBuilderV2(time_fn=lambda: 1, id_fn=lambda: "refused").build_jobs(base_config=_config())


def test_the_default_setting_leaves_the_forge_route_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backend_types, "configured_image_backend_id", lambda: "forge_webui")
    record = JobBuilderV2(time_fn=lambda: 1, id_fn=lambda: "forge").build_jobs(
        base_config=_config()
    )[0]
    assert record.backend_options["image"]["backend_id"] == "forge_webui"
