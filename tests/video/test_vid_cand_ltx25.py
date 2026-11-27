"""VID-CAND-LTX25: the experimental LTX-2.5 distilled I2V candidate specs.

Deterministic and GPU-free: a fake Comfy client and fake managed runtime, no model, no process, no generation.  It
proves both specs are registered, gated, pinned and wired as declared, that the audio-off graph carries no audio node
and the audio-on graph routes the audio latent through both stages, and that readiness and the dependency probe refuse
before any queue call.  It demonstrates no speed, quality, audio or resource envelope, and not that the real ComfyUI
accepts the graph.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.video_workflow_controller import VideoWorkflowController
from src.video.comfy_dependency_probe import ComfyDependencyProbe
from src.video.workflow_catalog_ltx25 import (
    LTX25_AUDIO_ID,
    LTX25_AUDIO_STOCK_NODES,
    LTX25_FRAME_COUNT_POLICY,
    LTX25_ID,
    LTX25_IDS,
    LTX25_MODEL_FILES,
    LTX25_REPO,
    LTX25_REVISION,
    LTX25_STOCK_NODES,
    LTX25_VERSION,
)
from src.video.workflow_catalog_wan_a14b import WAN_A14B_ID, WAN_A14B_VERSION
from src.video.workflow_compiler import WorkflowCompiler
from src.video.workflow_frame_count import frame_count_projection, legal_frame_counts
from src.video.workflow_picker import recommended_workflow_id
from src.video.workflow_registry import build_default_workflow_registry
from tests.video.test_vid_clip_370_candidate_specs import (
    _a14b_backend,
    _a14b_request,
    _fake_export,
    _FramesFake,
)
from tests.video.test_wan22_experimental_workflow import _FakeComfy, _stats

FRAMES = 25  # the fake run's frame count; the catalog default is 121
SAVE_FRAMES_NODE = "25"
AUDIO_FILE = "ltx-2.5-audio-vae-bf16.safetensors"
NODES = {LTX25_ID: LTX25_STOCK_NODES, LTX25_AUDIO_ID: LTX25_AUDIO_STOCK_NODES}


def _spec(workflow_id: str):
    return build_default_workflow_registry().get(
        workflow_id, LTX25_VERSION, allow_experimental=True
    )


def _info(
    workflow_id: str = LTX25_ID, *, drop_file: str | None = None, drop_node: str | None = None
) -> dict[str, Any]:
    """What the managed ComfyUI would advertise once the files are installed."""

    info: dict[str, Any] = {node: {"input": {"required": {}}} for node in NODES[workflow_id]}
    options: dict[tuple[str, str], list[str]] = {}
    for _id, name, hint, _folder, _size, _digest in LTX25_MODEL_FILES:
        loader, input_name = hint.split(".")
        options.setdefault((loader, input_name), [])
        if name != drop_file:
            options[(loader, input_name)].append(name)
    for (loader, input_name), names in options.items():
        info[loader]["input"]["required"][input_name] = [names]
    info["CLIPLoader"]["input"]["required"]["type"] = [["stable_diffusion", "ltxv", "wan"]]
    if drop_node:
        del info[drop_node]
    return info


def _request(tmp_path: Path, workflow_id: str, *, opt_in: bool = True):
    return _a14b_request(
        tmp_path,
        workflow_id=workflow_id,
        version=LTX25_VERSION,
        width=768,
        height=1344,
        frames=FRAMES,
        opt_in=opt_in,
    )


def _compiled(workflow_id: str, tmp_path: Path) -> dict[str, Any]:
    return (
        WorkflowCompiler()
        .compile(_spec(workflow_id), _request(tmp_path, workflow_id))
        .backend_payload["prompt"]
    )


@pytest.fixture
def _no_encode(monkeypatch):
    monkeypatch.setattr("src.video.frames_out.export_image_sequence_video", _fake_export)
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.write_video_container_metadata", lambda *_a, **_k: True
    )


# --- registration, governance, picker and licence ---------------------------------------------


@pytest.mark.parametrize("workflow_id", LTX25_IDS)
def test_both_ids_are_experimental_and_refused_without_the_opt_in(workflow_id: str) -> None:
    registry = build_default_workflow_registry()
    spec = _spec(workflow_id)

    assert registry.list_versions(workflow_id) == [LTX25_VERSION]
    assert spec.governance_state == "experimental" and spec.is_experimental
    assert spec.pinned_revision == f"catalog:{workflow_id}@{LTX25_VERSION}"
    assert "(Experimental)" in spec.display_name
    assert spec.governance_notes.startswith("EXPERIMENTAL")
    assert "NOT QUALIFIED" in spec.governance_notes
    assert spec.backend_defaults["make_video_default"] is False
    with pytest.raises(KeyError, match="explicit experimental opt-in"):
        registry.get(workflow_id, LTX25_VERSION)
    runnable = {s.workflow_id for s in registry.list_specs_for_backend("comfy")}
    assert workflow_id not in runnable


def test_the_approved_a14b_stays_the_default_and_the_candidates_are_never_preselected() -> None:
    controller = VideoWorkflowController(
        app_controller=SimpleNamespace(job_service=SimpleNamespace(), output_dir="out")
    )
    listed = controller.list_workflow_specs()
    records = {r["workflow_id"]: r for r in listed}

    assert recommended_workflow_id(listed) == WAN_A14B_ID
    form = controller.build_default_form_state()
    assert (form["workflow_id"], form["workflow_version"]) == (WAN_A14B_ID, WAN_A14B_VERSION)
    for workflow_id in LTX25_IDS:
        assert records[workflow_id]["experimental"] is True
        assert records[workflow_id]["make_video_default"] is False


@pytest.mark.parametrize("workflow_id", LTX25_IDS)
def test_the_licence_restriction_is_visible_to_the_operator(workflow_id: str) -> None:
    spec = _spec(workflow_id)

    assert "sexually explicit" in spec.description
    assert "sexually explicit" in spec.governance_notes
    assert "Acceptable Use Policy" in spec.backend_defaults["provenance"]["license"]
    assert "sexually explicit" in spec.backend_defaults["operator_projection"]["fixed_settings"][
        "licence"
    ]


# --- pinned files and provenance --------------------------------------------------------------


def test_every_model_file_is_pinned_by_sha256_size_folder_revision_and_loader_input() -> None:
    names = [entry[1] for entry in LTX25_MODEL_FILES]
    assert len(set(names)) == len(names) == 5
    for dependency_id, name, hint, folder, size, digest in LTX25_MODEL_FILES:
        assert re.fullmatch(r"[0-9a-f]{64}", digest), dependency_id
        assert re.fullmatch(r"[A-Za-z]+\.[a-z_0-9]+", hint)
        assert folder in {"diffusion_models", "text_encoders", "vae", "latent_upscale_models"}
        assert name.endswith(".safetensors") and size > 0
    assert len({entry[5] for entry in LTX25_MODEL_FILES}) == 5
    assert re.fullmatch(r"[0-9a-f]{40}", LTX25_REVISION) and LTX25_REPO == "Lightricks/LTX-2.5"

    video_only = _spec(LTX25_ID).backend_defaults["provenance"]
    with_audio = _spec(LTX25_AUDIO_ID).backend_defaults["provenance"]
    assert with_audio["files"] == {entry[1]: entry[5] for entry in LTX25_MODEL_FILES}
    assert set(with_audio["files"]) - set(video_only["files"]) == {AUDIO_FILE}
    for provenance in (video_only, with_audio):
        assert provenance["upstream_revision"] == LTX25_REVISION
        assert provenance["comfyui_version"] == "0.38.0"
        assert provenance["qualification"].startswith("NOT QUALIFIED")
        assert set(provenance["file_bytes"]) == set(provenance["files"])


# The published specs are immutable once registered: a change is a new version (VIDEO_PIPELINE section 13).
# sha256 of json.dumps(spec.to_dict(), sort_keys=True, ensure_ascii=False, default=str), pinned from the first
# registration; ``test_pr_vid_196_readiness_and_guidance.py`` pins the graphs with the rest of the catalog.
PINNED_SPEC_SHA256 = {
    LTX25_ID: "be6dc00e0b69f46876807210130d6997bb201282cba5e45fd0d8dd91c76dd0a0",
    LTX25_AUDIO_ID: "b9add8800b01eaa18baea0eee5cfa5b0167b834e0d5be8146e76f7a01218bbc7",
}


@pytest.mark.parametrize("workflow_id", LTX25_IDS)
def test_the_registered_specs_are_pinned_byte_for_byte(workflow_id: str) -> None:
    text = json.dumps(
        _spec(workflow_id).to_dict(), sort_keys=True, ensure_ascii=False, default=str
    )
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == PINNED_SPEC_SHA256[workflow_id]


# --- the graphs --------------------------------------------------------------------------------


@pytest.mark.parametrize("workflow_id", LTX25_IDS)
def test_the_compiled_graph_is_a_resolved_stock_node_graph(
    tmp_path: Path, workflow_id: str
) -> None:
    graph = _compiled(workflow_id, tmp_path)

    assert {node["class_type"] for node in graph.values()} == set(NODES[workflow_id])
    assert not any("{{" in json.dumps(node) for node in graph.values())
    for node in graph.values():
        for value in node["inputs"].values():
            if isinstance(value, list):  # a link must point at a node that exists
                assert value[0] in graph
    declared = {
        d.locator for d in _spec(workflow_id).dependency_specs if d.dependency_kind == "stock_node"
    }
    assert declared == set(NODES[workflow_id])


@pytest.mark.parametrize("workflow_id", LTX25_IDS)
def test_the_two_stage_recipe_is_the_template_one(tmp_path: Path, workflow_id: str) -> None:
    graph = _compiled(workflow_id, tmp_path)

    # Stage 1 at half the frozen target, taken from the expression's integer output.
    assert graph["10"]["inputs"] == {"expression": "a/2", "values.a": 768}
    assert graph["11"]["inputs"] == {"expression": "a/2", "values.a": 1344}
    assert graph["12"]["inputs"]["width"] == ["10", 1]
    assert graph["12"]["inputs"]["height"] == ["11", 1]
    assert graph["12"]["inputs"]["length"] == FRAMES
    assert graph["9"]["inputs"]["frame_rate"] == 24
    assert graph["13"]["inputs"]["strength"] == 0.7 and graph["20"]["inputs"]["strength"] == 1.0
    assert graph["14"]["inputs"]["sampler_name"] == "euler_ancestral"
    assert len(graph["15"]["inputs"]["sigmas"].split(",")) == 9  # 8 steps
    assert len(graph["21"]["inputs"]["sigmas"].split(",")) == 4  # 3 steps
    assert graph["16"]["inputs"]["noise_seed"] == 7  # the job's seed
    assert graph["22"]["inputs"]["noise_seed"] == 42  # the template's fixed second-stage noise
    assert (graph["17"]["inputs"]["video_cfg"], graph["17"]["inputs"]["audio_cfg"]) == (1.0, 1.0)
    assert graph["19"]["class_type"] == "LTXVLatentUpsampler"
    assert graph["24"]["class_type"] == "VAEDecodeTiled"


def test_audio_off_has_no_audio_node_and_ends_in_lossless_frames(tmp_path: Path) -> None:
    graph = _compiled(LTX25_ID, tmp_path)

    classes = {node["class_type"] for node in graph.values()}
    assert not any("Audio" in c or "AV" in c for c in classes)
    assert AUDIO_FILE not in json.dumps(graph)
    assert graph["18"]["inputs"]["latent_image"] == ["13", 0]  # a video-only latent
    assert graph[SAVE_FRAMES_NODE]["class_type"] == "SaveImage"
    assert _spec(LTX25_ID).backend_defaults["output_policy"] == {"mode": "frames", "fps": 24}


def test_audio_on_carries_the_audio_latent_through_both_stages_into_the_video(
    tmp_path: Path,
) -> None:
    graph = _compiled(LTX25_AUDIO_ID, tmp_path)

    assert graph["31"]["inputs"]["frames_number"] == FRAMES
    assert graph["18"]["inputs"]["latent_image"] == ["32", 0]
    assert graph["19"]["inputs"]["samples"] == ["33", 0]  # only the video latent is upscaled
    assert graph["34"]["inputs"] == {"video_latent": ["20", 0], "audio_latent": ["33", 1]}
    assert graph["23"]["inputs"]["latent_image"] == ["34", 0]
    assert graph["24"]["inputs"]["samples"] == ["35", 0]
    assert graph["36"]["inputs"]["samples"] == ["35", 1]
    assert graph["37"]["inputs"]["audio"] == ["36", 0]
    assert graph["38"]["class_type"] == "SaveVideo"
    assert "SaveImage" not in {n["class_type"] for n in graph.values()}
    assert "output_policy" not in _spec(LTX25_AUDIO_ID).backend_defaults


# --- policies ----------------------------------------------------------------------------------


@pytest.mark.parametrize("workflow_id", LTX25_IDS)
def test_the_policies_give_five_seconds_at_24_fps_on_8n_plus_1_lengths(workflow_id: str) -> None:
    spec = _spec(workflow_id)
    defaults = spec.backend_defaults

    assert defaults["frame_count_policy"] == LTX25_FRAME_COUNT_POLICY
    legal = legal_frame_counts(spec)
    assert legal[0] == 25 and legal[-1] == 121 and all((n - 1) % 8 == 0 for n in legal)
    assert frame_count_projection(spec)["default"] == 121
    assert defaults["runtime_policy"]["required_launch_flags"] == ["--disable-pinned-memory"]
    assert defaults["resource_readiness"]["min_available_to_comfy_vram_mib"] <= 12282
    prep = defaults["source_preparation"]
    for target in ("portrait_target", "landscape_target"):
        # both edges halve to a multiple of the 32 px latent grid
        assert all(value % 64 == 0 for value in prep[target].values())


# --- dependency probe and backend runs on a fake Comfy ----------------------------------------


@pytest.mark.parametrize("workflow_id", LTX25_IDS)
def test_the_probe_accepts_a_runtime_that_advertises_everything(workflow_id: str) -> None:
    probe = ComfyDependencyProbe().probe_workflow(
        _spec(workflow_id), object_info=_info(workflow_id)
    )
    assert probe.ready


@pytest.mark.parametrize(
    ("kwargs", "missing"),
    [
        (
            {"drop_file": "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"},
            "ltx25_latent_spatial_upscaler_x2",
        ),
        ({"drop_node": "LTXVLatentUpsampler"}, "node_ltxvlatentupsampler"),
    ],
)
def test_a_missing_file_or_node_is_named_by_the_probe(kwargs: dict[str, str], missing: str) -> None:
    result = ComfyDependencyProbe().probe_workflow(
        _spec(LTX25_ID), object_info=_info(**kwargs)
    )
    assert not result.ready and missing in result.missing_required


def test_a_missing_audio_vae_blocks_only_the_audio_workflow() -> None:
    silent = ComfyDependencyProbe().probe_workflow(
        _spec(LTX25_ID), object_info=_info(drop_file=AUDIO_FILE)
    )
    audio = ComfyDependencyProbe().probe_workflow(
        _spec(LTX25_AUDIO_ID), object_info=_info(LTX25_AUDIO_ID, drop_file=AUDIO_FILE)
    )
    assert silent.ready
    assert not audio.ready and "ltx25_audio_vae" in audio.missing_required


def test_an_opted_in_silent_job_completes_through_the_frames_out_path(
    tmp_path: Path, _no_encode
) -> None:
    client = _FramesFake(tmp_path, save_node=SAVE_FRAMES_NODE, info=_info(), frames=FRAMES)

    result = _a14b_backend(client, tmp_path).execute(None, _request(tmp_path, LTX25_ID))

    assert result is not None
    [queued] = client.queued
    assert queued["prompt"][SAVE_FRAMES_NODE]["class_type"] == "SaveImage"
    payload = result.to_variant_payload()
    assert payload["frames_out"]["frame_count"] == FRAMES
    assert payload["frames_out"]["reconciliation"]["status"] == "match"


def test_an_opted_in_audio_job_takes_the_saved_video_as_its_output(
    tmp_path: Path, _no_encode
) -> None:
    class _VideoFake(_FakeComfy):
        def get_history(self, prompt_id=None, **_kw):
            saved = {"filename": "ltx25_job_00001_.mp4", "subfolder": "stablenew", "type": "output"}
            return {
                prompt_id: {
                    "outputs": {"38": {"images": [saved], "animated": [True]}},
                    "status": {"status_str": "success", "completed": True},
                }
            }

    client = _VideoFake(tmp_path, info=_info(LTX25_AUDIO_ID))

    result = _a14b_backend(client, tmp_path).execute(None, _request(tmp_path, LTX25_AUDIO_ID))

    assert result is not None
    assert result.to_variant_payload()["video_path"].endswith("ltx25_job_00001_.mp4")


@pytest.mark.parametrize("workflow_id", LTX25_IDS)
def test_a_job_without_the_opt_in_or_without_gpu_headroom_never_reaches_comfy(
    tmp_path: Path, workflow_id: str
) -> None:
    client = _FramesFake(tmp_path, save_node=SAVE_FRAMES_NODE, info=_info(workflow_id))
    with pytest.raises(KeyError, match="explicit experimental opt-in"):
        _a14b_backend(client, tmp_path).execute(
            None, _request(tmp_path, workflow_id, opt_in=False)
        )
    low = _FramesFake(
        tmp_path,
        save_node=SAVE_FRAMES_NODE,
        info=_info(workflow_id),
        stats=_stats(free_mib=5000),
    )
    with pytest.raises(RuntimeError, match="not resource-ready"):
        _a14b_backend(low, tmp_path).execute(None, _request(tmp_path, workflow_id))
    assert client.queued == [] and low.queued == []
