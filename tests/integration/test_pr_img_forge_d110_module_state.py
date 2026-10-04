"""PR-IMG-FORGE-D110: ordinary Forge work never inherits a previous job's persisted module state.

D100 found that a managed Forge left holding the FLUX.2 Klein modules (``flux2-vae`` + ``qwen_3_4b``)
loaded an ordinary SDXL checkpoint with them and answered HTTP 500. These tests drive the canonical
path (``NJR -> JobService -> SQLite -> PipelineRunner.run_njr -> ForgeWebUIImageBackend -> executor ->
ForgeWebUIClient``) against a stateful Forge-shaped fake whose ``forge_additional_modules`` option
persists across jobs and which rejects an SDXL generation made with Klein modules, exactly like the
real endpoint. Only ``requests.Session.request`` (and the Klein host-memory/asset probes) are replaced.
"""

from __future__ import annotations

import pytest

import src.image_backends.forge_webui_backend as forge_backend_module
from src.api.client import SDWebUIClient
from src.api.forge_client import ForgeWebUIClient
from src.image_backends import A1111WebUIImageBackend
from src.image_backends.forge_klein_profile import KLEIN_PROFILE_ID
from src.image_backends.forge_klein_readiness import HostMemorySnapshot
from src.queue.job_model import JobStatus
from tests.helpers.fake_webui_transport import FakeWebUITransport
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config
from tests.helpers.njr_queue_harness import run_njr_via_queue

KLEIN = "flux-2-klein-4b-fp8.safetensors"
SDXL = "sdxl.safetensors"
MODULES = [
    {"model_name": "qwen_3_4b.safetensors", "filename": "/data/models/text_encoder/qwen_3_4b.safetensors"},
    {"model_name": "flux2-vae.safetensors", "filename": "/data/models/VAE/flux2-vae.safetensors"},
    {"model_name": "sdxl_vae.safetensors", "filename": "/data/models/VAE/sdxl_vae.safetensors"},
]
KLEIN_RESIDUE = [m["filename"] for m in MODULES[:2]]  # what D100 found persisted on the managed Forge
_STUB_IDENTITY = {"transformer": {"name": KLEIN, "verified": "sha256"}}


def _klein_modules_on_an_ordinary_checkpoint(options: dict) -> str | None:
    """Forge's real failure: an SDXL checkpoint loaded with the Flux.2 VAE / Qwen text encoder."""

    modules = [str(m).rsplit("/", 1)[-1] for m in options.get("forge_additional_modules") or []]
    if "klein" not in str(options.get("sd_model_checkpoint", "")).lower() and any(
        m.startswith(("qwen", "flux2")) for m in modules
    ):
        return f"Error(s) in loading state_dict for IntegratedAutoencoderKL (modules {modules})"
    return None


@pytest.fixture(autouse=True)
def _qualified_klein_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        forge_backend_module,
        "read_host_memory",
        lambda: HostMemorySnapshot(total_bytes=34_107_092_992, available_bytes=17_000_000_000),
    )
    monkeypatch.setattr(forge_backend_module, "verify_klein_assets", lambda profile, **_k: _STUB_IDENTITY)


def _client(transport: FakeWebUITransport, cls: type[SDWebUIClient] = ForgeWebUIClient) -> SDWebUIClient:
    client = cls(base_url="http://127.0.0.1:7861", options_write_enabled=True)
    client._session.request = transport  # type: ignore[method-assign]
    client._options_min_interval_seconds = 0.0
    return client


def _forge(*, checkpoint: str = SDXL, residue: list[str] | None = None, **kwargs) -> FakeWebUITransport:
    transport = FakeWebUITransport(
        flavor="forge",
        checkpoint=checkpoint,
        modules=MODULES,
        reject_generation_when=kwargs.pop("reject_generation_when", _klein_modules_on_an_ordinary_checkpoint),
        **kwargs,
    )
    if residue is not None:
        transport.options["forge_additional_modules"] = list(residue)
    return transport


def _sdxl_njr(*, vae: str = "Automatic", chain: tuple[str, ...] = ("txt2img",), backend: str = "forge_webui", job_id: str = "d110-sdxl"):
    stages = {
        "txt2img": make_stage_config(
            "txt2img", steps=24, cfg_scale=5.5, sampler_name="Euler a", scheduler="Karras", model=SDXL, vae=vae
        ),
        "adetailer": make_stage_config(
            "adetailer", model=SDXL, vae=vae, extra={"adetailer_model": "face_yolov8n.pt", "prompt": "detailed face"}
        ),
        "upscale": make_stage_config(
            "upscale", model=SDXL, vae=vae, extra={"upscaler": "R-ESRGAN 4x+", "upscale_factor": 1.5}
        ),
    }
    return make_pipeline_njr(
        job_id=job_id,
        positive_prompt="a lighthouse at dusk",
        negative_prompt="lowres",
        base_model=SDXL,
        sampler_name="Euler a",
        steps=24,
        cfg_scale=5.5,
        width=832,
        height=1216,
        seed=424242,
        stage_chain=tuple(stages[name] for name in chain),
        config={
            "model": SDXL, "vae": vae, "prompt": "a lighthouse at dusk", "sampler_name": "Euler a",
            "scheduler": "Karras", "steps": 24, "cfg_scale": 5.5, "width": 832, "height": 1216,
        },
        backend_options={"image": {"backend_id": backend}},
    )


def _klein_njr(job_id: str = "d110-klein"):
    config = {
        "model": KLEIN, "prompt": "portrait", "sampler_name": "Euler", "scheduler": "Beta", "steps": 4,
        "cfg_scale": 1.0, "width": 768, "height": 1024, "negative_prompt": "",
        "prompt_optimizer": {"enabled": False},
        "pipeline": {"apply_global_negative_txt2img": False, "apply_global_positive_txt2img": False},
        "global_positive_prompt": "", "global_negative_prompt": "", "global_prompt_policy_source": "frozen_njr",
    }
    return make_pipeline_njr(
        job_id=job_id, positive_prompt="portrait of an adult on a rainy street", negative_prompt="",
        base_model=KLEIN, sampler_name="Euler", steps=4, cfg_scale=1.0, width=768, height=1024, seed=424242,
        stage_chain=(make_stage_config("txt2img", steps=4, cfg_scale=1.0, sampler_name="Euler", scheduler="Beta", model=KLEIN),),
        config=config,
        backend_options={"image": {"backend_id": "forge_webui", "model_profile": {"id": KLEIN_PROFILE_ID, "version": 1}}},
    )


def _run(njr, transport, cls: type[SDWebUIClient] = ForgeWebUIClient):
    """One job on a brand-new client/runner/executor stack against the (persistent) endpoint."""

    return run_njr_via_queue(njr, _client(transport, cls), timeout_seconds=60.0)


def _module_writes(transport: FakeWebUITransport) -> list[list[str]]:
    return [
        body["forge_additional_modules"]
        for verb, path, body in transport.calls
        if verb == "POST" and path == "/sdapi/v1/options" and "forge_additional_modules" in (body or {})
    ]


def _first_index(transport: FakeWebUITransport, predicate) -> int:
    return next(i for i, call in enumerate(transport.calls) if predicate(call))


def _is_generation(call) -> bool:
    return call[0] == "POST" and call[1] in ("/sdapi/v1/txt2img", "/sdapi/v1/img2img", "/sdapi/v1/extra-single-image")


def _names(options: dict) -> list[str]:
    return sorted(str(m).rsplit("/", 1)[-1] for m in options.get("forge_additional_modules") or [])


# ------------------------------------------------------------------------------------ A, B


def test_klein_residue_is_cleared_before_the_ordinary_sdxl_model_can_load() -> None:  # A
    transport = _forge(residue=KLEIN_RESIDUE)
    entry = _run(_sdxl_njr(), transport)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert transport.rejected_generations == []
    assert transport.generation_module_state == [[]]  # the exact empty set at the moment of generation
    assert _names(transport.options) == []
    assert _module_writes(transport) == [[]]  # one verified clear through the existing module write
    clear = _first_index(transport, lambda c: c[1] == "/sdapi/v1/options" and c[2] == {"forge_additional_modules": []})
    assert clear < _first_index(transport, _is_generation)
    assert len(transport.generation_calls) == 1
    meta = ((entry.result or {}).get("variants") or [{}])[0].get("image_backend_metadata", {})
    baseline = meta["forge_module_baseline"]
    assert baseline["applied"] is True and sorted(baseline["observed_before"]) == ["flux2-vae.safetensors", "qwen_3_4b.safetensors"]
    assert baseline["required"] == []


def test_without_the_normalization_the_dirty_endpoint_fails_like_d100(monkeypatch: pytest.MonkeyPatch) -> None:  # B
    monkeypatch.setattr(
        forge_backend_module.ForgeWebUIImageBackend, "_normalize_module_baseline", lambda self, pipeline, request: {}
    )
    transport = _forge(residue=KLEIN_RESIDUE)
    entry = _run(_sdxl_njr(job_id="d110-old-behavior"), transport)

    assert entry.status is JobStatus.FAILED  # the pre-D110 behavior: stale modules reach the model load
    assert transport.rejected_generations and "IntegratedAutoencoderKL" in transport.rejected_generations[0]
    assert _module_writes(transport) == []  # nothing ever cleared them


# ------------------------------------------------------------------------------------ C, D


def test_a_new_executor_instance_still_detects_state_left_by_a_klein_job() -> None:  # C
    transport = _forge(checkpoint=KLEIN)
    klein = _run(_klein_njr(), transport)
    assert klein.status is JobStatus.COMPLETED, klein.error_message
    assert _names(transport.options) == ["flux2-vae.safetensors", "qwen_3_4b.safetensors"]  # persistent residue

    sdxl = _run(_sdxl_njr(job_id="d110-after-klein"), transport)  # fresh client/runner/executor: no in-memory cache
    assert sdxl.status is JobStatus.COMPLETED, sdxl.error_message
    assert transport.rejected_generations == []
    assert transport.generation_module_state == [["flux2-vae.safetensors", "qwen_3_4b.safetensors"], []]
    assert _names(transport.options) == []


def test_an_already_clean_automatic_endpoint_is_not_written_to() -> None:  # D
    transport = _forge()
    entry = _run(_sdxl_njr(), transport)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert _module_writes(transport) == []
    meta = ((entry.result or {}).get("variants") or [{}])[0].get("image_backend_metadata", {})
    assert meta["forge_module_baseline"]["applied"] is False
    assert len(transport.generation_calls) == 1


# ------------------------------------------------------------------------------------ E


def test_klein_residue_does_not_survive_an_explicit_sdxl_vae_job() -> None:  # E
    transport = _forge(checkpoint=KLEIN)
    assert _run(_klein_njr(), transport).status is JobStatus.COMPLETED

    entry = _run(_sdxl_njr(vae="sdxl_vae.safetensors", job_id="d110-explicit-vae"), transport)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert transport.rejected_generations == []
    assert transport.generation_module_state[-1] == ["sdxl_vae.safetensors"]  # the requested VAE, and nothing else
    assert _names(transport.options) == ["sdxl_vae.safetensors"]
    sdxl_writes = _module_writes(transport)[1:]  # after the Klein job's own exact write
    assert sdxl_writes and all(w == ["sdxl_vae.safetensors"] for w in sdxl_writes)  # never silently dropped or replaced


# ------------------------------------------------------------------------------------ F


@pytest.mark.parametrize("vae", ["Automatic", "sdxl_vae.safetensors"])
def test_a_stage_chain_normalizes_once_and_never_reapplies_valid_state(vae: str) -> None:  # F
    transport = _forge(residue=KLEIN_RESIDUE)
    entry = _run(_sdxl_njr(vae=vae, chain=("txt2img", "adetailer", "upscale"), job_id="d110-chain"), transport)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    posts = [p for _, p, _ in transport.generation_calls]
    assert posts[0] == "/sdapi/v1/txt2img" and "/sdapi/v1/img2img" in posts and posts[-1] == "/sdapi/v1/extra-single-image"
    assert transport.rejected_generations == []
    expected = [] if vae == "Automatic" else ["sdxl_vae.safetensors"]
    assert all(state == expected for state in transport.generation_module_state)  # valid at every stage dispatch
    writes = _module_writes(transport)
    assert writes[0] == expected  # the one normalization, before the first generation
    clears = [w for w in writes if w == []]
    assert len(clears) <= 1  # never destroyed/reapplied between stages


# ------------------------------------------------------------------------------------ G


def test_klein_still_applies_and_verifies_its_exact_two_module_set_without_a_preceding_clear() -> None:  # G
    transport = _forge(checkpoint=KLEIN, residue=[MODULES[2]["filename"]])  # an unrelated stale VAE
    entry = _run(_klein_njr(), transport)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    writes = _module_writes(transport)
    assert writes == [["qwen_3_4b.safetensors", "flux2-vae.safetensors"]]  # exact set, no clear-to-empty first
    assert transport.generation_module_state == [["flux2-vae.safetensors", "qwen_3_4b.safetensors"]]
    meta = ((entry.result or {}).get("variants") or [{}])[0].get("image_backend_metadata", {})
    assert "klein_profile" in meta and "forge_module_baseline" not in meta


# ------------------------------------------------------------------------------------ H


def test_unreadable_module_state_fails_before_any_dispatch_or_write(monkeypatch: pytest.MonkeyPatch) -> None:  # H
    transport = _forge(residue=KLEIN_RESIDUE)
    monkeypatch.setattr(ForgeWebUIClient, "get_additional_modules", lambda self: None)
    entry = _run(_sdxl_njr(job_id="d110-unreadable"), transport)

    assert entry.status is JobStatus.FAILED
    assert "module" in str(entry.error_message).lower()
    assert transport.generation_calls == [] and _module_writes(transport) == []


def test_a_clear_that_does_not_stick_fails_before_generation() -> None:  # H
    transport = _forge(residue=KLEIN_RESIDUE, ignore_module_writes=True)
    entry = _run(_sdxl_njr(job_id="d110-unverified"), transport)

    assert entry.status is JobStatus.FAILED
    assert transport.generation_calls == []  # never guessed empty, never dispatched
    assert _names(transport.options) == ["flux2-vae.safetensors", "qwen_3_4b.safetensors"]


def test_a_refused_module_write_fails_before_generation(monkeypatch: pytest.MonkeyPatch) -> None:  # H
    transport = _forge(residue=KLEIN_RESIDUE)
    monkeypatch.setattr(ForgeWebUIClient, "set_additional_modules", lambda self, modules: False)
    entry = _run(_sdxl_njr(job_id="d110-refused"), transport)

    assert entry.status is JobStatus.FAILED
    assert transport.generation_calls == []


# ------------------------------------------------------------------------------------ I


def test_a1111_work_never_touches_the_forge_module_api() -> None:  # I
    transport = FakeWebUITransport(flavor="a1111", modules=[MODULES[2]])
    entry = _run(_sdxl_njr(vae="sdxl_vae.safetensors", backend="a1111_webui", job_id="d110-a1111"), transport, SDWebUIClient)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    # (the shared identity probe lists /sd-modules for either flavor; that is unchanged read-only behavior)
    assert not hasattr(A1111WebUIImageBackend, "_normalize_module_baseline")
    assert not any("forge_additional_modules" in (body or {}) for _, _, body in transport.calls)
    meta = ((entry.result or {}).get("variants") or [{}])[0].get("image_backend_metadata", {})
    assert "forge_module_baseline" not in meta
