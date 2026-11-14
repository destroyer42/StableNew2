"""Deterministic tests for the offline visual import and contained evaluation boundary."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from src.ai_assist.paths import runtime_dir
from src.utils.managed_process import ProcessOutcome
from src.utils.process_observation import ProcessTreeSample
from tests.tools.test_ai_vl220_candidate import (
    PROJECTOR_ENTRIES,
    acknowledgement,
    build_fixture,
)
from tests.tools.test_ai_vl220_invocation import World, world  # noqa: F401 - pytest fixture
from tools.qualification.vl220 import __main__ as cli
from tools.qualification.vl220 import candidates, contract, driver, plan, staging
from tools.qualification.vl220.visual_argv import (
    VISION_BUILD_ID,
    VisualArgvRefused,
    VisualLimits,
    check_visual_argv,
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
    assert item.runtime.required_build_id == "b11960-cpu"
    assert plan.evaluation_limits(item).max_peak_working_set_bytes > item.download_bytes


def gemma_pair(tmp_path: Path) -> tuple[candidates.VisualCandidate, Path]:
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
    return build_fixture(tmp_path, model_header, projector_header, candidate_index=1)


def test_gemma_import_uses_its_own_projection_and_identity(tmp_path: Path) -> None:
    item, staged = gemma_pair(tmp_path)
    target = staging.import_candidate(
        item,
        staged,
        tmp_path / "eval",
        build_id=item.runtime.required_build_id,
        acknowledgement=acknowledgement(item),
    )
    assert target.parent.name == candidates.GEMMA_CANDIDATE_ID
    assert candidates.verify_pair(item, target).ok
    assert cli._load_json(target / "import_record.json") == staging.import_record(item)


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


def test_gemma_uses_the_merged_driver_with_its_own_template_and_containment(world: World) -> None:  # noqa: F811
    source = world.tmp / "gemma"
    source.mkdir()
    item, staged = gemma_pair(source)
    ack = acknowledgement(item)
    staging.import_candidate(
        item,
        staged,
        world.kwargs["evaluation_root"],
        build_id=item.runtime.required_build_id,
        acknowledgement=ack,
    )
    gemma_world = replace(world, candidate=item, kwargs={**world.kwargs, "acknowledgement": ack})
    case = world.case(contract.KIND_BEFORE_AFTER)

    class ObservedChild:
        pid = 123

        def sample(self) -> ProcessTreeSample:
            return ProcessTreeSample(self.pid, 1, 4096, 8192, 0.1, True)

    def runner(command: list[str], **opts: Any) -> ProcessOutcome:
        assert opts["require_containment"] is True and opts["memory_limit_mb"] == 12288
        argv = gemma_world.launches[-1][1]
        assert argv.count("--jinja") == 1 and argv.count("--image") == 2
        check_visual_argv(argv, use_jinja=True)
        with pytest.raises(VisualArgvRefused, match="forbidden_flag"):
            check_visual_argv(argv)
        assert opts["env"]["CUDA_VISIBLE_DEVICES"] == "-1"
        opts["observe"](ObservedChild())
        assert opts["cancel"]() is False
        answer = contract.canonical_json(
            {
                "schema": contract.RESPONSE_SCHEMA,
                "status": "ok",
                "kind": case.kind,
                "preferred": "tie",
                "reason": "no_difference",
            }
        )
        return ProcessOutcome(
            returncode=0,
            stdout=answer.encode(),
            contained=True,
            memory_limit_enforced=True,
        )

    result = gemma_world.driver(runner=runner).run_case(world.case_set, case)
    assert result.evidence.status == driver.STATUS_VALID
    assert result.evidence.peak_working_set_bytes == 8192
    assert (world.ai_root / "runtimes" / VISION_BUILD_ID) == gemma_world.launches[-1][0].parent


def test_readiness_refuses_an_unpinned_loadable_file(world: World) -> None:  # noqa: F811
    assert world.driver().readiness()["launch_prerequisites_met"] is True
    (runtime_dir(world.ai_root, VISION_BUILD_ID) / "unsigned.dll").write_bytes(b"unlisted")
    report = world.driver().readiness()
    assert not report["launch_prerequisites_met"]
    assert report["reasons"] == [driver.REFUSED_RUNTIME, "unexpected_runtime_file"]


def test_gemma_cli_requires_frozen_execution_case_and_label_digests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    item = candidates.find_candidate(candidates.GEMMA_CANDIDATE_ID)
    identity = driver.execution_identity(item, VisualLimits())
    assert identity["jinja"] and identity["resources"]["max_peak_working_set_bytes"] == 12 * 1024**3
    evidence = tmp_path / "evidence.json"
    args = [
        "--candidate",
        item.candidate_id,
        "evaluate",
        "--evaluation-root",
        str(tmp_path),
        "--assets",
        str(tmp_path),
        "--acknowledgement",
        str(tmp_path / "ack.json"),
        "--evidence-out",
        str(evidence),
        "--i-have-the-plan-digest",
        identity["plan_sha256"],
        "--generation-idle",
    ]

    def unexpected(**kwargs: Any) -> None:
        pytest.fail("driver constructed without frozen inputs")

    monkeypatch.setattr(driver, "VisualDriver", unexpected)
    assert cli.main(args) == 2
    assert (
        cli.main(
            [
                *args,
                "--execution-sha256",
                identity["execution_sha256"],
                "--case-sha256",
                "0" * 64,
                "--label-sha256",
                "0" * 64,
            ]
        )
        == 2
    )
    assert capsys.readouterr().err.count("evaluation_identity_mismatch") == 2
    assert not evidence.exists()
