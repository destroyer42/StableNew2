"""PR-VID-UX-310: the managed Comfy contract is readable by production code, read-only."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.video.managed_comfy_runtime import (
    DEFAULT_MANAGED_COMFY_PORT,
    MANAGED_COMFY_MANIFEST_PATH,
    ManagedComfyContractError,
    assess_comfy_command,
    build_managed_launch_command,
    detect_managed_comfy,
    load_managed_comfy_contract,
    missing_required_flags,
    port_from_base_url,
    with_required_flags,
)
from tools.runtime import verify_managed_comfy


def _install(root: Path, contract, *, version: str | None = None) -> Path:
    install_dir = root / contract.install_dir_name
    python = install_dir / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    source = install_dir / "source"
    source.mkdir(parents=True)
    (source / "main.py").write_text("", encoding="utf-8")
    (source / "comfyui_version.py").write_text(
        f'__version__ = "{version or contract.version}"\n', encoding="utf-8"
    )
    return install_dir


def _runtime(root: Path, contract) -> Path:
    for folder in contract.runtime_folders:
        (root / folder).mkdir(parents=True)
    (root / contract.extra_model_paths_file).write_text("comfyui: {}\n", encoding="utf-8")
    return root


def test_contract_loads_from_the_checked_in_manifest() -> None:
    contract = load_managed_comfy_contract()
    manifest = json.loads(MANAGED_COMFY_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert contract.release == manifest["upstream"]["release"]
    assert contract.listen == "127.0.0.1"
    assert "--disable-pinned-memory" in contract.required_flags
    assert contract.install_dir_name == (
        f"{manifest['upstream']['release']}-py{manifest['python']['minor'].replace('.', '')}"
    )


def test_launch_command_matches_the_operator_verifier(tmp_path) -> None:
    contract = load_managed_comfy_contract()
    manifest = verify_managed_comfy.load_manifest()
    install_dir = tmp_path / "install"
    runtime_dir = tmp_path / "runtime"
    expected = verify_managed_comfy.build_launch_command(
        manifest, install_dir=install_dir, runtime_dir=runtime_dir, port=8199
    )
    actual = build_managed_launch_command(
        contract, install_dir=install_dir, runtime_dir=runtime_dir, port=8199
    )
    if os.name == "nt":
        assert actual == expected
    else:  # the verifier is Windows-only; everything after the interpreter must still agree
        assert actual[1:] == expected[1:]


@pytest.mark.parametrize("payload", ["not json", "[]", json.dumps({"upstream": {}})])
def test_unreadable_contract_raises_a_contract_error(tmp_path, payload) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ManagedComfyContractError):
        load_managed_comfy_contract(path)


def test_detection_finds_a_complete_installation_and_builds_its_settings(tmp_path) -> None:
    contract = load_managed_comfy_contract()
    install_dir = _install(tmp_path / "root", contract)
    runtime_dir = _runtime(tmp_path / "runtime", contract)

    detection = detect_managed_comfy(
        contract, port=8190, install_root=tmp_path / "root", runtime_dir=runtime_dir
    )

    assert detection.found, detection.problems
    updates = detection.settings_updates()
    assert updates["comfy_base_url"] == "http://127.0.0.1:8190"
    assert updates["comfy_workdir"] == str(install_dir / "source")
    command = updates["comfy_command"]
    assert command[command.index("--port") + 1] == "8190"
    assert not missing_required_flags(command, contract.required_flags)
    assessment = assess_comfy_command(command, contract)
    assert assessment.kind == "managed" and assessment.flags_complete


def test_detection_reports_each_missing_piece_and_offers_no_command(tmp_path) -> None:
    contract = load_managed_comfy_contract()

    detection = detect_managed_comfy(
        contract, install_root=tmp_path / "root", runtime_dir=tmp_path / "runtime"
    )

    assert not detection.found
    assert detection.command == ()
    text = " ".join(detection.problems)
    assert "no managed ComfyUI" in text and "bootstrap_managed_comfy_windows.ps1" in text
    assert "runtime folder missing" in text and "model path config missing" in text


def test_detection_refuses_an_installation_of_another_version(tmp_path) -> None:
    contract = load_managed_comfy_contract()
    _install(tmp_path / "root", contract, version="0.0.1")
    runtime_dir = _runtime(tmp_path / "runtime", contract)

    detection = detect_managed_comfy(
        contract, install_root=tmp_path / "root", runtime_dir=runtime_dir
    )

    assert not detection.found
    assert any("reports version 0.0.1" in problem for problem in detection.problems)


def test_assessment_of_none_and_custom_commands() -> None:
    contract = load_managed_comfy_contract()
    assert assess_comfy_command([], contract).kind == "none"
    assert not assess_comfy_command([], contract).flags_complete

    custom = ["C:/desktop/python.exe", "main.py", "--disable-auto-launch"]
    assessment = assess_comfy_command(custom, contract)
    assert assessment.kind == "custom"
    assert "--disable-pinned-memory" in assessment.missing_flags


def test_with_required_flags_appends_only_missing_flags_and_keeps_the_command() -> None:
    command = ["python.exe", "main.py", "--port", "8000", "--disable-auto-launch"]
    fixed = with_required_flags(command, ["--disable-pinned-memory", "--disable-auto-launch"])
    assert fixed == [*command, "--disable-pinned-memory"]
    assert with_required_flags(fixed, ["--disable-pinned-memory"]) == fixed


@pytest.mark.parametrize(
    ("url", "port"),
    [
        ("http://127.0.0.1:8000", 8000),
        ("http://127.0.0.1", DEFAULT_MANAGED_COMFY_PORT),
        ("", DEFAULT_MANAGED_COMFY_PORT),
        ("not a url:abc", DEFAULT_MANAGED_COMFY_PORT),
    ],
)
def test_port_from_base_url(url, port) -> None:
    assert port_from_base_url(url) == port
