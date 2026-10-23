"""PR-ASSET-130 readiness CLI: offline, sanitized, deterministic, cache-only unless refresh is explicit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.assets.readiness_fixtures_130 import (
    aux_dir,
    controlnet_capability,
    controlnet_dir,
    file_spec,
    make_registry,
    resource,
    sha256_of,
    variant,
    write_safetensors,
)
from tests.conditioning.openpose_fixtures_210 import write_controlnet_weights
from tools import asset_readiness_report as cli


@pytest.fixture
def scenario(tmp_path: Path) -> tuple[Path, Path]:
    """A verified ControlNet, a mismatched one, a bundle missing a dependency and a verified-but-unsupported model."""

    registry = make_registry(tmp_path)
    canny = write_controlnet_weights(controlnet_dir(registry) / "canny_xl.safetensors", "sdxl")
    expected_depth = write_controlnet_weights(
        tmp_path / "upstream_depth.safetensors", "sdxl_original_layout"
    )
    write_safetensors(controlnet_dir(registry) / "depth_xl.safetensors", b"\x07\x07\x07\x07")
    segment = write_safetensors(
        aux_dir(registry) / "fx-segment" / "model.safetensors", b"\x05\x05\x05\x05"
    )
    bundle = write_safetensors(
        aux_dir(registry) / "fx-pose-bundle" / "model.safetensors", b"\x06\x06\x06\x06"
    )
    catalog = {
        "contract": "curated_asset_catalog/1",
        "catalog_version": "fixture.1",
        "description": "fixture",
        "hash_semantics": "fixture",
        "resources": [
            resource(
                "fx-canny",
                [file_spec("weights", [variant("canny_xl.safetensors", sha256_of(canny))])],
                root="controlnet",
                capability=controlnet_capability("canny"),
            ),
            resource(
                "fx-depth",
                [
                    file_spec(
                        "weights", [variant("depth_xl.safetensors", sha256_of(expected_depth))]
                    )
                ],
                root="controlnet",
                capability=controlnet_capability("depth"),
            ),
            resource(
                "fx-pose-bundle",
                [
                    file_spec("weights", [variant("model.safetensors", sha256_of(bundle))]),
                    file_spec("model_config", [variant("config.json", None)]),
                ],
            ),
            resource(
                "fx-segment",
                [file_spec("weights", [variant("model.safetensors", sha256_of(segment))])],
            ),
        ],
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    return tmp_path, path


def run(tmp_path: Path, catalog: Path, *extra: str) -> int:
    return cli.main(
        [
            "--webui-root",
            str(tmp_path / "webui"),
            "--cache-path",
            str(tmp_path / "state" / "asset_registry_v1.json"),
            "--catalog",
            str(catalog),
            *extra,
        ]
    )


def test_refresh_reports_each_readiness_state_in_sanitized_stable_json(
    scenario, tmp_path_factory
) -> None:
    tmp_path, catalog = scenario
    first, second = tmp_path / "a.json", tmp_path / "b.json"

    assert run(tmp_path, catalog, "--refresh", "--json", str(first)) == 0
    assert run(tmp_path, catalog, "--refresh", "--json", str(second)) == 0

    assert first.read_bytes() == second.read_bytes()
    report = json.loads(first.read_text(encoding="utf-8"))
    assert {item["id"]: item["status"] for item in report["resources"]} == {
        "fx-canny": "verified",
        "fx-depth": "mismatch",
        "fx-pose-bundle": "missing",
        "fx-segment": "needs_integration",
    }
    assert next(i for i in report["resources"] if i["id"] == "fx-pose-bundle")["missing_roles"] == [
        "model_config"
    ]
    assert str(tmp_path) not in first.read_text(encoding="utf-8")
    verified_files = [
        file
        for item in report["resources"]
        for file in item["files"]
        if file["status"] == "verified"
    ]
    assert verified_files and all(
        "verified_under_alias_name" not in f["reason_codes"] for f in verified_files
    )


def test_default_run_reads_the_cache_only_and_cannot_claim_absence(scenario, capsys) -> None:
    tmp_path, catalog = scenario

    assert run(tmp_path, catalog) == 3

    assert not (tmp_path / "state" / "asset_registry_v1.json").exists()
    out = capsys.readouterr().out
    assert "INCOMPLETE" in out and "missing" not in out.split("\n", 1)[0]


def test_an_unusable_catalog_is_refused_before_any_scan(tmp_path: Path, capsys) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")

    assert run(tmp_path, bad, "--refresh") == 2
    assert "Catalog refused" in capsys.readouterr().err
    assert not (tmp_path / "state").exists()


def test_the_checked_in_catalog_on_an_empty_library_is_all_missing(tmp_path: Path) -> None:
    (tmp_path / "webui" / "models").mkdir(parents=True)
    out = tmp_path / "report.json"
    argv = [
        "--webui-root",
        str(tmp_path / "webui"),
        "--cache-path",
        str(tmp_path / "c.json"),
        "--refresh",
    ]

    assert cli.main([*argv, "--json", str(out)]) == 0

    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["summary"]["missing"] == 8
    assert all(item["acquisition"]["steps"] for item in report["resources"])
