from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.gui.controllers.vid193_qualification_adapter import (
    Vid193Ad0QualificationAdapter,
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
        Vid193Ad0QualificationAdapter().prepare([_source()])


def test_exact_preview_and_cancel_without_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STABLENEW_VID193_QUALIFICATION", "1")
    service = _JobServiceSpy()
    adapter = Vid193Ad0QualificationAdapter()
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


def test_queue_first_and_single_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STABLENEW_VID193_QUALIFICATION", "1")
    service = _JobServiceSpy()
    adapter = Vid193Ad0QualificationAdapter()
    njr, _ = adapter.prepare([_source()])
    assert adapter.submit(njr, service) == njr.job_id
    assert len(service.calls) == 1
    assert service.calls[0][0] == [njr]
    with pytest.raises(RuntimeError, match="already attempted"):
        adapter.submit(njr, service)
    assert len(service.calls) == 1


def test_source_selection_must_match(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STABLENEW_VID193_QUALIFICATION", "1")
    adapter = Vid193Ad0QualificationAdapter()
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
        Vid193Ad0QualificationAdapter(descriptor_path=changed).prepare([_source()])


def test_submit_requires_prepared_njr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STABLENEW_VID193_QUALIFICATION", "1")
    prepared, _ = Vid193Ad0QualificationAdapter().prepare([_source()])
    service = _JobServiceSpy()
    with pytest.raises(RuntimeError, match="not prepared"):
        Vid193Ad0QualificationAdapter().submit(prepared, service)
    assert service.calls == []
