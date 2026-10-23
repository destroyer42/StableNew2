"""Provenance-gated registry, local import and fail-closed verification (owner decisions D4 and D6)."""

from __future__ import annotations

import json
import os
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from src.ai_assist.contracts import OutcomeCode
from src.ai_assist.manifests import (
    ImportRefused,
    ModelRegistry,
    RuntimeManifest,
    hash_file,
    import_model,
    import_runtime,
    load_model_registry,
    load_runtime_manifest,
    record_active,
    verify_installation,
)
from src.ai_assist.paths import active_pointer_path, model_dir, runtime_dir
from src.ai_assist.status import MODEL_REGISTRY_PATH, RUNTIME_MANIFEST_PATH

from .conftest import FILES, MODEL_BYTES, Install, build_archive, make_build, make_entry, sha


def test_shipped_manifests_parse_cleanly_and_nothing_is_qualified() -> None:
    runtime = load_runtime_manifest(RUNTIME_MANIFEST_PATH)
    registry = load_model_registry(MODEL_REGISTRY_PATH)
    assert runtime.problems == () and registry.problems == ()
    # No runtime build is pinned until the operator imports the archive and every loadable file can be hashed.
    assert runtime.builds == ()
    assert not any(build.qualified for build in runtime.builds)
    assert len(registry.entries) >= 1 and not any(entry.qualified for entry in registry.entries)


def test_shipped_candidate_pins_are_complete_unique_and_content_addressed() -> None:
    import re

    registry = load_model_registry(MODEL_REGISTRY_PATH)
    assert len({e.model_id for e in registry.entries}) == len(registry.entries)
    assert len({e.sha256 for e in registry.entries}) == len(registry.entries)
    for entry in registry.entries:
        assert re.fullmatch(r"[0-9a-f]{64}", entry.sha256) and entry.bytes > 10**8
        assert entry.filename.endswith(".gguf") and entry.license_spdx == "Apache-2.0"
        assert re.fullmatch(r"[0-9a-f]{40}", entry.provenance.publisher_revision)
        assert re.fullmatch(r"[0-9a-f]{40}", entry.provenance.packager_revision)
        assert entry.provenance.source_url.startswith("https://huggingface.co/")
        assert entry.provenance.packager_revision in entry.provenance.source_url
        assert entry.filename in entry.provenance.source_url


def _model_doc(**overrides) -> dict:
    entry = {
        "model_id": "m1",
        "display_name": "M1",
        "license_spdx": "Apache-2.0",
        "architecture": "qwen3_5",
        "quantization": "Q4_K_M",
        "filename": "m1.gguf",
        "bytes": 10,
        "sha256": "a" * 64,
        "provenance": {
            "publisher_repo": "Qwen/Qwen3.5-9B",
            "publisher_revision": "abc1234",
            "packager_repo": "someone/gguf",
            "packager_revision": "def5678",
            "converter": "llama.cpp b0",
            "source_url": "https://huggingface.co/someone/gguf",
        },
    }
    entry.update(overrides)
    return {"schema_version": 1, "models": [entry]}


def test_registry_entry_needs_complete_provenance_hash_and_a_plain_filename() -> None:
    assert len(load_model_registry(json.dumps(_model_doc())).entries) == 1
    broken = [
        _model_doc(provenance={"publisher_repo": "x"}),
        _model_doc(provenance=None),
        _model_doc(sha256="A" * 64),
        _model_doc(sha256="a" * 63),
        _model_doc(bytes=0),
        _model_doc(filename="../escape.gguf"),
        _model_doc(filename="model.bin"),
        _model_doc(model_id="../x"),
        _model_doc(max_context=10),
    ]
    http = _model_doc()
    http["models"][0]["provenance"]["source_url"] = "http://insecure.example"
    broken.append(http)
    for document in broken:
        registry = load_model_registry(json.dumps(document))
        assert registry.entries == () and len(registry.problems) == 1, document


def test_unreadable_or_unsupported_documents_yield_problems_not_exceptions(tmp_path: Path) -> None:
    assert load_model_registry(tmp_path / "missing.json").problems
    assert load_runtime_manifest("{broken").problems
    assert load_runtime_manifest(json.dumps({"schema_version": 9, "builds": []})).problems


def test_runtime_build_must_pin_every_file_and_name_an_executable_among_them() -> None:
    build = make_build(build_archive(FILES))
    good = {
        "build_id": build.build_id,
        "upstream_repository": build.upstream_repository,
        "upstream_tag": build.upstream_tag,
        "asset_name": build.asset_name,
        "asset_sha256": build.asset_sha256,
        "asset_bytes": build.asset_bytes,
        "license_spdx": "MIT",
        "executable": "llama-cli.exe",
        "files": dict(build.files),
    }
    assert (
        len(load_runtime_manifest(json.dumps({"schema_version": 1, "builds": [good]})).builds) == 1
    )
    for patch in (
        {"executable": "other.exe"},
        {"files": {}},
        {"files": {"../evil.dll": "a" * 64, "llama-cli.exe": "a" * 64}},
        {"files": {"C:/evil.dll": "a" * 64, "llama-cli.exe": "a" * 64}},
        {"asset_sha256": "xyz"},
    ):
        parsed = load_runtime_manifest(
            json.dumps({"schema_version": 1, "builds": [{**good, **patch}]})
        )
        assert parsed.builds == () and parsed.problems


def test_import_model_proves_identity_before_installing(tmp_path: Path) -> None:
    entry = make_entry()
    good = tmp_path / "m.gguf"
    good.write_bytes(MODEL_BYTES)
    wrong_size = tmp_path / "s.gguf"
    wrong_size.write_bytes(MODEL_BYTES + b"x")
    wrong_hash = tmp_path / "h.gguf"
    wrong_hash.write_bytes(b"X" * len(MODEL_BYTES))
    root = tmp_path / "ai"
    for bad, code in (
        (wrong_size, "size_mismatch"),
        (wrong_hash, "hash_mismatch"),
        (tmp_path / "no", "source_missing"),
    ):
        with pytest.raises(ImportRefused) as raised:
            import_model(bad, entry, root)
        assert raised.value.code == code
    assert not (root / "models").exists() or not list((root / "models").rglob("*.gguf"))
    installed = import_model(good, entry, root)
    assert installed == model_dir(root, entry.sha256) / entry.filename
    assert hash_file(installed)[0] == entry.sha256
    with pytest.raises(ImportRefused) as again:
        import_model(good, entry, root)
    assert again.value.code == "already_installed"
    assert not list(installed.parent.glob("*.partial"))


def test_import_runtime_confines_the_archive_and_pins_every_loadable_file(tmp_path: Path) -> None:
    archive_bytes = build_archive(FILES)
    build = make_build(archive_bytes)
    root = tmp_path / "ai"

    def attempt(data: bytes, **build_changes) -> str:
        path = tmp_path / "a.zip"
        path.write_bytes(data)
        target = replace(build, asset_sha256=sha(data), asset_bytes=len(data), **build_changes)
        with pytest.raises(ImportRefused) as raised:
            import_runtime(path, target, root)
        return raised.value.code

    assert attempt(build_archive(FILES, {"../escape.dll": b"x"})) == "unsafe_archive_path"
    assert attempt(build_archive(FILES, {"extra.exe": b"x"})) == "unlisted_executable_content"
    assert attempt(build_archive(FILES, {"run.ps1": b"x"})) == "unlisted_executable_content"
    assert (
        attempt(build_archive({"llama-cli.exe": FILES["llama-cli.exe"]})) == "pinned_file_missing"
    )
    tampered = dict(FILES, **{"ggml.dll": b"tampered!!!!!!!!!!"})
    assert attempt(build_archive(tampered)) == "pinned_file_hash_mismatch"
    assert attempt(b"not a zip at all") == "archive_unreadable"
    wrong = tmp_path / "wrong.zip"
    wrong.write_bytes(archive_bytes + b"\0")
    with pytest.raises(ImportRefused) as raised:
        import_runtime(wrong, build, root)
    assert raised.value.code == "size_mismatch"
    assert not runtime_dir(root, build.build_id).exists()
    assert not list((root / "runtimes").glob(".*staging")) if (root / "runtimes").exists() else True

    good = tmp_path / "good.zip"
    good.write_bytes(archive_bytes)
    installed = import_runtime(good, build, root)
    assert (installed / "llama-cli.exe").read_bytes() == FILES["llama-cli.exe"]
    with pytest.raises(ImportRefused) as again:
        import_runtime(good, build, root)
    assert again.value.code == "already_installed"


def test_symlink_members_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "link.zip"
    with zipfile.ZipFile(path, "w") as bundle:
        info = zipfile.ZipInfo("llama-cli.exe")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        bundle.writestr(info, "target")
    data = path.read_bytes()
    build = replace(make_build(build_archive(FILES)), asset_sha256=sha(data), asset_bytes=len(data))
    with pytest.raises(ImportRefused) as raised:
        import_runtime(path, build, tmp_path / "ai")
    assert raised.value.code == "archive_symlink"


def test_verification_passes_for_an_intact_installation(installation: Install) -> None:
    result = verify_installation(installation.root, installation.manifest, installation.registry)
    assert result.ok and result.executable is not None and result.model_path is not None
    assert verify_installation(
        installation.root, installation.manifest, installation.registry, deep=True
    ).ok


def test_nothing_installed_is_not_installed_and_a_corrupt_pointer_is_an_integrity_failure(
    installation: Install, tmp_path: Path
) -> None:
    empty = verify_installation(tmp_path / "nothing", installation.manifest, installation.registry)
    assert empty.code is OutcomeCode.NOT_INSTALLED
    active_pointer_path(installation.root).write_text("{broken", encoding="utf-8")
    broken = verify_installation(installation.root, installation.manifest, installation.registry)
    assert (broken.code, broken.reason) == (OutcomeCode.INTEGRITY_FAILED, "pointer_invalid")


def test_unknown_hash_or_build_is_refused_with_no_override(installation: Install) -> None:
    other_model = verify_installation(installation.root, installation.manifest, ModelRegistry(()))
    assert (other_model.code, other_model.reason) == (
        OutcomeCode.INTEGRITY_FAILED,
        "unknown_model_hash",
    )
    other_build = verify_installation(installation.root, RuntimeManifest(()), installation.registry)
    assert (other_build.code, other_build.reason) == (
        OutcomeCode.INTEGRITY_FAILED,
        "unknown_runtime_build",
    )
    pointer = json.loads(active_pointer_path(installation.root).read_text(encoding="utf-8"))
    pointer["model_sha256"] = "f" * 64
    active_pointer_path(installation.root).write_text(json.dumps(pointer), encoding="utf-8")
    forged = verify_installation(installation.root, installation.manifest, installation.registry)
    assert forged.reason == "unknown_model_hash"


def test_tampering_is_detected_fast_by_stat_and_deeply_by_hash(installation: Install) -> None:
    dll = runtime_dir(installation.root, installation.build.build_id) / "ggml.dll"
    original_stat = dll.stat()
    dll.write_bytes(b"X" * len(FILES["ggml.dll"]))  # same size, different bytes
    os.utime(dll, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))  # same mtime too
    fast = verify_installation(installation.root, installation.manifest, installation.registry)
    assert fast.ok, "a same-size same-mtime edit is exactly what the deep check exists for"
    deep = verify_installation(
        installation.root, installation.manifest, installation.registry, deep=True
    )
    assert (deep.code, deep.reason) == (OutcomeCode.INTEGRITY_FAILED, "runtime_file_hash:ggml.dll")
    dll.write_bytes(b"short")
    changed = verify_installation(installation.root, installation.manifest, installation.registry)
    assert changed.reason == "runtime_file_changed:ggml.dll"
    dll.unlink()
    assert (
        verify_installation(installation.root, installation.manifest, installation.registry).reason
        == "runtime_file_missing:ggml.dll"
    )


def test_model_file_changes_and_removal_are_integrity_failures(installation: Install) -> None:
    path = model_dir(installation.root, installation.entry.sha256) / installation.entry.filename
    stat = path.stat()
    path.write_bytes(b"Y" * len(MODEL_BYTES))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert verify_installation(installation.root, installation.manifest, installation.registry).ok
    deep = verify_installation(
        installation.root, installation.manifest, installation.registry, deep=True
    )
    assert deep.reason == "model_hash"
    path.write_bytes(b"Y")
    assert (
        verify_installation(installation.root, installation.manifest, installation.registry).reason
        == "model_file_changed"
    )
    path.unlink()
    assert (
        verify_installation(installation.root, installation.manifest, installation.registry).reason
        == "model_file_missing"
    )


def test_unqualified_candidates_are_usable_only_by_the_qualification_harness(
    installation: Install,
) -> None:
    candidate_model = replace(installation.entry, qualified=False)
    registry = ModelRegistry((candidate_model,))
    refused = verify_installation(installation.root, installation.manifest, registry)
    assert (refused.code, refused.reason) == (OutcomeCode.NOT_INSTALLED, "model_not_qualified")
    assert verify_installation(
        installation.root, installation.manifest, registry, allow_candidate=True
    ).ok
    candidate_runtime = RuntimeManifest((replace(installation.build, qualified=False),))
    assert (
        verify_installation(installation.root, candidate_runtime, installation.registry).reason
        == "runtime_not_qualified"
    )


def test_record_active_snapshots_every_pinned_file(installation: Install) -> None:
    pointer = json.loads(active_pointer_path(installation.root).read_text(encoding="utf-8"))
    assert set(pointer["runtime_files"]) == set(FILES)
    assert pointer["model_sha256"] == installation.entry.sha256
    record_active(
        installation.root, installation.build, installation.entry
    )  # re-recording is allowed and atomic
