"""PR-IMG-MODELS-150: installed-model readiness and the Forge dependency-state preflight.

A stateful Forge-shaped fake (no GPU, no model bytes, no network) holds an unqualified multi-component checkpoint with its
Qwen3 text encoder and FLUX.2 VAE selected. The canonical path
(``NJR -> JobService -> SQLite -> PipelineRunner.run_njr -> ForgeWebUIImageBackend -> executor -> ForgeWebUIClient``)
must refuse such work before any module write or generation POST, while ordinary SDXL work and the qualified Klein 4B
path behave exactly as before (see ``test_pr_img_forge_d110_module_state.py``). Header fixtures are tiny synthetic
safetensors files whose *shapes* carry the structural signature; real weights are never needed or read.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

import src.image_backends.forge_webui_backend as forge_backend_module
from src.api.forge_client import ForgeWebUIClient
from src.assets.component_evidence import (
    ARCH_FLUX2_DIT,
    ROLE_BUNDLED,
    ROLE_TEXT_ENCODER,
    ROLE_TRANSFORMER,
    ROLE_VAE,
    classify_tensor_table,
    inspect_component_file,
)
from src.image_backends.model_readiness import (
    CatalogModule,
    ReadinessStatus,
    assess_model_readiness,
)
from src.queue.job_model import JobStatus
from tests.helpers.fake_webui_transport import FakeWebUITransport
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config
from tests.helpers.njr_queue_harness import run_njr_via_queue

NINE_B = "flux-2-klein-base-9b.safetensors"
SDXL = "sdxl.safetensors"
HIDDEN = 64  # scaled-down hidden size: the classifier is shape-driven, so tiny files carry the same signature
_DTYPE_BYTES = {"BF16": 2, "F16": 2, "F32": 4}


# ------------------------------------------------------------------------------------------- synthetic headers


def write_safetensors(path: Path, tensors: dict[str, tuple[str, list[int]]], *, metadata: dict | None = None) -> Path:
    """A valid safetensors file with zero payload: header, offsets and sizes are consistent, weights are all zero."""

    header: dict[str, object] = {}
    offset = 0
    for name, (dtype, shape) in tensors.items():
        count = 1
        for dimension in shape:
            count *= dimension
        size = count * _DTYPE_BYTES[dtype]
        header[name] = {"dtype": dtype, "shape": shape, "data_offsets": [offset, offset + size]}
        offset += size
    if metadata:
        header["__metadata__"] = metadata
    encoded = json.dumps(header).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + bytes(offset))
    return path


def flux2_transformer(hidden: int = HIDDEN, dtype: str = "BF16", **overrides) -> dict[str, tuple[str, list[int]]]:
    table = {
        "img_in.weight": (dtype, [hidden, 128]),
        "txt_in.weight": (dtype, [hidden, hidden * 3]),
        "double_stream_modulation_img.lin.weight": (dtype, [4, hidden]),
        "double_blocks.0.img_attn.qkv.weight": (dtype, [4, hidden]),
        "double_blocks.1.img_attn.qkv.weight": (dtype, [4, hidden]),
        "single_blocks.0.linear1.weight": (dtype, [4, hidden]),
        "final_layer.linear.weight": (dtype, [4, hidden]),
    }
    table.update(overrides)
    return table


def qwen3_encoder(hidden: int = HIDDEN, dtype: str = "BF16", **overrides) -> dict[str, tuple[str, list[int]]]:
    table = {
        "model.embed_tokens.weight": (dtype, [32, hidden]),
        "model.layers.0.self_attn.q_norm.weight": (dtype, [4]),
        "model.layers.1.self_attn.q_norm.weight": (dtype, [4]),
    }
    table.update(overrides)
    return table


def flux_vae(latent: int = 32, dtype: str = "F32") -> dict[str, tuple[str, list[int]]]:
    return {
        "decoder.conv_in.weight": (dtype, [8, latent, 3, 3]),
        "decoder.conv_out.weight": (dtype, [3, 8, 3, 3]),
        "decoder.mid.block_1.conv1.weight": (dtype, [8, 8, 3, 3]),
        "bn.running_mean": ("F32", [128]),
    }


def sdxl_bundle() -> dict[str, tuple[str, list[int]]]:
    return {
        "model.diffusion_model.input_blocks.0.0.weight": ("F16", [4, 4, 3, 3]),
        "first_stage_model.decoder.conv_in.weight": ("F16", [4, 4, 3, 3]),
        "conditioner.embedders.0.transformer.text_model.embeddings.token_embedding.weight": ("F16", [4, 4]),
    }


@pytest.fixture
def models(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "models"
    for sub in ("Stable-diffusion", "text_encoder", "VAE"):
        (root / sub).mkdir(parents=True)
    return {
        "nine_b": write_safetensors(root / "Stable-diffusion" / NINE_B, flux2_transformer()),
        "sdxl": write_safetensors(root / "Stable-diffusion" / SDXL, sdxl_bundle()),
        "qwen8": write_safetensors(root / "text_encoder" / "qwen_3_8b.safetensors", qwen3_encoder()),
        "qwen4": write_safetensors(root / "text_encoder" / "qwen_3_4b.safetensors", qwen3_encoder(hidden=40)),
        "vae": write_safetensors(root / "VAE" / "flux2-vae.safetensors", flux_vae()),
        "sdxl_vae": write_safetensors(root / "VAE" / "sdxl_vae.safetensors", flux_vae(latent=4)),
    }


def _modules(models: dict[str, Path], *keys: str) -> list[dict[str, str]]:
    return [{"model_name": models[key].name, "filename": str(models[key])} for key in keys]


# ------------------------------------------------------------------------------------------- fake Forge + NJR


def _qwen_state_dict_failure(options: dict) -> str | None:
    """Forge's real failure for a 9B checkpoint loaded without the Qwen3 text encoder."""

    if "klein-base-9b" in str(options.get("sd_model_checkpoint", "")).lower():
        names = [str(m).replace("\\", "/").rsplit("/", 1)[-1] for m in options.get("forge_additional_modules") or []]
        if not any(name.startswith("qwen_3_8b") for name in names):
            return "AssertionError: You do not have Qwen3 state dict!"
    return None


def _forge(models, *, checkpoint=NINE_B, selected=None, catalog=("qwen8", "qwen4", "vae", "sdxl_vae"), **kwargs):
    transport = FakeWebUITransport(
        flavor="forge",
        checkpoint=checkpoint,
        modules=_modules(models, *catalog),
        checkpoint_files={NINE_B: str(models["nine_b"]), SDXL: str(models["sdxl"])},
        reject_generation_when=_qwen_state_dict_failure,
        **kwargs,
    )
    transport.options["forge_additional_modules"] = [str(models[key]) for key in (selected or ())]
    return transport


def _client(transport: FakeWebUITransport) -> ForgeWebUIClient:
    client = ForgeWebUIClient(base_url="http://127.0.0.1:7861", options_write_enabled=True)
    client._session.request = transport  # type: ignore[method-assign]
    client._options_min_interval_seconds = 0.0
    return client


def _njr(model: str = NINE_B, job_id: str = "m150", chain: tuple[str, ...] = ("txt2img",)):
    stages = {
        "txt2img": make_stage_config("txt2img", steps=20, cfg_scale=4.0, sampler_name="Euler", scheduler="Beta", model=model),
        "adetailer": make_stage_config(
            "adetailer", model=model, extra={"adetailer_model": "face_yolov8n.pt", "prompt": "detailed face"}
        ),
    }
    return make_pipeline_njr(
        job_id=job_id,
        positive_prompt="a lighthouse at dusk",
        negative_prompt="",
        base_model=model,
        sampler_name="Euler",
        steps=20,
        cfg_scale=4.0,
        width=1024,
        height=1024,
        seed=424242,
        stage_chain=tuple(stages[name] for name in chain),
        config={
            "model": model, "vae": "Automatic", "prompt": "a lighthouse at dusk", "sampler_name": "Euler",
            "scheduler": "Beta", "steps": 20, "cfg_scale": 4.0, "width": 1024, "height": 1024,
        },
        backend_options={"image": {"backend_id": "forge_webui"}},
    )


def _run(njr, transport):
    return run_njr_via_queue(njr, _client(transport), timeout_seconds=60.0)


def _posts(transport: FakeWebUITransport) -> list[tuple[str, str]]:
    return [(verb, path) for verb, path, _ in transport.calls if verb == "POST"]


def _module_writes(transport: FakeWebUITransport) -> list[list[str]]:
    return [
        body["forge_additional_modules"]
        for verb, path, body in transport.calls
        if verb == "POST" and path == "/sdapi/v1/options" and "forge_additional_modules" in (body or {})
    ]


def _selected_names(transport: FakeWebUITransport) -> list[str]:
    return sorted(str(m).replace("\\", "/").rsplit("/", 1)[-1] for m in transport.options.get("forge_additional_modules") or [])


# ------------------------------------------------------------------------------------------- the defect + the repair


def test_without_the_gate_the_ordinary_path_strips_the_modules_a_9b_checkpoint_needs(
    monkeypatch: pytest.MonkeyPatch, models
) -> None:
    """Reproduction of the confirmed source mechanism: the generic baseline normalization clears the module set."""

    monkeypatch.setattr(
        forge_backend_module.ForgeWebUIImageBackend, "_dependency_gate", lambda self, pipeline, request: None
    )
    transport = _forge(models, selected=("qwen8", "vae"))
    entry = _run(_njr(job_id="m150-old"), transport)

    assert entry.status is JobStatus.FAILED
    assert _module_writes(transport) == [[]]  # the encoder + VAE were cleared by the generic path ...
    assert transport.rejected_generations == ["AssertionError: You do not have Qwen3 state dict!"]  # ... then Forge failed


def test_unqualified_9b_with_its_modules_selected_is_refused_before_any_write_or_generation(models) -> None:
    transport = _forge(models, selected=("qwen8", "vae"))
    before = list(transport.options["forge_additional_modules"])

    entry = _run(_njr(), transport)

    assert entry.status is JobStatus.FAILED
    message = str(entry.error_message)
    assert "multi-component" in message and "no exact qualified execution profile" in message
    assert "was not dispatched" in message and "module selection was not changed" in message
    assert "hidden size 64" in message and "32 latent channels" in message  # what the header asks for
    assert "qwen_3_8b.safetensors" in message and "flux2-vae.safetensors" in message  # present and selected
    assert "qwen_3_4b" not in message  # the 4B-class encoder is not offered as a match
    assert _posts(transport) == []  # no options write, no generation, nothing mutating at all
    assert transport.generation_calls == [] and transport.rejected_generations == []
    assert transport.options["forge_additional_modules"] == before  # the operator's selection is untouched


@pytest.mark.parametrize(
    ("selected", "catalog", "status"),
    [
        (("vae",), ("qwen8", "qwen4", "vae"), ReadinessStatus.DEPENDENCIES_PRESENT_NOT_SELECTED),  # only the VAE
        (("qwen8",), ("qwen8", "qwen4", "vae"), ReadinessStatus.DEPENDENCIES_PRESENT_NOT_SELECTED),  # only the encoder
        ((), ("qwen8", "qwen4", "vae"), ReadinessStatus.DEPENDENCIES_PRESENT_NOT_SELECTED),  # nothing selected
        (("qwen4", "vae"), ("qwen4", "vae"), ReadinessStatus.DEPENDENCIES_INCOMPLETE),  # 4B-class encoder is no match
        (("qwen8",), ("qwen8",), ReadinessStatus.DEPENDENCIES_INCOMPLETE),  # no VAE listed at all
    ],
)
def test_every_dependency_state_of_the_9b_is_refused_without_touching_forge(models, selected, catalog, status) -> None:
    transport = _forge(models, selected=selected, catalog=catalog)
    before = list(transport.options["forge_additional_modules"])

    entry = _run(_njr(job_id=f"m150-{status.value}"), transport)

    assert entry.status is JobStatus.FAILED
    assert _posts(transport) == [] and transport.options["forge_additional_modules"] == before
    assert STATUS_LABEL(status) in str(entry.error_message)


def STATUS_LABEL(status: ReadinessStatus) -> str:  # noqa: N802 - local helper reads like a constant table
    from src.image_backends.model_readiness import STATUS_LABELS

    return STATUS_LABELS[status]


def test_an_unreadable_module_state_is_reported_unavailable_not_empty_and_still_refused(
    monkeypatch: pytest.MonkeyPatch, models
) -> None:
    transport = _forge(models, selected=("qwen8", "vae"))
    monkeypatch.setattr(ForgeWebUIClient, "get_additional_modules", lambda self: None)

    entry = _run(_njr(job_id="m150-unreadable"), transport)

    assert entry.status is JobStatus.FAILED
    assert "Unavailable/stale" in str(entry.error_message)
    assert "could not be read" in str(entry.error_message)
    assert _posts(transport) == []


def test_every_stage_of_a_chain_is_gated_and_the_first_one_refuses(models) -> None:
    transport = _forge(models, selected=("qwen8", "vae"))
    entry = _run(_njr(job_id="m150-chain", chain=("txt2img", "adetailer")), transport)

    assert entry.status is JobStatus.FAILED
    assert _posts(transport) == []


# ------------------------------------------------------------------------------------------- preserved behavior


def test_an_unverifiable_listing_preserves_the_generic_path_exactly(models) -> None:
    """No positive identification (the listing cannot be read): previously supported generic behavior, unchanged."""

    transport = _forge(models, selected=("qwen8", "vae"), models_listing_status=500)
    entry = _run(_njr(job_id="m150-unverified"), transport)

    assert entry.status is JobStatus.FAILED  # the ordinary path, as before the package ...
    assert _module_writes(transport) == [[]]  # ... including its baseline clear (nothing newly refused)
    assert transport.rejected_generations


def test_ordinary_sdxl_work_is_not_gated_and_still_normalizes_stale_modules(models) -> None:
    transport = _forge(models, checkpoint=SDXL, selected=("qwen8", "vae"))
    transport.reject_generation_when = None
    entry = _run(_njr(model=SDXL, job_id="m150-sdxl"), transport)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert _module_writes(transport) == [[]]  # D110: the stale text encoder/VAE are cleared for ordinary SDXL
    assert len(transport.generation_calls) == 1


def test_a_missing_or_ambiguous_served_file_is_unverified_not_refused(models, tmp_path: Path) -> None:
    transport = _forge(models, selected=("qwen8", "vae"))
    transport.checkpoint_files = {NINE_B: str(tmp_path / "does-not-exist.safetensors")}
    entry = _run(_njr(job_id="m150-missing"), transport)
    assert "was not dispatched" not in str(entry.error_message)  # the gate had no positive evidence

    transport = _forge(models, selected=("qwen8", "vae"))
    transport.checkpoint_files = {NINE_B: str(models["nine_b"]), "other/" + NINE_B: str(models["sdxl"])}
    entry = _run(_njr(job_id="m150-ambiguous"), transport)
    assert "was not dispatched" not in str(entry.error_message)  # two different files share the name: identity unknown


def test_positive_identification_is_by_bytes_never_by_filename(models, tmp_path: Path) -> None:
    flux_named_sdxl = write_safetensors(tmp_path / "models" / "Stable-diffusion" / "flux-looking-sdxl.safetensors", sdxl_bundle())
    sdxl_named_flux = write_safetensors(tmp_path / "models" / "Stable-diffusion" / "plain-name.safetensors", flux2_transformer())
    assert inspect_component_file(flux_named_sdxl).dependency_bearing is False
    assert inspect_component_file(sdxl_named_flux).dependency_bearing is True


# ------------------------------------------------------------------------------------------- component evidence


def test_the_real_9b_header_signature_is_recognized_with_its_fixed_requirements() -> None:
    """Shapes taken from the observed installed checkpoint (hidden 4096, txt_in 12288, 128 input channels)."""

    shapes = {
        "img_in.weight": [4096, 128],
        "txt_in.weight": [4096, 12288],
        "double_stream_modulation_img.lin.weight": [24576, 4096],
        "double_blocks.0.img_attn.qkv.weight": [12288, 4096],
        "single_blocks.0.linear1.weight": [36864, 4096],
    }
    evidence = classify_tensor_table(shapes, dict.fromkeys(shapes, "BF16"))

    assert (evidence.role, evidence.architecture, evidence.dependency_bearing) == (ROLE_TRANSFORMER, ARCH_FLUX2_DIT, True)
    assert evidence.fact("required_text_encoder_hidden_size") == 4096  # 12288 / 3: an 8B-class (hidden 4096) encoder
    assert evidence.fact("required_vae_latent_channels") == 32  # 128 / 4
    assert evidence.fact("dtype") == "BF16"


@pytest.mark.parametrize(
    ("hidden", "label"), [(4096, "qwen3_8b"), (2560, "qwen3_4b"), (3000, None)]
)
def test_qwen3_size_is_labelled_only_from_exact_structure(hidden: int, label: str | None) -> None:
    shapes = {"model.embed_tokens.weight": [151936, hidden], "model.layers.0.self_attn.q_norm.weight": [128]}
    shapes.update({f"model.layers.{i}.self_attn.q_norm.weight": [128] for i in range(36)})
    evidence = classify_tensor_table(shapes, dict.fromkeys(shapes, "F16"))

    assert (evidence.role, evidence.fact("hidden_size"), evidence.fact("size_label")) == (ROLE_TEXT_ENCODER, hidden, label)
    assert evidence.fact("dtype") == "F16" and evidence.fact("quantized") is False  # F16 is a recorded fact, not BF16


def test_a_quantized_encoder_is_not_interchangeable_with_the_plain_dtype(models, tmp_path: Path) -> None:
    quantized = write_safetensors(
        tmp_path / "q.safetensors",
        {"model.embed_tokens.weight": ("BF16", [32, HIDDEN]), "model.layers.0.self_attn.q_norm.weight": ("BF16", [4]),
         "model.layers.0.mlp.weight_scale": ("F32", [1])},
    )
    evidence = inspect_component_file(quantized)
    assert evidence.fact("quantized") is True
    readiness = assess_model_readiness(
        NINE_B,
        checkpoint=inspect_component_file(models["nine_b"]),
        catalog=[CatalogModule("q.safetensors", evidence), CatalogModule("flux2-vae.safetensors", inspect_component_file(models["vae"]))],
        selected=["q.safetensors", "flux2-vae.safetensors"],
    )
    assert readiness.status is ReadinessStatus.DEPENDENCIES_INCOMPLETE  # a quantized encoder never satisfies the plain one


def test_vae_latent_channels_and_key_format_are_recorded(models) -> None:
    evidence = inspect_component_file(models["vae"])
    assert (evidence.role, evidence.fact("latent_channels"), evidence.fact("key_format")) == (ROLE_VAE, 32, "native")
    assert inspect_component_file(models["sdxl_vae"]).fact("latent_channels") == 4
    assert inspect_component_file(models["sdxl"]).role == ROLE_BUNDLED


def test_malformed_headers_never_manufacture_evidence(tmp_path: Path) -> None:
    good = write_safetensors(tmp_path / "good.safetensors", flux2_transformer())
    raw = good.read_bytes()
    size = struct.unpack("<Q", raw[:8])[0]
    header = json.loads(raw[8 : 8 + size])
    cases: dict[str, bytes] = {}

    cases["truncated"] = raw[: 8 + size // 2]
    cases["oversized_length"] = struct.pack("<Q", 1 << 40) + raw[8:]
    bad_offsets = json.loads(json.dumps(header))
    bad_offsets["img_in.weight"]["data_offsets"] = [0, 999999]
    encoded = json.dumps(bad_offsets).encode()
    cases["bad_offsets"] = struct.pack("<Q", len(encoded)) + encoded + raw[8 + size :]
    duplicate = raw[8 : 8 + size].decode().replace('"txt_in.weight"', '"img_in.weight"', 1).encode()
    cases["duplicate_key"] = struct.pack("<Q", len(duplicate)) + duplicate + raw[8 + size :]
    not_json = b"{nope"
    cases["not_json"] = struct.pack("<Q", len(not_json)) + not_json

    for name, payload in cases.items():
        target = tmp_path / f"{name}.safetensors"
        target.write_bytes(payload)
        evidence = inspect_component_file(target)
        assert evidence.error and not evidence.dependency_bearing and evidence.role == "unrecognized", name
    assert inspect_component_file(tmp_path / "missing.safetensors").error
    ckpt = tmp_path / "old.ckpt"
    ckpt.write_bytes(b"x")
    assert "unsupported format" in str(inspect_component_file(ckpt).error)


def test_header_evidence_is_re_read_when_a_file_is_replaced(models) -> None:
    from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend

    backend = ForgeWebUIImageBackend()
    path = str(models["qwen8"])
    first = backend._component_evidence(path)
    assert backend._component_evidence(path) is first  # an unchanged file is not re-read
    write_safetensors(models["qwen8"], qwen3_encoder(hidden=96))  # replaced in place: different size
    second = backend._component_evidence(path)
    assert second is not first and second.fact("hidden_size") == 96  # the stale evidence is not served
    assert backend._component_evidence(str(models["qwen8"]) + ".gone") is None


# ------------------------------------------------------------------------------------------- readiness projection


def _ready(models, *, catalog, selected, **kwargs):
    return assess_model_readiness(
        NINE_B,
        checkpoint=kwargs.pop("checkpoint", inspect_component_file(models["nine_b"])),
        catalog=catalog,
        selected=selected,
        **kwargs,
    )


def _catalog(models, *keys):
    return [CatalogModule(models[key].name, inspect_component_file(models[key])) for key in keys]


def test_readiness_labels_cover_the_required_operator_vocabulary(models) -> None:
    full = _catalog(models, "qwen8", "vae")
    assert _ready(models, catalog=full, selected=[], profile_available=True).status is (
        ReadinessStatus.PROFILE_AVAILABLE  # an exact profile exists; nothing verified assets or the runtime
    )
    assert _ready(models, catalog=full, selected=[], profile_available=True, profile_verified=True).status is (
        ReadinessStatus.QUALIFIED
    )
    assert _ready(models, catalog=full, selected=["qwen_3_8b.safetensors", "flux2-vae.safetensors"]).status is (
        ReadinessStatus.SELECTED_UNQUALIFIED
    )
    assert _ready(models, catalog=full, selected=["flux2-vae.safetensors"]).status is (
        ReadinessStatus.DEPENDENCIES_PRESENT_NOT_SELECTED
    )
    assert _ready(models, catalog=_catalog(models, "vae"), selected=[]).status is ReadinessStatus.DEPENDENCIES_INCOMPLETE
    assert _ready(models, catalog=None, selected=[]).status is ReadinessStatus.UNAVAILABLE_OR_STALE
    assert _ready(models, catalog=full, selected=None).status is ReadinessStatus.UNAVAILABLE_OR_STALE
    assert _ready(models, catalog=full, selected=[], checkpoint=None).status is ReadinessStatus.UNAVAILABLE_OR_STALE
    duplicate = full + [CatalogModule("QWEN_3_8B.safetensors", inspect_component_file(models["qwen4"]))]
    assert _ready(models, catalog=duplicate, selected=[]).status is ReadinessStatus.UNKNOWN_OR_CONFLICTING
    bundled = _ready(models, catalog=full, selected=[], checkpoint=inspect_component_file(models["sdxl"]))
    assert bundled.status is ReadinessStatus.NOT_DEPENDENCY_BEARING and bundled.blocks_dispatch is False


def test_the_readiness_record_is_path_free_and_marks_the_selection_source(models) -> None:
    readiness = _ready(models, catalog=_catalog(models, "qwen8", "vae"), selected=["qwen_3_8b.safetensors"], observed_at=123.0)
    record = readiness.as_dict()

    assert record["checkpoint"] == NINE_B and record["selection_source"] == "forge_options_get" and record["observed_at"] == 123.0
    assert record["evidence_type"] == "safetensors_header" and record["qualification_status"] == "unqualified"
    assert record["selected_modules"] == ["qwen_3_8b.safetensors"]
    assert str(models["nine_b"].parent) not in json.dumps(record)  # no local path in durable diagnostics
    assert _ready(models, catalog=None, selected=None).as_dict()["selection_source"] == "unavailable"


def test_a_structural_match_never_reads_as_executable(models) -> None:
    readiness = _ready(models, catalog=_catalog(models, "qwen8", "vae"), selected=["qwen_3_8b.safetensors", "flux2-vae.safetensors"])
    assert readiness.qualified is False and readiness.qualification_status == "unqualified"
    assert "not proof that the model loads" in readiness.summary()
    assert "PR-IMG-MODELS-151" in readiness.summary()  # the physical qualification prerequisite is named


# ------------------------------------------------------------------------------------------- final repairs (PR #77)


def _nested(depth: int) -> bytes:
    body = b'{"a":' * depth + b"1" + b"}" * depth
    return struct.pack("<Q", len(body)) + body


def test_deeply_nested_header_json_is_bounded_unrecognized_evidence_not_a_recursion_error(tmp_path: Path) -> None:
    from src.assets.checkpoint_structure import checkpoint_header_evidence

    target = tmp_path / "nested.safetensors"
    target.write_bytes(_nested(200_000))

    evidence = inspect_component_file(target)
    assert evidence.error and evidence.role == "unrecognized" and not evidence.dependency_bearing
    assert str(tmp_path) not in evidence.error  # path-free

    structural = checkpoint_header_evidence(target)  # the shared parser boundary: the registry path is covered too
    assert structural["structure"]["architecture"] == "unrecognized" and structural["structure"]["error"]
    assert str(tmp_path) not in json.dumps(structural, default=str)


def test_the_header_bounds_still_reject_oversized_and_duplicate_headers(tmp_path: Path) -> None:
    oversized = tmp_path / "big.safetensors"
    oversized.write_bytes(struct.pack("<Q", (64 * 1024 * 1024) + 1) + b"{}")
    assert inspect_component_file(oversized).error
    duplicate = tmp_path / "dup.safetensors"
    body = b'{"a":{"dtype":"F32","shape":[1],"data_offsets":[0,4]},"a":{"dtype":"F32","shape":[1],"data_offsets":[0,4]}}'
    duplicate.write_bytes(struct.pack("<Q", len(body)) + body + bytes(4))
    assert inspect_component_file(duplicate).error


def test_a_successful_empty_catalog_means_absent_but_a_failed_catalog_read_means_unavailable(
    models, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = _forge(models, selected=("qwen8", "vae"), catalog=())  # Forge answered: it lists no modules at all
    entry = _run(_njr(job_id="m150-empty-catalog"), empty)
    assert entry.status is JobStatus.FAILED and _posts(empty) == []
    assert "Discovered \u2014 dependencies incomplete" in str(entry.error_message)
    assert "Not found in Forge's module catalog" in str(entry.error_message)

    # A failed catalog read is exercised at the probe: the runtime identity guard (which also lists /sd-modules) would
    # refuse such an endpoint before the gate in a full job. The probe is exactly what the gate and the UI both use.
    from src.image_backends.model_readiness_probe import probe_model_readiness

    failed = _forge(models, selected=("qwen8", "vae"), modules_listing_status=500)  # the read failed: unknown, not absent
    readiness = probe_model_readiness(_client(failed), NINE_B)
    assert readiness.status is ReadinessStatus.UNAVAILABLE_OR_STALE and readiness.catalog_names is None
    assert readiness.blocks_dispatch is True  # still refused: the checkpoint itself is positively identified
    assert "module catalog could not be read" in readiness.summary()
    assert "Not found in Forge's module catalog" not in readiness.summary()  # never reported as absent
    assert _posts(failed) == []  # reading is all it did

    # A cooldown / startup-grace / unreadable catalog read is the case where the legacy list silently became [].
    blocked = _forge(models, selected=("qwen8", "vae"))
    monkeypatch.setattr(ForgeWebUIClient, "_resource_endpoint_on_cooldown", lambda self, endpoint: endpoint.endswith("sd-modules"))
    again = probe_model_readiness(_client(blocked), NINE_B)
    assert again.status is ReadinessStatus.UNAVAILABLE_OR_STALE and again.catalog_names is None  # never "absent"
    assert again.blocks_dispatch is True


def test_the_module_catalog_contract_for_other_callers_is_unchanged(models, monkeypatch: pytest.MonkeyPatch) -> None:
    ok = _client(_forge(models, catalog=("qwen8",)))
    assert [m["model_name"] for m in ok.get_vae_models()] == ["qwen_3_8b.safetensors"]
    assert [m["model_name"] for m in _client(_forge(models, catalog=("qwen8",))).get_module_catalog()] == [
        "qwen_3_8b.safetensors"
    ]
    assert _client(_forge(models, catalog=())).get_module_catalog() == []  # an answer: Forge lists nothing
    assert _client(_forge(models, catalog=())).get_vae_models() == []

    blocked = _client(_forge(models, catalog=("qwen8",)))
    monkeypatch.setattr(ForgeWebUIClient, "_resource_endpoint_on_cooldown", lambda self, endpoint: True)
    assert blocked.get_vae_models() == []  # the legacy list keeps its [] for a cooldown / startup-grace / failed read ...
    assert blocked.get_module_catalog() is None  # ... while the tri-state read reports it as not readable


def test_a_klein_4b_name_is_profile_available_not_qualified_and_nothing_is_hashed() -> None:
    from src.image_backends.model_readiness_probe import probe_model_readiness

    readiness = probe_model_readiness(None, "flux-2-klein-4b-fp8.safetensors", profile_available=True)
    assert readiness.status is ReadinessStatus.PROFILE_AVAILABLE and readiness.qualified is False
    assert readiness.blocks_dispatch is False
    assert "not verified here" in readiness.summary()  # byte verification stays at dispatch, never claimed here
    verified = probe_model_readiness(None, "flux-2-klein-4b-fp8.safetensors", profile_available=True, profile_verified=True)
    assert verified.status is ReadinessStatus.QUALIFIED and verified.qualified is True


def test_the_exact_klein_4b_name_is_exempt_from_the_gate_even_on_a_dependency_bearing_file(models) -> None:
    klein = "flux-2-klein-4b-fp8.safetensors"
    transport = _forge(models, checkpoint=klein, selected=("qwen8", "vae"))
    transport.checkpoint_files = {klein: str(models["nine_b"])}  # structurally dependency-bearing, but the exact name
    transport.reject_generation_when = None
    entry = _run(_njr(model=klein, job_id="m150-klein-name"), transport)
    assert "was not dispatched" not in str(entry.error_message)  # the gate never fires for the exact Klein name
    assert "multi-component" not in str(entry.error_message)


def test_an_unqualified_model_in_a_later_stage_is_refused_before_that_stage_writes_anything(models) -> None:
    """Per-stage gating at the backend boundary: a safe first stage passes, the 9B second stage never reaches a write."""

    from pathlib import Path as _Path
    from types import SimpleNamespace

    from src.image_backends.forge_webui_backend import (
        ForgeUnqualifiedModelError,
        ForgeWebUIImageBackend,
    )
    from src.image_backends.image_backend_types import ImageExecutionRequest

    transport = _forge(models, checkpoint=SDXL, selected=())
    pipeline = SimpleNamespace(client=_client(transport))
    backend = ForgeWebUIImageBackend()

    def request(stage: str, model: str) -> ImageExecutionRequest:
        return ImageExecutionRequest(
            backend_id="forge_webui", stage_name=stage, stage_config={}, output_dir=_Path("."),
            selected_model=model, job_id="m150-later", backend_options={"image": {"backend_id": "forge_webui"}},
        )

    backend._before_dispatch(pipeline, request("txt2img", SDXL))  # an ordinary first stage is admitted
    with pytest.raises(ForgeUnqualifiedModelError):
        backend._before_dispatch(pipeline, request("adetailer", NINE_B))  # a later stage with the 9B is refused
    with pytest.raises(ForgeUnqualifiedModelError):
        backend._before_dispatch(pipeline, request("img2img", NINE_B))
    assert _posts(transport) == []  # nothing mutating happened at any stage
    assert _module_writes(transport) == [] and transport.generation_calls == []
