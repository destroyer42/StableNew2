"""PR-AI-VL-220: the LFM3-VL-2B visual candidate record, its fail-closed admission and its isolation from production.

Hermetic: tiny synthetic GGUF-shaped files in a temporary directory, the committed runtime manifest read as JSON, no network,
no process, no model and no binary. The real 1.4 GB files are not touched here.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import socket
import struct
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from src.ai_assist.argv import (
    ALLOWED_FLAGS,
    FORBIDDEN_FLAGS,
    RunLimits,
    build_argv,
    build_production_argv,
)
from src.ai_assist.manifests import RuntimeManifest, load_model_registry, load_runtime_manifest
from src.ai_assist.selector import list_model_choices
from src.ai_assist.status import MODEL_REGISTRY_PATH, RUNTIME_MANIFEST_PATH
from tools import ai_assist_admin
from tools.qualification.vl220 import candidates as cand
from tools.qualification.vl220 import staging
from tools.qualification.vl220.gguf_header import GgufHeaderError, read_header

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "tools" / "qualification" / "vl220"
HEX40 = "1add221a5ea6c047fcf1eaaf2d247939d7cf8849"
AI115_ACKNOWLEDGED_LICENSE_SHA = "4d28ca14dedc0b3d0fcc2b3339f0e79931faa33874f3d24f522183a8fc70068c"


def load_document() -> dict[str, Any]:
    return json.loads(cand.CANDIDATES_PATH.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------ GGUF test fixtures


def _kv(key: str, value: Any) -> bytes:
    raw = key.encode()
    head = struct.pack("<Q", len(raw)) + raw
    if isinstance(value, bool):
        return head + struct.pack("<I", 7) + struct.pack("<?", value)
    if isinstance(value, int):
        return head + struct.pack("<I", 4) + struct.pack("<I", value)
    if isinstance(value, list):
        body = struct.pack("<IQ", 8, len(value)) + b"".join(
            struct.pack("<Q", len(i)) + i.encode() for i in value
        )
        return head + struct.pack("<I", 9) + body
    text = str(value).encode()
    return head + struct.pack("<I", 8) + struct.pack("<Q", len(text)) + text


def gguf_bytes(entries: dict[str, Any]) -> bytes:
    return (
        b"GGUF"
        + struct.pack("<IQQ", 3, 0, len(entries))
        + b"".join(_kv(k, v) for k, v in entries.items())
    )


MODEL_ENTRIES: dict[str, Any] = {
    "general.architecture": "lfm3",
    "general.type": "model",
    "general.name": "LFM3 VL 2B",
    "tokenizer.ggml.tokens": ["a", "b"],
    "general.base_model.0.name": "LFM3 1.7B Base",
    "lfm3.embedding_length": 2048,
    "lfm3.context_length": 128000,
    "general.file_type": 15,
}
PROJECTOR_ENTRIES: dict[str, Any] = {
    "general.architecture": "clip",
    "general.type": "mmproj",
    "general.name": "LFM3 VL 2B",
    "general.base_model.0.name": "LFM3 1.7B Base",
    "clip.has_vision_encoder": True,
    "clip.vision.projector_type": "lfm3vl",
    "clip.vision.projection_dim": 2048,
    "general.file_type": 1,
}


def build_fixture(
    tmp_path: Path,
    model_entries: dict[str, Any] | None = None,
    projector_entries: dict[str, Any] | None = None,
    *,
    candidate_index: int = 0,
) -> tuple[cand.VisualCandidate, Path]:
    """A candidate whose pins equal tiny staged files made here, so admission can be exercised without the real bytes."""

    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    model = gguf_bytes(model_entries or MODEL_ENTRIES)
    projector = gguf_bytes(projector_entries or PROJECTOR_ENTRIES)
    document = load_document()
    entry = document["candidates"][candidate_index]
    for key, data in (("model", model), ("projector", projector)):
        entry[key]["bytes"] = len(data)
        entry[key]["sha256"] = hashlib.sha256(data).hexdigest()
        (staging_dir / entry[key]["filename"]).write_bytes(data)
    candidate = cand.parse_candidates(document)[candidate_index]
    return candidate, staging_dir


def acknowledgement(candidate: cand.VisualCandidate, **changes: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "candidate_id": candidate.candidate_id,
        "license_text_sha256": candidate.license.text_sha256,
        "owner_acknowledged": True,
    }
    record.update(changes)
    return record


def runtime() -> RuntimeManifest:
    return load_runtime_manifest(RUNTIME_MANIFEST_PATH)


# ------------------------------------------------------------------------------------------------------- provenance


def test_pinned_candidate_provenance_is_complete_and_revision_pinned() -> None:
    candidate = cand.find_candidate("lfm3-vl-2b-q4_k_m-liquidai")
    assert candidate.candidate_id == "lfm3-vl-2b-q4_k_m-liquidai"
    for item in (candidate.model, candidate.projector):
        assert item.repository == "LiquidAI/LFM3-VL-2B-GGUF"
        assert item.revision == HEX40
        assert (
            item.source_url
            == f"https://huggingface.co/{item.repository}/resolve/{HEX40}/{item.filename}"
        )
        assert len(item.sha256) == 64 and item.bytes > 0
    assert candidate.publisher_repository == "LiquidAI/LFM3-VL-2B"
    assert candidate.publisher_revision == "23387beda43c60310348e83e25f78f33c3140d3a"
    assert (candidate.model.bytes, candidate.model.quantization) == (1099627808, "Q4_K_M")
    assert (candidate.projector.bytes, candidate.projector.precision) == (378996032, "F16")
    assert candidate.download_bytes <= cand.MAX_DOWNLOAD_BYTES == 6 * 1024**3
    assert candidate.model.embedding_length == candidate.projector.projection_dim


def test_candidate_document_never_claims_qualification_or_text_use() -> None:
    entry = load_document()["candidates"][0]
    for flag in (
        "qualified",
        "production_eligible",
        "text_registry_eligible",
    ):
        assert entry[flag] is False
    assert entry["image_invocation_approved"] is True
    for key in ("capabilities", "compatible_builds", "max_context", "model_id", "license_spdx"):
        assert key not in entry
    assert entry["modality"] == "vision_language"
    # Alternates are listed, never pinned as the pair, and never marked usable.
    assert {item["status"] for item in entry["alternate_projectors"]} == {
        "listed_not_downloaded_not_approved"
    }
    assert entry["projector"]["sha256"] not in {
        item["sha256"] for item in entry["alternate_projectors"]
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e["model"].update(revision="main"),
        lambda e: e["model"].update(revision="1add221"),
        lambda e: e["model"].update(
            source_url=e["model"]["source_url"].replace("https://", "http://")
        ),
        lambda e: e["model"].update(source_url=e["model"]["source_url"].replace(HEX40, "main")),
        lambda e: e["projector"].update(sha256="ab" * 31),
        lambda e: e["projector"].update(bytes=0),
        lambda e: e["projector"].update(filename="LFM3-VL-2B-F16.gguf"),
        lambda e: e["model"].update(filename="mmproj-LFM3-VL-2B-Q4.gguf"),
        lambda e: e["projector"].update(revision="0" * 40),
        lambda e: e["model"].update(bytes=cand.MAX_DOWNLOAD_BYTES),
        lambda e: e.update(qualified=True),
        lambda e: e.update(production_eligible=True),
        lambda e: e.update(text_registry_eligible=True),
        lambda e: e.update(image_invocation_approved=1),
        lambda e: e.pop("image_invocation_approved"),
        lambda e: e.update(capabilities=["prompt_rewrite"]),
        lambda e: e.update(compatible_builds=["b11960-cpu-vision"]),
        lambda e: e.update(modality="text"),
        lambda e: e.update(unknown_key=1),
        lambda e: e["license"].update(acknowledgement_required=False),
        lambda e: e["license"].update(text_sha256="x"),
        lambda e: e["runtime"].update(unsupported_build_ids=["b11960-cpu-vision"]),
        lambda e: e["alternate_projectors"][0].update(status="approved"),
    ],
)
def test_malformed_or_overclaiming_candidate_documents_are_refused(mutate: Any) -> None:
    document = load_document()
    mutate(document["candidates"][0])
    with pytest.raises(cand.CandidateInvalid):
        cand.parse_candidates(document)


def test_document_level_refusals() -> None:
    document = load_document()
    for broken in (
        {**document, "schema_version": 2},
        {**document, "candidates": []},
        {**document, "extra": 1},
        {**document, "candidates": [document["candidates"][0]] * 2},
    ):
        with pytest.raises(cand.CandidateInvalid):
            cand.parse_candidates(broken)
    with pytest.raises(cand.CandidateInvalid):
        cand.load_candidates(REPO / "does-not-exist.json")


def test_runtime_requirement_matches_the_committed_manifest() -> None:
    candidate = cand.find_candidate("lfm3-vl-2b-q4_k_m-liquidai")
    manifest = runtime()
    required = manifest.find(candidate.runtime.required_build_id)
    assert required is not None and required.upstream_tag == "b11960"
    assert candidate.runtime.tool == required.executable
    assert candidate.runtime.tool in required.files and required.qualified is False
    for unsupported in candidate.runtime.unsupported_build_ids:
        assert manifest.find(unsupported) is not None


# --------------------------------------------------------------------------------------------------------- license


def test_license_record_names_this_exact_text_not_the_earlier_acknowledgement() -> None:
    candidate = cand.find_candidate("lfm3-vl-2b-q4_k_m-liquidai")
    # Same licence terms as the LFM3-1.7B record, but different bytes (whitespace), so the earlier owner
    # acknowledgement (AI-QUAL-115) does not name this text and a new one is required.
    assert candidate.license.text_sha256 != AI115_ACKNOWLEDGED_LICENSE_SHA
    assert candidate.license.text_source_url.endswith(f"/resolve/{HEX40}/LICENSE")
    assert candidate.license.spdx == "LicenseRef-LFM-Open-License-1.0"


def test_license_acknowledgement_is_required_and_must_match(tmp_path: Path) -> None:
    candidate, staged = build_fixture(tmp_path)
    for record, reason in (
        (None, cand.REASON_LICENSE_MISSING),
        ({}, cand.REASON_LICENSE_MISSING),
        (acknowledgement(candidate, owner_acknowledged=False), cand.REASON_LICENSE_MISSING),
        (
            acknowledgement(candidate, license_text_sha256=AI115_ACKNOWLEDGED_LICENSE_SHA),
            cand.REASON_LICENSE_MISMATCH,
        ),
        (
            acknowledgement(candidate, candidate_id="another-candidate"),
            cand.REASON_LICENSE_MISMATCH,
        ),
    ):
        verdict = cand.check_admission(
            candidate,
            staged,
            build_id="b11960-cpu-vision",
            runtime_manifest=runtime(),
            acknowledgement=record,
        )
        assert (verdict.ok, verdict.reasons) == (False, (reason,))


# ------------------------------------------------------------------------------------------------------- admission


def admit(candidate: cand.VisualCandidate, staged: Path, **kwargs: Any) -> cand.Admission:
    kwargs.setdefault("build_id", "b11960-cpu-vision")
    kwargs.setdefault("runtime_manifest", runtime())
    kwargs.setdefault("acknowledgement", acknowledgement(candidate))
    return cand.check_admission(candidate, staged, **kwargs)


def test_admission_passes_only_for_the_matching_pair_on_the_required_build(tmp_path: Path) -> None:
    candidate, staged = build_fixture(tmp_path)
    assert admit(candidate, staged) == cand.Admission(True, ())


def test_missing_projector_is_refused(tmp_path: Path) -> None:
    candidate, staged = build_fixture(tmp_path)
    (staged / candidate.projector.filename).unlink()
    assert admit(candidate, staged) == cand.Admission(False, (cand.REASON_PROJECTOR_MISSING,))
    (staged / candidate.model.filename).unlink()
    assert admit(candidate, staged).reasons == (
        cand.REASON_MODEL_MISSING,
        cand.REASON_PROJECTOR_MISSING,
    )


def test_mismatched_projector_bytes_are_refused(tmp_path: Path) -> None:
    candidate, staged = build_fixture(tmp_path)
    path = staged / candidate.projector.filename
    original = path.read_bytes()
    path.write_bytes(original + b"x")
    assert admit(candidate, staged).reasons == (cand.REASON_PROJECTOR_SIZE,)
    path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    assert admit(candidate, staged).reasons == (cand.REASON_PROJECTOR_HASH,)
    (staged / candidate.model.filename).write_bytes(b"GGUF")
    assert cand.REASON_MODEL_SIZE in admit(candidate, staged).reasons


@pytest.mark.parametrize(
    ("projector_change", "reason"),
    [
        ({"clip.vision.projector_type": "qwen2vl"}, cand.REASON_PROJECTOR_HEADER),
        ({"general.architecture": "lfm3"}, cand.REASON_PROJECTOR_HEADER),
        ({"general.type": "model"}, cand.REASON_PROJECTOR_HEADER),
        ({"general.file_type": 7}, cand.REASON_PROJECTOR_HEADER),
        ({"clip.vision.projection_dim": 1024}, cand.REASON_PAIR_MISMATCH),
        ({"general.base_model.0.name": "Qwen3.5 9B"}, cand.REASON_PAIR_MISMATCH),
        ({"general.name": "Some Other Model"}, cand.REASON_PAIR_MISMATCH),
    ],
)
def test_projector_that_does_not_match_the_model_is_refused(
    tmp_path: Path, projector_change: dict[str, Any], reason: str
) -> None:
    candidate, staged = build_fixture(
        tmp_path, projector_entries={**PROJECTOR_ENTRIES, **projector_change}
    )
    assert reason in admit(candidate, staged).reasons
    assert admit(candidate, staged).ok is False


@pytest.mark.parametrize(
    "model_change",
    [
        {"general.architecture": "qwen3_5"},
        {"general.type": "mmproj"},
        {"lfm3.embedding_length": 1024},
        {"general.file_type": 17},
    ],
)
def test_model_with_the_wrong_header_is_refused(
    tmp_path: Path, model_change: dict[str, Any]
) -> None:
    candidate, staged = build_fixture(tmp_path, model_entries={**MODEL_ENTRIES, **model_change})
    assert cand.REASON_MODEL_HEADER in admit(candidate, staged).reasons


def test_a_non_gguf_file_with_the_pinned_hash_is_still_refused(tmp_path: Path) -> None:
    candidate, staged = build_fixture(tmp_path)
    junk = b"not a gguf file at all"
    document = load_document()
    entry = document["candidates"][0]
    entry["model"].update(bytes=len(junk), sha256=hashlib.sha256(junk).hexdigest())
    entry["projector"].update(
        bytes=(staged / candidate.projector.filename).stat().st_size,
        sha256=candidate.projector.sha256,
    )
    junk_candidate = cand.parse_candidates(document)[0]
    (staged / junk_candidate.model.filename).write_bytes(junk)
    assert cand.REASON_MODEL_HEADER in admit(junk_candidate, staged).reasons


def test_unsupported_or_unknown_runtime_is_refused(tmp_path: Path) -> None:
    candidate, staged = build_fixture(tmp_path)
    assert admit(candidate, staged, build_id="b11840-cpu").reasons == (
        cand.REASON_RUNTIME_UNSUPPORTED,
    )
    assert admit(candidate, staged, build_id="b99999-cpu").reasons == (cand.REASON_RUNTIME_UNKNOWN,)
    manifest = runtime()
    build = manifest.find("b11960-cpu-vision")
    assert build is not None
    no_tool = RuntimeManifest(
        builds=tuple(
            replace(b, files={k: v for k, v in b.files.items() if k != candidate.runtime.tool})
            if b.build_id == "b11960-cpu-vision"
            else b
            for b in manifest.builds
        )
    )
    assert admit(candidate, staged, runtime_manifest=no_tool).reasons == (
        cand.REASON_RUNTIME_UNSUPPORTED,
    )
    qualified = RuntimeManifest(builds=tuple(replace(b, qualified=True) for b in manifest.builds))
    assert admit(candidate, staged, runtime_manifest=qualified).reasons == (
        cand.REASON_RUNTIME_UNSUPPORTED,
    )


def test_admission_is_fail_closed_on_unexpected_errors(tmp_path: Path) -> None:
    candidate, staged = build_fixture(tmp_path)
    assert cand.check_admission(
        candidate,
        None,
        build_id="b11960-cpu-vision",
        runtime_manifest=runtime(),
        acknowledgement=acknowledgement(candidate),
    ) == cand.Admission(False, (cand.REASON_INTERNAL,))  # type: ignore[arg-type]
    assert (
        cand.check_admission(
            candidate,
            staged,
            build_id="b11960-cpu-vision",
            runtime_manifest="nope",
            acknowledgement=acknowledgement(candidate),
        ).ok
        is False
    )  # type: ignore[arg-type]
    empty = tmp_path / "empty"
    empty.mkdir()
    verdict = admit(candidate, empty, acknowledgement=None)
    assert verdict.ok is False and cand.REASON_LICENSE_MISSING in verdict.reasons


def test_cancellation_stops_hashing_and_admits_nothing(tmp_path: Path) -> None:
    candidate, staged = build_fixture(tmp_path)
    assert admit(candidate, staged, cancel=lambda: True) == cand.Admission(
        False, (cand.REASON_CANCELLED,)
    )
    assert cand.hash_file(staged / candidate.model.filename, lambda: True) is None


# --------------------------------------------------------------------------------------------- operator workflow


def test_download_commands_are_anonymous_and_revision_pinned() -> None:
    candidate = cand.find_candidate("lfm3-vl-2b-q4_k_m-liquidai")
    lines = staging.download_commands(candidate, "D:/stage")
    assert len(lines) == 2
    for line in lines:
        assert HEX40 in line and "Authorization" not in line and "token" not in line.lower()
        assert line.startswith('curl --proto "=https" --proto-redir "=https" ')


def test_stage_report_is_content_free_and_reflects_admission(tmp_path: Path) -> None:
    candidate, staged = build_fixture(tmp_path)
    report = staging.stage_report(
        candidate, staged, build_id="b11960-cpu-vision", acknowledgement=None
    )
    assert report["admitted"] is False and report["reasons"] == [cand.REASON_LICENSE_MISSING]
    assert all(item["present"] for item in report["files"])
    assert str(tmp_path) not in json.dumps(report)


def test_import_copies_only_after_admission_and_never_into_managed_ai_or_git(
    tmp_path: Path,
) -> None:
    candidate, staged = build_fixture(tmp_path)
    ack = acknowledgement(candidate)
    common: dict[str, Any] = {"build_id": "b11960-cpu-vision"}
    root = tmp_path / "evalroot"
    with pytest.raises(staging.StagingRefused) as refused:
        staging.import_candidate(candidate, staged, root, acknowledgement=None, **common)
    assert refused.value.reasons == (cand.REASON_LICENSE_MISSING,) and not root.exists()
    with pytest.raises(staging.StagingRefused) as managed:
        staging.import_candidate(
            candidate,
            staged,
            tmp_path / "StableNew" / "ManagedAi" / "x",
            acknowledgement=ack,
            **common,
        )
    assert managed.value.code == staging.REFUSED_UNDER_MANAGED_AI
    with pytest.raises(staging.StagingRefused) as in_repo:
        staging.import_candidate(
            candidate, staged, REPO / "build" / "vl220-eval", acknowledgement=ack, **common
        )
    assert (
        in_repo.value.code == staging.REFUSED_IN_REPOSITORY
        and not (REPO / "build" / "vl220-eval").exists()
    )
    target = staging.import_candidate(candidate, staged, root, acknowledgement=ack, **common)
    assert sorted(item.name for item in target.iterdir()) == sorted(
        [candidate.model.filename, candidate.projector.filename, "import_record.json"]
    )
    with pytest.raises(staging.StagingRefused) as again:
        staging.import_candidate(candidate, staged, root, acknowledgement=ack, **common)
    assert again.value.code == staging.REFUSED_EXISTS


def test_a_cancelled_import_leaves_nothing_behind(tmp_path: Path) -> None:
    candidate, staged = build_fixture(tmp_path)
    root = tmp_path / "evalroot"
    calls = {"n": 0}

    def cancel_during_copy() -> bool:
        calls["n"] += 1
        return calls["n"] > 3  # preflight and both hashes pass; copying is cancelled

    with pytest.raises(staging.StagingRefused) as refused:
        staging.import_candidate(
            candidate, staged, root, build_id="b11960-cpu-vision",
            acknowledgement=acknowledgement(candidate), cancel=cancel_during_copy,
        )  # fmt: skip
    assert cand.REASON_CANCELLED in refused.value.reasons
    assert not any(item.is_file() for item in root.rglob("*"))


def test_a_copy_that_differs_from_the_pin_is_not_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, staged = build_fixture(tmp_path)
    source = staged / candidate.model.filename
    original = staging._copy_verified
    root = tmp_path / "evalroot"

    def replace_after_admission(path, target, pin, cancel):
        if path == source:
            path.write_bytes(b"changed")
        original(path, target, pin, cancel)

    monkeypatch.setattr(staging, "_copy_verified", replace_after_admission)
    with pytest.raises(staging.StagingRefused):
        staging.import_candidate(
            candidate,
            staged,
            root,
            build_id=candidate.runtime.required_build_id,
            acknowledgement=acknowledgement(candidate),
        )
    assert not staging.installed_pair(root, candidate).exists()
    assert not list(root.rglob(".import-*"))


# ------------------------------------------------------------------------------------------------------- GGUF reader


def test_gguf_reader_skips_arrays_and_is_bounded(tmp_path: Path) -> None:
    path = tmp_path / "ok.gguf"
    path.write_bytes(gguf_bytes(MODEL_ENTRIES))
    header = read_header(path)
    assert header.architecture == "lfm3" and "tokenizer.ggml.tokens" not in header.metadata
    bad_cases = {
        "magic": b"GGUX" + gguf_bytes(MODEL_ENTRIES)[4:],
        "version": b"GGUF" + struct.pack("<IQQ", 9, 0, 0),
        "too_many": b"GGUF" + struct.pack("<IQQ", 3, 0, 10**6),
        "truncated": gguf_bytes(MODEL_ENTRIES)[:-3],
        "empty": b"",
        "key_length": b"GGUF" + struct.pack("<IQQ", 3, 0, 1) + struct.pack("<Q", 10**6),
    }
    for name, data in bad_cases.items():
        broken = tmp_path / f"{name}.gguf"
        broken.write_bytes(data)
        with pytest.raises(GgufHeaderError):
            read_header(broken)
    with pytest.raises(GgufHeaderError):
        read_header(tmp_path / "missing.gguf")


# ------------------------------------------------------------------- isolation from production (decision D22)


def test_text_registry_is_unchanged_in_meaning_and_has_no_visual_entry() -> None:
    registry = load_model_registry(MODEL_REGISTRY_PATH)
    assert {entry.model_id for entry in registry.entries} == {
        "qwen3.5-9b-q4_k_m-unsloth",
        "qwen3.5-9b-q5_k_m-unsloth",
        "qwen3.5-4b-q8_0-unsloth",
        "qwen3.5-4b-q4_k_m-unsloth",
        "lfm3-1.7b-q4_k_m-liquidai",
        "lfm3-1.7b-q8_0-liquidai",
    }
    assert all(entry.qualified is False for entry in registry.entries)
    for visual in cand.load_candidates():
        assert registry.find_by_sha(visual.model.sha256) is None
        assert registry.find_by_sha(visual.projector.sha256) is None
        for model in registry.entries:
            assert visual.runtime.required_build_id not in model.compatible_builds
    text = MODEL_REGISTRY_PATH.read_text(encoding="utf-8").lower()
    for needle in ("lfm3-vl", "mmproj", "vision_language", "image-text", "image_text"):
        assert needle not in text


def test_nothing_in_production_reads_the_visual_candidate_file() -> None:
    needles = ("ai_visual_candidates", "tools.qualification.vl220", "vl220")
    scanned = 0
    for path in [*(REPO / "src").rglob("*.py"), REPO / "tools" / "ai_assist_admin.py"]:
        text = path.read_text(encoding="utf-8")
        scanned += 1
        for needle in needles:
            assert needle not in text, f"{path} references {needle}"
    assert scanned > 100
    # Nor does any other runtime-facing config reader.
    for name in ("managed_ai_runtime.json", "ai_model_registry.json"):
        assert "ai_visual_candidates" not in (REPO / "config" / name).read_text(encoding="utf-8")


def test_selector_activation_and_import_model_ignore_the_visual_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    candidate = cand.find_candidate("lfm3-vl-2b-q4_k_m-liquidai")
    registry = load_model_registry(MODEL_REGISTRY_PATH)
    manifest = runtime()
    root = tmp_path / "ai"
    # Even if the visual model's bytes sat in the AI root, the selector lists registry models only.
    fake = tmp_path / "ai" / "models" / candidate.model.sha256
    fake.mkdir(parents=True)
    (fake / candidate.model.filename).write_bytes(b"x")
    assert [c.model_id for c in list_model_choices(root, manifest, registry)] == []
    assert (
        ai_assist_admin.main(
            [
                "--root",
                str(root),
                "import-model",
                str(fake / candidate.model.filename),
                "--model-id",
                candidate.candidate_id,
            ]
        )
        == 2
    )
    assert "model_not_registered" in capsys.readouterr().out
    assert (
        ai_assist_admin.main(
            [
                "--root",
                str(root),
                "activate",
                "--build-id",
                "b11960-cpu-vision",
                "--model-id",
                candidate.candidate_id,
            ]
        )
        == 2
    )


# ----------------------------------------------------------------------------------- no network, no process, no flag


def test_the_package_cannot_open_sockets_or_spawn_a_child_directly() -> None:
    forbidden = {
        "socket", "ssl", "http", "urllib", "ftplib", "smtplib", "requests", "httpx", "aiohttp", "subprocess",
        "multiprocessing", "asyncio", "webbrowser", "threading", "concurrent", "huggingface_hub",
        "llama_cpp", "torch", "transformers", "onnxruntime",
    }  # fmt: skip
    files = sorted(PACKAGE.glob("*.py"))
    assert len(files) >= 8
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in forbidden, f"{path.name} imports {name}"
        source = path.read_text(encoding="utf-8")
        for flag in ("Popen", "os.system", "os.startfile"):
            assert flag not in source, f"{path.name} contains {flag}"


def test_non_execution_commands_run_with_network_and_process_creation_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tools.qualification.vl220 import __main__ as cli

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network or process use is not allowed")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    candidate, staged = build_fixture(tmp_path)
    assert cli.main(["describe"]) == 0
    assert cli.main(["describe-execution"]) == 0
    assert cli.main(["dry-run"]) == 0
    assert cli.main(["commands", "--dest", str(tmp_path)]) == 0
    assert (
        cli.main(["verify-staging", "--staging", str(staged), "--build-id", "b11960-cpu-vision"])
        == 1
    )
    assert cli.main(["write-synthetic", "--dest", str(tmp_path / "synthetic")]) == 0
    assert cli.main(["write-synthetic", "--dest", str(tmp_path / "synthetic")]) == 1
    capsys.readouterr()
    ack = tmp_path / "ack.json"
    ack.write_text(json.dumps(acknowledgement(candidate)), encoding="utf-8")
    assert cli.main(["--candidate", "nope", "describe"]) == 2
    with pytest.raises(SystemExit):
        cli.main(["run"])


def test_the_frozen_runtime_vocabulary_still_refuses_projectors_and_images(tmp_path: Path) -> None:
    for flag in ("--mmproj", "--mmproj-url", "-mmu", "--rpc"):
        assert flag in FORBIDDEN_FLAGS
    assert not {"--mmproj", "--image", "-mm", "--video", "--audio"} & ALLOWED_FLAGS
    for argv in (
        build_argv(tmp_path / "m", tmp_path / "p", tmp_path / "s", RunLimits()),
        build_production_argv(tmp_path / "m", tmp_path / "p", tmp_path / "s", RunLimits()),
    ):
        assert not {"--mmproj", "--image", "-mm"} & set(argv)
    assert copy.deepcopy(cand.MAX_DOWNLOAD_BYTES) == 6 * 1024**3
