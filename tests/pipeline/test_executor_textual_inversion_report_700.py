"""The executor carries the backend's textual-inversion report into stage metadata (EMBED-700).

Forge Neo puts the embedding names it used in ``info["extra_generation_params"]["TI"]``. The executor only records
that evidence; it never infers consumption and never changes the request.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.pipeline.executor import Pipeline
from src.utils import StructuredLogger
from src.utils.embedding_prompt_utils import textual_inversion_report
from tests.pipeline.test_executor_prompt_optimizer import _allow_runtime, _Client, _fake_save_image


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        (
            {"extra_generation_params": {"TI": "PortraitStyle, FilmGrain"}},
            ["PortraitStyle", "FilmGrain"],
        ),
        ({"extra_generation_params": {"TI": "Solo"}}, ["Solo"]),
        ({"extra_generation_params": {}}, []),
        ({"extra_generation_params": {"TI": ""}}, []),
    ],
)
def test_report_lists_the_names_the_backend_used(info, expected):
    assert textual_inversion_report(info) == {"reported": True, "names": expected}


@pytest.mark.parametrize("info", [{}, {"seed": 1}, None, "text", {"extra_generation_params": "x"}])
def test_absent_extra_generation_params_report_nothing(info):
    assert textual_inversion_report(info) is None


def _run(tmp_path: Path, monkeypatch, info: dict) -> dict:
    pipeline = Pipeline(client=_Client(), structured_logger=StructuredLogger())
    _allow_runtime(pipeline, monkeypatch)
    monkeypatch.setattr(pipeline, "_apply_webui_defaults_once", lambda: None)
    monkeypatch.setattr(pipeline, "_ensure_model_and_vae", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_ensure_hypernetwork", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "_generate_images_with_progress",
        lambda _stage, _payload, **_kwargs: {"images": ["ignored"], "info": info},
    )
    monkeypatch.setattr("src.pipeline.executor.save_image_from_base64", _fake_save_image)
    config = {
        "txt2img": {
            "steps": 20,
            "cfg_scale": 7.0,
            "width": 1024,
            "height": 1024,
            "sampler_name": "Euler a",
        },
        "pipeline": {
            "apply_global_positive_txt2img": False,
            "apply_global_negative_txt2img": False,
        },
        "aesthetic": {"enabled": False},
        "prompt_optimizer": {"enabled": False},
    }
    result = pipeline.run_txt2img_stage("PortraitStyle knight", "blurry", config, tmp_path, "ti")
    assert result is not None
    return result


def test_stage_result_and_manifest_carry_the_backend_report(tmp_path, monkeypatch):
    info = {
        "seed": 1,
        "subseed": 2,
        "all_seeds": [1],
        "all_subseeds": [2],
        "extra_generation_params": {"TI": "PortraitStyle"},
    }
    result = _run(tmp_path, monkeypatch, info)
    assert result["backend_textual_inversion"] == {"reported": True, "names": ["PortraitStyle"]}
    assert result["final_prompt"] == "PortraitStyle knight"  # the request is never rewritten
    manifest = json.loads((tmp_path / "manifests" / "ti.json").read_text(encoding="utf-8"))
    assert manifest["backend_textual_inversion"] == {"reported": True, "names": ["PortraitStyle"]}


def test_a_response_without_the_field_records_no_report(tmp_path, monkeypatch):
    info = {"seed": 1, "subseed": 2, "all_seeds": [1], "all_subseeds": [2]}
    assert _run(tmp_path, monkeypatch, info)["backend_textual_inversion"] is None
