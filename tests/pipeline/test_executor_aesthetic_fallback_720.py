"""Aesthetic fallback at the real executor/fake WebUI boundary; no runtime or assets."""

import json
from copy import deepcopy

import pytest

from src.api.types import GenerateErrorCode, GenerateOutcome, GenerateResult
from src.pipeline.executor import PipelineStageError
from src.pipeline.global_prompt_policy import apply_global_prompt_policy
from src.pipeline.prompt_pack_parser import PackRow
from src.pipeline.resolution_layer import render_pack_intent, resolve_pack_intent
from tests.pipeline.test_prompt_optimizer_transport_570 import transport as _transport

BASE = "Cinematic portrait of a medieval knight"
NEGATIVE = "blurry, low quality"
EXPECTED = f"{BASE}, dramatic lighting, detailed armor, PortraitStyle"


@pytest.fixture
def transport(monkeypatch):
    return _transport.__wrapped__(monkeypatch)


def _config():
    return {
        "txt2img": {
            "model": "model.safetensors",
            "width": 512,
            "height": 512,
            "steps": 20,
            "cfg_scale": 7.0,
            "sampler_name": "Euler",
        },
        "pipeline": {
            "apply_global_positive_txt2img": False,
            "apply_global_negative_txt2img": False,
            "apply_global_positive_img2img": False,
            "apply_global_negative_img2img": False,
        },
        "aesthetic": {
            "enabled": True,
            "mode": "prompt",
            "text": "dramatic lighting",
            "text_is_negative": False,
            "fallback_prompt": "detailed armor",
            "embedding": "PortraitStyle",
            "weight": 0.37,
            "learning_rate": 0.002,
        },
        "prompt_optimizer": {"enabled": False, "log_before_after": False},
    }


def _run(stage, tmp_path, transport, config, prompt=BASE):
    pipeline, _client = transport
    if stage == "txt2img":
        return pipeline.run_txt2img_stage(prompt, NEGATIVE, config, tmp_path, "aesthetic")
    source = tmp_path / "source.png"
    source.write_bytes(b"synthetic")
    return pipeline.run_img2img_stage(
        source,
        prompt,
        {**config["txt2img"], "negative_prompt": NEGATIVE},
        tmp_path,
        "aesthetic",
        full_config=config,
    )


@pytest.mark.parametrize("stage", ["txt2img", "img2img"])
def test_golden_outbound_payload(stage, tmp_path, transport, monkeypatch):
    config = _config()
    before = deepcopy(config)
    model_calls = []
    monkeypatch.setattr(
        transport[0], "_ensure_model_and_vae", lambda *args: model_calls.append(args)
    )
    result = _run(stage, tmp_path, transport, config)
    assert result is not None
    [actual] = transport[1].requests
    actual_stage, payload = actual
    assert actual_stage == stage
    assert payload["prompt"] == EXPECTED
    assert "<embedding:" not in payload["prompt"]
    assert payload["negative_prompt"] == NEGATIVE
    assert not payload.get("alwayson_scripts")
    assert not payload.get("enable_hr")
    assert not payload.get("use_refiner")
    assert model_calls[0][0] == "model.safetensors"
    assert result["final_prompt"] == payload["prompt"]
    assert result.get("backend_textual_inversion") is None
    assert config == before


@pytest.mark.parametrize("stage", ["txt2img", "img2img"])
@pytest.mark.parametrize("optimizer", [False, True])
@pytest.mark.parametrize(
    "name", ["PortraitStyle", "portrait_style_v2", "portrait-style", "My Style"]
)
def test_valid_name_survives_optimizer_and_stage_policy(
    stage, optimizer, name, tmp_path, transport
):
    config = _config()
    config["aesthetic"]["embedding"] = name
    config["prompt_optimizer"]["enabled"] = optimizer
    result = _run(stage, tmp_path, transport, config)
    assert result is not None
    [(_, payload)] = transport[1].requests
    assert payload["prompt"].count(name) == 1
    assert "<embedding:" not in payload["prompt"]
    assert name not in payload["negative_prompt"]
    assert result["final_prompt"] == payload["prompt"]
    assert result["prompt_optimizer_analysis"]["stage_policy"]["mode"] == "auto_safe_fill_v1"


@pytest.mark.parametrize("stage", ["txt2img", "img2img"])
@pytest.mark.parametrize(
    "name", ["a:b", "a,b", "a(b)", "a[b]", "<a>", "a|b", "a\\b", "a\nb", " padded", " ", 12]
)
def test_invalid_name_raises_before_generation(stage, name, tmp_path, transport):
    config = _config()
    config["aesthetic"]["embedding"] = name
    with pytest.raises(
        PipelineStageError, match="Aesthetic embedding.*cannot be invoked safely"
    ) as caught:
        _run(stage, tmp_path, transport, config)
    assert caught.value.error.code == GenerateErrorCode.PAYLOAD_VALIDATION
    assert transport[1].requests == []


@pytest.mark.parametrize("name", [None, "", "None"])
def test_no_selection_and_disabled_aesthetic_preserve_inputs(name, transport):
    pipeline, _client = transport
    config = _config()
    config["aesthetic"] = {"enabled": True, "mode": "prompt", "embedding": name}
    payload = {"prompt": BASE, "negative_prompt": NEGATIVE}
    before = deepcopy(config)
    assert pipeline._apply_aesthetic_to_payload(payload, config) == (BASE, NEGATIVE)
    config["aesthetic"] = {"enabled": False, "embedding": "<invalid>"}
    assert pipeline._apply_aesthetic_to_payload(payload, config) == (BASE, NEGATIVE)
    assert before["aesthetic"]["embedding"] == name


@pytest.mark.parametrize("stage", ["txt2img", "img2img"])
def test_negative_text_and_global_prompt_policy(stage, tmp_path, transport):
    config = _config()
    config["aesthetic"]["text_is_negative"] = True
    config = apply_global_prompt_policy(
        config,
        positive_enabled=True,
        negative_enabled=True,
        positive_text="global positive",
        negative_text="global negative",
    )
    assert _run(stage, tmp_path, transport, config) is not None
    [(_, payload)] = transport[1].requests
    # Global positive is applied in txt2img only; img2img receives its effective input.
    prefix = "global positive, " if stage == "txt2img" else ""
    assert payload["prompt"] == f"{prefix}{BASE}, detailed armor, PortraitStyle"
    assert payload["negative_prompt"] == f"{NEGATIVE}, global negative, dramatic lighting"


@pytest.mark.parametrize("stage", ["txt2img", "img2img"])
@pytest.mark.parametrize("weight", [1.0, 0.8])
def test_compiled_pack_invocation_is_not_duplicated(stage, weight, tmp_path, transport):
    row = PackRow(
        embeddings=(("PortraitStyle", weight),),
        subject_template=BASE,
        quality_line="",
        lora_tags=(),
        negative_embeddings=(),
        negative_phrases=(),
    )
    rendered = render_pack_intent(
        resolve_pack_intent(pack_row=row, pack_negative="", apply_global_negative=False)
    )
    config = _config()
    assert _run(stage, tmp_path, transport, config, rendered.positive) is not None
    [(_, payload)] = transport[1].requests
    assert payload["prompt"].count("PortraitStyle") == 1
    assert payload["prompt"].startswith(rendered.positive)


@pytest.mark.parametrize(
    "existing", ["PortraitStyle-other", "OtherPortraitStyle", "<lora:PortraitStyle:1>"]
)
def test_other_tokens_do_not_suppress_selected_embedding(existing, transport):
    prompt, _ = transport[0]._apply_aesthetic_to_payload(
        {"prompt": existing, "negative_prompt": NEGATIVE}, _config()
    )
    assert prompt == f"{existing}, dramatic lighting, detailed armor, PortraitStyle"


def test_repeated_fallback_appends_embedding_once(transport):
    pipeline, _ = transport
    config = _config()
    payload = {"prompt": BASE, "negative_prompt": NEGATIVE}
    for _ in range(2):
        payload["prompt"], payload["negative_prompt"] = pipeline._apply_aesthetic_to_payload(
            payload, config
        )
    assert payload["prompt"].count("PortraitStyle") == 1


@pytest.mark.parametrize("stage", ["txt2img", "img2img"])
def test_script_mode_keeps_exact_arguments_and_never_renders(
    stage, tmp_path, transport, monkeypatch
):
    def forbidden(*_args, **_kwargs):
        pytest.fail("script mode must not render a prompt-fallback invocation")

    monkeypatch.setattr("src.pipeline.executor.render_embedding_invocation", forbidden)
    config = _config()
    config["aesthetic"].update(
        mode="script",
        steps=7,
        slerp=True,
        slerp_angle=0.25,
        text_is_negative=True,
        embedding="<script setting unchanged>",
    )
    before = deepcopy(config)
    assert _run(stage, tmp_path, transport, config) is not None
    [(_, payload)] = transport[1].requests
    assert payload["prompt"] == BASE
    assert payload["negative_prompt"] == NEGATIVE
    assert payload["alwayson_scripts"] == {
        "Aesthetic embeddings": {
            "args": [
                0.37,
                7,
                "0.002",
                True,
                "<script setting unchanged>",
                "dramatic lighting",
                0.25,
                True,
            ]
        }
    }
    assert config == before


def test_script_argument_failure_uses_existing_prompt_fallback(transport, monkeypatch):
    pipeline, _ = transport
    monkeypatch.setattr(pipeline, "_build_aesthetic_script_args", lambda _cfg: None)
    config = _config()
    config["aesthetic"]["mode"] = "script"
    payload = {"prompt": BASE, "negative_prompt": NEGATIVE}
    assert pipeline._apply_aesthetic_to_payload(payload, config) == (EXPECTED, NEGATIVE)
    assert "alwayson_scripts" not in payload


@pytest.mark.parametrize("stage", ["txt2img", "img2img"])
def test_no_aesthetic_processing_leaves_normal_requests_unchanged(stage, tmp_path, transport):
    config = _config()
    config["aesthetic"]["enabled"] = False
    assert _run(stage, tmp_path, transport, config) is not None
    [(_, payload)] = transport[1].requests
    assert payload["prompt"] == BASE
    assert payload["negative_prompt"] == NEGATIVE
    assert not payload.get("alwayson_scripts")


@pytest.mark.parametrize("stage", ["txt2img", "img2img"])
@pytest.mark.parametrize("params", [None, {}, {"TI": "PortraitStyle"}])
def test_backend_consumption_evidence_is_only_the_response(
    stage, params, tmp_path, transport, monkeypatch
):
    client = transport[1]
    original = client.generate_images

    def response(*, stage, payload):
        original(stage=stage, payload=payload)
        info = {"seed": 123, "all_seeds": [123]}
        if params is not None:
            info["extra_generation_params"] = params
        return GenerateOutcome(result=GenerateResult(images=["synthetic"], info=info, stage=stage))

    monkeypatch.setattr(client, "generate_images", response)
    result = _run(stage, tmp_path, transport, _config())
    assert result is not None
    expected = (
        None if params is None else {"reported": True, "names": ["PortraitStyle"] if params else []}
    )
    if stage == "txt2img":
        assert result["backend_textual_inversion"] == expected
    else:
        # EMBED-700's response extractor observes TI for both stages, but img2img's
        # existing stage metadata does not expose it. Do not invent new evidence.
        assert "backend_textual_inversion" not in result
        info = {} if params is None else {"extra_generation_params": params}
        assert (
            transport[0]._extract_generation_info({"info": info})["backend_textual_inversion"]
            == expected
        )
    manifests = list((tmp_path / "manifests").glob("*.json"))
    manifests = [p for p in manifests if ".prompt_" not in p.name]
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text())
    if stage == "txt2img":
        assert manifest["backend_textual_inversion"] == expected
    else:
        assert "backend_textual_inversion" not in manifest
