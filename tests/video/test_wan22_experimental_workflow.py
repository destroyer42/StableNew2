"""PR-VID-130: Wan2.2 TI2V-5B experimental workflow, governance, readiness and dependency proof.

Fake Comfy client only: no GPU, no model, no process. ``queue_prompt`` must never be reached when
governance, dependency or resource readiness blocks the job.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.video import ComfyWorkflowVideoBackend, VideoExecutionRequest
from src.video.comfy_dependency_probe import ComfyDependencyProbe
from src.video.video_backend_registry import VideoBackendRegistry
from src.video.video_backend_types import (
    CONTROL_CONTROL_VIDEO,
    CONTROL_END_ANCHOR,
    CONTROL_NEGATIVE_PROMPT,
    CONTROL_POSE_VIDEO,
    CONTROL_PROMPT_TEXT,
    CONTROL_SOURCE_IMAGE,
)
from src.video.video_execution_resolver import VideoContractError, VideoExecutionResolver
from src.video.workflow_catalog import WAN22_MODEL_FILES, WAN22_STOCK_NODES
from src.video.workflow_compiler import WorkflowCompiler
from src.video.workflow_contracts import WorkflowSpec
from src.video.workflow_readiness import WorkflowResourceReadiness
from src.video.workflow_registry import WorkflowRegistry, build_default_workflow_registry

WAN_ID = "wan22_ti2v_5b_i2v_v1"
MIB = 1024 * 1024


def _wan_spec() -> WorkflowSpec:
    return build_default_workflow_registry().get(WAN_ID, allow_experimental=True)


def _object_info(*, missing_node: str | None = None, files: dict[str, str] | None = None):
    info = {node: {"input": {"required": {}}} for node in WAN22_STOCK_NODES if node != missing_node}
    loaders = {"UNETLoader": "unet_name", "CLIPLoader": "clip_name", "VAELoader": "vae_name"}
    for _id, filename, hint, _digest in WAN22_MODEL_FILES:
        loader, _, input_name = hint.partition(".")
        if missing_node == loader:
            continue
        choice = (files or {}).get(loader, filename)
        info[loader] = {"input": {"required": {loaders[loader]: [[choice]]}}}
    return info


def _stats(*, free_mib: float, held_mib: float = 0.0, total_mib: float = 12282.0):
    # Comfy's own vram_free is not what the guard trusts; the driver probe below is.
    return {
        "devices": [
            {
                "type": "cuda",
                "index": 0,
                "vram_total": total_mib * MIB,
                "vram_free": free_mib * MIB,
                "torch_vram_total": held_mib * MIB,
                "torch_vram_free": 0,
                "_driver_free_mib": free_mib,
            }
        ]
    }


def _driver_probe(stats):
    device = stats["devices"][0]
    return lambda _index: (device["vram_total"] / MIB, device["_driver_free_mib"])


def _readiness(stats, *, ram_gb: float = 24.0) -> WorkflowResourceReadiness:
    return WorkflowResourceReadiness(ram_probe=lambda: ram_gb, gpu_probe=_driver_probe(stats))


class _FakeComfy:
    def __init__(self, tmp: Path, *, info=None, stats=None) -> None:
        self.info = info if info is not None else _object_info()
        self.stats = stats if stats is not None else _stats(free_mib=11000)
        self.queued: list[dict] = []
        self.tmp = tmp

    def get_object_info(self, **_kw):
        return self.info

    def get_system_stats(self, **_kw):
        return self.stats

    def upload_image(self, path, **_kw):
        return {"name": Path(path).name, "subfolder": ""}

    def queue_prompt(self, payload, **_kw):
        self.queued.append(payload)
        return {"prompt_id": "p-1"}

    def get_history(self, prompt_id=None, **_kw):
        entry = {
            "outputs": {
                "12": {
                    "images": [
                        {
                            "filename": "wan22_job_00001_.mp4",
                            "subfolder": "stablenew",
                            "type": "output",
                        }
                    ],
                    "animated": [True],
                }
            },
            "status": {"status_str": "success", "completed": True},
        }
        return {prompt_id: entry}

    def download_view(self, filename, destination, *, subfolder="", file_type="output", **_kw):
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(b"fake-mp4")
        return Path(destination)


def _backend(client, *, ram_gb: float = 24.0) -> ComfyWorkflowVideoBackend:
    return ComfyWorkflowVideoBackend(
        client=client,
        process_manager=SimpleNamespace(
            ensure_running=lambda: True, _config=SimpleNamespace(base_url="http://x")
        ),
        readiness=_readiness(client.stats, ram_gb=ram_gb),
    )


def _request(tmp: Path, *, opt_in: bool, seed: int = 7) -> VideoExecutionRequest:
    source = tmp / "source.png"
    source.write_bytes(b"png")
    return VideoExecutionRequest(
        backend_id="comfy",
        stage_name="video_workflow",
        stage_config={"workflow_id": WAN_ID, "workflow_version": "1.0.0", "seed": seed},
        output_dir=tmp / "run",
        input_image_path=source,
        prompt="the person waves",
        negative_prompt="blurry",
        job_id="job-1",
        workflow_id=WAN_ID,
        workflow_version="1.0.0",
        requested_controls=(CONTROL_SOURCE_IMAGE, CONTROL_PROMPT_TEXT, CONTROL_NEGATIVE_PROMPT),
        experimental_opt_in=opt_in,
    )


# ------------------------------------------------------------------ identity / governance


def test_wan_is_registered_as_experimental_with_exact_pins_and_no_extra_controls() -> None:
    spec = _wan_spec()
    assert spec.governance_state == "experimental" and spec.is_experimental
    assert spec.backend_id == "comfy" and spec.workflow_version == "1.0.0"
    assert spec.pinned_revision == "catalog:wan22_ti2v_5b_i2v_v1@1.0.0"
    assert set(spec.required_input_names) == {"source_image", "prompt", "seed"}  # no end anchor
    assert "end_anchor" not in spec.declared_input_names
    assert set(spec.accepted_controls) == {"source_image", "prompt_text", "negative_prompt"}
    assert not {CONTROL_CONTROL_VIDEO, CONTROL_POSE_VIDEO, CONTROL_END_ANCHOR} & set(
        spec.accepted_controls
    )
    files = {d.locator for d in spec.dependency_specs if d.dependency_kind == "model_file"}
    assert files == {
        "wan2.2_ti2v_5B_fp16.safetensors",
        "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "wan2.2_vae.safetensors",
    }
    nodes = {d.locator for d in spec.dependency_specs if d.dependency_kind == "stock_node"}
    assert nodes == set(WAN22_STOCK_NODES)
    provenance = spec.backend_defaults["provenance"]
    assert provenance["upstream_revision"] == "c4f60d30c55a624e35427060fdd217579a6c1d77"
    assert provenance["files"]["wan2.2_vae.safetensors"].startswith("e40321bd36b97099")


def test_experimental_needs_opt_in_and_disabled_never_runs() -> None:
    registry = build_default_workflow_registry()
    with pytest.raises(KeyError, match="explicit experimental opt-in"):
        registry.get(WAN_ID)
    assert registry.get(WAN_ID, allow_experimental=True).is_experimental
    assert WAN_ID not in [s.workflow_id for s in registry.list_specs_for_backend("comfy")]
    assert WAN_ID in [s.workflow_id for s in registry.list_offerable_specs("comfy")]

    disabled = WorkflowRegistry()
    off = _wan_spec()
    disabled.register(
        WorkflowSpec(
            **{
                **{f: getattr(off, f) for f in off.__dataclass_fields__},
                "workflow_id": "wan_off",
                "governance_state": "disabled",
            }
        )
    )
    with pytest.raises(KeyError, match="not approved"):
        disabled.get("wan_off", allow_experimental=True)  # opt-in cannot override disabled
    assert disabled.list_offerable_specs("comfy") == []


def test_graph_is_the_qualified_stock_graph_not_a_redesign(tmp_path: Path) -> None:
    from tools.qualification.vid110.workflows import GenerationSpec, build_lane_a

    spec = _wan_spec()
    request = _request(tmp_path, opt_in=True, seed=12345)
    request.negative_prompt = spec.backend_defaults["default_negative_prompt"]
    compiled = WorkflowCompiler().compile(spec, request)
    produced = compiled.backend_payload["prompt"]
    qualified = build_lane_a(
        GenerationSpec(
            prompt=request.prompt,
            negative=request.negative_prompt,
            width=480,
            height=832,
            length=49,
            fps=24.0,
            steps=20,
            cfg=5.0,
            shift=8.0,
            seed=12345,
        ),
        str(request.input_image_path),
        prefix="stablenew/wan22_job-1",
    )
    assert produced == qualified  # node ids, classes, links and every literal are identical


# ------------------------------------------------------------------------- dependency probe


def test_dependency_probe_names_missing_files_nodes_and_unverifiable_loaders() -> None:
    spec = _wan_spec()
    probe = ComfyDependencyProbe()
    assert probe.probe_workflow(spec, object_info=_object_info()).ready
    wrong_file = probe.probe_workflow(
        spec, object_info=_object_info(files={"UNETLoader": "wan2.2_ti2v_5B_fp8.safetensors"})
    )
    assert wrong_file.missing_required == ("wan22_unet",)  # exact pinned file, no substitute
    node = probe.probe_workflow(
        spec, object_info=_object_info(missing_node="Wan22ImageToVideoLatent")
    )
    assert node.missing_required == ("node_wan22imagetovideolatent",)
    no_loader = probe.probe_workflow(spec, object_info=_object_info(missing_node="VAELoader"))
    assert {"wan22_vae", "node_vaeloader"} <= set(no_loader.missing_required)  # never assumed


# ---------------------------------------------------------------------- resource readiness


def test_readiness_uses_driver_free_vram_plus_comfy_held_and_reports_what_blocks() -> None:
    spec = _wan_spec()
    ok_stats = _stats(free_mib=10500)
    ok = _readiness(ok_stats).evaluate(spec, system_stats=ok_stats)
    assert ok.ready and ok.observations["vram_available_to_comfy_mib"] == 10500
    warm_stats = _stats(free_mib=600, held_mib=10200)
    assert _readiness(warm_stats).evaluate(spec, system_stats=warm_stats).ready  # warm Comfy ok
    blocked_stats = _stats(free_mib=6000, held_mib=100)
    blocked = _readiness(blocked_stats).evaluate(spec, system_stats=blocked_stats)
    assert not blocked.ready and "A1111" in blocked.message and "will not stop" in blocked.message
    low_ram = _readiness(ok_stats, ram_gb=9.0).evaluate(spec, system_stats=ok_stats)
    assert not low_ram.ready and "system RAM" in low_ram.message
    no_gpu = _readiness(ok_stats).evaluate(spec, system_stats={"devices": []})
    assert not no_gpu.ready and "no CUDA device" in no_gpu.message
    ltx = build_default_workflow_registry().get("ltx_multiframe_anchor_v1")
    assert _readiness(ok_stats).evaluate(ltx, system_stats={}).ready  # only declared policies


def test_comfys_own_free_figure_is_not_trusted_and_an_unreadable_driver_fails_closed() -> None:
    """Observed live: Comfy said 11,056 MiB free while A1111 held 7,259 MiB (driver: 3,298 free)."""

    spec = _wan_spec()
    lying = _stats(free_mib=11056)  # what /system_stats claimed
    driver_truth = WorkflowResourceReadiness(
        ram_probe=lambda: 24.0, gpu_probe=lambda _i: (12282.0, 3298.0)
    )
    result = driver_truth.evaluate(spec, system_stats=lying)
    assert not result.ready  # the unsafe pass a Comfy-stats guard would have given
    assert result.observations["comfy_reported_free_mib"] == 11056
    assert result.observations["vram_free_mib"] == 3298
    unreadable = WorkflowResourceReadiness(ram_probe=lambda: 24.0, gpu_probe=lambda _i: None)
    closed = unreadable.evaluate(spec, system_stats=lying)
    assert not closed.ready and "could not be read" in closed.message


# ------------------------------------------------- resolver + backend, fail before queue_prompt


def test_success_compiles_the_wan_graph_and_returns_a_canonical_local_artifact(tmp_path) -> None:
    client = _FakeComfy(tmp_path)
    result = _backend(client).execute(SimpleNamespace(), _request(tmp_path, opt_in=True))
    [payload] = client.queued
    prompt = payload["prompt"]
    assert prompt["9"]["inputs"]["seed"] == 7 and prompt["7"]["inputs"]["image"] == "source.png"
    assert prompt["12"]["inputs"]["filename_prefix"] == "stablenew/wan22_job-1"
    assert result is not None and result.primary_path.endswith("wan22_job_00001_.mp4")
    assert Path(result.primary_path).parent == tmp_path / "run"  # StableNew owns the artifact
    assert Path(result.primary_path).is_file()
    assert result.artifact["stage"] == "video_workflow"
    assert result.diagnostic_payload["resource_readiness"]["ready"] is True


@pytest.mark.parametrize(
    ("client_kwargs", "opt_in", "ram", "fragment"),
    [
        ({}, False, 24.0, "explicit experimental opt-in"),
        (
            {"info": _object_info(files={"CLIPLoader": "other.safetensors"})},
            True,
            24.0,
            "wan22_text_encoder",
        ),
        ({"info": _object_info(missing_node="KSampler")}, True, 24.0, "node_ksampler"),
        ({"stats": _stats(free_mib=5000)}, True, 24.0, "not resource-ready"),
        ({}, True, 4.0, "not resource-ready"),
    ],
)
def test_governance_dependency_and_readiness_fail_before_queue_prompt(
    tmp_path, client_kwargs, opt_in, ram, fragment
) -> None:
    client = _FakeComfy(tmp_path, **client_kwargs)
    with pytest.raises((RuntimeError, KeyError), match=fragment):
        _backend(client, ram_gb=ram).execute(SimpleNamespace(), _request(tmp_path, opt_in=opt_in))
    assert client.queued == []  # nothing dispatched, nothing stopped or restarted


def test_resolver_rejects_wan_without_opt_in_and_unsupported_controls_before_dispatch(
    tmp_path,
) -> None:
    backend = _backend(_FakeComfy(tmp_path))
    registry = VideoBackendRegistry()
    registry.register(backend)
    resolver = VideoExecutionResolver(registry)

    def intent(controls, *, opt_in):
        config = {
            "video_execution": {
                "backend_id": "comfy",
                "task": "image_to_video",
                "controls": list(controls),
                "workflow_id": WAN_ID,
                "workflow_version": "1.0.0",
                "experimental_opt_in": opt_in,
            },
        }
        return config, resolver.build_intent("video_workflow", config, has_source_image=True)

    for controls, opt_in, fragment in (
        ([CONTROL_PROMPT_TEXT], False, "experimental"),
        ([CONTROL_END_ANCHOR], True, "does not declare"),
        ([CONTROL_POSE_VIDEO], True, "does not declare"),
    ):
        config, resolved = intent(controls, opt_in=opt_in)
        request = _request(tmp_path, opt_in=False)
        request.stage_config = config
        with pytest.raises(VideoContractError, match=fragment) as caught:
            resolver.apply(request, resolved)
        assert caught.value.code == "invalid_workflow"
    config, resolved = intent([CONTROL_PROMPT_TEXT], opt_in=True)
    request = _request(tmp_path, opt_in=False)
    request.stage_config = config
    resolver.apply(request, resolved)
    assert request.experimental_opt_in is True and request.backend_id == "comfy"
