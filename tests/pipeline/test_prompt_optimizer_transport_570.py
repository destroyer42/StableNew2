"""Capture real executor dispatch into a synthetic WebUI client, never a runtime."""

from copy import deepcopy

import pytest

from src.api.types import GenerateOutcome, GenerateResult
from src.image_backends.a1111_webui_backend import A1111WebUIImageBackend
from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend
from src.image_backends.image_backend_types import ImageExecutionRequest
from src.pipeline.executor import Pipeline
from src.pipeline.global_prompt_policy import apply_global_prompt_policy
from src.utils import StructuredLogger
from tests.pipeline.test_executor_prompt_optimizer import _fake_save_image


class CaptureClient:
    options_write_enabled = True

    def __init__(self):
        self.requests = []

    def get_current_model(self):
        return "model.safetensors"

    def get_current_vae(self):
        return "vae.pt"

    def generate_images(self, *, stage, payload):
        self.requests.append((stage, deepcopy(payload)))
        return GenerateOutcome(
            result=GenerateResult(
                images=["synthetic"],
                info={"seed": 123, "all_seeds": [123]},
                stage=stage,
            )
        )


@pytest.fixture
def transport(monkeypatch):
    client = CaptureClient()
    pipeline = Pipeline(client=client, structured_logger=StructuredLogger())
    for method in (
        "_apply_webui_defaults_once",
        "_ensure_model_and_vae",
        "_ensure_hypernetwork",
        "_ensure_webui_true_ready",
        "_check_webui_health_before_stage",
        "_poll_progress_loop",
    ):
        monkeypatch.setattr(pipeline, method, lambda *_a, **_k: None)
    monkeypatch.setattr(
        pipeline, "_ensure_runtime_admissible", lambda **_k: {"status": "healthy", "reasons": []}
    )
    monkeypatch.setattr(pipeline, "_assess_stage_pressure", lambda **_k: {})
    monkeypatch.setattr(pipeline, "_load_image_base64", lambda *_a: "synthetic")
    monkeypatch.setattr("src.pipeline.executor.save_image_from_base64", _fake_save_image)
    return pipeline, client


@pytest.mark.parametrize("backend", [A1111WebUIImageBackend, ForgeWebUIImageBackend])
@pytest.mark.parametrize("enabled", [False, True])
def test_authored_row_and_style_loras_compile_through_adapter_to_dispatch(
    tmp_path, transport, backend, enabled
):
    from src.gui.app_state_v2 import PackJobEntry
    from src.pipeline.job_builder_v2 import JobBuilderV2
    from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
    from src.training.style_lora_manager import StyleLoRAManager
    from src.utils.config import ConfigManager
    from tests.pipeline.test_prompt_authoring_contract_540 import _author_pack
    from tests.pipeline.test_prompt_pack_job_builder import _write_style_catalog

    packs = tmp_path / "packs"
    packs.mkdir()
    pack = _author_pack(packs)
    before = pack.read_bytes()
    catalog, _ = _write_style_catalog(tmp_path)
    builder = PromptPackNormalizedJobBuilder(
        config_manager=ConfigManager(presets_dir=tmp_path / "presets", packs_dir=packs),
        job_builder=JobBuilderV2(),
        packs_dir=packs,
        style_lora_manager=StyleLoRAManager(catalog_path=catalog, webui_root=None),
    )
    [record] = builder.build_jobs(
        [
            PackJobEntry(
                pack_id=pack.name,
                pack_name="Authored",
                pack_row_index=0,
                config_snapshot={
                    "prompt_optimizer": {"enabled": enabled, "log_before_after": False}
                },
                stage_flags={"txt2img": True},
                randomizer_metadata={"enabled": False},
            )
        ]
    )
    request = ImageExecutionRequest(
        backend_id=backend.backend_id,
        stage_name="txt2img",
        stage_config={},
        output_dir=tmp_path,
        prompt=record.positive_prompt,
        negative_prompt=record.negative_prompt,
        execution_config=record.config,
    )
    config = backend._txt2img_executor_config(request)
    assert config["prompt_optimizer"]["enabled"] is enabled
    pipeline, client = transport
    result = pipeline.run_txt2img_stage(
        record.positive_prompt, record.negative_prompt, config, tmp_path, "compiled"
    )
    assert result is not None
    [(_stage, outbound)] = client.requests
    for tag in ("<lora:pack_style:0.45>", "<lora:style_cinematic_grit:0.65>"):
        assert outbound["prompt"].count(tag) == 1
        assert tag not in outbound["negative_prompt"]
    assert "sunlit film grain" in outbound["prompt"]
    assert outbound["prompt"] == result["final_prompt"]
    assert outbound["negative_prompt"] == result["final_negative_prompt"]
    if not enabled:
        assert outbound["prompt"] == record.positive_prompt
    assert pack.read_bytes() == before


@pytest.mark.parametrize("mode", ["enabled", "disabled", "stage_opt_out"])
def test_actual_txt2img_order_after_globals_aesthetic_and_promptpatch(tmp_path, transport, mode):
    config = apply_global_prompt_policy(
        {
            "txt2img": {
                "width": 512,
                "height": 512,
                "steps": 20,
                "cfg_scale": 7.0,
                "sampler_name": "Euler",
            },
            "prompt_optimizer": {
                "enabled": mode != "disabled",
                "log_before_after": False,
                "opt_out_pipeline_names": ["txt2img"] if mode == "stage_opt_out" else [],
            },
            "aesthetic": {"enabled": True, "mode": "prompt", "text": "cinematic lighting"},
            "adaptive_refinement": {
                "decision_bundle": {"prompt_patch": {"add_positive": ["85mm lens"]}}
            },
        },
        positive_enabled=True,
        negative_enabled=True,
        positive_text="masterpiece",
        negative_text="bad anatomy",
    )
    pipeline, client = transport
    result = pipeline.run_txt2img_stage("beautiful woman", "watermark", config, tmp_path, "stages")
    assert result is not None
    [(_stage, outbound)] = client.requests
    if mode == "enabled":
        assert outbound["prompt"] == "beautiful woman, cinematic lighting, 85mm lens, masterpiece"
        assert outbound["negative_prompt"] == "bad anatomy, watermark"
    else:
        assert outbound["prompt"] == "masterpiece, beautiful woman, 85mm lens, cinematic lighting"
        assert outbound["negative_prompt"] == "watermark, bad anatomy"


def test_img2img_dispatch_keeps_grouped_tokens_and_distinct_attention(tmp_path, transport):
    pipeline, client = transport
    source = tmp_path / "source.png"
    source.write_bytes(b"synthetic")
    positive = "(beautiful woman <lora:Detail:0.70>:1.2), beautiful woman, [beautiful woman]"
    negative = "(bad anatomy <embedding:avoid>:0.8), bad anatomy"
    config = {
        "steps": 20,
        "cfg_scale": 7.0,
        "sampler_name": "Euler",
        "negative_prompt": negative,
        "prompt_optimizer": {"enabled": True, "log_before_after": False},
        "aesthetic": {"enabled": False},
    }
    full = apply_global_prompt_policy(
        config, positive_enabled=False, negative_enabled=False, positive_text="", negative_text=""
    )
    result = pipeline.run_img2img_stage(source, positive, config, tmp_path, "img", full_config=full)
    assert result is not None
    [(_stage, outbound)] = client.requests
    for part in ("(beautiful woman <lora:Detail:0.70>:1.2)", "[beautiful woman]"):
        assert part in outbound["prompt"]
    assert "(bad anatomy <embedding:avoid>:0.8)" in outbound["negative_prompt"]
    assert outbound["prompt"].count("<lora:Detail:0.70>") == 1
    assert "<lora:" not in outbound["negative_prompt"]
