"""VID-FINISH: the experimental SeedVR2 upscale pass (pinned graph, preflight refusal, limits, VRAM stop rule).

No weights, no ComfyUI, no GPU: model folders and node lists are fakes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.video import seedvr2_upscale as upscale
from src.video.workflow_readiness import WorkflowResourceReadiness

MIB = 1024 * 1024


def _comfy(tmp_path: Path, *, nodes: bool = True) -> SimpleNamespace:
    source = tmp_path / "comfy"
    (source / "comfy_extras").mkdir(parents=True)
    if nodes:
        (source / "comfy_extras" / "nodes_seedvr.py").write_text("# stock", encoding="utf-8")
    return SimpleNamespace(command=("python", "main.py"), working_dir=str(source))


def _weights(config: SimpleNamespace, *, short: str = "") -> None:
    for item in upscale.UPSCALE_FILES:
        folder = Path(config.working_dir) / "models" / item.folder
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / item.name).open("wb") as handle:
            handle.truncate(item.size - (1 if item.name == short else 0))  # sparse, nothing real


def test_missing_weights_are_named_with_their_size_and_the_owner_ok(tmp_path: Path) -> None:
    issues = upscale.upscale_install_issues(_comfy(tmp_path))

    text = upscale.upscale_refusal(issues)
    assert "seedvr2_3b_int8_convrot.safetensors" in text and "models/diffusion_models" in text
    assert "seedvr2_ema_vae_fp16.safetensors" in text and "models/vae" in text
    assert "3.46 GB" in text and "0.50 GB" in text
    assert "owner's OK" in text and "Nothing was downloaded" in text
    assert "Turn off the upscale" in text


def test_missing_nodes_are_named(tmp_path: Path) -> None:
    config = _comfy(tmp_path, nodes=False)
    _weights(config)

    issues = upscale.upscale_install_issues(config)

    assert len(issues) == 1 and "SeedVR2 nodes" in issues[0] and "0.38.0" in issues[0]


def test_a_truncated_file_is_not_accepted(tmp_path: Path) -> None:
    config = _comfy(tmp_path)
    _weights(config, short="seedvr2_ema_vae_fp16.safetensors")

    issues = upscale.upscale_install_issues(config)

    assert len(issues) == 1 and "size" in issues[0] and "seedvr2_ema_vae_fp16" in issues[0]


def test_a_complete_install_has_no_issues(tmp_path: Path) -> None:
    config = _comfy(tmp_path)
    _weights(config)

    assert upscale.upscale_install_issues(config) == ()


def test_an_unknown_comfy_source_cannot_be_verified() -> None:
    issues = upscale.upscale_install_issues(SimpleNamespace(command=(), working_dir=None))
    assert issues and "cannot be verified" in issues[0]
    assert upscale.upscale_install_issues(None)


def test_the_serving_comfy_must_offer_every_node_the_graph_uses() -> None:
    graph = upscale.build_upscale_prompt("clip.mp4", seed=7, filename_prefix="stablenew/up")
    assert {node["class_type"] for node in graph.values()} == set(upscale.UPSCALE_NODES)

    info = {name: {} for name in upscale.UPSCALE_NODES}
    assert upscale.upscale_node_issues(info) == ()
    del info["SeedVR2Conditioning"]
    del info["VAEDecodeTiled"]
    issues = upscale.upscale_node_issues(info)
    assert len(issues) == 1
    assert "SeedVR2Conditioning" in issues[0] and "VAEDecodeTiled" in issues[0]


def test_the_graph_follows_comfys_blueprint_with_fixed_chunking() -> None:
    graph = upscale.build_upscale_prompt("clip.mp4", seed=7, filename_prefix="stablenew/up")
    nodes = {node["class_type"]: node["inputs"] for node in graph.values()}

    assert nodes["LoadVideo"] == {"file": "clip.mp4"}
    assert nodes["UNETLoader"]["unet_name"] == "seedvr2_3b_int8_convrot.safetensors"
    assert nodes["VAELoader"]["vae_name"] == "seedvr2_ema_vae_fp16.safetensors"
    assert nodes["ResizeImageMaskNode"]["resize_type"] == "scale by multiplier"
    assert nodes["ResizeImageMaskNode"]["resize_type.multiplier"] == 2.0
    assert nodes["ResizeImageMaskNode"]["scale_method"] == "lanczos"
    # Fixed chunking: ``auto`` would make the output depend on how much memory happened to be free.
    assert nodes["SeedVR2TemporalChunk"]["chunking_mode"] == "manual"
    assert nodes["SeedVR2TemporalChunk"]["chunking_mode.frames_per_chunk"] == 5
    assert nodes["SeedVR2TemporalChunk"]["temporal_overlap"] == 1
    sampler = nodes["KSampler"]
    assert (sampler["seed"], sampler["steps"], sampler["cfg"]) == (7, 1, 1.0)
    assert (sampler["sampler_name"], sampler["scheduler"], sampler["denoise"]) == (
        "euler",
        "simple",
        1.0,
    )
    assert nodes["SeedVR2PostProcessing"]["color_correction_method"] == "lab"
    assert nodes["SaveImage"]["filename_prefix"] == "stablenew/up"
    for node in graph.values():
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert value[0] in graph  # every link points at a node of this graph


def test_the_pinned_graph_and_files_change_only_with_a_new_version() -> None:
    payload = {
        "graph": upscale.build_upscale_prompt("v", seed=0, filename_prefix="p"),
        "files": [(item.folder, item.name, item.size) for item in upscale.UPSCALE_FILES],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    assert upscale.UPSCALE_PASS_ID == "seedvr2_3b_int8_upscale_2x"
    assert upscale.UPSCALE_PASS_VERSION == "1.0.0"
    assert digest == upscale.UPSCALE_PINNED_DIGEST


def test_the_pass_is_experimental_and_warns_on_the_queue_summary() -> None:
    warning = upscale.upscale_warning()
    assert warning.code == "video_upscale_experimental"
    assert warning.subject == "seedvr2_3b_int8_upscale_2x@1.0.0"
    assert "experimental" in warning.title and "never been run" in warning.why
    assert "opt-in" in warning.fix


def test_what_a_job_freezes() -> None:
    frozen = upscale.frozen_upscale(seed=11)
    assert frozen == {
        "pass_id": "seedvr2_3b_int8_upscale_2x",
        "pass_version": "1.0.0",
        "scale": 2,
        "seed": 11,
        "experimental_opt_in": True,
    }
    assert upscale.require_frozen_upscale(frozen) == frozen
    with pytest.raises(ValueError, match="opt-in"):
        upscale.require_frozen_upscale({**frozen, "experimental_opt_in": False})
    with pytest.raises(ValueError, match="version"):
        upscale.require_frozen_upscale({**frozen, "pass_version": "0.9.0"})


@pytest.mark.parametrize(
    ("width", "height", "frames", "message"),
    [
        (480, 832, 81, None),
        (624, 624, 121, None),
        (704, 1280, 81, "480p"),
        (544, 720, 161, "121 frames"),
        (0, 0, 81, "frame size"),
        (480, 832, 0, "length"),
    ],
)
def test_only_clips_the_12gb_estimate_covers_may_be_upscaled(
    width, height, frames, message
) -> None:
    issue = upscale.upscale_size_issue(width, height, frames)
    if message is None:
        assert issue is None
    else:
        assert issue is not None and message in issue


def _stats(free_mib: float, held_mib: float = 0.0) -> dict:
    return {"devices": [{"type": "cuda", "index": 0, "torch_vram_total": held_mib * MIB}]}


@pytest.mark.parametrize(
    ("free_mib", "held_mib", "ready"),
    [(11000, 0, True), (2000, 8500, True), (9000, 0, False)],
)
def test_the_existing_vram_stop_rule_gates_the_pass(free_mib, held_mib, ready) -> None:
    readiness = WorkflowResourceReadiness(
        ram_probe=lambda: 30.0, gpu_probe=lambda _index: (12282.0, float(free_mib))
    )

    result = readiness.evaluate(
        upscale.upscale_readiness_spec(), system_stats=_stats(free_mib, held_mib)
    )

    assert result.ready is ready
    assert result.observations["vram_floor_mib"] == 10000
    # The estimate the floor was chosen from stays under it.
    assert upscale.ESTIMATED_PEAK_VRAM_MIB < 10000


def test_an_unreadable_driver_blocks_the_pass() -> None:
    readiness = WorkflowResourceReadiness(ram_probe=lambda: 30.0, gpu_probe=lambda _index: None)

    result = readiness.evaluate(upscale.upscale_readiness_spec(), system_stats=_stats(0))

    assert not result.ready


def test_the_lossless_input_command_keeps_every_pixel(tmp_path: Path) -> None:
    command = upscale.build_lossless_input_command(
        "ffmpeg", tmp_path / "frame_%06d.png", tmp_path / "in.mp4", fps=16
    )

    assert command[command.index("-framerate") + 1] == "16"
    assert command[command.index("-c:v") + 1] == "libx264rgb"
    assert command[command.index("-qp") + 1] == "0"
    assert command[-1] == str(tmp_path / "in.mp4")
