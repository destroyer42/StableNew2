"""PR-IMG-117: FLUX.2 Klein 4B FP8 profile v2 (one qualified LoRA) through the canonical path (fakes only).

``NJR -> JobService -> SQLite -> PipelineRunner.run_njr -> ForgeWebUIImageBackend -> executor ->
ForgeWebUIClient``. Only ``requests.Session.request``, the host-memory probe, the asset-identity check, the LoRA
registry resolver and the managed-runtime log tail are replaced, so no WebUI, model or GPU is used. They are the
deterministic stand-ins for the physical acceptance recorded in ``PR-IMG-117``.
"""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

import src.image_backends.forge_webui_backend as forge_backend_module
from src.api.forge_client import ForgeWebUIClient
from src.image_backends.forge_klein_lora import (
    KleinLoraDecision,
    KleinLoraStatus,
    unavailable_decision,
)
from src.image_backends.forge_klein_profile import (
    KLEIN_PROFILE_ID,
    KLEIN_PROFILE_V1,
    KLEIN_PROFILE_V2,
    latest_klein_profile,
    resolve_model_profile,
)
from src.image_backends.forge_klein_readiness import HostMemorySnapshot
from src.pipeline.job_models_v2 import LoRATag, NormalizedJobRecord
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.queue.job_model import JobStatus
from tests.helpers.fake_webui_transport import FakeWebUITransport
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config
from tests.helpers.njr_queue_harness import run_njr_via_queue

KLEIN = "flux-2-klein-4b-fp8.safetensors"
MODULES = [
    {"model_name": "qwen_3_4b.safetensors", "filename": "/data/models/text_encoder/qwen_3_4b.safetensors"},
    {"model_name": "flux2-vae.safetensors", "filename": "/data/models/VAE/flux2-vae.safetensors"},
]
V1 = {"id": KLEIN_PROFILE_ID, "version": 1}
V2 = {"id": KLEIN_PROFILE_ID, "version": 2}
SHA = "0d028797b10e46e049cf2953bf14c486cbf511c336a6d99df7848979cf90f4bd"
LORA = "klein-style"
LORA_PATH = "/virtual/stable-diffusion-webui/models/Lora/klein-style.safetensors"
LOADED = (
    "[LORA] Loaded klein-style.safetensors  networks.py :: INFO\n"
    "for KModel-UNet with 80 keys at weight 0.8 (skipped 0\n"
    "keys) with on_the_fly = False"
)
MISMATCH = "[LORA] LoRA mismatch for KModel: klein-style.safetensors  networks.py :: WARNING"


def compatible(name: str = LORA) -> KleinLoraDecision:
    return KleinLoraDecision(
        name, KleinLoraStatus.COMPATIBLE, "explicit FLUX.2 Klein 4B metadata",
        "embedded_metadata:ss_base_model_version", "flux2_klein_4b", SHA,
    )


class FakeResolver:
    def __init__(self, decisions: dict[str, KleinLoraDecision], paths: dict[str, tuple[str, ...]] | None = None) -> None:
        self.decisions = decisions
        self.paths = paths if paths is not None else {LORA: (LORA_PATH,)}

    def __call__(self, name: str) -> KleinLoraDecision:
        return self.decisions.get(name) or unavailable_decision(name, "not found in the local asset registry")

    def locations_for(self, name: str) -> tuple[str, ...]:
        return self.paths.get(name, ())


@pytest.fixture
def resolver(monkeypatch: pytest.MonkeyPatch) -> FakeResolver:
    fake = FakeResolver({LORA: compatible()})
    monkeypatch.setattr(forge_backend_module, "RegistryLoraResolver", lambda *a, **k: fake)
    return fake


@pytest.fixture
def forge_log(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The managed runtime's output tail the backend reads (the existing manager authority; faked)."""

    state = SimpleNamespace(stdout_tail=LOADED)
    manager = SimpleNamespace(
        get_recent_output_tail=lambda max_lines=200: {"stdout_tail": state.stdout_tail, "stderr_tail": ""}
    )
    monkeypatch.setattr(forge_backend_module, "_active_manager", lambda: manager)
    return state


@pytest.fixture(autouse=True)
def _qualified_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        forge_backend_module,
        "read_host_memory",
        lambda: HostMemorySnapshot(total_bytes=34_107_092_992, available_bytes=17_000_000_000),
    )
    monkeypatch.setattr(
        forge_backend_module, "verify_klein_assets", lambda profile, **_k: {"transformer": {"name": KLEIN}}
    )
    monkeypatch.setattr("src.image_backends.image_backend_types.configured_image_backend_id", lambda: "forge_webui")


def _client(transport: FakeWebUITransport) -> ForgeWebUIClient:
    client = ForgeWebUIClient(base_url="http://127.0.0.1:7861", options_write_enabled=True)
    client._session.request = transport  # type: ignore[method-assign]
    client._options_min_interval_seconds = 0.0
    return client


def _transport(*, loras: list[dict] | None = None) -> FakeWebUITransport:
    listed = loras if loras is not None else [{"name": LORA, "alias": LORA, "path": LORA_PATH}]
    return FakeWebUITransport(flavor="forge", checkpoint=KLEIN, modules=MODULES, loras=listed)


def _njr(prompt: str = f"portrait <lora:{LORA}:0.8>", *, profile=V2, declared=True, **overrides):
    config = {
        "model": KLEIN, "prompt": prompt, "sampler_name": "Euler", "scheduler": "Beta", "steps": 4,
        "cfg_scale": 1.0, "width": 768, "height": 1024, "negative_prompt": "",
        "prompt_optimizer": {"enabled": False},
        "pipeline": {"apply_global_negative_txt2img": False, "apply_global_positive_txt2img": False},
        "global_positive_prompt": "", "global_negative_prompt": "", "global_prompt_policy_source": "frozen_njr",
    }
    config.update(overrides.pop("config", {}))
    image = {"backend_id": overrides.pop("backend_id", "forge_webui")}
    if profile is not None:
        image["model_profile"] = profile
    return make_pipeline_njr(
        job_id=overrides.pop("job_id", "klein-lora"),
        positive_prompt=prompt,
        negative_prompt=overrides.pop("negative_prompt", ""),
        base_model=overrides.pop("base_model", KLEIN),
        sampler_name="Euler", steps=4, cfg_scale=1.0, width=768, height=1024, seed=424242,
        stage_chain=overrides.pop("stage_chain", (
            make_stage_config("txt2img", steps=4, cfg_scale=1.0, sampler_name="Euler", scheduler="Beta", model=KLEIN),
        )),
        config=config,
        backend_options={"image": image},
        lora_tags=((LoRATag(LORA, 0.8),) if declared else ()),
        **overrides,
    )


def _run(njr, transport, **kwargs):
    return run_njr_via_queue(njr, _client(transport), timeout_seconds=60.0, **kwargs)


def _failed_before_any_generation(entry, transport, *needles: str) -> None:
    assert entry.status is JobStatus.FAILED
    assert transport.generation_calls == []
    text = str(entry.error_message or "")
    for needle in needles:
        assert needle in text, (needle, text)


# --- profile versions ----------------------------------------------------------------------------


def test_v2_is_published_alongside_an_unchanged_v1_and_is_what_new_work_uses() -> None:
    assert resolve_model_profile({"image": {"model_profile": V1}}) is KLEIN_PROFILE_V1
    assert resolve_model_profile({"image": {"model_profile": V2}}) is KLEIN_PROFILE_V2
    assert latest_klein_profile() is KLEIN_PROFILE_V2
    assert (KLEIN_PROFILE_V1.version, KLEIN_PROFILE_V1.max_loras) == (1, 0)
    assert (KLEIN_PROFILE_V2.version, KLEIN_PROFILE_V2.max_loras) == (2, 1)
    # v2's only intended envelope expansion is the bounded single-LoRA capability
    assert replace(KLEIN_PROFILE_V2, version=1, max_loras=0) == KLEIN_PROFILE_V1


# --- v2: exactly one explicitly compatible LoRA -----------------------------------------------------


def test_v2_runs_one_compatible_lora_once_and_records_path_free_evidence(resolver, forge_log) -> None:
    transport = _transport()
    entry = _run(_njr(), transport)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert [p for _, p, _ in transport.generation_calls] == ["/sdapi/v1/txt2img"]
    payload = transport.payloads["/sdapi/v1/txt2img"][0]
    assert f"<lora:{LORA}:0.8>" in payload["prompt"]
    assert payload["negative_prompt"] == ""
    assert (payload["sampler_name"], payload["scheduler"], payload["steps"], payload["cfg_scale"]) == ("Euler", "Beta", 4, 1.0)
    evidence = ((entry.result or {}).get("variants") or [{}])[0]["image_backend_metadata"]["klein_profile"]
    assert evidence["model_profile"] == V2
    lora = evidence["lora"]
    assert (lora["name"], lora["requested_weight"], lora["sha256"]) == (LORA, 0.8, SHA)
    assert lora["compatibility"] == {
        "status": "compatible",
        "evidence_source": "embedded_metadata:ss_base_model_version",
        "evidence_raw_value": "flux2_klein_4b",
    }
    assert lora["served"] == {"listed": True, "path_bound_to_registry_identity": True}
    assert lora["observation"]["consumed"] is True and lora["observation"]["keys"] == 80
    assert "/virtual" not in json.dumps(evidence) and "\\" not in json.dumps(lora)  # no machine-local path


def test_v2_without_a_lora_is_the_same_qualified_run(resolver, forge_log) -> None:
    transport = _transport()
    entry = _run(_njr("portrait", declared=False), transport)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    evidence = ((entry.result or {}).get("variants") or [{}])[0]["image_backend_metadata"]["klein_profile"]
    assert "lora" not in evidence and len(transport.generation_calls) == 1


def test_a_lora_name_and_weight_survive_serialization_and_replay(resolver) -> None:
    njr = _njr()
    restored = NormalizedJobRecord.from_dict(njr.to_dict())
    assert [(t.name, t.weight) for t in restored.lora_tags] == [(LORA, 0.8)]
    assert f"<lora:{LORA}:0.8>" in restored.positive_prompt

    replayed = compile_replay_intent(ReplayIntent(record=restored))
    assert replayed.job_id != restored.job_id and replayed.source.parent_job_id == restored.job_id
    assert resolve_model_profile(replayed.backend_options) is KLEIN_PROFILE_V2
    assert [(t.name, t.weight) for t in replayed.lora_tags] == [(LORA, 0.8)]
    assert replayed.positive_prompt == restored.positive_prompt


def test_a_persisted_v1_record_replays_as_v1_and_is_never_upgraded() -> None:
    njr = _njr(profile=V1, declared=False, prompt="portrait")
    restored = NormalizedJobRecord.from_dict(njr.to_dict())
    replayed = compile_replay_intent(ReplayIntent(record=restored))

    assert resolve_model_profile(replayed.backend_options) is KLEIN_PROFILE_V1
    assert replayed.backend_options["image"]["model_profile"] == V1


# --- v2 rejections happen before any generation POST ------------------------------------------------


def test_two_loras_are_rejected_before_dispatch(resolver, forge_log) -> None:
    resolver.decisions["other"] = compatible("other")
    transport = _transport()
    entry = _run(_njr(f"portrait <lora:{LORA}:0.8> <lora:other:0.5>", declared=False), transport)

    _failed_before_any_generation(entry, transport, "2 LoRAs", "at most 1")


@pytest.mark.parametrize(
    ("status", "needle"),
    [
        (KleinLoraStatus.UNVERIFIED, "unverified"),
        (KleinLoraStatus.INCOMPATIBLE, "incompatible"),
        (KleinLoraStatus.CONFLICTING, "conflicting"),
    ],
)
def test_an_unverified_incompatible_or_conflicting_lora_is_rejected_before_dispatch(resolver, forge_log, status, needle) -> None:
    resolver.decisions[LORA] = KleinLoraDecision(LORA, status, "because")
    transport = _transport()
    entry = _run(_njr(), transport)

    _failed_before_any_generation(entry, transport, "not verified for FLUX.2 Klein 4B", needle)


def test_an_adapter_the_registry_does_not_know_is_rejected_with_an_explanation(resolver, forge_log) -> None:
    resolver.decisions.clear()
    transport = _transport()
    entry = _run(_njr(), transport)

    _failed_before_any_generation(entry, transport, "not found in the local asset registry")


@pytest.mark.parametrize("weight", ["0", "-0.5", "2.5", "nan", "inf"])
def test_a_bad_weight_is_rejected_before_dispatch(resolver, forge_log, weight) -> None:
    transport = _transport()
    entry = _run(_njr(f"portrait <lora:{LORA}:{weight}>", declared=False), transport)

    _failed_before_any_generation(entry, transport)


def test_a_declared_lora_that_is_not_in_the_prompt_is_not_silently_dropped(resolver, forge_log) -> None:
    transport = _transport()
    entry = _run(_njr("portrait", declared=True), transport)

    _failed_before_any_generation(entry, transport, "declared by the job but is not in the prompt")


def test_negative_prompts_and_global_terms_stay_unsupported_for_v2(resolver, forge_log) -> None:
    transport = _transport()
    entry = _run(_njr(negative_prompt="ugly, blurry"), transport)
    _failed_before_any_generation(entry, transport, "negative prompt is not supported")

    transport = _transport()
    entry = _run(_njr(config={"global_positive_prompt": "masterpiece"}, job_id="klein-globals"), transport)
    _failed_before_any_generation(entry, transport, "global positive prompt terms")

    transport = _transport()
    entry = _run(_njr(config={"prompt_optimizer": {"enabled": True}}, job_id="klein-opt"), transport)
    _failed_before_any_generation(entry, transport, "prompt optimizer")


def test_hires_and_other_unsupported_features_stay_rejected_alongside_a_lora(resolver, forge_log) -> None:
    transport = _transport()
    entry = _run(_njr(config={"hires_fix": {"enabled": True}}, job_id="klein-hires"), transport)

    _failed_before_any_generation(entry, transport, "hires fix")


def test_a_lora_is_not_qualified_for_single_reference_edit(resolver, forge_log) -> None:
    transport = _transport()
    njr = _njr(
        stage_chain=(make_stage_config("img2img", steps=4, cfg_scale=1.0, sampler_name="Euler", scheduler="Beta", model=KLEIN),),
        input_image_paths=("source.png",),
        job_id="klein-edit-lora",
    )
    entry = _run(njr, transport)

    _failed_before_any_generation(entry, transport, "text-to-image only")


def test_forge_must_list_the_adapter_it_will_load(resolver, forge_log) -> None:
    transport = _transport(loras=[])
    entry = _run(_njr(), transport)

    _failed_before_any_generation(entry, transport, f"Forge does not list the LoRA '{LORA}'")


def test_an_unreadable_forge_lora_listing_refuses_dispatch(resolver, forge_log) -> None:
    transport = _transport()
    client = _client(transport)
    client.get_loras = lambda: None  # type: ignore[method-assign]
    entry = run_njr_via_queue(_njr(), client, timeout_seconds=60.0)

    _failed_before_any_generation(entry, transport, "LoRA listing could not be read")


def test_forge_serving_a_different_file_than_the_registry_identity_is_refused(resolver, forge_log) -> None:
    transport = _transport(loras=[{"name": LORA, "alias": LORA, "path": "/elsewhere/klein-style.safetensors"}])
    entry = _run(_njr(), transport)

    _failed_before_any_generation(entry, transport, "different file than StableNew's local asset identity")


def test_a_forge_that_does_not_apply_the_adapter_fails_the_job_instead_of_recording_a_lora_result(resolver, forge_log) -> None:
    forge_log.stdout_tail = MISMATCH
    transport = _transport()
    entry = _run(_njr(), transport)

    assert entry.status is JobStatus.FAILED
    assert len(transport.generation_calls) == 1  # dispatched once, never replayed
    assert "did not apply the LoRA" in str(entry.error_message)


def test_an_absent_log_line_is_recorded_as_unobserved_not_as_failure(resolver, forge_log) -> None:
    forge_log.stdout_tail = "nothing about loras here"
    entry = _run(_njr(), _transport())

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    evidence = ((entry.result or {}).get("variants") or [{}])[0]["image_backend_metadata"]["klein_profile"]
    assert evidence["lora"]["observation"]["consumed"] is None


# --- v1 is unchanged -------------------------------------------------------------------------------


def test_v1_still_rejects_every_lora_exactly_as_before(resolver, forge_log) -> None:
    transport = _transport()
    entry = _run(_njr(profile=V1), transport)

    _failed_before_any_generation(entry, transport, "LoRA is not supported")
    assert "not verified for FLUX.2 Klein 4B" not in str(entry.error_message)  # v1 never consults compatibility


# --- ordinary behavior is unchanged -----------------------------------------------------------------


def test_an_ordinary_sdxl_forge_job_keeps_its_lora_prompt_untouched(resolver, forge_log) -> None:
    transport = FakeWebUITransport(flavor="forge", checkpoint="sdxl.safetensors", modules=[])
    njr = make_pipeline_njr(
        job_id="sdxl-lora",
        positive_prompt="portrait <lora:style:0.7>",
        base_model="sdxl.safetensors",
        backend_options={"image": {"backend_id": "forge_webui"}},
        lora_tags=(LoRATag("style", 0.7),),
    )
    entry = _run(njr, transport)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert "<lora:style:0.7>" in transport.payloads["/sdapi/v1/txt2img"][0]["prompt"]
    assert not [c for c in transport.calls if c[1] == "/sdapi/v1/loras"]  # no Klein LoRA machinery for SDXL
