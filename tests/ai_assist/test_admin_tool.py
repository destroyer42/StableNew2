"""Operator tooling: a manifest entry is computed from a local archive by reading only; nothing is extracted or run."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from src.ai_assist.manifests import ImportRefused, describe_runtime_archive
from tools import ai_assist_admin

from .conftest import FILES, build_archive, make_build, sha

DESCRIBE = {
    "build_id": "b0000-cpu",
    "upstream_repository": "https://example.invalid/llama.cpp",
    "upstream_tag": "b0000",
    "license_spdx": "MIT",
    "executable": "llama-cli.exe",
}


def test_describe_matches_the_hand_built_entry_and_extracts_nothing(tmp_path: Path) -> None:
    data = build_archive(FILES, {"README.txt": b"docs"})
    archive = tmp_path / "pkg" / "runtime.zip"
    archive.parent.mkdir()
    archive.write_bytes(data)
    entry = describe_runtime_archive(archive, **DESCRIBE)
    expected = make_build(data, qualified=False)
    assert entry["asset_sha256"] == sha(data) == expected.asset_sha256
    assert entry["files"] == dict(sorted(expected.files.items()))
    assert entry["qualified"] is False and entry["asset_name"] == "runtime.zip"
    assert [p.name for p in archive.parent.iterdir()] == ["runtime.zip"], "nothing may be extracted"


def test_describe_refuses_hostile_or_unusable_archives(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as bundle:
        bundle.writestr("../evil.dll", b"x")
    with pytest.raises(ImportRefused):
        describe_runtime_archive(bad, **DESCRIBE)
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"not a zip")
    with pytest.raises(ImportRefused) as caught:
        describe_runtime_archive(broken, **DESCRIBE)
    assert caught.value.code == "archive_unreadable"
    missing_exe = tmp_path / "noexe.zip"
    missing_exe.write_bytes(build_archive({"ggml.dll": b"x"}))
    with pytest.raises(ImportRefused) as caught:
        describe_runtime_archive(missing_exe, **DESCRIBE)
    assert caught.value.code == "entry_invalid"


def test_cli_describe_prints_json_and_imports_refuse_unpinned(tmp_path: Path, capsys) -> None:
    archive = tmp_path / "runtime.zip"
    archive.write_bytes(build_archive(FILES))
    root = ["--root", str(tmp_path / "ai")]
    argv = [
        *root,
        "describe-runtime",
        str(archive),
        "--build-id",
        "b0000-cpu",
        "--upstream-repository",
        "https://example.invalid/llama.cpp",
        "--upstream-tag",
        "b0000",
        "--license-spdx",
        "MIT",
        "--executable",
        "llama-cli.exe",
    ]
    assert ai_assist_admin.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["executable"] == "llama-cli.exe"
    assert not (tmp_path / "ai").exists()
    assert ai_assist_admin.main([*root, "import-runtime", str(archive), "--build-id", "nope"]) == 2
    assert ai_assist_admin.main([*root, "import-model", str(archive), "--model-id", "nope"]) == 2
    assert ai_assist_admin.main([*root, "status"]) == 0
    assert not (tmp_path / "ai").exists()


def test_cli_attestation_and_status(tmp_path: Path, capsys) -> None:
    root = ["--root", str(tmp_path / "ai")]
    assert ai_assist_admin.main([*root, "record-attestation", "--statement", "rule X"]) == 0
    capsys.readouterr()
    assert ai_assist_admin.main([*root, "status"]) == 0
    assert json.loads(capsys.readouterr().out)["egress"] == "attested"
