from __future__ import annotations

import ast
import hashlib
import json
import os
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.gui.controllers.vid193_qualification_adapter import (
    Vid193QualificationAdapter,
    qualification_enabled,
)
from src.state.output_routing import classify_njr_output_route


class _JobServiceSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[list, object]] = []

    def submit_njrs(self, jobs: list, policy: object) -> list[str]:
        self.calls.append((jobs, policy))
        return [job.job_id for job in jobs]


def _source() -> Path:
    return Path(
        "C:/Users/rob/projects/StableNew-main/reports/vid193/inputs/"
        "source_fullbody_512_letterbox.png"
    )


def test_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STABLENEW_VID193_QUALIFICATION", raising=False)
    assert not qualification_enabled()
    with pytest.raises(RuntimeError, match="disabled"):
        Vid193QualificationAdapter().prepare([_source()])


def test_exact_preview_and_cancel_without_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STABLENEW_VID193_QUALIFICATION", "1")
    service = _JobServiceSpy()
    adapter = Vid193QualificationAdapter()
    njr, preview_text = adapter.prepare([_source()])
    preview = json.loads(preview_text)

    assert preview["job_count"] == 1
    assert preview["start_stage"] == "animatediff"
    assert preview["stage_chain"] == ["animatediff"]
    assert preview["resolved_backend"] == "animatediff"
    assert preview["source_image_path"] == str(_source())
    assert preview["source_sha256"] == "52c415946d5d6a5479c58b63b1d294d2f4b204fc7433bee620d64b3c79943fba"
    assert preview["output_dir"] == r"C:\Users\rob\projects\StableNew-main\output"
    assert preview["output_route"] == "animatediff"
    assert preview["effective_routed_root"] == r"C:\Users\rob\projects\StableNew-main\output\animatediff"
    assert preview["descriptor_sha256"] == "e6bf26a45390ec85e9919298d1cd4b58b834722aa5965ef2b599b00c19c3a70b"
    assert preview["required_a1111_options"] == {
        "pad_cond_uncond": True,
        "pad_cond_uncond_v0": False,
    }
    assert tuple(njr.input_image_paths) == (str(_source()),)
    assert njr.start_stage == "animatediff"
    assert njr.stage_chain_labels == ["animatediff"]
    assert classify_njr_output_route(njr) == "animatediff"
    assert njr.positive_prompt == preview["prompt"]
    assert njr.negative_prompt == preview["negative_prompt"]
    assert njr.base_model == preview["checkpoint"]
    stage = preview["stage_config"]
    descriptor = json.loads(
        (Path(__file__).resolve().parents[2] / "docs/Subsystems/Video/PR-VID-193_AD0_qualification.json")
        .read_text(encoding="utf-8")
    )
    assert all(stage[key] == value for key, value in descriptor["config"]["animatediff"].items())
    assert preview["prompt"] == descriptor["prompt"]
    assert preview["negative_prompt"] == descriptor["negative_prompt"]
    assert preview["checkpoint"] == descriptor["checkpoint"]
    assert stage["seed"] == 1733123036
    assert (stage["width"], stage["height"]) == (512, 512)
    assert (stage["video_length"], stage["fps"], stage["batch_size"]) == (8, 8, 8)
    assert stage["motion_module"] == "mm_sdxl_hs.safetensors"
    assert stage["denoising_strength"] == 0.3
    assert stage["sampler_name"] == "Euler a"
    assert stage["scheduler"] == "Karras"
    assert stage["steps"] == 20
    assert stage["cfg_scale"] == 6.0
    assert stage["vae"] == "Automatic"
    assert stage["clip_skip"] == 2
    assert stage["format"] == ["PNG", "Frame"]
    assert service.calls == []  # Closing the preview does not submit.


@pytest.mark.parametrize("mode", ["1", "AD0", "AD1"])
def test_queue_first_and_single_attempt(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv("STABLENEW_VID193_QUALIFICATION", mode)
    service = _JobServiceSpy()
    adapter = Vid193QualificationAdapter()
    njr, _ = adapter.prepare([_source()])
    snapshot = njr.to_dict()
    assert adapter.submit(njr, service) == njr.job_id
    assert njr.to_dict() == snapshot
    assert len(service.calls) == 1
    assert service.calls[0][0] == [njr]
    with pytest.raises(RuntimeError, match="already attempted"):
        adapter.submit(njr, service)
    assert len(service.calls) == 1


def test_source_selection_must_match(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STABLENEW_VID193_QUALIFICATION", "1")
    adapter = Vid193QualificationAdapter()
    with pytest.raises(ValueError, match="exactly one"):
        adapter.prepare([])
    with pytest.raises(ValueError, match="exactly one"):
        adapter.prepare([_source(), _source()])
    other = tmp_path / "other.png"
    other.write_bytes(b"other")
    with pytest.raises(ValueError, match="not the frozen"):
        adapter.prepare([other])


def test_descriptor_change_blocks_preview(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("STABLENEW_VID193_QUALIFICATION", "1")
    changed = tmp_path / "changed.json"
    changed.write_text('{"qualification_id":"changed"}', encoding="utf-8")
    with pytest.raises(ValueError, match="descriptor hash"):
        Vid193QualificationAdapter(descriptor_path=changed).prepare([_source()])


def test_submit_requires_prepared_njr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STABLENEW_VID193_QUALIFICATION", "1")
    prepared, _ = Vid193QualificationAdapter().prepare([_source()])
    service = _JobServiceSpy()
    with pytest.raises(RuntimeError, match="not prepared"):
        Vid193QualificationAdapter().submit(prepared, service)
    assert service.calls == []

def _descriptor(arm: str) -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / f"docs/Subsystems/Video/PR-VID-193_{arm}_qualification.json"
    )


def _differences(left, right, path: str = "") -> dict[str, tuple]:
    if isinstance(left, dict) and isinstance(right, dict):
        assert left.keys() == right.keys()
        result = {}
        for key in left:
            result.update(_differences(left[key], right[key], f"{path}.{key}".lstrip(".")))
        return result
    if isinstance(left, list) and isinstance(right, list):
        assert len(left) == len(right)
        result = {}
        for index, (first, second) in enumerate(zip(left, right, strict=True)):
            result.update(_differences(first, second, f"{path}[{index}]"))
        return result
    return {} if left == right else {path: (left, right)}


@pytest.mark.parametrize("mode,arm", [("1", "AD0"), ("AD0", "AD0"), ("AD1", "AD1")])
def test_explicit_arm_preview(monkeypatch: pytest.MonkeyPatch, mode: str, arm: str) -> None:
    monkeypatch.setenv("STABLENEW_VID193_QUALIFICATION", mode)
    adapter = Vid193QualificationAdapter()
    njr, preview_text = adapter.prepare([_source()])
    preview = json.loads(preview_text)
    descriptor = json.loads(_descriptor(arm).read_text(encoding="utf-8"))

    assert qualification_enabled()
    assert adapter.arm == arm
    assert preview["qualification"] == f"PR-VID-193-{arm}"
    assert preview["job_count"] == 1
    assert preview["job_id"] == njr.job_id
    assert preview["job_id"] == {
        "AD0": "0c0194c74b41526cadf374a5b83fc2a8",
        "AD1": "fe28de9c7d3e596b9dd1afa7c5ccad79",
    }[arm]
    assert preview["descriptor_sha256"] == Vid193QualificationAdapter._hash_descriptor(descriptor)
    assert preview["source_image_path"] == str(_source())
    assert preview["source_sha256"] == hashlib.sha256(_source().read_bytes()).hexdigest()
    assert preview["start_stage"] == "animatediff"
    assert preview["stage_chain"] == ["animatediff"]
    assert preview["resolved_backend"] == "animatediff"
    assert preview["checkpoint"] == descriptor["checkpoint"]
    assert preview["prompt"] == descriptor["prompt"]
    assert preview["negative_prompt"] == descriptor["negative_prompt"]
    assert preview["required_a1111_options"] == descriptor["required_a1111_options"]
    assert preview["output_dir"] == descriptor["config"]["pipeline"]["output_dir"]
    assert preview["output_route"] == "animatediff"
    assert preview["effective_routed_root"] == (
        r"C:\Users\rob\projects\StableNew-main\output\animatediff"
    )
    assert all(
        preview["stage_config"][key] == value
        for key, value in descriptor["config"]["animatediff"].items()
    )
    assert preview["stage_config"]["denoising_strength"] == {"AD0": 0.3, "AD1": 0.5}[arm]
    assert tuple(njr.input_image_paths) == (str(_source()),)
    with pytest.raises(FrozenInstanceError):
        njr.job_id = "mutated"


def test_ad0_bytes_and_ad1_one_factor_descriptor() -> None:
    assert hashlib.sha256(_descriptor("AD0").read_bytes()).hexdigest() == (
        "1538f85102fda2058c012ee85fb93061585b93d148bfc9d7031707759568e0ea"
    )
    descriptors = [json.loads(_descriptor(arm).read_text()) for arm in ("AD0", "AD1")]
    assert Vid193QualificationAdapter._hash_descriptor(descriptors[0]) == (
        "e6bf26a45390ec85e9919298d1cd4b58b834722aa5965ef2b599b00c19c3a70b"
    )
    assert Vid193QualificationAdapter._hash_descriptor(descriptors[1]) == (
        "4240e65e1322cda58fe718aaab6c53aa3ee6943a04484f32c9d1a67fec1cedae"
    )
    for arm, descriptor in zip(("AD0", "AD1"), descriptors, strict=True):
        assert descriptor.pop("qualification_id") == f"PR-VID-193-{arm}"
    assert _differences(*descriptors) == {
        "config.animatediff.denoising_strength": (0.3, 0.5)
    }


def test_effective_njr_one_factor_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    records = []
    previews = []
    for arm in ("AD0", "AD1"):
        monkeypatch.setenv("STABLENEW_VID193_QUALIFICATION", arm)
        njr, preview = Vid193QualificationAdapter().prepare([_source()])
        records.append(njr.to_dict())
        previews.append(json.loads(preview))

    assert records[0]["job_id"] != records[1]["job_id"]
    for record in records:
        record.pop("job_id")
        record["source"].pop("display_name")
        for metadata in (record["provenance"]["metadata"], record["workload"]["metadata"]):
            qualification = metadata["qualification"]
            assert qualification.keys() == {"id", "sha256"}
            qualification.pop("id")
            qualification.pop("sha256")
    assert _differences(*records) == {
        "stages[0].denoising_strength": (0.3, 0.5),
        "stages[0].extra.denoising_strength": (0.3, 0.5),
        "workload.config.animatediff.denoising_strength": (0.3, 0.5),
    }
    for preview in previews:
        for key in ("qualification", "descriptor_sha256", "job_id"):
            preview.pop(key)
    assert _differences(*previews) == {
        "stage_config.denoising_strength": (0.3, 0.5)
    }


@pytest.mark.parametrize("mode", ["", "0", "AD2", "anything"])
def test_unknown_modes_are_disabled(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv("STABLENEW_VID193_QUALIFICATION", mode)
    assert not qualification_enabled()
    with pytest.raises(RuntimeError, match="disabled"):
        Vid193QualificationAdapter().prepare([_source()])


def test_mode_change_blocks_existing_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STABLENEW_VID193_QUALIFICATION", "AD1")
    adapter = Vid193QualificationAdapter()
    njr, _ = adapter.prepare([_source()])
    monkeypatch.setenv("STABLENEW_VID193_QUALIFICATION", "AD0")
    service = _JobServiceSpy()
    with pytest.raises(RuntimeError, match="changed"):
        adapter.prepare([_source()])
    with pytest.raises(RuntimeError, match="changed"):
        adapter.submit(njr, service)
    assert service.calls == []


def test_ad1_rejects_ad0_descriptor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STABLENEW_VID193_QUALIFICATION", "AD1")
    with pytest.raises(ValueError, match="descriptor hash"):
        Vid193QualificationAdapter(descriptor_path=_descriptor("AD0")).prepare([_source()])


@pytest.mark.parametrize("mode", ["AD0", "AD1"])
def test_gui_preview_cancel_and_confirmation_use_only_job_service(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    from src.gui.views import review_tab_frame_v2 as review

    monkeypatch.setenv("STABLENEW_VID193_QUALIFICATION", mode)
    service = _JobServiceSpy()
    dialog = Mock()
    buttons = []
    monkeypatch.setattr(review.tk, "Toplevel", Mock(return_value=dialog))
    monkeypatch.setattr(review.tk, "Text", Mock())
    for widget in ("Frame", "Scrollbar"):
        monkeypatch.setattr(review.ttk, widget, Mock())

    def button(_parent, **kwargs):
        buttons.append(kwargs)
        return Mock()

    monkeypatch.setattr(review.ttk, "Button", button)
    monkeypatch.setattr(review, "apply_toplevel_theme", Mock())
    monkeypatch.setattr(review.messagebox, "showinfo", Mock())
    monkeypatch.setattr(review.messagebox, "showerror", Mock())
    frame = SimpleNamespace(
        _vid193_qualification=Vid193QualificationAdapter(),
        app_controller=SimpleNamespace(job_service=service),
        _get_selected_review_paths=lambda: [_source()],
        winfo_toplevel=lambda: None,
    )
    review.ReviewTabFrame._preview_vid193_qualification(frame)
    assert service.calls == []
    assert [item["text"] for item in buttons] == ["Cancel", f"Queue {mode} once"]
    buttons[0]["command"]()
    dialog.destroy.assert_called_once()
    assert service.calls == []

    buttons.clear()
    dialog.reset_mock()
    review.ReviewTabFrame._preview_vid193_qualification(frame)
    buttons[1]["command"]()
    assert len(service.calls) == 1
    assert len(service.calls[0][0]) == 1
    assert service.calls[0][0][0].job_id == {
        "AD0": "0c0194c74b41526cadf374a5b83fc2a8",
        "AD1": "fe28de9c7d3e596b9dd1afa7c5ccad79",
    }[mode]
    review.messagebox.showerror.assert_not_called()


def test_gui_gate_and_no_direct_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "src/gui/views/review_tab_frame_v2.py").read_text())
    frame = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ReviewTabFrame"
    )
    initializer = next(
        node for node in frame.body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    gate = next(
        node for node in initializer.body
        if isinstance(node, ast.If) and "STABLENEW_VID193_QUALIFICATION" in ast.unparse(node.test)
    )
    for mode, enabled in (("", False), ("AD2", False), ("1", True), ("AD0", True), ("AD1", True)):
        monkeypatch.setenv("STABLENEW_VID193_QUALIFICATION", mode)
        expression = compile(ast.Expression(gate.test), "<qualification gate>", "eval")
        assert eval(expression, {"os": os}) is enabled
    preview = next(
        node for node in frame.body
        if isinstance(node, ast.FunctionDef) and node.name == "_preview_vid193_qualification"
    )
    adapter = ast.parse((root / "src/gui/controllers/vid193_qualification_adapter.py").read_text())
    forbidden = {"run_njr", "execute", "run_animatediff_stage", "img2img", "txt2img", "generate_images"}
    for subtree in (preview, adapter):
        assert not any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in forbidden
            for node in ast.walk(subtree)
        )
