"""PR-IMG-CNET-230 repair of two inherited PR-ASSET-130 readiness defects (offline; no model, GPU or network).

A. A verified, SDXL-shaped ControlNet weight is runnable only when production admission would admit its model identity for the
   modality (``forge_controlnet_units.model_problem``); integrity, architecture, identity and availability stay separate.
B. A required auxiliary file is matched only inside its own resource's ``models/StableNewAux/<resource-id>/`` directory, so
   identical bytes belonging to another resource never satisfy it.

Fixtures use the real production identity names; no invented alias is treated as supported.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.assets import controlnet_identity
from src.assets.resource_catalog import load_catalog
from src.assets.resource_readiness import (
    INCOMPLETE,
    MISMATCH,
    MISSING,
    PRESENT_UNVERIFIED,
    UNSUPPORTED,
    VERIFIED,
    InstalledEvidence,
    InstalledFile,
    build_report,
    collect_installed_evidence,
)
from src.conditioning.reference_map import auxiliary
from src.conditioning.reference_map.contracts import ProviderUnavailable
from src.image_backends import forge_controlnet_units
from src.image_backends.forge_controlnet_units import MODEL_MODALITIES, model_problem
from tests.assets.readiness_fixtures_130 import (
    aux_dir,
    controlnet_capability,
    controlnet_dir,
    file_spec,
    make_catalog,
    make_registry,
    resource,
    sha256_of,
    variant,
    write_safetensors,
)
from tests.conditioning.openpose_fixtures_210 import write_controlnet_weights

IDENTITY_REASON = "controlnet_identity_not_admitted"


def _entry(report: dict, rid: str) -> dict:
    return next(item for item in report["resources"] if item["id"] == rid)


def _controlnet(
    tmp_path: Path,
    *,
    modality: str,
    installed: str,
    expected: str | None = None,
    family: str = "sdxl",
    wrong_bytes: bool = False,
    subfolder: str = "",
) -> dict:
    registry = make_registry(tmp_path)
    folder = controlnet_dir(registry) / subfolder if subfolder else controlnet_dir(registry)
    pristine = write_controlnet_weights(tmp_path / "pristine.safetensors", family)
    target = folder / installed
    target.parent.mkdir(parents=True, exist_ok=True)
    if wrong_bytes:
        write_safetensors(target, b"\x07\x07\x07\x07")
    else:
        target.write_bytes(pristine.read_bytes())
    catalog = make_catalog(
        resource(
            "cn",
            [file_spec("weights", [variant(expected or installed, sha256_of(pristine))])],
            root="controlnet",
            capability=controlnet_capability(modality),
        )
    )
    evidence = collect_installed_evidence(registry, catalog, refresh=True)
    return _entry(build_report(catalog, evidence), "cn")


# ------------------------------------------------------------------------------------------ Finding A


@pytest.mark.parametrize(
    ("modality", "name"),
    [
        ("canny", "diffusers_xl_canny_full.safetensors"),
        ("depth", "diffusers_xl_depth_full.safetensors"),
        ("openpose", "thibaud_xl_openpose.safetensors"),
        ("openpose", "xinsir_openpose_sdxl.safetensors"),
    ],
)
def test_admitted_production_identities_with_correct_bytes_and_sdxl_evidence_stay_runnable(
    tmp_path, modality, name
) -> None:
    entry = _controlnet(tmp_path, modality=modality, installed=name)
    assert entry["status"] == VERIFIED and entry["ready_for_use"] is True
    assert IDENTITY_REASON not in entry["reason_codes"]


@pytest.mark.parametrize(
    ("modality", "name"),
    [
        ("canny", "diffusers_xl_canny_fp16.safetensors"),
        ("depth", "diffusers_xl_depth_fp16.safetensors"),
    ],
)
def test_catalogued_but_unadmitted_fp16_identities_are_not_runnable(
    tmp_path, modality, name
) -> None:
    entry = _controlnet(tmp_path, modality=modality, installed=name)
    assert entry["ready_for_use"] is False
    assert entry["status"] == UNSUPPORTED and IDENTITY_REASON in entry["reason_codes"]
    # integrity is a separate fact: the bytes are the expected ones and the architecture is SDXL
    (weights,) = entry["files"]
    assert weights["status"] == VERIFIED
    assert "controlnet_header_not_sdxl" not in entry["reason_codes"]


def test_an_arbitrary_alias_with_the_correct_digest_is_not_runnable(tmp_path) -> None:
    entry = _controlnet(
        tmp_path,
        modality="canny",
        installed="my_favourite_canny.safetensors",
        expected="diffusers_xl_canny_full.safetensors",
    )
    (weights,) = entry["files"]
    assert weights["status"] == VERIFIED and "verified_under_alias_name" in weights["reason_codes"]
    assert entry["ready_for_use"] is False and IDENTITY_REASON in entry["reason_codes"]


def test_a_sanctioned_name_in_a_subfolder_or_other_case_remains_runnable(tmp_path) -> None:
    entry = _controlnet(
        tmp_path,
        modality="canny",
        installed="Diffusers_XL_Canny_Full.safetensors",
        expected="diffusers_xl_canny_full.safetensors",
        subfolder="sdxl",
    )
    assert entry["status"] == VERIFIED and entry["ready_for_use"] is True


def test_another_modalitys_admitted_identity_does_not_admit_this_modality(tmp_path) -> None:
    entry = _controlnet(tmp_path, modality="canny", installed="diffusers_xl_depth_full.safetensors")
    assert entry["ready_for_use"] is False and IDENTITY_REASON in entry["reason_codes"]


def test_correct_filename_with_wrong_hash_is_a_mismatch(tmp_path) -> None:
    entry = _controlnet(
        tmp_path,
        modality="canny",
        installed="diffusers_xl_canny_full.safetensors",
        wrong_bytes=True,
    )
    assert entry["status"] == MISMATCH and entry["ready_for_use"] is False


@pytest.mark.parametrize("family", ["unknown", "contradictory", "sd15"])
def test_unknown_or_incompatible_architecture_fails_closed(tmp_path, family) -> None:
    entry = _controlnet(
        tmp_path, modality="canny", installed="diffusers_xl_canny_full.safetensors", family=family
    )
    assert entry["ready_for_use"] is False


def test_the_checked_in_catalog_filenames_match_the_production_identity_policy() -> None:
    admitted = {"canny": set(), "depth": set(), "openpose": set()}
    refused = set()
    for item in load_catalog().resources:
        if not item.capability.id.startswith("controlnet_unit."):
            continue
        for spec in item.files:
            for option in spec.variants:
                name = option.suggested_filename
                if model_problem(item.capability.modality, name, "sdxl") == "":
                    admitted[item.capability.modality].add(name)
                else:
                    refused.add(name)
    assert admitted["canny"] == {"diffusers_xl_canny_full.safetensors"}
    assert admitted["depth"] == {"diffusers_xl_depth_full.safetensors"}
    assert admitted["openpose"] == {
        "thibaud_xl_openpose.safetensors",
        "xinsir_openpose_sdxl.safetensors",
    }
    assert refused == {"diffusers_xl_canny_fp16.safetensors", "diffusers_xl_depth_fp16.safetensors"}
    assert set(MODEL_MODALITIES) >= {
        name.removesuffix(".safetensors") for names in admitted.values() for name in names
    }


# ------------------------------------------------------------------------------------------ Finding B


def _aux_catalog(*directories: str, required: bool = True, digest: str):
    return make_catalog(
        *(
            resource(
                name,
                [file_spec("weights", [variant("model.safetensors", digest)], required=required)],
            )
            for name in directories
        )
    )


def _aux_registry(tmp_path: Path, *placements: str):
    registry = make_registry(tmp_path)
    digest = ""
    for placement in placements:
        weights = write_safetensors(aux_dir(registry) / placement / "model.safetensors")
        digest = sha256_of(weights)
    return registry, digest


def test_bytes_in_one_resources_directory_never_satisfy_another_resource(tmp_path) -> None:
    registry, digest = _aux_registry(tmp_path, "res-a")
    catalog = _aux_catalog("res-a", "res-b", digest=digest)
    report = build_report(catalog, collect_installed_evidence(registry, catalog, refresh=True))
    assert _entry(report, "res-a")["files"][0]["status"] == VERIFIED
    b = _entry(report, "res-b")
    assert b["status"] == MISSING and b["files"][0]["status"] == MISSING
    assert b["files"][0]["installed"] == []


def test_the_same_bytes_in_the_correct_directory_verify_each_resource(tmp_path) -> None:
    registry, digest = _aux_registry(tmp_path, "res-a", "res-b")
    catalog = _aux_catalog("res-a", "res-b", digest=digest)
    report = build_report(catalog, collect_installed_evidence(registry, catalog, refresh=True))
    assert _entry(report, "res-a")["files"][0]["status"] == VERIFIED
    assert _entry(report, "res-b")["files"][0]["status"] == VERIFIED
    assert _entry(report, "res-b")["files"][0]["installed"][0]["locations"] == [
        "models/StableNewAux/res-b/model.safetensors"
    ]


def test_wrong_bytes_in_the_correct_directory_are_a_mismatch_not_an_ambiguity(tmp_path) -> None:
    registry, digest = _aux_registry(tmp_path, "res-a")
    write_safetensors(aux_dir(registry) / "res-b" / "model.safetensors", b"\x05\x05\x05\x05")
    catalog = _aux_catalog("res-a", "res-b", digest=digest)
    report = build_report(catalog, collect_installed_evidence(registry, catalog, refresh=True))
    assert _entry(report, "res-a")["files"][0]["status"] == VERIFIED
    assert _entry(report, "res-b")["files"][0]["status"] == MISMATCH


@pytest.mark.parametrize(
    "relative",
    [
        "res-a/model.safetensors",
        "../res-a/model.safetensors",
        "res-b/../res-a/model.safetensors",
        "res-b/./../res-a/model.safetensors",
        "RES-A/model.safetensors",
        "res-bx/model.safetensors",
        "model.safetensors",
        "/res-b/model.safetensors",
        "res-b//model.safetensors",
    ],
)
def test_paths_outside_or_escaping_the_resource_directory_are_never_candidates(relative) -> None:
    digest = "a" * 64
    catalog = _aux_catalog("res-b", digest=digest)
    evidence = InstalledEvidence(
        (InstalledFile("auxiliary", relative, 10, digest),), "explicit_refresh", True
    )
    entry = _entry(build_report(catalog, evidence), "res-b")
    assert entry["files"][0]["status"] == MISSING and entry["files"][0]["installed"] == []


def test_a_nested_file_inside_the_resource_directory_still_counts_by_digest() -> None:
    digest = "b" * 64
    catalog = _aux_catalog("res-b", digest=digest)
    evidence = InstalledEvidence(
        (InstalledFile("auxiliary", "res-b/sub/copy.safetensors", 10, digest),),
        "explicit_refresh",
        True,
    )
    assert _entry(build_report(catalog, evidence), "res-b")["files"][0]["status"] == VERIFIED


def test_cached_or_incomplete_inventory_never_proves_absence_or_presence_elsewhere(
    tmp_path,
) -> None:
    registry, digest = _aux_registry(tmp_path, "res-a")
    catalog = _aux_catalog("res-a", "res-b", digest=digest)
    cached = collect_installed_evidence(registry, catalog, refresh=False)
    assert cached.complete is False
    b = _entry(build_report(catalog, cached), "res-b")
    assert b["files"][0]["status"] == INCOMPLETE and b["status"] == INCOMPLETE
    incomplete = InstalledEvidence(
        (InstalledFile("auxiliary", "res-a/model.safetensors", 10, digest),),
        "cached_snapshot",
        False,
        "not_refreshed",
    )
    report = build_report(catalog, incomplete)
    assert _entry(report, "res-b")["files"][0]["status"] == INCOMPLETE
    assert _entry(report, "res-a")["files"][0]["status"] == VERIFIED


def test_reference_map_verification_cannot_borrow_another_resources_file(tmp_path) -> None:
    registry = make_registry(tmp_path)
    foreign = write_safetensors(aux_dir(registry) / "some-other-resource" / "model.safetensors")
    catalog = make_catalog(
        resource(
            "depth-anything-v2-small-hf",
            [file_spec("weights", [variant("model.safetensors", sha256_of(foreign))])],
        )
    )
    with pytest.raises(ProviderUnavailable) as caught:
        auxiliary.verify_resource(registry, "depth", catalog=catalog)
    assert caught.value.reasons == ("resource_missing:weights",)
    # the same bytes in the resource's own directory are accepted, from that directory
    write_safetensors(aux_dir(registry) / "depth-anything-v2-small-hf" / "model.safetensors")
    verified = auxiliary.verify_resource(registry, "depth", catalog=catalog)
    assert [item.relative for item in verified.files] == [
        "depth-anything-v2-small-hf/model.safetensors"
    ]


def test_unpinned_files_still_report_present_unverified_inside_their_directory(tmp_path) -> None:
    registry = make_registry(tmp_path)
    (aux_dir(registry) / "res-c").mkdir(parents=True)
    (aux_dir(registry) / "res-c" / "config.json").write_text("{}", encoding="utf-8")
    catalog = make_catalog(resource("res-c", [file_spec("cfg", [variant("config.json", None)])]))
    report = build_report(catalog, collect_installed_evidence(registry, catalog, refresh=True))
    assert _entry(report, "res-c")["files"][0]["status"] == PRESENT_UNVERIFIED


def test_readiness_and_production_admission_share_one_identity_policy() -> None:
    assert forge_controlnet_units.MODEL_MODALITIES is controlnet_identity.MODEL_MODALITIES
    assert forge_controlnet_units.model_problem is controlnet_identity.model_problem
