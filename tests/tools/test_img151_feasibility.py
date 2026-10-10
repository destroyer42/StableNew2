"""PR-IMG-MODELS-151: the read-only feasibility evaluator, proven with synthetic evidence only.

No GPU, no Forge, no model bytes, no network and no subprocess: telemetry comes from injected fakes, headers are tiny
synthetic safetensors files, and the evaluator is a pure function over evidence objects.
"""

from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path

import pytest

import tools.qualification.img151.feasibility as feas
from src.assets.component_evidence import ComponentEvidence, classify_tensor_table
from src.image_backends.forge_klein_readiness import HostMemorySnapshot
from tools.qualification.img151.feasibility import (
    ELIGIBLE,
    GIB,
    IDENTITY_PENDING,
    INCONCLUSIVE,
    MISSING_DEPENDENCY,
    NO_GO_PINNED_FORGE,
    NO_GO_RESOURCE_RISK,
    VERDICTS,
    CandidateFile,
    CandidateSet,
    HostTelemetry,
    PinEvidence,
    collect_candidate,
    collect_pin,
    collect_telemetry,
    evaluate,
    run_read_only,
)

REPO = Path(__file__).resolve().parents[2]
HASH = "a" * 64

# ------------------------------------------------------------------------------------------- synthetic evidence


def _transformer(hidden: int = 4096, dtype: str = "BF16") -> ComponentEvidence:
    shapes = {
        "img_in.weight": [hidden, 128],
        "txt_in.weight": [hidden, hidden * 3],
        "double_stream_modulation_img.lin.weight": [4, hidden],
        "double_blocks.0.img_attn.qkv.weight": [4, hidden],
        "single_blocks.0.linear1.weight": [4, hidden],
    }
    return classify_tensor_table(shapes, dict.fromkeys(shapes, dtype))


def _encoder(hidden: int = 4096, dtype: str = "BF16", *, quantized: bool = False) -> ComponentEvidence:
    shapes = {"model.embed_tokens.weight": [151936, hidden], "model.layers.0.self_attn.q_norm.weight": [128]}
    shapes.update({f"model.layers.{i}.self_attn.q_norm.weight": [128] for i in range(36)})
    dtypes = dict.fromkeys(shapes, dtype)
    if quantized:
        shapes["model.layers.0.mlp.weight_scale"] = [1]
        dtypes["model.layers.0.mlp.weight_scale"] = "F32"
    return classify_tensor_table(shapes, dtypes)


def _vae(latent: int = 32) -> ComponentEvidence:
    shapes = {"decoder.conv_in.weight": [512, latent, 3, 3], "decoder.conv_out.weight": [3, 128, 3, 3]}
    return classify_tensor_table(shapes, dict.fromkeys(shapes, "F32"))


def _file(role: str, name: str, size: int, evidence: ComponentEvidence | None, *, sha: str | None = HASH, present: bool = True):
    return CandidateFile(role, name, present, size if present else None, evidence if present else None, sha if present else None)


def _candidate(**overrides) -> CandidateSet:
    parts = {
        "transformer": _file("transformer", feas.TRANSFORMER_NAME, 18_157_185_200, _transformer()),
        "text_encoder": _file("text_encoder", feas.ENCODER_NAME, 16_381_517_176, _encoder()),
        "vae": _file("vae", feas.VAE_NAME, 336_211_292, _vae()),
    }
    alternates = overrides.pop("alternates", ())
    official = overrides.pop("official_identity_verified", False)
    parts.update(overrides)
    return CandidateSet(**parts, alternates=alternates, official_identity_verified=official)


PIN_OK = PinEvidence(
    marker_revision=feas.PINNED_REVISION, marker_status="verified", source_scanned=True,
    supports_flux2_9b=True, supports_qwen3_8b=True, supported_dtypes=("bfloat16",), memory_usage_factor=19.5,
)
# The measured workstation (RTX 4070 Ti, ~34 GB RAM) and a hypothetical large machine.
THIS_MACHINE = HostTelemetry(
    total_ram_bytes=34_107_092_992, available_ram_bytes=18_880_086_016, commit_headroom_bytes=27_075_874_816,
    pagefile_allocated_bytes=19_327_352_832, vram_total_bytes=12_878_610_432, vram_used_bytes=1_651_507_200,
    vram_free_bytes=10_926_161_920, gpu_name="NVIDIA GeForce RTX 4070 Ti", shared_gpu_memory_bytes=53_161_984,
    forge_endpoint_listening=False,
)
BIG_MACHINE = HostTelemetry(
    total_ram_bytes=128 * GIB, available_ram_bytes=100 * GIB, commit_headroom_bytes=200 * GIB,
    vram_total_bytes=48 * GIB, vram_used_bytes=1 * GIB, vram_free_bytes=47 * GIB, shared_gpu_memory_bytes=0,
    forge_endpoint_listening=False,
)


# ------------------------------------------------------------------------------------------- verdicts


def test_this_workstation_is_a_resource_no_go_with_the_three_independent_reasons() -> None:
    report = evaluate(_candidate(), PIN_OK, THIS_MACHINE)

    assert report.verdict == NO_GO_RESOURCE_RISK
    codes = set(report.reason_codes)
    assert {"HOST_RESIDENT_WEIGHTS_EXCEED_PHYSICAL", "HOST_PEAK_EXCEEDS_COMMIT_HEADROOM", "VRAM_TRANSFORMER_EXCEEDS_DEDICATED"} <= codes
    assert "PIN_SUPPORTS_9B_SOFTWARE" in codes  # software support is reported, and is not the problem
    assert "OFFICIAL_BASE_SETTINGS_DIFFER_FROM_KLEIN4B_PROFILE" in codes and "KNOWN_GPU_RISK_CONTEXT" in codes
    assert "no model load, no generation" in report.next_recommendation
    est = report.estimated
    assert est["weights_bytes"] == 18_157_185_200 + 16_381_517_176 + 336_211_292
    assert est["host_peak_best_case_bytes"] > est["usable_physical_bytes"]  # fails even in the best case
    assert est["host_peak_scaled_bytes"] > THIS_MACHINE.commit_headroom_bytes
    assert est["runtime_cost_ratio_vs_klein4b_distilled"] == pytest.approx(28.1, abs=0.1)


def test_measured_estimated_documented_and_assumed_facts_stay_separate() -> None:
    report = evaluate(_candidate(), PIN_OK, THIS_MACHINE)
    kinds = {finding.code: finding.kind for finding in report.findings}

    assert kinds["HOST_RESIDENT_WEIGHTS_EXCEED_PHYSICAL"] == "estimated"
    assert kinds["OFFICIAL_BASE_SETTINGS_DIFFER_FROM_KLEIN4B_PROFILE"] == "documented"
    assert kinds["OFFICIAL_IDENTITY_UNVERIFIED"] == "assumed"
    assert kinds["PIN_SUPPORTS_9B_SOFTWARE"] == "measured"
    assert report.measured["telemetry"]["total_ram_bytes"] == THIS_MACHINE.total_ram_bytes  # measured values are not estimates
    assert "host_reserve_bytes" in report.assumptions and "baseline" in report.assumptions


def test_a_large_machine_with_complete_identity_is_eligible_for_owner_authorization_only() -> None:
    report = evaluate(_candidate(official_identity_verified=True), PIN_OK, BIG_MACHINE)
    assert report.verdict == ELIGIBLE
    assert "separate owner authorization" in report.next_recommendation  # never an instruction to load


def test_a_machine_that_fits_but_has_no_byte_identity_is_identity_pending() -> None:
    no_hash = _candidate(transformer=_file("transformer", feas.TRANSFORMER_NAME, 18_157_185_200, _transformer(), sha=None))
    report = evaluate(no_hash, PIN_OK, BIG_MACHINE)
    assert report.verdict == IDENTITY_PENDING and "TRANSFORMER_SHA256_PENDING" in report.reason_codes
    hashed_but_unofficial = evaluate(_candidate(), PIN_OK, BIG_MACHINE)  # hashes exist, official equality does not
    assert hashed_but_unofficial.verdict == IDENTITY_PENDING and "OFFICIAL_IDENTITY_UNVERIFIED" in hashed_but_unofficial.reason_codes


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"transformer": _file("transformer", feas.TRANSFORMER_NAME, 0, None, present=False)}, "TRANSFORMER_FILE_MISSING"),
        ({"text_encoder": _file("text_encoder", feas.ENCODER_NAME, 0, None, present=False)}, "TEXT_ENCODER_FILE_MISSING"),
        ({"vae": _file("vae", feas.VAE_NAME, 0, None, present=False)}, "VAE_FILE_MISSING"),
        ({"text_encoder": _file("text_encoder", feas.ENCODER_NAME, 8_044_982_048, _encoder(2560))}, "ENCODER_HIDDEN_SIZE_MISMATCH"),
        ({"text_encoder": _file("text_encoder", feas.ENCODER_NAME, 16_381_516_808, _encoder(dtype="F16"))}, "ENCODER_NOT_BF16"),
        ({"text_encoder": _file("text_encoder", feas.ENCODER_NAME, 8_664_848_742, _encoder(quantized=True))}, "ENCODER_QUANTIZED"),
        ({"vae": _file("vae", feas.VAE_NAME, 335_304_388, _vae(16))}, "VAE_LATENT_CHANNEL_MISMATCH"),
        ({"transformer": _file("transformer", feas.TRANSFORMER_NAME, 9_000_000_000, _transformer(3072))}, "TRANSFORMER_NOT_9B_CLASS"),
        ({"transformer": _file("transformer", feas.TRANSFORMER_NAME, 18_000_000_000, _transformer(dtype="F16"))}, "TRANSFORMER_NOT_BF16"),
        ({"transformer": _file("transformer", feas.TRANSFORMER_NAME, 1, ComponentEvidence(error="malformed header"))}, "TRANSFORMER_NOT_FLUX2_STRUCTURE"),
        ({"vae": _file("vae", feas.VAE_NAME, 1, ComponentEvidence(error="malformed header"))}, "VAE_NOT_RECOGNIZED"),
    ],
)
def test_missing_or_mismatched_components_are_a_missing_dependency_and_never_substituted(overrides, code) -> None:
    report = evaluate(_candidate(**overrides), PIN_OK, BIG_MACHINE)
    assert report.verdict == MISSING_DEPENDENCY and code in report.reason_codes


def test_alternate_encoders_are_reported_but_never_substituted_for_a_missing_named_file() -> None:
    f16 = _file("text_encoder", "model.safetensors", 16_381_516_808, _encoder(dtype="F16"))
    quant = _file("text_encoder", "qwen_3_8b_fp8mixed.safetensors", 8_664_848_742, _encoder(quantized=True))
    four_b = _file("text_encoder", "qwen3_4b.safetensors", 8_044_982_048, _encoder(2560))
    report = evaluate(
        _candidate(text_encoder=_file("text_encoder", feas.ENCODER_NAME, 0, None, present=False), alternates=(f16, quant, four_b)),
        PIN_OK, BIG_MACHINE,
    )
    assert report.verdict == MISSING_DEPENDENCY and "TEXT_ENCODER_FILE_MISSING" in report.reason_codes  # no silent swap
    assert "ALTERNATE_COMPONENT_FILES_PRESENT" in report.reason_codes
    assert {a["name"] for a in report.candidate["alternates"]} == {"model.safetensors", quant.name, four_b.name}


def test_precedence_is_missing_then_pin_then_resource_then_inconclusive_then_identity() -> None:
    broken_pin = PinEvidence(marker_revision="deadbeef", marker_status="verified", source_scanned=True,
                             supports_flux2_9b=False, supports_qwen3_8b=True)
    missing_vae = {"vae": _file("vae", feas.VAE_NAME, 0, None, present=False)}
    assert evaluate(_candidate(**missing_vae), broken_pin, THIS_MACHINE).verdict == MISSING_DEPENDENCY
    pinned = evaluate(_candidate(), broken_pin, THIS_MACHINE)
    assert pinned.verdict == NO_GO_PINNED_FORGE and {"PIN_NOT_VERIFIED", "PIN_LACKS_FLUX2_9B"} <= set(pinned.reason_codes)
    assert evaluate(_candidate(), PIN_OK, THIS_MACHINE).verdict == NO_GO_RESOURCE_RISK
    assert evaluate(_candidate(), PIN_OK, HostTelemetry(total_ram_bytes=BIG_MACHINE.total_ram_bytes)).verdict == INCONCLUSIVE
    assert evaluate(_candidate(), PIN_OK, BIG_MACHINE).verdict == IDENTITY_PENDING


def test_a_definite_resource_failure_is_not_hidden_by_other_missing_telemetry() -> None:
    partial = HostTelemetry(total_ram_bytes=THIS_MACHINE.total_ram_bytes)  # no VRAM, no commit headroom
    report = evaluate(_candidate(), PIN_OK, partial)
    assert report.verdict == NO_GO_RESOURCE_RISK  # total RAM alone already proves the best case cannot fit
    assert {"TELEMETRY_VRAM_TOTAL_BYTES_MISSING", "TELEMETRY_COMMIT_HEADROOM_MISSING"} <= set(report.reason_codes)


@pytest.mark.parametrize("missing", ["total_ram_bytes", "vram_total_bytes"])
def test_incomplete_telemetry_is_inconclusive_not_a_guess(missing: str) -> None:
    fields = {**BIG_MACHINE.__dict__, missing: None}
    report = evaluate(_candidate(official_identity_verified=True), PIN_OK, HostTelemetry(**fields))
    assert report.verdict == INCONCLUSIVE and f"TELEMETRY_{missing.upper()}_MISSING" in report.reason_codes


def test_an_unreadable_pinned_source_is_inconclusive_and_a_mismatched_marker_is_a_pin_no_go() -> None:
    unread = PinEvidence(marker_revision=feas.PINNED_REVISION, marker_status="verified", source_scanned=False)
    assert evaluate(_candidate(official_identity_verified=True), unread, BIG_MACHINE).verdict == INCONCLUSIVE
    stale = PinEvidence(marker_revision=feas.PINNED_REVISION, marker_status="drift", source_scanned=True,
                        supports_flux2_9b=True, supports_qwen3_8b=True)
    assert evaluate(_candidate(), stale, BIG_MACHINE).verdict == NO_GO_PINNED_FORGE


def test_every_verdict_is_one_of_the_declared_set_and_the_report_serializes() -> None:
    for pin, tele in ((PIN_OK, THIS_MACHINE), (PIN_OK, BIG_MACHINE), (PinEvidence(), BIG_MACHINE)):
        report = evaluate(_candidate(), pin, tele)
        assert report.verdict in VERDICTS
        assert json.loads(json.dumps(report.as_dict()))["verdict"] == report.verdict
    assert len(VERDICTS) == 6


# ------------------------------------------------------------------------------------------- collectors (fakes)


def _write(path: Path, tensors: dict[str, tuple[str, list[int]]]) -> Path:
    header, offset = {}, 0
    for name, (dtype, shape) in tensors.items():
        count = 1
        for dim in shape:
            count *= dim
        size = count * {"BF16": 2, "F16": 2, "F32": 4}[dtype]
        header[name] = {"dtype": dtype, "shape": shape, "data_offsets": [offset, offset + size]}
        offset += size
    encoded = json.dumps(header).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + bytes(offset))
    return path


def _install_models(root: Path, *, hidden: int = 64, encoder_dtype: str = "BF16", with_vae: bool = True) -> None:
    models = root / "models"
    _write(models / "Stable-diffusion" / feas.TRANSFORMER_NAME, {
        "img_in.weight": ("BF16", [hidden, 128]), "txt_in.weight": ("BF16", [hidden, hidden * 3]),
        "double_stream_modulation_img.lin.weight": ("BF16", [4, hidden]),
        "double_blocks.0.img_attn.qkv.weight": ("BF16", [4, hidden]), "single_blocks.0.linear1.weight": ("BF16", [4, hidden]),
    })
    enc = {"model.embed_tokens.weight": (encoder_dtype, [32, hidden])}
    enc.update({f"model.layers.{i}.self_attn.q_norm.weight": (encoder_dtype, [4]) for i in range(36)})
    _write(models / "text_encoder" / feas.ENCODER_NAME, enc)
    _write(models / "text_encoder" / "model.safetensors", {name: ("F16", shape) for name, (_dtype, shape) in enc.items()})
    if with_vae:
        _write(models / "VAE" / feas.VAE_NAME, {"decoder.conv_in.weight": ("F32", [8, 32, 3, 3]), "decoder.conv_out.weight": ("F32", [3, 8, 3, 3])})


def test_collect_candidate_finds_the_exact_files_and_keeps_the_f16_encoder_as_an_alternate(tmp_path: Path) -> None:
    _install_models(tmp_path)
    found = collect_candidate(tmp_path)

    assert found.transformer.present and found.text_encoder.present and found.vae.present
    assert found.text_encoder.fact("dtype") == "BF16" and found.text_encoder.sha256 is None  # identity pending, not invented
    assert [a.name for a in found.alternates] == ["model.safetensors"]
    assert found.alternates[0].fact("dtype") == "F16"
    report = evaluate(found, PIN_OK, BIG_MACHINE, expected_hidden_size=64)
    assert report.verdict == IDENTITY_PENDING  # the structure is complete; only identity is pending


def test_collect_candidate_reports_missing_and_invalid_files_without_repairing_anything(tmp_path: Path) -> None:
    _install_models(tmp_path, with_vae=False)
    (tmp_path / "models" / "Stable-diffusion" / feas.TRANSFORMER_NAME).write_bytes(b"\x01\x00")  # truncated header
    before = sorted(p.name for p in tmp_path.rglob("*"))
    found = collect_candidate(tmp_path)
    assert not found.vae.present and found.transformer.evidence.error
    report = evaluate(found, PIN_OK, BIG_MACHINE, expected_hidden_size=64)
    assert report.verdict == MISSING_DEPENDENCY
    assert {"VAE_FILE_MISSING", "TRANSFORMER_NOT_FLUX2_STRUCTURE"} <= set(report.reason_codes)
    assert sorted(p.name for p in tmp_path.rglob("*")) == before  # nothing created, moved or deleted


def test_conflicting_same_name_candidates_are_resolved_by_exact_path_only(tmp_path: Path) -> None:
    """A same-named encoder with the wrong dtype is a mismatch of the exact file, never a swap to the other file."""

    _install_models(tmp_path, encoder_dtype="F16")
    report = evaluate(collect_candidate(tmp_path), PIN_OK, BIG_MACHINE, expected_hidden_size=64)
    assert report.verdict == MISSING_DEPENDENCY and "ENCODER_NOT_BF16" in report.reason_codes


def test_provenance_uses_file_identity_or_size_never_the_name(tmp_path: Path) -> None:
    _install_models(tmp_path)
    cache = tmp_path / "hf"
    mirror = cache / "models--darknight9121--FLUX.2-klein-base-9B-bucket-uncensored" / "snapshots" / "abc"
    mirror.mkdir(parents=True)
    (mirror / "README.md").write_text("---\nlicense: other\nlicense_name: flux-non-commercial-license\n---\n", encoding="utf-8")
    installed = tmp_path / "models" / "Stable-diffusion" / feas.TRANSFORMER_NAME
    (mirror / feas.TRANSFORMER_NAME).write_bytes(installed.read_bytes()[:-1] + b"\x01")  # same size, other bytes
    found = collect_candidate(tmp_path, hf_cache=cache)
    assert found.transformer.provenance == "same_size_as_recorded_source"  # a size match is not equality
    hashed = collect_candidate(tmp_path, hf_cache=cache, hash_files=True)
    assert hashed.transformer.provenance == "differs_from_recorded_source"  # hashing shows the bytes differ
    (mirror / feas.TRANSFORMER_NAME).write_bytes(installed.read_bytes())
    equal = collect_candidate(tmp_path, hf_cache=cache, hash_files=True)
    assert equal.transformer.provenance == "same_bytes_as_recorded_source"
    assert "BYTES_MATCH_RECORDED_SOURCE_CACHE" in evaluate(equal, PIN_OK, BIG_MACHINE, expected_hidden_size=64).reason_codes
    assert found.source["transformer"]["license_name"] == "flux-non-commercial-license"
    assert found.official_identity_verified is False


def test_hashing_is_read_only_and_optional(tmp_path: Path) -> None:
    _install_models(tmp_path)
    target = tmp_path / "models" / "VAE" / feas.VAE_NAME
    before = target.read_bytes()
    assert collect_candidate(tmp_path).vae.sha256 is None
    hashed = collect_candidate(tmp_path, hash_files=True)
    import hashlib

    assert hashed.vae.sha256 == hashlib.sha256(before).hexdigest()
    assert target.read_bytes() == before


def test_collect_pin_reads_the_marker_and_the_pinned_model_definitions(tmp_path: Path) -> None:
    install = tmp_path / "neo-d70373eb"
    (install / "source" / "modules_forge" / "packages" / "huggingface_guess").mkdir(parents=True)
    (install / "source" / "backend").mkdir(parents=True)
    (install / ".stablenew-managed-forge.json").write_text(
        json.dumps({"revision": feas.PINNED_REVISION, "status": "verified"}), encoding="utf-8-sig")
    guess = install / "source" / "modules_forge" / "packages" / "huggingface_guess" / "model_list.py"
    guess.write_text('class Flux2K9B(Flux):\n    unet_config = {"hidden_size": 4096}\n    memory_usage_factor = 19.5\n'
                     "    supported_inference_dtypes = [torch.bfloat16, torch.float16]\n\nclass Other:\n    pass\n", encoding="utf-8")
    (install / "source" / "backend" / "loader.py").write_text("from backend.nn.llm.llama import Qwen3_8B as QTE\n", encoding="utf-8")

    pin = collect_pin(install)
    assert (pin.marker_revision, pin.marker_status, pin.supports_flux2_9b, pin.supports_qwen3_8b) == (
        feas.PINNED_REVISION, "verified", True, True)
    assert pin.memory_usage_factor == 19.5 and "bfloat16" in pin.supported_dtypes

    guess.write_text("class Flux2K4B(Flux):\n    pass\n", encoding="utf-8")
    assert collect_pin(install).supports_flux2_9b is False  # the pinned source lacks 9B: a Forge no-go
    assert collect_pin(tmp_path / "missing").source_scanned is False  # unreadable: inconclusive, not a guess


def test_telemetry_is_parsed_from_the_allow_listed_queries_and_incomplete_data_is_recorded() -> None:
    outputs = {
        feas.READ_ONLY_COMMANDS["nvidia_smi"]: "NVIDIA GeForce RTX 4070 Ti, 12282, 1575, 10420, 38, 617.14\n",
        feas.READ_ONLY_COMMANDS["pagefile"]: json.dumps({"Name": "C:\\pagefile.sys", "AllocatedBaseSize": 18432}),
        feas.READ_ONLY_COMMANDS["processes"]: json.dumps([{"Name": "chrome", "WorkingSet64": 1_181_116_006}]),
        feas.READ_ONLY_COMMANDS["gpu_shared_memory"]: "53161984\n",
    }
    asked: list[tuple[str, ...]] = []

    def runner(argv):
        asked.append(tuple(argv))
        return outputs.get(tuple(argv))

    snapshot = HostMemorySnapshot(34_107_092_992, 18_880_086_016, 27_075_874_816)
    tele = collect_telemetry(runner=runner, memory_probe=lambda: snapshot, port_probe=lambda port: False)
    assert tele.total_ram_bytes == 34_107_092_992 and tele.commit_headroom_bytes == 27_075_874_816
    assert tele.vram_total_bytes == 12282 * 1024 * 1024 and tele.pagefile_allocated_bytes == 18432 * 1024 * 1024
    assert tele.shared_gpu_memory_bytes == 53_161_984 and tele.competing_processes == (("chrome", 1_181_116_006),)
    assert tele.forge_endpoint_listening is False and tele.missing == ()
    assert set(asked) <= set(feas.READ_ONLY_COMMANDS.values())  # only the allow-listed read-only queries were issued

    def broken_probe() -> HostMemorySnapshot:
        raise OSError("no counters")

    partial = collect_telemetry(runner=lambda argv: None, memory_probe=broken_probe, port_probe=lambda port: False)
    assert {"host_memory", "pagefile", "vram", "shared_gpu_memory", "processes"} <= set(partial.missing)
    assert partial.total_ram_bytes is None and partial.vram_total_bytes is None  # unknown, never zero


# ------------------------------------------------------------------------------------------- zero unauthorized side effects


def test_only_allow_listed_read_only_commands_can_ever_be_run(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: started.append(list(argv)) or subprocess.CompletedProcess(argv, 0, "", ""))
    for forbidden in (
        ["taskkill", "/IM", "python.exe"],
        ["powershell", "-Command", "Stop-Process -Name python"],
        ["nvidia-smi", "-pl", "150"],  # a power-limit change
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", "Set-ItemProperty HKCU:\\x y 1"],
    ):
        with pytest.raises(PermissionError):
            run_read_only(forbidden)
    assert started == []
    run_read_only(feas.READ_ONLY_COMMANDS["nvidia_smi"])  # an allow-listed query is the only thing that runs
    assert started == [list(feas.READ_ONLY_COMMANDS["nvidia_smi"])]
    for argv in feas.READ_ONLY_COMMANDS.values():
        text = " ".join(argv).lower()
        assert not any(word in text for word in ("set-", "stop-", "start-", "remove-", "kill", "-pl ", "reset", "--gpu-reset"))


def test_the_evaluator_has_no_write_launch_download_or_load_surface() -> None:
    source = (REPO / "tools" / "qualification" / "img151" / "feasibility.py").read_text(encoding="utf-8")
    for forbidden in (
        "shutil", "os.remove", "unlink(", "rename(", "os.replace", "urlopen", "import requests", "urllib.request",
        "import torch", "WebUIProcessManager", "set_additional_modules", "/sdapi/v1/options", "txt2img", "Popen(",
        "huggingface_hub", "snapshot_download",
    ):
        assert forbidden not in source, forbidden
    assert source.count(".write_text(") == 1  # the report file the caller names (in main) is the only write


def test_importing_and_evaluating_starts_no_process_and_opens_no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def refuse(*_a, **_k):
        raise AssertionError("unauthorized side effect")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert evaluate(_candidate(), PIN_OK, THIS_MACHINE).verdict == NO_GO_RESOURCE_RISK


def test_the_feasibility_phase_does_not_touch_the_pr150_gate_or_production_modules() -> None:
    """Qualification-only: nothing under src/ changed for this phase and the tool never imports a backend."""

    source = (REPO / "tools" / "qualification" / "img151" / "feasibility.py").read_text(encoding="utf-8")
    assert "forge_webui_backend" not in source and "_dependency_gate" not in source
    from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend

    assert hasattr(ForgeWebUIImageBackend, "_dependency_gate")  # the PR-150 pre-dispatch gate is intact
