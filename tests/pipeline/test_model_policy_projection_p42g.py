"""P4-2G: one model compile-policy result, projected onto the nested and the flat PromptPack shape.

The flat projection replaced a second application of the policy on every record's payload. The legacy application
(``apply_model_compile_policy``, still the nested authority and the oracle here) must produce, for the same payload,
exactly what the projection produces: the same keys in the same order, the same values, the same refusals.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from src.image_backends import model_policy
from src.image_backends.forge_klein_profile import latest_klein_profile
from src.image_backends.forge_zimage_profile import (
    ZIMAGE_PROFILE_V1,
    ZImageProfileError,
    apply_zimage_compile_policy,
)
from src.image_backends.model_policy import (
    ModelPolicyResult,
    apply_model_compile_policy,
    compile_model_policy,
)
from tests.pipeline.test_klein_compile_policy import KLEIN, _pack_job
from tests.pipeline.test_njr_compile_invocations_p42e import _pack_records
from tests.pipeline.test_zimage_compile_policy import _pack as zimage_pack

ZIMAGE = ZIMAGE_PROFILE_V1.transformer.filename


@pytest.fixture(autouse=True)
def _forge_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.image_backends.image_backend_types.configured_image_backend_id", lambda: "forge_webui"
    )


def _outcome(run: Callable[[], Any]) -> tuple[str, Any]:
    try:
        return "ok", json.dumps(run())  # insertion order is part of the comparison
    except Exception as exc:  # the refusal is the result
        return "refused", (type(exc).__name__, str(exc))


def _legacy_and_projected(payload: dict[str, Any]) -> tuple[tuple[str, Any], tuple[str, Any]]:
    result = ModelPolicyResult({})
    return (
        _outcome(lambda: apply_model_compile_policy(copy.deepcopy(payload))),
        _outcome(lambda: result.project_flat(copy.deepcopy(payload))),
    )


@pytest.fixture
def oracle(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Check every flat projection the PromptPack builder makes against the legacy application of the same payload."""

    seen: list[tuple[str, Any]] = []
    real = ModelPolicyResult.project_flat

    def checked(self: ModelPolicyResult, payload: dict[str, Any]) -> dict[str, Any]:
        before = copy.deepcopy(payload)
        legacy = _outcome(lambda: apply_model_compile_policy(copy.deepcopy(before)))
        projected = _outcome(lambda: real(self, payload))
        assert projected == legacy
        seen.append(projected)
        return payload

    monkeypatch.setattr(ModelPolicyResult, "project_flat", checked)
    return seen


# ------------------------------------------------------------------------ the builder's real payloads


@pytest.mark.parametrize(
    "slot",
    [
        {},
        {"loras": [["adapter", 0.7]], "positive_embeddings": [["token", 1]]},
        {"negative": "bad", "negative_embeddings": [["token", 1]]},
    ],
)
def test_the_zimage_projection_reproduces_the_legacy_application(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    oracle: list[tuple[str, Any]],
    slot: dict[str, Any],
) -> None:
    builder, entry, _path, _original = zimage_pack(tmp_path, monkeypatch, **slot)
    records = builder.build_jobs([entry])

    assert len(records) == len(oracle) == 1
    assert oracle[0][0] == "ok"
    config = records[0].config
    assert config["txt2img"]["distilled_cfg_scale"] == config["distilled_cfg_scale"] == 9.0


def test_the_zimage_projection_matches_for_operator_values_and_seeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, oracle: list[tuple[str, Any]]
) -> None:
    builder, entry, _path, _original = zimage_pack(tmp_path, monkeypatch)
    manager = builder._config_manager
    manager._config["txt2img"].update(
        {"distilled_cfg_scale": 9.0, "vae": "", "sampler_name": "Euler", "seed": 7}
    )
    entry.config_snapshot = {"randomization_enabled": True, "max_variants": 3, "seed": 11}

    records = builder.build_jobs([entry])

    assert len(oracle) == len(records) >= 1
    assert {kind for kind, _ in oracle} == {"ok"}


def test_the_klein_projection_reproduces_the_legacy_application(
    tmp_path: Path, oracle: list[tuple[str, Any]]
) -> None:
    record = _pack_job(tmp_path, KLEIN)

    assert [kind for kind, _ in oracle] == ["ok"]
    assert (
        record.config["backend_options"]["image"]["model_profile"]
        == latest_klein_profile().reference()
    )
    assert record.config["txt2img"]["steps"] == 4


def test_the_sdxl_projection_changes_nothing(tmp_path: Path, oracle: list[tuple[str, Any]]) -> None:
    records = _pack_records(tmp_path, loop_count=2)

    assert len(oracle) == len(records) == 2
    assert {kind for kind, _ in oracle} == {"ok"}
    assert all(
        "model_profile" not in str(record.config.get("backend_options")) for record in records
    )


# ---------------------------------------------------------------------------------- synthetic payloads


def _zimage_payload(**changes: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt": "A ceramic teapot on a wooden table.",
        "negative_prompt": "",
        "model": ZIMAGE,
        "sampler": "Euler",
        "scheduler": "Beta",
        "steps": 9,
        "cfg_scale": 1.0,
        "width": 1024,
        "height": 1024,
        "seed": 42,
        "clip_skip": 1,
        "vae": None,
        "prompt_optimizer": {"enabled": False},
        "pipeline": {"loop_count": 1},
        "stages": ["txt2img"],
    }
    payload.update(changes)
    return payload


def _klein_payload(**changes: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt": "portrait on a rainy street",
        "negative_prompt": "blurry",
        "model": KLEIN,
        "sampler": "DPM++ 2M",
        "scheduler": "DDIM",
        "steps": 24,
        "cfg_scale": 7.5,
        "width": 768,
        "height": 1024,
        "vae": "sdxl_vae.safetensors",
        "prompt_optimizer": {"enabled": True, "mode": "x"},
        "pipeline": {"apply_global_negative_adetailer": True, "loop_count": 1},
        "global_positive_prompt": "masterpiece",
        "global_negative_prompt": "ugly",
    }
    payload.update(changes)
    return payload


@pytest.mark.parametrize(
    "payload",
    [
        _zimage_payload(),
        _zimage_payload(txt2img=None) | {"txt2img": {}},
        _zimage_payload(distilled_cfg_scale=9.0, sampler_name="Euler", vae=""),
        _zimage_payload(
            global_positive_prompt="", global_negative_prompt="", global_prompt_policy_source="x"
        ),
        _zimage_payload(
            model=None,
            sampler=None,
            scheduler=None,
            steps=None,
            cfg_scale=None,
            width=None,
            height=None,
        ),
        _klein_payload(),
        _klein_payload(
            txt2img={"model": KLEIN, "steps": 24, "seed": 3},
            sampler_name="X",
            backend_options={"image": {"k": 1}},
        ),
        _klein_payload(txt2img="not-a-section", prompt_optimizer=None, pipeline=None),
        _klein_payload(backend_options={"video": {"a": 1}}),
        {"model": "sdxl.safetensors", "steps": 30, "prompt_optimizer": {"enabled": True}},
        {},
    ],
    ids=[
        "zimage",
        "zimage-empty-section",
        "zimage-explicit-profile-values",
        "zimage-global-terms-present",
        "zimage-fills-missing-values",
        "klein",
        "klein-existing-section-and-options",
        "klein-odd-shapes",
        "klein-other-backend-options",
        "ordinary-model",
        "empty",
    ],
)
def test_the_projection_matches_the_legacy_application_on_synthetic_payloads(
    payload: dict[str, Any],
) -> None:
    legacy, projected = _legacy_and_projected(payload)

    assert projected == legacy


@pytest.mark.parametrize(
    "payload",
    [
        _zimage_payload(width=640),
        _zimage_payload(seed=-5),
        _zimage_payload(prompt="a (red dress:1.2) harbor"),
        _zimage_payload(enable_hr=True),
        _zimage_payload(stages=["txt2img", "upscale"]),
        _zimage_payload(backend_options={"image": {"backend_id": "a1111_webui"}}),
        {
            "backend_options": {"image": {"model_profile": ZIMAGE_PROFILE_V1.reference()}},
            "model": "sdxl.safetensors",
        },
    ],
    ids=[
        "geometry",
        "seed",
        "weighted-prompt",
        "hires",
        "stages",
        "other-backend",
        "profile-without-checkpoint",
    ],
)
def test_the_projection_refuses_exactly_what_the_legacy_application_refused(
    payload: dict[str, Any],
) -> None:
    legacy, projected = _legacy_and_projected(payload)

    assert legacy[0] == "refused"
    assert projected == legacy


# ------------------------------------------------------------------------------------------- the seam


def test_compile_policy_evaluates_once_and_the_nested_projection_is_the_evaluated_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    real = model_policy.apply_model_compile_policy

    def counted(config: dict[str, Any]) -> dict[str, Any]:
        calls.append(config)
        return real(config)

    monkeypatch.setattr(model_policy, "apply_model_compile_policy", counted)
    config = {"txt2img": {"model": KLEIN, "steps": 24}, "prompt_optimizer": {"enabled": True}}

    result = compile_model_policy(config)
    flat = result.project_flat(_klein_payload())

    assert len(calls) == 1  # projecting the flat shape evaluates nothing
    assert result.project_nested() is config
    assert config["txt2img"]["steps"] == 4 and flat["steps"] == 4


def test_a_refused_evaluation_yields_no_result_to_project() -> None:
    with pytest.raises(ZImageProfileError):
        compile_model_policy({"txt2img": {"model": ZIMAGE, "width": 640}})


def test_the_zimage_flat_defaults_are_the_profiles_own_section() -> None:
    """Drift guard: the projection's fill values equal what the profile's own compile function fills."""

    expected = apply_zimage_compile_policy({"model": ZIMAGE})["txt2img"]
    flat = ModelPolicyResult({}).project_flat({"model": ZIMAGE})

    assert flat["txt2img"] == expected


def test_a_non_selecting_payload_is_returned_as_given() -> None:
    payload = {"model": "sdxl.safetensors", "steps": 30}

    assert ModelPolicyResult({}).project_flat(payload) is payload
    assert payload == {"model": "sdxl.safetensors", "steps": 30}
