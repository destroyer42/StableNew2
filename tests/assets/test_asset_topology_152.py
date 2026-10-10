"""PR-IMG-MODELS-152 acceptance tests A1-A17: observational inventory, bundles, report, read-only reconciliation.

Synthetic headers only: no weights, GPU, network, backend process or real model tree.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.api.webui_runtime_identity import FORGE_WEBUI_IDENTITY, WebUIRuntimeIdentity
from src.assets import observation
from src.assets.bundles import (
    CONFLICTING,
    INCOMPATIBLE,
    MISSING,
    NOT_CHECKED,
    POSSIBLE,
    UNKNOWN,
    build_bundles,
)
from src.assets.gguf import inspect_gguf
from src.assets.inventory_report import build_report, collisions, render_json
from src.assets.observation import ObservationRoot, ScanLimits, observe_roots
from src.assets.registry import AssetKind, AssetRegistry
from src.image_backends.model_inventory_reconcile import read_forge_state
from tests.assets import topology_fixtures_152 as fx

RECORD = {
    "id": "PR-IMG-MODELS-151",
    "verdict": "NO_GO_RESOURCE_RISK",
    "scope": "exact evaluated stack",
    "applies_to": {
        "architecture": "flux2_dit",
        "hidden_size": 4096,
        "precision_layout": "plain",
        "dominant_dtype_by_bytes": "BF16",
        "file_name": "flux-2-klein-base-9b.safetensors",
        "size_bytes": None,
        "sha256": None,
    },
}


@pytest.fixture
def webui(tmp_path: Path) -> Path:
    return fx.webui_tree(tmp_path / "webui")


def registry(webui: Path, tmp_path: Path) -> AssetRegistry:
    return AssetRegistry(webui, cache_path=tmp_path / "cache" / "registry.json")


def bundle_for(bundles, fragment: str):
    matches = [item for item in bundles if fragment in item.bundle_id]
    assert len(matches) == 1, [item.bundle_id for item in bundles]
    return matches[0]


def leaf(bundle_id: str) -> str:
    return bundle_id.rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def relation(bundle, role: str):
    return next(item for item in bundle.relationships if item.role == role)


def outcomes(rel) -> dict[str, str]:
    return {item.path.rsplit("/", 1)[-1]: item.outcome for item in rel.candidates}


def make_link(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
        return
    except (OSError, NotImplementedError):
        pass
    if sys.platform == "win32" and target.is_dir():
        done = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False
        )
        if done.returncode == 0:
            return
    pytest.skip("this environment cannot create the link under test")


# --------------------------------------------------------------------------------------------------- A1


def test_a1_both_embedding_roots_are_enumerated_without_basename_dedup(webui, tmp_path):
    fx.safetensors(webui / "embeddings/DeepNegative_xl_v1.safetensors", fx.sdxl_embedding())
    fx.safetensors(webui / "embeddings/ac_neg1.safetensors", fx.sdxl_embedding())
    fx.safetensors(webui / "models/embeddings/ac_neg1.safetensors", fx.sd1_embedding())
    fx.raw_file(webui / "models/embeddings/old.pt", b"pickle-not-opened")

    scan = registry(webui, tmp_path).observe()

    labels = {root.label: root for root in scan.roots}
    assert labels["embeddings"].scanned and labels["models/embeddings"].scanned
    names = sorted(item.relative for item in scan.files if item.kind == "embedding")
    assert names == [
        "DeepNegative_xl_v1.safetensors",
        "ac_neg1.safetensors",
        "ac_neg1.safetensors",
        "old.pt",
    ]
    found = collisions(scan.files)
    assert [item["name"] for item in found] == ["ac_neg1.safetensors"]
    assert len(found[0]["locations"]) == 2
    pickle = next(item for item in scan.files if item.suffix == ".pt")
    assert (
        pickle.header.format == observation.FORMAT_UNINSPECTED
    )  # a pickle container is never deserialized


# --------------------------------------------------------------------------------------------------- A2


def test_a2_nested_roots_mixed_case_extensions_and_quotas(webui, tmp_path):
    fx.safetensors(
        webui / "models/Stable-diffusion/Not Working/Nested.SafeTensors", fx.unet_bundle("sdxl")
    )
    fx.safetensors(webui / "models/text_encoder/enc.safetensors", fx.qwen3_encoder(4096))
    fx.safetensors(webui / "models/Lora/a.safetensors", fx.kohya_lora())
    fx.safetensors(webui / "models/VAE/v.safetensors", fx.vae(32, batch_norm=True))

    scan = registry(webui, tmp_path).observe()

    assert scan.complete
    assert {item.relative for item in scan.files} >= {
        "Not Working/Nested.SafeTensors",
        "enc.safetensors",
        "a.safetensors",
    }
    assert (
        next(i for i in scan.files if i.name == "Nested.SafeTensors").header.checkpoint_architecture
        == "sdxl_base"
    )

    limited = observe_roots(
        registry(webui, tmp_path).observation_roots(), limits=ScanLimits(max_files=2)
    )
    assert limited.truncated == "max_files" and not limited.complete and len(limited.files) <= 2

    shallow = observe_roots(
        registry(webui, tmp_path).observation_roots(), limits=ScanLimits(max_depth=0)
    )
    assert ("models/Stable-diffusion/Not Working", "max depth reached") in shallow.skipped
    assert all(item.name != "Nested.SafeTensors" for item in shallow.files)


def test_a2_a_directory_with_too_many_entries_stops_the_scan_incomplete(webui, tmp_path):
    for index in range(6):
        (webui / f"models/VAE/note{index}.txt").write_text("x")
    scan = registry(webui, tmp_path).observe(limits=ScanLimits(max_dir_entries=4))
    assert scan.truncated == "max_dir_entries" and not scan.complete


def test_a2_cancellation_returns_a_partial_incomplete_scan(webui, tmp_path):
    for index in range(5):
        fx.safetensors(webui / f"models/VAE/v{index}.safetensors", fx.vae(4))
    calls = {"n": 0}

    def cancel_after_a_few() -> bool:
        calls["n"] += 1
        return calls["n"] > 3

    scan = registry(webui, tmp_path).observe(cancelled=cancel_after_a_few)
    assert scan.cancelled and not scan.complete
    assert registry(webui, tmp_path).observe(cancelled=lambda: True).files == ()


# --------------------------------------------------------------------------------------------------- A3


def test_a3_links_are_not_followed_and_cannot_escape_the_root(webui, tmp_path):
    outside = tmp_path / "outside"
    fx.safetensors(outside / "stolen.safetensors", fx.vae(4))
    fx.safetensors(webui / "models/VAE/real.safetensors", fx.vae(4))
    make_link(webui / "models/VAE/dir_link", outside)
    scan = registry(webui, tmp_path).observe()
    assert [item.relative for item in scan.files if item.kind == "vae"] == ["real.safetensors"]
    assert any(reason == "directory link not followed" for _name, reason in scan.skipped)


def test_a3_a_cyclic_directory_link_terminates(webui, tmp_path):
    fx.safetensors(webui / "models/VAE/real.safetensors", fx.vae(4))
    make_link(webui / "models/VAE/loop", webui / "models/VAE")
    scan = registry(webui, tmp_path).observe()
    assert [item.relative for item in scan.files if item.kind == "vae"] == ["real.safetensors"]


def test_a3_a_file_link_resolving_outside_the_root_is_skipped(webui, tmp_path):
    outside = fx.safetensors(tmp_path / "outside/escape.safetensors", fx.vae(4))
    try:
        os.symlink(outside, webui / "models/VAE/escape.safetensors")
    except (OSError, NotImplementedError):
        pytest.skip("file symlinks are unavailable")
    scan = registry(webui, tmp_path).observe()
    assert not [item for item in scan.files if item.kind == "vae"]
    assert any(reason == "link resolves outside its root" for _name, reason in scan.skipped)


def test_a3_one_physical_file_is_observed_once_with_its_alias(webui, tmp_path):
    real = fx.safetensors(webui / "models/Lora/a.safetensors", fx.kohya_lora())
    try:
        os.symlink(real, webui / "models/Lora/alias.safetensors")
    except (OSError, NotImplementedError):
        pytest.skip("file symlinks are unavailable")
    scan = registry(webui, tmp_path).observe()
    loras = [item for item in scan.files if item.kind == "lora"]
    assert len(loras) == 1 and loras[0].aliases


def test_a3_directory_links_are_skipped_even_when_the_platform_check_is_the_only_signal(
    webui, tmp_path, monkeypatch
):
    fx.safetensors(webui / "models/VAE/sub/inner.safetensors", fx.vae(4))
    fx.safetensors(webui / "models/VAE/top.safetensors", fx.vae(4))
    monkeypatch.setattr(observation, "_is_link", lambda entry: entry.name == "sub")
    scan = registry(webui, tmp_path).observe()
    assert [item.relative for item in scan.files if item.kind == "vae"] == ["top.safetensors"]


# --------------------------------------------------------------------------------------------------- A4 / A5 / A17


def test_a4_cold_observation_never_hashes_or_writes_the_cache(webui, tmp_path, monkeypatch):
    fx.safetensors(webui / "embeddings/e.safetensors", fx.sdxl_embedding())
    fx.safetensors(webui / "models/Stable-diffusion/m.safetensors", fx.unet_bundle("sdxl"))
    fx.safetensors(webui / "models/text_encoder/enc.safetensors", fx.qwen3_encoder(4096))
    reg = registry(webui, tmp_path)
    calls = []
    real = hashlib.sha256
    monkeypatch.setattr(hashlib, "sha256", lambda *a, **k: calls.append(1) or real(*a, **k))

    scan = reg.observe()
    build_report(scan)

    assert calls == []
    assert not reg.cache_path.exists()
    assert {item.identity.status for item in scan.files} == {"pending"}
    assert all(item.identity.sha256 is None for item in scan.files)


def test_a4_explicit_refresh_still_hashes_and_observation_then_reports_verified(webui, tmp_path):
    first = fx.safetensors(webui / "embeddings/e.safetensors", fx.sdxl_embedding())
    second = fx.safetensors(webui / "models/embeddings/e.safetensors", fx.sdxl_embedding())
    encoder = fx.safetensors(webui / "models/text_encoder/enc.safetensors", fx.qwen3_encoder(4096))
    reg = registry(webui, tmp_path)

    result = reg.refresh(kinds=[AssetKind.EMBEDDING])

    assert (
        result.hashes_computed == 1 or result.hashes_computed == 2
    )  # one cache key per resolved path
    assert reg.cache_path.exists()
    assert all(len(record.sha256) == 64 for record in result.snapshot.records)
    by_name = {item.path: item for item in reg.observe().files}
    verified = [item for item in by_name.values() if item.identity.status == "verified"]
    assert verified and all(item.kind == "embedding" for item in verified)
    assert (
        by_name[observation._key(encoder)].identity.status == "pending"
    )  # observation-only kinds are never hashed
    expected = hashlib.sha256(first.read_bytes()).hexdigest()
    assert by_name[observation._key(first)].identity.sha256 == expected
    assert second.exists()
    cache = json.loads(reg.cache_path.read_text(encoding="utf-8"))
    assert all("enc.safetensors" not in key for key in cache["entries"])


def test_a4_default_refresh_does_not_widen_to_encoders_or_transformers(webui, tmp_path):
    fx.safetensors(webui / "models/text_encoder/enc.safetensors", fx.qwen3_encoder(4096))
    fx.safetensors(webui / "models/transformer/t.safetensors", fx.flux2_native())
    fx.safetensors(webui / "models/VAE/v.safetensors", fx.vae(4))
    reg = registry(webui, tmp_path)
    reg.refresh()
    entries = json.loads(reg.cache_path.read_text(encoding="utf-8"))["entries"]
    assert any(key.endswith("v.safetensors") for key in entries)
    assert not any(
        "text_encoder" in key or "transformer" in key.replace("\\", "/") for key in entries
    )


def test_a5_same_name_is_never_same_bytes_and_equal_size_is_unverified(webui, tmp_path):
    fx.safetensors(webui / "models/Lora/x.safetensors", fx.kohya_lora(2048))
    fx.safetensors(webui / "models/LyCORIS/x.safetensors", fx.kohya_lora(768))
    fx.safetensors(webui / "models/Lora/y.safetensors", fx.kohya_lora(2048))
    fx.safetensors(
        webui / "models/LyCORIS/y.safetensors", fx.kohya_lora(2048)
    )  # same length, same bytes, unverified
    fx.safetensors(webui / "models/Lora/z.safetensors", fx.kohya_lora(2048), {"a": "1"})
    fx.safetensors(
        webui / "models/LyCORIS/z.safetensors", fx.kohya_lora(2048), {"a": "2"}
    )  # same length, other bytes
    found = {item["name"]: item for item in collisions(registry(webui, tmp_path).observe().files)}
    assert (
        found["x.safetensors"]["byte_equality"] == "different"
    )  # different lengths prove different bytes
    assert (
        found["y.safetensors"]["byte_equality"] == "unverified"
    )  # name and size never imply equality
    assert found["z.safetensors"]["byte_equality"] == "unverified"
    reg = registry(webui, tmp_path)
    reg.refresh(kinds=[AssetKind.LORA])
    again = {item["name"]: item for item in collisions(reg.observe().files)}
    assert (
        again["y.safetensors"]["byte_equality"] == "identical"
    )  # only verified SHA-256 values establish it
    assert again["z.safetensors"]["byte_equality"] == "different"


def test_a17_a_stale_or_invalid_cache_entry_never_fabricates_identity(webui, tmp_path):
    path = fx.safetensors(webui / "embeddings/e.safetensors", fx.sdxl_embedding())
    reg = registry(webui, tmp_path)
    reg.refresh(kinds=[AssetKind.EMBEDDING])
    assert reg.observe().files[0].identity.status == "verified"

    path.write_bytes(path.read_bytes() + b"\x00")  # fingerprint changes
    assert registry(webui, tmp_path).observe().files[0].identity.status == "pending"

    data = json.loads(reg.cache_path.read_text(encoding="utf-8"))
    for entry in data["entries"].values():
        entry["size"], entry["mtime_ns"] = path.stat().st_size, path.stat().st_mtime_ns
        entry["sha256"] = "not-a-digest"
    reg.cache_path.write_text(json.dumps(data), encoding="utf-8")
    assert registry(webui, tmp_path).observe().files[0].identity.status == "pending"


# --------------------------------------------------------------------------------------------------- A6


def test_a6_sd1_inpaint_turbo_and_ordinary_sdxl_are_distinct(webui, tmp_path):
    sd = webui / "models/Stable-diffusion"
    fx.safetensors(sd / "sd15.safetensors", fx.unet_bundle("sd1"))
    fx.safetensors(sd / "inpaint.safetensors", fx.unet_bundle("inpaint"))
    fx.safetensors(sd / "ordinary.safetensors", fx.unet_bundle("sdxl"))
    fx.safetensors(
        sd / "renamed_xl.safetensors",
        fx.unet_bundle("sdxl"),
        {"modelspec.architecture": "stable-diffusion-xl-turbo-v1"},
    )
    fx.safetensors(sd / "turbo_by_name_only.safetensors", fx.unet_bundle("sdxl"))

    bundles = build_bundles(registry(webui, tmp_path).observe())

    sd1 = bundle_for(bundles, "sd15")
    assert (sd1.architecture, sd1.family) == (
        "sd1",
        "sd1",
    ) and sd1.architecture != "sdxl_unet_bundle"
    inpaint = bundle_for(bundles, "inpaint")
    assert (inpaint.architecture, inpaint.variant, inpaint.variant_basis) == (
        "sdxl_inpaint",
        "inpaint",
        "tensor_shape",
    )
    ordinary = bundle_for(bundles, "ordinary")
    assert (ordinary.architecture, ordinary.variant) == ("sdxl_unet_bundle", None)
    turbo = bundle_for(bundles, "renamed_xl")
    assert (turbo.architecture, turbo.variant, turbo.variant_basis) == (
        "sdxl_unet_bundle",
        "turbo",
        "embedded_metadata",
    )
    assert bundle_for(bundles, "turbo_by_name_only").variant is None  # a filename is never evidence


# --------------------------------------------------------------------------------------------------- A7


def test_a7_complete_two_shard_package_is_one_logical_candidate(webui, tmp_path):
    fx.safetensors(webui / "models/Stable-diffusion/native.safetensors", fx.flux2_native())
    fx.shard_pair(webui / "models/transformer")

    scan = registry(webui, tmp_path).observe()
    bundles = build_bundles(scan)

    package = scan.packages[0]
    assert package.status == "complete" and len(package.members) == 2
    assert package.config_association == "validated"
    assert "secret_note" not in package.config  # only allow-listed config keys are retained
    sharded = bundle_for(bundles, "diffusion_pytorch_model.safetensors.index.json")
    assert (sharded.packaging, sharded.architecture, sharded.package_status) == (
        "diffusers_sharded",
        "flux2_dit",
        "complete",
    )
    native = bundle_for(bundles, "native.safetensors")
    assert native.packaging == "native" and native.architecture == "flux2_dit"
    assert len([item for item in bundles if item.bundle_id.startswith("models/transformer")]) == 1
    assert {item.bundle_id for item in bundles} == {sharded.bundle_id, native.bundle_id}


@pytest.mark.parametrize(
    "defect",
    [{"drop_second": True}, {"escape": True}, {"stray": True}, {"wrong_total": True}],
    ids=["missing", "escaping", "extra", "size_conflict"],
)
def test_a7_defective_manifests_never_yield_a_runnable_looking_shard(webui, tmp_path, defect):
    fx.shard_pair(webui / "models/transformer", **defect)
    scan = registry(webui, tmp_path).observe()
    bundles = build_bundles(scan)
    assert scan.packages[0].status != "complete"
    assert len(bundles) == 1  # no shard is a standalone candidate
    only = bundles[0]
    assert only.packaging == "diffusers_sharded" and only.relationships == ()
    assert only.readiness["installed"] != "present"
    assert only.readiness["dependencies_feasible"] == UNKNOWN


def test_a7_duplicate_index_keys_and_a_lone_named_shard_are_not_candidates(webui, tmp_path):
    directory = webui / "models/transformer"
    fx.safetensors(directory / "model-00001-of-00002.safetensors", fx.flux2_diffusers_shard(1))
    scan = registry(webui, tmp_path).observe()
    only = build_bundles(scan)[0]
    assert only.packaging == "unindexed_shard" and only.readiness["installed"] == "orphan_shard"

    (directory / "model.safetensors.index.json").write_text(
        '{"weight_map": {"a": "model-00001-of-00002.safetensors", "a": "model-00002-of-00002.safetensors"}}'
    )
    scan = registry(webui, tmp_path).observe()
    assert scan.packages[0].status == "invalid"
    bundles = build_bundles(scan)
    assert {item.packaging for item in bundles} <= {"diffusers_sharded", "unindexed_shard"}
    assert all(
        item.relationships == () and item.readiness["installed"] != "present" for item in bundles
    )


def test_a7_a_shared_config_is_not_attributed_to_every_model_in_the_directory(webui, tmp_path):
    directory = webui / "models/Stable-diffusion"
    fx.safetensors(directory / "a.safetensors", fx.flux2_native())
    fx.safetensors(directory / "b.safetensors", fx.flux2_native())
    (directory / "config.json").write_text('{"hidden_size": 1}')
    scan = registry(webui, tmp_path).observe()
    assert scan.packages == ()
    assert scan.unassociated_configs
    assert all(not bundle.claims.get("package_config") for bundle in build_bundles(scan))


# --------------------------------------------------------------------------------------------------- A8


def test_a8_gguf_candidates_are_bounded_container_evidence_only(webui, tmp_path):
    sd = webui / "models/Stable-diffusion"
    fx.gguf(sd / "q6.gguf", file_type=18)
    fx.gguf(sd / "q8.gguf", file_type=7)
    fx.gguf(sd / "unlabelled-Q4_K_M.gguf", file_type=None)

    scan = registry(webui, tmp_path).observe()
    by_name = {item.name: item for item in scan.files}

    assert by_name["q6.gguf"].header.gguf.quantization == "Q6_K"
    assert by_name["q8.gguf"].header.gguf.quantization == "Q8_0"
    assert (
        by_name["unlabelled-Q4_K_M.gguf"].header.gguf.quantization is None
    )  # never inferred from the name
    for item in scan.files:
        assert item.header.component is None  # no fabricated safetensors classification
    bundle = bundle_for(build_bundles(scan), "q6.gguf")
    assert (bundle.packaging, bundle.architecture) == ("gguf", "gguf:flux")
    assert bundle.readiness["dependencies_feasible"] == UNKNOWN and bundle.relationships == ()
    assert any("unverified" in note for note in bundle.notes)


@pytest.mark.parametrize("cut", [0, 3, 4, 12, 30])
def test_a8_malformed_or_truncated_gguf_yields_a_safe_error(tmp_path, cut):
    path = fx.gguf(tmp_path / "x.gguf", truncate_at=cut)
    evidence = inspect_gguf(path)
    assert evidence.parsed is False and evidence.error


def test_a8_an_absurd_gguf_key_count_is_rejected_without_allocation(tmp_path):
    import struct

    path = fx.raw_file(tmp_path / "huge.gguf", b"GGUF" + struct.pack("<IQQ", 3, 1, 10**12))
    assert inspect_gguf(path).error == "metadata key count is implausible"


# --------------------------------------------------------------------------------------------------- A9


def test_a9_fp8_named_klein_is_judged_by_dtype_histogram_not_name_or_one_dtype(webui, tmp_path):
    sd = webui / "models/Stable-diffusion"
    fx.safetensors(sd / "flux-2-klein-base-9b-fp8.safetensors", fx.flux2_native(quantized=True))
    fx.safetensors(sd / "flux-2-klein-fp8-but-actually-bf16.safetensors", fx.flux2_native())

    bundles = build_bundles(registry(webui, tmp_path).observe())

    quantized = bundle_for(bundles, "klein-base-9b-fp8").quantization
    assert quantized["precision_layout"] == "mixed_scaled"
    assert quantized["dominant_dtype_by_tensor_count"] == "F32"  # named as such, not as the layout
    assert quantized["dominant_dtype_by_bytes"] == "F8_E4M3"
    assert set(quantized["dtype_histogram"]) == {"BF16", "F32", "F8_E4M3"}
    assert quantized["scale_key_count"] > 0
    renamed = bundle_for(bundles, "but-actually-bf16").quantization
    assert renamed["precision_layout"] == "plain"  # all BF16: the "fp8" in the name claims nothing


# --------------------------------------------------------------------------------------------------- A10


def test_a10_qwen3_encoders_are_not_interchangeable_and_qwen_image_stays_missing(webui, tmp_path):
    fx.safetensors(webui / "models/Stable-diffusion/klein9b.safetensors", fx.flux2_native(4096))
    fx.safetensors(webui / "models/Stable-diffusion/qwen_image.safetensors", fx.qwen_image_dit())
    fx.safetensors(webui / "models/text_encoder/qwen3_4b.safetensors", fx.qwen3_encoder(2560))
    fx.safetensors(webui / "models/text_encoder/qwen3_8b.safetensors", fx.qwen3_encoder(4096))
    fx.safetensors(
        webui / "models/text_encoder/qwen3_8b_fp8.safetensors",
        fx.qwen3_encoder(4096, quantized=True),
    )

    bundles = build_bundles(registry(webui, tmp_path).observe())

    klein = relation(bundle_for(bundles, "klein9b"), "text_encoder")
    assert outcomes(klein) == {
        "qwen3_4b.safetensors": INCOMPATIBLE,
        "qwen3_8b.safetensors": POSSIBLE,
        "qwen3_8b_fp8.safetensors": UNKNOWN,
    }
    assert (
        klein.requirement["hidden_size"] == 4096 and klein.requirement_basis == "header+documented"
    )
    qwen_image = relation(bundle_for(bundles, "qwen_image"), "text_encoder")
    assert qwen_image.outcome == MISSING
    assert set(outcomes(qwen_image).values()) == {
        INCOMPATIBLE
    }  # Qwen3 never fills a Qwen2.5-VL requirement
    assert (
        qwen_image.requirement["family"] == "qwen2_5_vl"
        and qwen_image.requirement["hidden_size"] == 3584
    )


# --------------------------------------------------------------------------------------------------- A11


def test_a11_vaes_are_not_cross_admitted_by_latent_channels(webui, tmp_path):
    vae_dir = webui / "models/VAE"
    fx.safetensors(vae_dir / "flux1_ae.safetensors", fx.vae(16))
    fx.safetensors(vae_dir / "flux2_native.safetensors", fx.vae(32, batch_norm=True))
    fx.safetensors(
        vae_dir / "flux2_diffusers.safetensors", fx.vae(32, key_format="diffusers", batch_norm=True)
    )
    fx.safetensors(vae_dir / "sdxl_like.safetensors", fx.vae(4))
    fx.safetensors(vae_dir / "qwen_image.safetensors", fx.qwen_image_vae())
    sd = webui / "models/Stable-diffusion"
    fx.safetensors(sd / "klein.safetensors", fx.flux2_native())
    fx.safetensors(sd / "zimage.safetensors", fx.z_image_dit())
    fx.safetensors(sd / "qwen_image.safetensors", fx.qwen_image_dit())

    bundles = build_bundles(registry(webui, tmp_path).observe())

    klein = relation(bundle_for(bundles, "klein"), "vae")
    assert [name for name, outcome in outcomes(klein).items() if outcome == POSSIBLE] == [
        "flux2_native.safetensors"
    ]
    diffusers = next(
        item for item in klein.candidates if item.path.endswith("flux2_diffusers.safetensors")
    )
    assert diffusers.outcome == INCOMPATIBLE and any(
        "key format" in reason for reason in diffusers.reasons
    )
    assert not any(
        "latent channels" in reason for reason in diffusers.reasons
    )  # 32 channels alone matched; format did not
    zimage = relation(bundle_for(bundles, "zimage"), "vae")
    assert [n for n, o in outcomes(zimage).items() if o == POSSIBLE] == ["flux1_ae.safetensors"]
    qwen = relation(bundle_for(bundles, "qwen_image"), "vae")
    assert [n for n, o in outcomes(qwen).items() if o == POSSIBLE] == ["qwen_image.safetensors"]
    assert outcomes(klein)["sdxl_like.safetensors"] == INCOMPATIBLE


# --------------------------------------------------------------------------------------------------- A12 / A13


def test_a12_a_vae_like_file_in_the_lora_folder_is_suspected_not_usable_and_stays_put(
    webui, tmp_path
):
    misplaced = fx.safetensors(webui / "models/Lora/autoencoder.safetensors", fx.vae_like_in_lora())
    fx.safetensors(webui / "models/Lora/real.safetensors", fx.kohya_lora(2048))
    fx.safetensors(
        webui / "models/Lora/conflict.safetensors",
        fx.kohya_lora(2048),
        {
            "ss_base_model_version": "sdxl_base_v1-0",
            "modelspec.architecture": "stable-diffusion-v1",
        },
    )
    fx.safetensors(webui / "models/Stable-diffusion/xl.safetensors", fx.unet_bundle("sdxl"))

    scan = registry(webui, tmp_path).observe()
    by_name = {item.name: item for item in scan.files}

    assert by_name["autoencoder.safetensors"].header.lora.suspected_misplaced_as == "vae_like"
    assert misplaced.exists() and misplaced.parent.name == "Lora"
    conflict = by_name["conflict.safetensors"].header.lora
    assert conflict.conflicts and conflict.tensor_family == "sdxl"
    adapters = bundle_for(build_bundles(scan), "xl.safetensors").adapters["lora"]
    assert adapters["possible_named"] == ["models/Lora/real.safetensors"]
    assert adapters["counts"][CONFLICTING] == 1 and adapters["counts"][UNKNOWN] == 1


def test_a13_embedding_suitability_needs_a_positive_signature_and_inserts_nothing(webui, tmp_path):
    fx.safetensors(webui / "embeddings/sdxl.safetensors", fx.sdxl_embedding())
    fx.safetensors(webui / "embeddings/sd1.safetensors", fx.sd1_embedding())
    fx.safetensors(webui / "embeddings/mystery.safetensors", {"weird": ("F16", [2, 7])})
    fx.safetensors(webui / "models/embeddings/sdxl.safetensors", fx.sdxl_embedding())

    scan = registry(webui, tmp_path).observe()
    suitability = {
        (item.root_label, item.name): item.header.embedding.suitability for item in scan.files
    }
    assert suitability[("embeddings", "mystery.safetensors")] == "unknown"
    assert suitability[("embeddings", "sd1.safetensors")] == "sd1"
    assert suitability[("embeddings", "sdxl.safetensors")] == "sdxl"
    text = render_json(build_report(scan)).lower()
    assert "negative_prompt" not in text and "insert" not in text.replace(
        "nothing is ever inserted", ""
    )


# --------------------------------------------------------------------------------------------------- A14


class _FakeForge:
    """A GET-only fake endpoint; every write-capable call fails the test."""

    def __init__(self, *, models, catalog, modules, current, identity=FORGE_WEBUI_IDENTITY):
        self._models, self._catalog, self._modules, self._current = (
            models,
            catalog,
            modules,
            current,
        )
        self._identity = identity

    def probe_runtime_identity(self):
        return WebUIRuntimeIdentity(identity=self._identity)

    def get_models(self):
        return self._models

    def get_current_model(self):
        return self._current

    def get_module_catalog(self):
        return self._catalog

    def get_additional_modules(self):
        return self._modules

    def __getattr__(self, name):
        if name.startswith(("set_", "update_", "post", "load", "refresh", "txt2img", "img2img")):
            raise AssertionError(f"a write-capable call was attempted: {name}")
        raise AttributeError(name)


def test_a14_unavailable_empty_selected_and_served_stay_distinct(webui, tmp_path):
    checkpoint = fx.safetensors(
        webui / "models/Stable-diffusion/klein.safetensors", fx.flux2_native()
    )
    scan = registry(webui, tmp_path).observe()

    down = read_forge_state(_FakeForge(models=[], catalog=None, modules=None, current=None))
    assert (down["checkpoint_listing"], down["module_catalog"], down["selected_modules"]) == (
        "unavailable",
        "unavailable",
        None,
    )

    empty = read_forge_state(_FakeForge(models=[], catalog=[], modules=[], current=None))
    assert (
        empty["module_catalog"] == "empty" and empty["selected_modules"] == []
    )  # a successful empty answer

    entry = {"title": "klein.safetensors [abc]", "model_name": "klein", "filename": str(checkpoint)}
    live = read_forge_state(
        _FakeForge(models=[entry], catalog=[], modules=[], current="klein.safetensors [abc]")
    )
    report = build_report(scan, runtime_state=live)
    bundle = report["bundles"]["items"][0]["readiness"]
    assert (bundle["served_in_forge"], bundle["selected_in_forge"]) == ("served", "selected")
    assert (
        bundle["exact_profile_admitted"] == NOT_CHECKED
        and bundle["hardware_qualified"] == NOT_CHECKED
    )
    assert report["runtime"]["module_catalog"] == "empty"

    unavailable = build_report(scan, runtime_state=down)["bundles"]["items"][0]["readiness"]
    assert (
        unavailable["served_in_forge"] == "unavailable"
        and unavailable["selected_in_forge"] == "unavailable"
    )


def test_a14_an_unverified_or_non_forge_endpoint_is_not_attributed_or_read(webui, tmp_path):
    fx.safetensors(webui / "models/Stable-diffusion/klein.safetensors", fx.flux2_native())
    other = read_forge_state(
        _FakeForge(
            models=[{"filename": "x"}], catalog=[], modules=[], current="x", identity="a1111"
        )
    )
    assert other["status"] == "unverified_runtime" and other["served_files"] is None
    report = build_report(registry(webui, tmp_path).observe(), runtime_state=other)
    assert report["bundles"]["items"][0]["readiness"]["served_in_forge"] == "unverified_runtime"


def test_a14_default_report_is_offline_and_marks_runtime_not_requested(webui, tmp_path):
    fx.safetensors(webui / "models/Stable-diffusion/klein.safetensors", fx.flux2_native())
    report = build_report(registry(webui, tmp_path).observe())
    assert report["runtime"]["status"] == "not_requested"
    assert report["bundles"]["items"][0]["readiness"]["served_in_forge"] == NOT_CHECKED


def test_a14_the_new_modules_contain_no_write_launch_or_network_calls():
    forbidden = {
        "post",
        "put",
        "delete",
        "patch",
        "Popen",
        "run",
        "system",
        "urlopen",
        "requests",
        "socket",
        "set_additional_modules",
        "update_options",
        "set_vae",
        "write_bytes",
        "unlink",
        "rename",
        "replace_file",
        "copy",
        "move",
        "rmtree",
    }
    root = Path(__file__).resolve().parents[2]
    for relative in (
        "src/assets/observation.py",
        "src/assets/bundles.py",
        "src/assets/inventory_report.py",
        "src/assets/gguf.py",
        "src/assets/adapter_evidence.py",
        "src/image_backends/model_inventory_reconcile.py",
    ):
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        names |= {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not (names & forbidden), (relative, names & forbidden)
        assert not any(
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "open"
            and len(node.args) > 1
            and "w" in ast.dump(node.args[1])
            for node in ast.walk(tree)
        ), relative


# --------------------------------------------------------------------------------------------------- A16


def _not_working_tree(webui: Path) -> None:
    sd = webui / "models/Stable-diffusion"
    fx.safetensors(sd / "flux-2-klein-base-9b.safetensors", fx.flux2_native())
    fx.safetensors(sd / "Not Working/flux2Klein_9bBase.safetensors", fx.flux2_native())
    fx.safetensors(sd / "Not Working/inpaint.safetensors", fx.unet_bundle("inpaint"))
    fx.safetensors(sd / "Not Working/realism.safetensors", fx.unet_bundle("sdxl"))
    fx.safetensors(
        sd / "Not Working/turbo.safetensors",
        fx.unet_bundle("sdxl"),
        {"modelspec.architecture": "sdxl-turbo"},
    )
    fx.safetensors(sd / "Not Working/v1-5.safetensors", fx.unet_bundle("sd1"))
    fx.safetensors(sd / "zimage-fp8.safetensors", fx.z_image_dit(quantized=True))
    fx.safetensors(sd / "flux-2-klein-base-9b-fp8.safetensors", fx.flux2_native(quantized=True))
    fx.gguf(sd / "klein-q6.gguf", file_type=18)
    fx.safetensors(sd / "qwen-image-fp8.safetensors", fx.qwen_image_dit())
    fx.safetensors(webui / "models/text_encoder/qwen3_4b.safetensors", fx.qwen3_encoder(2560))
    fx.safetensors(webui / "models/text_encoder/qwen3_8b.safetensors", fx.qwen3_encoder(4096))
    fx.safetensors(webui / "models/VAE/ae.safetensors", fx.vae(16))
    fx.safetensors(webui / "models/VAE/flux2.safetensors", fx.vae(32, batch_norm=True))


def _recorded(webui: Path) -> list[dict]:
    record = json.loads(json.dumps(RECORD))
    target = webui / "models/Stable-diffusion/flux-2-klein-base-9b.safetensors"
    record["applies_to"]["size_bytes"] = target.stat().st_size
    record["applies_to"]["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    return [record]


def test_a16_report_is_deterministic_redacted_and_bounded(webui, tmp_path):
    _not_working_tree(webui)
    reg = registry(webui, tmp_path)
    first = render_json(build_report(reg.observe(), recorded_outcomes=_recorded(webui)))
    second = render_json(build_report(reg.observe(), recorded_outcomes=_recorded(webui)))
    assert first == second
    assert (
        str(tmp_path) not in first and str(tmp_path).replace("\\", "\\\\") not in first
    )  # no absolute path by default
    assert "secret" not in first
    with_paths = render_json(
        build_report(
            reg.observe(),
            include_paths=True,
            roots=reg.observation_roots(),
            recorded_outcomes=_recorded(webui),
        )
    )
    assert (
        "webui" in with_paths and json.loads(with_paths)["redaction"] == "absolute_paths_included"
    )
    assert (
        len(first) < 2 * 1024 * 1024 and json.loads(first)["size_ceiling"]["sections_dropped"] == []
    )


def test_a16_five_not_working_cases_are_classified_separately_and_the_no_go_is_candidate_specific(
    webui, tmp_path
):
    _not_working_tree(webui)
    report = build_report(registry(webui, tmp_path).observe(), recorded_outcomes=_recorded(webui))

    cases = {leaf(item["bundle"]): item for item in report["not_working_cases"]["items"]}
    assert set(cases) == {
        "flux2Klein_9bBase.safetensors",
        "inpaint.safetensors",
        "realism.safetensors",
        "turbo.safetensors",
        "v1-5.safetensors",
    }
    assert (
        len({item["next_diagnostic"] for item in cases.values()}) == 5
    )  # no common root cause is asserted
    assert cases["inpaint.safetensors"]["evidence"]["variant"] == "inpaint"
    assert cases["turbo.safetensors"]["evidence"]["variant"] == "turbo"
    assert cases["v1-5.safetensors"]["evidence"]["architecture"] == "sd1"
    assert all(
        item["operator_status"] == "not_working_operator_provided" for item in cases.values()
    )

    priority = {leaf(item["bundle"]): item for item in report["priority_candidates"]["items"]}
    exact = priority["flux-2-klein-base-9b.safetensors"]["recorded_outcome"]
    # name and size alone are an explicitly unverified relation: the historical verdict is kept, never attributed
    assert exact["applies"] is False and exact["relation"] == "name_and_size_similar_unverified"
    assert exact["historical_verdict"] == "NO_GO_RESOURCE_RISK" and "verdict" not in exact
    sibling = cases["flux2Klein_9bBase.safetensors"]["recorded_outcome"]
    assert (
        sibling["applies"] is False
    )  # same structural class, different file: the verdict is not transferred
    assert priority["flux-2-klein-base-9b-fp8.safetensors"]["recorded_outcome"] is None
    categories = {item["category"] for item in report["priority_candidates"]["items"]}
    assert {
        "z_image",
        "flux2_quantized_native",
        "gguf_candidate",
        "qwen_image",
        "sdxl_family_special",
        "flux2_full_precision_native",
    } <= categories
    ranks = [item["rank"] for item in report["priority_candidates"]["items"]]
    assert ranks == sorted(ranks)
    readiness = next(
        b
        for b in report["bundles"]["items"]
        if b["bundle_id"].endswith(":flux-2-klein-base-9b.safetensors")
    )["readiness"]
    assert (
        readiness["hardware_qualified"] == NOT_CHECKED
    )  # an unverified observation is not promoted
    assert "ready" not in json.dumps(report["bundles"]).replace("not_ready", "")


def test_a16_report_bounds_lists_and_the_total_size(webui, tmp_path, monkeypatch):
    for index in range(40):
        fx.safetensors(webui / f"models/Lora/l{index}.safetensors", fx.kohya_lora())
    from src.assets import inventory_report

    monkeypatch.setattr(inventory_report, "MAX_LIST_ITEMS", 5)
    monkeypatch.setattr(inventory_report, "MAX_FILE_ROWS", 7)
    report = build_report(registry(webui, tmp_path).observe())
    assert len(report["files"]["items"]) == 7 and report["files"]["omitted"] == 33
    monkeypatch.setattr(inventory_report, "MAX_REPORT_BYTES", 2000)
    ceiling = build_report(registry(webui, tmp_path).observe())["size_ceiling"]
    assert "files" in ceiling["sections_dropped"]


# --------------------------------------------------------------------------------------------------- A17


@pytest.mark.parametrize(
    "payload",
    [b"", b"\x01\x02", (10**9).to_bytes(8, "little") + b"{", (5).to_bytes(8, "little") + b"notjs"],
)
def test_a17_corrupt_headers_are_errors_never_evidence(webui, tmp_path, payload):
    fx.raw_file(webui / "models/Stable-diffusion/bad.safetensors", payload)
    fx.safetensors(webui / "models/text_encoder/ok.safetensors", fx.qwen3_encoder(4096))
    scan = registry(webui, tmp_path).observe()
    bad = next(item for item in scan.files if item.name == "bad.safetensors")
    assert bad.header.error and bad.header.component is None
    bundle = bundle_for(build_bundles(scan), "bad.safetensors")
    assert bundle.relationships == () and bundle.readiness["dependencies_feasible"] == UNKNOWN
    assert bundle.readiness["header_identified"] == "error"
    assert bundle.architecture == "unrecognized"


def test_a17_a_file_changing_during_the_scan_yields_an_error_not_evidence(
    webui, tmp_path, monkeypatch
):
    target = fx.safetensors(
        webui / "models/Stable-diffusion/moving.safetensors", fx.unet_bundle("sdxl")
    )
    real = observation.inspect_file

    def mutate(path, kind, limits):
        found = real(path, kind, limits)
        path.write_bytes(path.read_bytes() + b"\x00")
        return found

    monkeypatch.setattr(observation, "inspect_file", mutate)
    scan = registry(webui, tmp_path).observe()
    moving = next(item for item in scan.files if item.name == "moving.safetensors")
    assert moving.errors == ("changed_during_scan",) and moving.header is None
    assert target.exists()
    assert build_bundles(scan)[0].readiness["header_identified"] != "identified"


def test_a17_empty_roots_and_missing_roots_report_nothing_ready(webui, tmp_path):
    report = build_report(registry(webui, tmp_path).observe())
    assert report["counts"]["observed_files"] == 0 and report["bundles"]["items"] == []
    assert report["completeness"]["complete"] is True
    missing = observe_roots([ObservationRoot("vae", tmp_path / "absent", "absent")])
    assert missing.roots[0].scanned is False and missing.roots[0].reason == "root not present"
    unconfigured = AssetRegistry(None, cache_path=tmp_path / "c.json")
    unconfigured.webui_root = None
    assert unconfigured.observation_roots() == ()


def test_a17_a_cancelled_report_declares_itself_incomplete(webui, tmp_path):
    fx.safetensors(webui / "models/VAE/v.safetensors", fx.vae(4))
    report = build_report(registry(webui, tmp_path).observe(cancelled=lambda: True))
    assert (
        report["completeness"]["complete"] is False and report["completeness"]["cancelled"] is True
    )
    assert "absence" in report["completeness"]["note"]
