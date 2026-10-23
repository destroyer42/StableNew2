"""Curated resource readiness (PR-ASSET-130): offline, byte-identity-first, deterministic, no model ever loaded."""

from __future__ import annotations

import ast
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from src.assets import registry as registry_module
from src.assets.resource_catalog import CatalogError, load_catalog, parse_catalog
from src.assets.resource_readiness import (
    AMBIGUOUS,
    INCOMPLETE,
    MISMATCH,
    MISSING,
    NEEDS_INTEGRATION,
    PRESENT_UNVERIFIED,
    UNSUPPORTED,
    VERIFIED,
    InstalledEvidence,
    InstalledFile,
    build_report,
    collect_installed_evidence,
    render_console,
    render_json,
)
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
    write_text,
)
from tests.conditioning.openpose_fixtures_210 import write_controlnet_weights


def _entry(report: dict, rid: str) -> dict:
    return next(item for item in report["resources"] if item["id"] == rid)


def _file(report: dict, rid: str, role: str) -> dict:
    return next(item for item in _entry(report, rid)["files"] if item["role"] == role)


def _report(tmp_path: Path, catalog, *, refresh: bool = True, **kwargs):
    registry = make_registry(tmp_path)
    evidence = collect_installed_evidence(registry, catalog, refresh=refresh, **kwargs)
    return build_report(catalog, evidence), registry


# ------------------------------------------------------------------ 1-2: genuine hash decides, never the filename


def test_genuine_sha256_verifies_and_capability_comes_from_product_policy(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    weights = write_controlnet_weights(controlnet_dir(registry) / "canny_xl.safetensors", "sdxl")
    catalog = make_catalog(
        resource(
            "cn-canny",
            [file_spec("weights", [variant("canny_xl.safetensors", sha256_of(weights))])],
            root="controlnet",
            capability=controlnet_capability("canny"),
        )
    )

    report, _ = _report(tmp_path, catalog)

    entry = _entry(report, "cn-canny")
    assert entry["status"] == VERIFIED
    assert entry["ready_for_use"] is True
    assert entry["capability"]["policy"] == "supported_now"
    assert _file(report, "cn-canny", "weights")["installed"][0]["locations"] == [
        "models/ControlNet/canny_xl.safetensors"
    ]


def test_verified_bytes_that_the_header_says_are_not_sdxl_are_unsupported(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    weights = write_controlnet_weights(controlnet_dir(registry) / "canny_xl.safetensors", "sd15")
    catalog = make_catalog(
        resource(
            "cn-canny",
            [file_spec("weights", [variant("canny_xl.safetensors", sha256_of(weights))])],
            root="controlnet",
            capability=controlnet_capability("canny"),
        )
    )

    entry = _entry(_report(tmp_path, catalog)[0], "cn-canny")

    assert entry["status"] == UNSUPPORTED
    assert entry["ready_for_use"] is False
    assert "controlnet_header_not_sdxl" in entry["reason_codes"]


def test_a_catalog_claim_cannot_grant_a_capability_the_product_lacks(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    weights = write_safetensors(aux_dir(registry) / "r" / "model.safetensors")
    catalog = make_catalog(
        resource(
            "r",
            [file_spec("weights", [variant("model.safetensors", sha256_of(weights))])],
            capability={
                "id": "segmentation.test",
                "policy": "supported_now",
                "modality": None,
                "reason_codes": [],
                "basis": "claimed",
            },
        )
    )

    entry = _entry(_report(tmp_path, catalog)[0], "r")

    assert entry["status"] == NEEDS_INTEGRATION
    assert entry["ready_for_use"] is False


def test_correct_filename_with_wrong_bytes_is_a_mismatch(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    expected = write_controlnet_weights(tmp_path / "expected.safetensors", "sdxl")
    write_safetensors(controlnet_dir(registry) / "canny_xl.safetensors", b"\x01\x02\x03\x04")
    catalog = make_catalog(
        resource(
            "cn-canny",
            [file_spec("weights", [variant("canny_xl.safetensors", sha256_of(expected))])],
            root="controlnet",
            capability=controlnet_capability("canny"),
        )
    )

    entry = _entry(_report(tmp_path, catalog)[0], "cn-canny")

    assert entry["status"] == MISMATCH
    assert entry["ready_for_use"] is False
    assert _file(_report(tmp_path, catalog)[0], "cn-canny", "weights")["reason_codes"] == [
        "hash_mismatch"
    ]


# ------------------------------------------------------------------ 3: groups


def test_an_incomplete_bundle_is_not_ready_and_names_the_missing_role(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    weights = write_safetensors(aux_dir(registry) / "bundle" / "model.safetensors")
    # An old same-named file in another resource's folder must never stand in for the missing config.
    write_text(aux_dir(registry) / "other" / "config.json", "{}")
    catalog = make_catalog(
        resource(
            "bundle",
            [
                file_spec("weights", [variant("model.safetensors", sha256_of(weights))]),
                file_spec("model_config", [variant("config.json", None)]),
            ],
        )
    )

    entry = _entry(_report(tmp_path, catalog)[0], "bundle")

    assert entry["status"] == MISSING
    assert entry["missing_roles"] == ["model_config"]
    assert entry["ready_for_use"] is False
    assert any("config.json" in step for step in entry["acquisition"]["steps"])


# ------------------------------------------------------------------ 4-5: aliases and collisions


def test_the_same_bytes_in_two_locations_are_one_identity_with_both_locations(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    weights = write_controlnet_weights(controlnet_dir(registry) / "canny_xl.safetensors", "sdxl")
    (controlnet_dir(registry) / "backup").mkdir()
    (controlnet_dir(registry) / "backup" / "canny_xl.safetensors").write_bytes(weights.read_bytes())
    catalog = make_catalog(
        resource(
            "cn-canny",
            [file_spec("weights", [variant("canny_xl.safetensors", sha256_of(weights))])],
            root="controlnet",
            capability=controlnet_capability("canny"),
        )
    )

    report, _ = _report(tmp_path, catalog)

    installed = _file(report, "cn-canny", "weights")["installed"]
    assert len(installed) == 1
    assert installed[0]["locations"] == [
        "models/ControlNet/backup/canny_xl.safetensors",
        "models/ControlNet/canny_xl.safetensors",
    ]
    assert _entry(report, "cn-canny")["status"] == VERIFIED
    assert "duplicate_locations" in _file(report, "cn-canny", "weights")["reason_codes"]


def test_same_filename_with_different_bytes_is_ambiguous_even_if_one_copy_is_right(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    right = write_controlnet_weights(controlnet_dir(registry) / "canny_xl.safetensors", "sdxl")
    write_safetensors(
        controlnet_dir(registry) / "old" / "canny_xl.safetensors", b"\x09\x09\x09\x09"
    )
    catalog = make_catalog(
        resource(
            "cn-canny",
            [file_spec("weights", [variant("canny_xl.safetensors", sha256_of(right))])],
            root="controlnet",
            capability=controlnet_capability("canny"),
        )
    )

    entry = _entry(_report(tmp_path, catalog)[0], "cn-canny")

    assert entry["status"] == AMBIGUOUS
    assert entry["ready_for_use"] is False
    assert len(entry["files"][0]["installed"]) == 2


# ------------------------------------------------------------------ 6: unverified evidence


def test_no_pinned_hash_is_present_unverified_without_an_integrity_claim(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    write_text(aux_dir(registry) / "bundle" / "config.json", "{}")
    catalog = make_catalog(
        resource("bundle", [file_spec("model_config", [variant("config.json", None)])])
    )

    entry = _entry(_report(tmp_path, catalog)[0], "bundle")

    assert entry["status"] == PRESENT_UNVERIFIED
    assert entry["files"][0]["reason_codes"] == ["no_pinned_hash"]
    assert entry["ready_for_use"] is False


def test_an_unreadable_safetensors_header_never_verifies(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    broken = aux_dir(registry) / "bundle" / "model.safetensors"
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"\xff" * 64)  # a header length no reader accepts
    catalog = make_catalog(
        resource(
            "bundle", [file_spec("weights", [variant("model.safetensors", sha256_of(broken))])]
        )
    )

    entry = _entry(_report(tmp_path, catalog)[0], "bundle")

    assert entry["status"] == PRESENT_UNVERIFIED
    assert "header_unreadable" in entry["files"][0]["reason_codes"]


# ------------------------------------------------------------------ 7: capability gating


def test_all_files_verified_for_an_unbuilt_feature_is_needs_integration(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    weights = write_safetensors(aux_dir(registry) / "sam" / "model.safetensors")
    catalog = make_catalog(
        resource(
            "sam",
            [file_spec("weights", [variant("model.safetensors", sha256_of(weights))])],
            prerequisites=[
                {
                    "id": "custom_code",
                    "kind": "custom_code",
                    "state": "blocked_by_policy",
                    "description": "d",
                }
            ],
        )
    )

    entry = _entry(_report(tmp_path, catalog)[0], "sam")

    assert entry["status"] == NEEDS_INTEGRATION
    assert entry["files"][0]["status"] == VERIFIED
    assert entry["ready_for_use"] is False
    assert entry["external_prerequisites"][0]["state"] == "blocked_by_policy"
    assert "dispatch" not in json.dumps(entry).lower()


# ------------------------------------------------------------------ 8, 14: offline and no admission


def test_report_generation_is_offline_and_never_loads_a_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = make_registry(tmp_path)
    weights = write_controlnet_weights(controlnet_dir(registry) / "canny_xl.safetensors", "sdxl")
    catalog = make_catalog(
        resource(
            "cn-canny",
            [file_spec("weights", [variant("canny_xl.safetensors", sha256_of(weights))])],
            root="controlnet",
            capability=controlnet_capability("canny"),
        )
    )

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("readiness must stay offline and side-effect free")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    heavy = ("torch", "onnxruntime", "transformers")
    before = {name: name in sys.modules for name in heavy}
    for name in heavy:
        if not before[name]:
            monkeypatch.setitem(sys.modules, name, None)  # an import attempt now raises ImportError

    evidence = collect_installed_evidence(registry, catalog, refresh=True)
    report = build_report(catalog, evidence)
    render_json(report)
    render_console(report)

    assert _entry(report, "cn-canny")["status"] == VERIFIED


def test_readiness_modules_import_no_queue_runner_gui_or_network_layer() -> None:
    forbidden_prefixes = (
        "src.queue",
        "src.controller",
        "src.pipeline",
        "src.api",
        "src.gui",
        "src.image_backends",
        "requests",
        "urllib",
        "http",
        "socket",
        "subprocess",
        "torch",
    )
    for name in ("resource_catalog", "resource_readiness"):
        source = (Path(registry_module.__file__).parent / f"{name}.py").read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                assert not module.startswith(forbidden_prefixes), f"{name} imports {module}"


# ------------------------------------------------------------------ 9: containment and bounded work


def test_wrong_extension_and_pickle_files_are_never_indexed(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    write_text(aux_dir(registry) / "bundle" / "weights.pt", "pickle")
    write_text(aux_dir(registry) / "bundle" / "weights.bin", "pickle")
    write_text(aux_dir(registry) / "bundle" / "notes.md", "x")
    catalog = make_catalog(
        resource("bundle", [file_spec("weights", [variant("model.safetensors", None)])])
    )

    report, _ = _report(tmp_path, catalog)

    assert report["evidence"]["installed_file_count"] == 0
    assert _entry(report, "bundle")["status"] == MISSING


def test_a_link_that_leaves_the_library_is_not_evidence(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    outside = write_text(tmp_path / "outside" / "config.json", "{}")
    link = aux_dir(registry) / "bundle" / "config.json"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable in this environment")
    catalog = make_catalog(
        resource("bundle", [file_spec("model_config", [variant("config.json", None)])])
    )

    report, _ = _report(tmp_path, catalog)

    assert report["evidence"]["installed_file_count"] == 0
    assert _entry(report, "bundle")["status"] == MISSING


def test_auxiliary_containment_rejects_paths_that_resolve_outside_the_root(tmp_path: Path) -> None:
    root = tmp_path / "StableNewAux"
    inside = write_text(root / "r" / "config.json", "{}")
    outside = write_text(tmp_path / "elsewhere" / "config.json", "{}")
    kind = registry_module.AssetKind.AUXILIARY_MODEL

    assert registry_module._contained(kind, root, inside) is True
    assert (
        registry_module._contained(kind, root, root / ".." / "elsewhere" / "config.json") is False
    )
    assert registry_module._contained(kind, root, outside) is False


def test_a_snapshot_location_outside_its_root_is_refused_and_counted(tmp_path: Path) -> None:
    root = tmp_path / "webui" / "models" / "StableNewAux"
    outside = write_text(tmp_path / "elsewhere" / "config.json", "{}")
    location = registry_module.AssetLocation(
        registry_module.AssetKind.AUXILIARY_MODEL, outside, root, "config", 2
    )
    record = registry_module.AssetRecord("ab" * 32, (location,), {}, None)

    class _Registry:
        webui_root = tmp_path / "webui"

        def refresh(self, **_kwargs):
            return type("R", (), {"snapshot": registry_module.AssetRegistrySnapshot((record,))})()

    catalog = make_catalog(
        resource("bundle", [file_spec("model_config", [variant("config.json", None)])])
    )

    evidence = collect_installed_evidence(_Registry(), catalog, refresh=True)

    assert evidence.files == ()
    assert evidence.refused_paths == 1
    assert evidence.complete is True


def test_an_oversized_auxiliary_file_is_refused_not_hashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = make_registry(tmp_path)
    write_text(aux_dir(registry) / "bundle" / "config.json", "x" * 128)
    monkeypatch.setattr(registry_module, "AUXILIARY_MAX_BYTES", 16)
    catalog = make_catalog(
        resource("bundle", [file_spec("model_config", [variant("config.json", None)])])
    )

    report, _ = _report(tmp_path, catalog)

    assert report["evidence"] == {
        "basis": "explicit_refresh",
        "complete": False,
        "incomplete_reason": "refresh_refused",
        "installed_file_count": 0,
        "refused_paths": 0,
    }
    assert _entry(report, "bundle")["status"] == INCOMPLETE


def test_a_cancelled_refresh_is_incomplete_never_missing_or_verified(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    write_text(aux_dir(registry) / "bundle" / "config.json", "{}")
    catalog = make_catalog(
        resource("bundle", [file_spec("model_config", [variant("config.json", None)])])
    )

    evidence = collect_installed_evidence(registry, catalog, refresh=True, cancelled=lambda: True)
    report = build_report(catalog, evidence)

    assert evidence.incomplete_reason == "cancelled"
    assert _entry(report, "bundle")["status"] == INCOMPLETE
    assert report["summary"][MISSING] == 0 and report["summary"][VERIFIED] == 0


def test_a_cached_snapshot_cannot_prove_absence(tmp_path: Path) -> None:
    catalog = make_catalog(
        resource("bundle", [file_spec("model_config", [variant("config.json", None)])])
    )

    report, _ = _report(tmp_path, catalog, refresh=False)

    assert report["evidence"]["basis"] == "cached_snapshot"
    assert report["evidence"]["complete"] is False
    assert _entry(report, "bundle")["status"] == INCOMPLETE


def test_a_header_bomb_is_bounded_and_does_not_verify(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    bomb = aux_dir(registry) / "bundle" / "model.safetensors"
    bomb.parent.mkdir(parents=True)
    bomb.write_bytes((1 << 40).to_bytes(8, "little") + b"{")
    catalog = make_catalog(
        resource("bundle", [file_spec("weights", [variant("model.safetensors", None)])])
    )

    entry = _entry(_report(tmp_path, catalog)[0], "bundle")

    assert entry["status"] == PRESENT_UNVERIFIED
    assert "header_unreadable" in entry["files"][0]["reason_codes"]


# ------------------------------------------------------------------ 10: the one cache


def test_cache_reuse_invalidation_and_recovery_use_the_single_registry_cache(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    weights = write_safetensors(
        aux_dir(registry) / "bundle" / "model.safetensors", b"\x01\x01\x01\x01"
    )
    catalog = make_catalog(
        resource(
            "bundle", [file_spec("weights", [variant("model.safetensors", sha256_of(weights))])]
        )
    )

    first = registry.refresh(kinds={registry_module.AssetKind.AUXILIARY_MODEL})
    second = registry.refresh(kinds={registry_module.AssetKind.AUXILIARY_MODEL})
    assert (first.hashes_computed, second.hashes_computed, second.hash_cache_hits) == (1, 0, 1)
    assert (
        _entry(
            build_report(catalog, collect_installed_evidence(registry, catalog, refresh=False)),
            "bundle",
        )["status"]
        == NEEDS_INTEGRATION
    )

    # A modified file is no longer the pinned bytes, in the cached view too.
    stat_before = weights.stat()
    write_safetensors(weights, b"\x02\x02\x02\x02")
    os.utime(weights, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns + 5_000_000_000))
    stale = collect_installed_evidence(registry, catalog, refresh=False)
    assert stale.files == ()
    refreshed = build_report(catalog, collect_installed_evidence(registry, catalog, refresh=True))
    assert _entry(refreshed, "bundle")["status"] == MISMATCH

    # A corrupted cache recovers on the next explicit refresh.
    registry.cache_path.write_text("{not json", encoding="utf-8")
    recovered = make_registry(tmp_path)
    again = build_report(catalog, collect_installed_evidence(recovered, catalog, refresh=True))
    assert _entry(again, "bundle")["status"] == MISMATCH
    created = sorted(path.name for path in (tmp_path / "state").iterdir())
    assert created == [
        "asset_registry_v1.json",
        "asset_registry_v1.json.lock",
        "asset_registry_v1.unreadable",
    ]
    assert not list(tmp_path.glob("data/*cache*"))


def test_default_registry_refresh_does_not_touch_auxiliary_files(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    write_text(aux_dir(registry) / "bundle" / "config.json", "{}")

    result = registry.refresh()

    assert result.snapshot.records == ()


# ------------------------------------------------------------------ 11: stable output


def test_report_is_byte_stable_and_independent_of_directory_order(tmp_path: Path) -> None:
    catalog = make_catalog(
        resource(
            "zz",
            [file_spec("a", [variant("a.json", None)]), file_spec("b", [variant("b.json", None)])],
        ),
        resource("aa", [file_spec("a", [variant("a.json", None)])]),
    )
    files = tuple(
        InstalledFile("auxiliary", rel, 2, "ab" * 32)
        for rel in ("zz/b.json", "zz/a.json", "aa/a.json")
    )
    forward = InstalledEvidence(files, "explicit_refresh", True)
    backward = InstalledEvidence(tuple(reversed(files)), "explicit_refresh", True)

    assert render_json(build_report(catalog, forward)) == render_json(
        build_report(catalog, backward)
    )
    assert [item["id"] for item in build_report(catalog, forward)["resources"]] == ["aa", "zz"]


def test_report_has_no_absolute_path_username_or_prompt_text(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    weights = write_controlnet_weights(controlnet_dir(registry) / "canny_xl.safetensors", "sdxl")
    catalog = make_catalog(
        resource(
            "cn-canny",
            [file_spec("weights", [variant("canny_xl.safetensors", sha256_of(weights))])],
            root="controlnet",
            capability=controlnet_capability("canny"),
        )
    )

    text = render_json(_report(tmp_path, catalog)[0]) + render_console(
        _report(tmp_path, catalog)[0]
    )

    assert str(tmp_path) not in text and tmp_path.name not in text
    assert os.path.expanduser("~") not in text
    assert "\\" not in text.replace("\\n", "")


# ------------------------------------------------------------------ catalog contract


def test_checked_in_catalog_is_valid_and_states_what_was_verified() -> None:
    catalog = load_catalog()
    ids = {item.id for item in catalog.resources}

    assert {
        "sdxl-controlnet-canny",
        "sdxl-controlnet-depth",
        "sdxl-controlnet-openpose-thibaud",
        "sdxl-controlnet-openpose-xinsir",
        "depth-anything-v2-small-hf",
        "dwpose-onnx",
        "sam-2-1-small",
        "florence-2-base-ft",
    } == ids
    for resource_ in catalog.resources:
        assert resource_.source["url"].startswith("https://huggingface.co/")
        assert resource_.source["revision_status"] == "pinned"
        assert len(resource_.source["revision"]) == 40
        assert resource_.source["license"]["status"] in {"model_card_declared", "unknown"}
        for spec in resource_.files:
            for item in spec.variants:
                assert (item.sha256 is None) == (item.hash_status == "pending_verification")
    # The unverified licence of one repository is stated, not inferred from its neighbours.
    thibaud = next(
        item for item in catalog.resources if item.id == "sdxl-controlnet-openpose-thibaud"
    )
    assert thibaud.source["license"]["status"] == "unknown"
    # Pickle-based containers are never catalogued.
    names = {
        item.suggested_filename
        for res in catalog.resources
        for s in res.files
        for item in s.variants
    }
    assert not any(name.endswith((".pt", ".pth", ".bin", ".ckpt")) for name in names)
    # SAM and Florence stay needs_integration regardless of files.
    for rid in ("sam-2-1-small", "florence-2-base-ft"):
        assert (
            next(r for r in catalog.resources if r.id == rid).capability.policy
            == "needs_integration"
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.update(contract="other/1"),
        lambda raw: raw["resources"][0]["files"][0]["variants"][0].update(sha256="ABC"),
        lambda raw: raw["resources"][0]["files"][0]["variants"][0].update(
            suggested_filename="../evil.json"
        ),
        lambda raw: raw["resources"][0]["files"][0]["variants"][0].update(
            suggested_filename="weights.pt"
        ),
        lambda raw: raw["resources"][0]["source"].update(url="https://example.com/model"),
        lambda raw: raw["resources"][0]["files"][0]["variants"][0].update(
            hash_status="verified_upstream"
        ),
        lambda raw: raw["resources"].append(raw["resources"][0]),
    ],
)
def test_malformed_catalogs_are_refused_whole(mutate) -> None:
    raw = json.loads(
        json.dumps(
            {
                "contract": "curated_asset_catalog/1",
                "catalog_version": "t",
                "description": "d",
                "hash_semantics": "h",
                "resources": [
                    resource("r", [file_spec("weights", [variant("config.json", None)])])
                ],
            }
        )
    )
    mutate(raw)

    with pytest.raises(CatalogError):
        parse_catalog(raw)
