"""PR-IMG-FORGE-100: forge_webui through the canonical path with Forge-shaped HTTP (fakes only).

``NJR -> JobService -> SQLite -> PipelineRunner.run_njr -> ForgeWebUIImageBackend -> executor ->
ForgeWebUIClient``; only ``requests.Session.request`` is replaced, so no WebUI/GPU/model is used.
These are deterministic stand-ins for the qualification journeys, never a substitute for the
physical acceptance run.
"""

from __future__ import annotations

import base64

import pytest
import requests

from src.api.client import SDWebUIClient
from src.api.forge_client import ForgeWebUIClient
from src.pipeline.global_prompt_policy import apply_global_prompt_policy
from src.queue.job_model import JobStatus
from tests.helpers.fake_webui_transport import GENERATION_PATHS, TINY_PNG_B64, FakeWebUITransport
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config
from tests.helpers.njr_queue_harness import run_njr_via_queue

VAE = {"model_name": "sdxl_vae.safetensors", "filename": "/models/VAE/sdxl_vae.safetensors"}


def _client(cls: type[SDWebUIClient], transport: FakeWebUITransport) -> SDWebUIClient:
    client = cls(base_url="http://127.0.0.1:7861", options_write_enabled=True)
    client._session.request = transport  # type: ignore[method-assign]
    client._options_min_interval_seconds = 0.0
    return client


def _txt2img_stage(**extra):
    return make_stage_config(
        "txt2img",
        steps=24,
        cfg_scale=5.5,
        sampler_name="Euler a",
        scheduler="Karras",
        model="sdxl.safetensors",
        vae="sdxl_vae.safetensors",
        **extra,
    )


def _njr(backend_id: str | None, **overrides):
    backend_options = {"image": {"backend_id": backend_id}} if backend_id else {}
    overrides.setdefault("stage_chain", (_txt2img_stage(),))
    return make_pipeline_njr(
        job_id=overrides.pop("job_id", f"{backend_id or 'historical'}-canonical"),
        positive_prompt="a lighthouse at dusk",
        negative_prompt="lowres, blurry",
        base_model="sdxl.safetensors",
        sampler_name="Euler a",
        steps=24,
        cfg_scale=5.5,
        width=832,
        height=1216,
        seed=overrides.pop("seed", 424242),
        # The frozen (empty) global prompt policy makes the NJR the only prompt authority; without
        # it the executor falls back to the mutable legacy global prompt files/defaults.
        config=apply_global_prompt_policy(
            {
                "model": "sdxl.safetensors",
                "vae": "sdxl_vae.safetensors",
                "prompt": "a lighthouse at dusk",
                "negative_prompt": "lowres, blurry",
                "sampler_name": "Euler a",
                "scheduler": "Karras",
                "steps": 24,
                "cfg_scale": 5.5,
                "width": 832,
                "height": 1216,
            },
            positive_enabled=False,
            positive_text="",
            negative_enabled=False,
            negative_text="",
        ),
        backend_options=backend_options,
        **overrides,
    )


def _run(njr, transport: FakeWebUITransport, cls: type[SDWebUIClient] = ForgeWebUIClient):
    return run_njr_via_queue(njr, _client(cls, transport), timeout_seconds=30.0)


def test_forge_txt2img_enters_through_queue_and_records_forge_identity_everywhere() -> None:
    transport = FakeWebUITransport(flavor="forge", modules=[VAE])
    entry = _run(_njr("forge_webui"), transport)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    # history/provenance: the repository snapshot and the normalized result both carry the identity
    snapshot = (entry.snapshot or {}).get("normalized_job", {})
    assert snapshot["workload"]["backend_options"]["image"]["backend_id"] == "forge_webui"
    assert (entry.result or {}).get("metadata", {}).get("image_backend_id") == "forge_webui"
    variants = (entry.result or {}).get("variants") or []
    assert variants and variants[0].get("image_backend_id") == "forge_webui"

    # exactly one txt2img generation POST; request preserves the authorized intent
    assert [path for _, path, _ in transport.generation_calls] == ["/sdapi/v1/txt2img"]
    payload = transport.payloads["/sdapi/v1/txt2img"][0]
    assert "a lighthouse at dusk" in payload["prompt"]
    assert payload["negative_prompt"] == "lowres, blurry"
    assert (payload["steps"], payload["cfg_scale"]) == (24, 5.5)
    assert (payload["width"], payload["height"]) == (832, 1216)
    assert payload["seed"] == 424242
    assert payload["sampler_name"] == "Euler a"
    assert payload["scheduler"] == "Karras"


def test_forge_vae_is_selected_through_sd_modules_and_forge_additional_modules() -> None:
    transport = FakeWebUITransport(flavor="forge", modules=[VAE])
    entry = _run(_njr("forge_webui"), transport)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert "/sdapi/v1/sd-modules" in transport.paths("GET")
    assert "/sdapi/v1/sd-vae" in transport.paths("GET")  # conflict check during identity probe
    option_writes = [b for v, p, b in transport.calls if v == "POST" and p == "/sdapi/v1/options"]
    assert {"forge_additional_modules": ["sdxl_vae.safetensors"]} in option_writes
    assert not any("sd_vae" in (body or {}) for body in option_writes)
    assert transport.options["forge_additional_modules"] == ["/models/VAE/sdxl_vae.safetensors"]


def test_forge_txt2img_adetailer_upscale_chain_uses_the_current_stage_contracts() -> None:
    chain = (
        _txt2img_stage(),
        make_stage_config(
            "adetailer",
            model="sdxl.safetensors",
            extra={"adetailer_model": "face_yolov8n.pt", "prompt": "detailed face"},
        ),
        make_stage_config(
            "upscale",
            model="sdxl.safetensors",
            extra={"upscaler": "R-ESRGAN 4x+", "upscale_factor": 2.0},
        ),
    )
    transport = FakeWebUITransport(flavor="forge", modules=[VAE])
    entry = _run(_njr("forge_webui", stage_chain=chain, job_id="forge-chain"), transport)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    posts = [path for _, path, _ in transport.generation_calls]
    assert posts[0] == "/sdapi/v1/txt2img"
    assert "/sdapi/v1/img2img" in posts  # ADetailer rides the img2img REST endpoint
    assert posts[-1] == "/sdapi/v1/extra-single-image"  # upscale keeps the extras path
    adetailer_payload = transport.payloads["/sdapi/v1/img2img"][0]
    script = adetailer_payload["alwayson_scripts"]["ADetailer"]
    assert script["args"][0] is True  # the real ADetailer REST contract, not a substitute detector
    assert any(
        isinstance(arg, dict) and arg.get("ad_model") == "face_yolov8n.pt" for arg in script["args"]
    )
    assert (entry.result or {}).get("metadata", {}).get("image_backend_id") == "forge_webui"


@pytest.mark.parametrize("seed", [424242, 0, -1])
@pytest.mark.parametrize("backend,client_type", [("a1111_webui", SDWebUIClient),
                                               ("forge_webui", ForgeWebUIClient)])
def test_adetailer_canonical_seed_reaches_both_backends_and_metadata(seed, backend, client_type, tmp_path):
    image = tmp_path / "input.png"
    image.write_bytes(base64.b64decode(TINY_PNG_B64))
    record = _njr(backend, seed=seed, start_stage="adetailer", input_image_paths=[str(image)],
                  stage_chain=(make_stage_config("adetailer", model="sdxl.safetensors",
                                                 extra={"seed": 999999}),))
    before = record.to_dict()
    transport = FakeWebUITransport(flavor="forge" if backend == "forge_webui" else "a1111",
                                   modules=[VAE], seed=987654)
    entry = run_njr_via_queue(record, _client(client_type, transport), artifact_root=tmp_path / "run")
    assert entry.status is JobStatus.COMPLETED, entry.error_message
    payload = transport.payloads["/sdapi/v1/img2img"][0]
    assert payload["seed"] == seed  # Immutable NJR provenance wins over stale stage extras.
    face, hand = payload["alwayson_scripts"]["ADetailer"]["args"][2:]
    for args, k in ((face, 3), (hand, 6)):
        assert "ad_mask_only_top_k_largest" not in args
        assert args["ad_mask_filter_method"] == "Area" and args["ad_mask_k"] == k
    variants = entry.result["variants"]
    assert variants
    for manifest in variants:
        assert manifest["requested_seed"] == manifest["seeds"]["original_seed"] == payload["seed"]
        assert manifest["actual_seed"] == manifest["seeds"]["final_seed"] == 987654
    assert record.to_dict() == before


@pytest.mark.parametrize(
    ("backend_id", "endpoint_flavor"),
    [
        ("forge_webui", "a1111"),  # forge NJR + identified A1111
        ("a1111_webui", "forge"),  # a1111 NJR + identified Forge
        (None, "forge"),  # historical no-ID NJR resolves to a1111, then mismatch
    ],
)
def test_identity_mismatch_fails_the_job_before_any_generation_post(
    backend_id: str | None, endpoint_flavor: str
) -> None:
    transport = FakeWebUITransport(flavor=endpoint_flavor, modules=[VAE])
    client_cls = ForgeWebUIClient if endpoint_flavor == "forge" else SDWebUIClient
    entry = _run(
        _njr(backend_id, job_id=f"mismatch-{backend_id}-{endpoint_flavor}"), transport, client_cls
    )

    assert entry.status is JobStatus.FAILED
    assert "identity mismatch" in (entry.error_message or "") or "identity mismatch" in str(
        entry.result or {}
    )
    assert transport.generation_calls == []  # failure before POST is safe
    assert not [c for c in transport.calls if c[0] == "POST" and c[1] == "/sdapi/v1/options"]


def test_a1111_njr_on_a1111_endpoint_is_unchanged_by_the_forge_guard() -> None:
    transport = FakeWebUITransport(flavor="a1111", modules=[VAE])
    entry = _run(_njr("a1111_webui", job_id="a1111-parity"), transport, SDWebUIClient)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert (entry.result or {}).get("metadata", {}).get("image_backend_id") == "a1111_webui"
    assert [path for _, path, _ in transport.generation_calls] == ["/sdapi/v1/txt2img"]
    assert "/sdapi/v1/sd-modules" in transport.paths("GET")  # identity probe only; read-only


def test_ambiguous_dispatched_forge_generation_post_is_never_replayed() -> None:
    transport = FakeWebUITransport(
        flavor="forge",
        modules=[VAE],
        generation_error=requests.ReadTimeout("response lost after dispatch"),
    )
    entry = _run(_njr("forge_webui", job_id="forge-ambiguous"), transport)

    assert entry.status is JobStatus.FAILED
    posts = [path for _, path, _ in transport.generation_calls]
    assert posts == ["/sdapi/v1/txt2img"]  # one POST only: no client retry, no queue replay


def test_generation_paths_constant_covers_the_endpoints_the_forge_backend_may_use() -> None:
    assert set(GENERATION_PATHS) == {
        "/sdapi/v1/txt2img",
        "/sdapi/v1/img2img",
        "/sdapi/v1/extra-single-image",
    }


@pytest.mark.parametrize("backend", ["forge_webui", "a1111_webui", None])
def test_cmd_flags_500_preserves_positive_identity_and_historical_guard(backend):
    from tests.helpers.fake_webui_transport import FakeResponse

    class BrokenFlags(FakeWebUITransport):
        def _get(self, path):
            if path == "/sdapi/v1/cmd-flags":
                return FakeResponse({"detail": "upstream response validation"}, 500)
            return super()._get(path)

    transport = BrokenFlags(flavor="forge", modules=[VAE])
    entry = _run(_njr(backend, job_id=f"cmd500-{backend}"), transport)
    if backend == "forge_webui":
        assert entry.status is JobStatus.COMPLETED, entry.error_message
        assert len(transport.generation_calls) == 1  # mocked only
    else:
        assert entry.status is JobStatus.FAILED
        assert not transport.generation_calls
        assert not [c for c in transport.calls if c[0] == "POST"]
