"""Deterministic tests for the offline visual import and contained evaluation boundary."""

from __future__ import annotations

import json
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest

from src.ai_assist.attestation import record_attestation
from src.ai_assist.host import HostMemory
from src.ai_assist.paths import runtime_dir
from src.utils.managed_process import ProcessOutcome
from src.utils.process_observation import ProcessTreeSample
from tests.tools.test_ai_vl220_candidate import (
    PROJECTOR_ENTRIES,
    acknowledgement,
    build_fixture,
)
from tools.qualification.vl220 import candidates, contract, driver, scoring, staging, synthetic
from tools.qualification.vl220.invocation import (
    VISUAL_ALLOWED_FLAGS,
    VISUAL_FORBIDDEN_FLAGS,
    InvocationRefused,
    strict_json,
)


def test_gemma_pins_match_the_reviewed_pair_and_are_offline_only() -> None:
    item = candidates.find_candidate(candidates.GEMMA_CANDIDATE_ID)
    assert (
        item.model.revision == item.projector.revision == "29d097773436b69ff9feafd636ab4cf873786537"
    )
    assert item.download_bytes == 7_150_994_912 < candidates.GEMMA_MAX_DOWNLOAD_BYTES
    assert item.model.architecture == "gemma4" and item.projector.projector_type == "gemma4uv"
    assert item.projector.projection_dim == item.model.embedding_length == 3840
    assert item.license.spdx == "Apache-2.0"
    assert item.runtime.required_build_id == candidates.VISION_BUILD_ID
    assert (
        driver.execution_identity(item)["limits"]["max_peak_working_set_bytes"]
        > item.download_bytes
    )


def test_gemma_import_uses_its_own_projection_and_identity(tmp_path: Path) -> None:
    identity = {
        "general.name": "Hf",
        "general.base_model.0.name": "Gemma 4 12B It",
    }
    model_header = {
        **identity,
        "general.type": "model",
        "general.architecture": "gemma4",
        "general.file_type": 2,
        "gemma4.embedding_length": 3840,
        "gemma4.context_length": 262144,
    }
    projector_header = {
        **PROJECTOR_ENTRIES,
        **identity,
        "clip.vision.projector_type": "gemma4uv",
        "clip.vision.projection_dim": 3840,
        "general.file_type": 32,
        "clip.has_audio_encoder": True,
    }
    item, staged = build_fixture(tmp_path, model_header, projector_header, candidate_index=1)
    target = staging.import_candidate(
        item,
        staged,
        tmp_path / "eval",
        build_id=item.runtime.required_build_id,
        acknowledgement=acknowledgement(item),
    )
    assert target.parent.name == candidates.GEMMA_CANDIDATE_ID
    assert candidates.verify_pair(item, target).ok
    assert driver.read_document(target / "import_record.json") == staging.import_record(item)


def test_a_projector_without_a_vision_encoder_is_refused(tmp_path: Path) -> None:
    item, source = build_fixture(
        tmp_path,
        projector_entries={
            **PROJECTOR_ENTRIES,
            "clip.has_vision_encoder": False,
        },
    )
    assert candidates.verify_pair(item, source).reasons == (candidates.REASON_PROJECTOR_HEADER,)


def test_symlink_source_and_install_destination_are_refused(tmp_path: Path) -> None:
    item, source = build_fixture(tmp_path)
    model = source / item.model.filename
    original = model.rename(tmp_path / "real.gguf")
    try:
        model.symlink_to(original)
    except OSError as exc:
        pytest.skip(
            f"creating a local symlink is unavailable: {exc.winerror if sys.platform == 'win32' else exc.errno}"
        )
    assert candidates.verify_pair(item, source).reasons == (candidates.REASON_UNSAFE_PATH,)
    model.unlink()
    original.rename(model)
    root = tmp_path / "eval"
    root.mkdir()
    alias = root / item.candidate_id
    alias.symlink_to(source, target_is_directory=True)
    with pytest.raises(staging.StagingRefused) as exc:
        staging.import_candidate(
            item,
            source,
            root,
            build_id=item.runtime.required_build_id,
            acknowledgement=acknowledgement(item),
        )
    assert exc.value.reasons == (candidates.REASON_UNSAFE_PATH,)
    assert sorted(p.name for p in source.iterdir()) == sorted(
        [item.model.filename, item.projector.filename]
    )


class FakeChild:
    pid = 42

    def sample(self) -> ProcessTreeSample:
        return ProcessTreeSample(self.pid, 1, 4096, 8192, 0.1, True)


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    item, source = build_fixture(tmp_path)
    root = tmp_path / "eval"
    ack = acknowledgement(item)
    staging.import_candidate(
        item, source, root, build_id=item.runtime.required_build_id, acknowledgement=ack
    )
    runtime = runtime_dir(root, item.runtime.required_build_id)
    runtime.mkdir(parents=True)
    (runtime / item.runtime.tool).write_bytes(b"dummy executable, never run")
    record_attestation(
        root, "synthetic fixture", [(item.runtime.required_build_id, item.runtime.tool)]
    )
    monkeypatch.setattr(driver, "runtime_import_problem", lambda root, build: "")
    monkeypatch.setattr(driver, "evaluation_slot", nullcontext)
    monkeypatch.setattr(driver, "find_candidate", lambda candidate_id: item)
    images, case_doc, label_doc = synthetic.build_synthetic_set()
    corpus = tmp_path / "corpus, original images"
    corpus.mkdir()
    cases = corpus / "cases.json"
    labels = tmp_path / "labels.json"
    for asset_id, data in images.items():
        (corpus / f"{asset_id}.png").write_bytes(data)
    cases.write_text(json.dumps(case_doc), encoding="utf-8")
    labels.write_text(json.dumps(label_doc), encoding="utf-8")
    return {
        "candidate_id": item.candidate_id,
        "root": root,
        "case_path": cases,
        "label_path": labels,
        "acknowledgement": ack,
        "execution_sha256": driver.execution_identity(item)["execution_sha256"],
        "case_sha256": contract.digest(case_doc),
        "label_sha256": contract.digest(label_doc),
        "memory_probe": lambda: HostMemory(20, 20),
        "busy_probe": lambda: [],
    }


def test_evaluate_uses_contained_argv_frozen_case_order_and_private_scoring(
    harness: dict[str, Any],
) -> None:
    cases = contract.validate_case_set(driver.read_document(harness["case_path"]))
    answers = scoring.baseline_responses(cases, "all_yes")
    launched: list[Path] = []

    def fake_runner(command: list[str], **opts: Any) -> ProcessOutcome:
        case = cases.cases[len(launched)]
        scratch = opts["cwd"]
        launched.append(scratch)
        argv = command[1:]
        flags = {token for token in argv if token.startswith("-") and token != "-1"}
        assert flags <= VISUAL_ALLOWED_FLAGS and not flags & VISUAL_FORBIDDEN_FLAGS
        assert argv.count("--mmproj") == 1
        assert Path(argv[argv.index("--mmproj") + 1]).is_relative_to(harness["root"])
        assert command[0].endswith("llama-mtmd-cli.exe")
        assert opts["require_containment"] and opts["memory_limit_mb"] == 6144
        assert opts["env"]["CUDA_VISIBLE_DEVICES"] == "-1"
        assert opts["env"]["PATH"] == str(Path(command[0]).parent)
        assert opts["env"]["TEMP"] == str(scratch)
        image_paths = [Path(argv[i + 1]) for i, flag in enumerate(argv) if flag == "--image"]
        assert len(image_paths) == len(case.asset_ids)
        for path, asset_id in zip(image_paths, case.asset_ids, strict=True):
            assert (
                path.read_bytes() == (harness["case_path"].parent / f"{asset_id}.png").read_bytes()
            )
        assert (scratch / "schema.json").read_text() == contract.canonical_json(
            contract.build_response_schema(case.kind)
        )
        assert (scratch / "prompt.txt").read_text().startswith(case.prompt)
        assert not any(case.prompt in arg for arg in argv)
        opts["observe"](FakeChild())
        assert not opts["cancel"]()
        return ProcessOutcome(
            returncode=0,
            stdout=answers[case.case_id].encode() + b"\r\n[end of text]\r\n",
            stderr=b"sensitive stderr",
            contained=True,
            memory_limit_enforced=True,
        )

    result = driver.evaluate(**harness, runner=fake_runner)
    assert result["complete"] and result["qualified"] is False
    assert result["scores"][contract.DIM_STRUCTURED]["valid_rate"] == 1
    assert result["scores"][contract.DIM_RESOURCES]["measured_cases"] == len(cases.cases)
    assert all(row["peak_working_set_bytes"] == 8192 for row in result["cases"])
    assert all(not path.exists() for path in launched)
    serialized = json.dumps(result)
    assert "sensitive stderr" not in serialized and str(harness["root"]) not in serialized
    assert all(answer not in serialized for answer in answers.values())


def _unexpected_launch(*args: Any, **kwargs: Any) -> ProcessOutcome:
    pytest.fail("model launch should have been refused")


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("ack", "license_acknowledgement_missing"),
        ("attestation", "operator_attestation_missing"),
        ("runtime", "unexpected_runtime_file"),
        ("image", "image_pin_mismatch"),
        ("busy", "generation_or_gate_active"),
        ("memory", "memory_headroom_insufficient"),
        ("cancel", "cancelled"),
    ],
)
def test_prelaunch_refusals(harness: dict[str, Any], scenario: str, expected: str) -> None:
    root = harness["root"]
    if scenario == "ack":
        harness["acknowledgement"] = None
    if scenario == "attestation":
        record_attestation(root, "text only", [("b11960-cpu", "llama-completion.exe")])
    if scenario == "runtime":
        (runtime_dir(root, candidates.VISION_BUILD_ID) / "unsigned.dll").write_bytes(b"fake")
    if scenario == "image":
        path = harness["case_path"].parent / "adh-1.png"
        path.write_bytes(b"\0" * path.stat().st_size)
    if scenario == "busy":
        harness["busy_probe"] = lambda: ["running"]
    if scenario == "memory":
        harness["memory_probe"] = lambda: HostMemory(1, 20)
    if scenario == "cancel":
        harness["cancel"] = lambda: True
    result = driver.evaluate(**harness, runner=_unexpected_launch)
    assert not result["complete"] and result["stop_reason"] == expected
    assert result["cases"] == [] and not list(root.glob(".case-*"))


def test_changed_case_digest_refuses_before_launch(harness: dict[str, Any]) -> None:
    harness["case_sha256"] = "0" * 64
    with pytest.raises(InvocationRefused, match="evaluation_identity_mismatch"):
        driver.evaluate(**harness, runner=_unexpected_launch)


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'])
def test_strict_json_refuses_duplicate_keys_and_nonfinite_constants(text: str) -> None:
    with pytest.raises(ValueError):
        strict_json(text)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows owns the operator runtime")
def test_visual_mutex_refuses_a_second_run_and_releases_after_failure() -> None:
    with pytest.raises(RuntimeError, match="simulation"):
        with driver.evaluation_slot():
            with pytest.raises(InvocationRefused, match="evaluation_in_progress"):
                with driver.evaluation_slot():
                    pytest.fail("second visual evaluation was admitted")
            raise RuntimeError("simulation")
    with driver.evaluation_slot():
        pass
