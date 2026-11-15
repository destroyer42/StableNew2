"""AI-VL-241: independent review fixes for the visual driver, and the Gemma resource envelope.

Hermetic like the VL-220 and VL-230 driver tests: a Python script stands in for ``llama-mtmd-cli.exe`` or a stub runner returns a
canned outcome; no model, no GPU, no network. Each test below pins one finding of ``docs/work_packages/AI-VL-241_gemma_readiness.md``.
"""

# ruff: noqa: F811 - pytest fixtures are re-declared as parameters

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from src.ai_assist.host import HostMemory
from src.utils.managed_process import ProcessOutcome
from src.utils.process_observation import ProcessTreeSample
from tests.tools.test_ai_vl220_candidate import acknowledgement
from tests.tools.test_ai_vl220_invocation import (  # noqa: F401 - pytest fixture
    World,
    cli_args,
    world,
)
from tests.tools.test_ai_vl230_driver import gemma_pair
from tools.qualification.vl220 import __main__ as cli
from tools.qualification.vl220 import candidates, contract, driver, plan, staging
from tools.qualification.vl220.visual_argv import (
    VISUAL_REFUSED_FLAGS,
    VisualArgvRefused,
    build_visual_argv,
    check_visual_argv,
)

GIB = 1024**3


def gemma_world(world: World) -> World:  # noqa: F811
    """The shared world, re-pointed at the real Gemma pins with a tiny stand-in pair (the same construction as VL-230)."""

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
    return replace(world, candidate=item, kwargs={**world.kwargs, "acknowledgement": ack})


class Child:
    """An observed child whose successive samples are the given ``(private, working set)`` byte pairs (the last repeats)."""

    pid = 4242

    def __init__(self, private: int, working_set: int, *later: tuple[int, int]) -> None:
        self._samples = [(private, working_set), *later]

    def sample(self) -> ProcessTreeSample:
        private, working_set = self._samples[0] if len(self._samples) == 1 else self._samples.pop(0)
        return ProcessTreeSample(self.pid, 1, private, working_set, 0.1, True)


# ------------------------------------------------------------------------------------------------ Part 2: the envelope


def test_memory_requirements_keep_the_old_rule_for_lfm_and_plan_for_gemma() -> None:
    lfm = candidates.find_candidate(candidates.LFM_CANDIDATE_ID)
    gemma = candidates.find_candidate(candidates.GEMMA_CANDIDATE_ID)
    lfm_need = driver.memory_requirements(lfm)
    assert (
        lfm_need == (lfm.download_bytes / GIB + 4.0,) * 2
    )  # unchanged: pinned download plus the 4 GiB margin
    available, commit = driver.memory_requirements(gemma)
    assert available == 11.0 and commit == 12.0
    # The commit requirement covers the planned private peak, the watch's own kill threshold and the margin ...
    assert commit == (
        driver.PLANNED_PRIVATE_GIB[gemma.candidate_id]
        + driver.GUARD_COMMIT_HEADROOM_GIB
        + driver.HEADROOM_MARGIN_GIB
    )
    # ... and is the job object's own commit cap, so no child can be admitted into a host that cannot hold the worst case.
    assert commit * GIB == plan.evaluation_limits(gemma).max_peak_working_set_bytes
    assert driver.PLANNED_PRIVATE_GIB[gemma.candidate_id] * GIB > gemma.download_bytes


def test_gemma_is_refused_cleanly_when_headroom_is_short_and_records_not_run(world: World) -> None:  # noqa: F811
    gw = gemma_world(world)
    case = gw.case(contract.KIND_ADHERENCE)
    for memory, code in (
        (HostMemory(10.9, 64.0), driver.REFUSED_MEMORY),
        (
            HostMemory(64.0, 11.9),
            driver.REFUSED_COMMIT,
        ),  # the old 10.66 GiB rule would have admitted this
        (HostMemory(64.0, 10.7), driver.REFUSED_COMMIT),
    ):
        run = gw.driver(memory_probe=lambda m=memory: m).run_case(gw.case_set, case)
        assert run.refusal is not None and run.refusal.code == code
        assert run.evidence.status == driver.STATUS_NOT_RUN and run.evidence.reason == code
        assert run.evidence.argv_shape_sha256 == "" and run.evidence.peak_private_bytes == 0
    assert gw.launches == [], "a refused case must launch nothing"
    assert not (gw.kwargs["evaluation_root"] / driver.LOCK_NAME).exists()
    # A set stops at the first such refusal with no score, and the evidence document says not_run, not a failure.
    stopped = gw.driver(memory_probe=lambda: HostMemory(64.0, 8.0)).run_cases(
        gw.case_set, gw.labels
    )
    assert stopped.refusal is not None and stopped.refusal.code == driver.REFUSED_COMMIT
    assert len(stopped.evidence) == 1 and stopped.report is None and not stopped.complete
    document = driver.evidence_document(
        stopped, plan_sha256="0" * 64, case_set_sha256="0" * 64, candidate=gw.candidate
    )
    assert document["cases"][0]["status"] == driver.STATUS_NOT_RUN
    assert document["refusal"] == {"code": driver.REFUSED_COMMIT, "reasons": []}


def test_gemma_is_admitted_at_exactly_the_required_headroom(world: World) -> None:  # noqa: F811
    gw = gemma_world(world)
    case = gw.case(contract.KIND_BEFORE_AFTER)
    expected = contract.canonical_json(
        {
            "schema": contract.RESPONSE_SCHEMA,
            "status": "ok",
            "kind": case.kind,
            "preferred": "tie",
            "reason": "no_difference",
        }
    )

    def runner(command: list[str], **opts: Any) -> ProcessOutcome:
        opts["observe"](Child(7 * GIB, 9 * GIB))
        assert (
            opts["cancel"]() is False
        )  # the launcher polls the watch, which is what observes the child
        return ProcessOutcome(0, expected.encode(), contained=True, memory_limit_enforced=True)

    run = gw.driver(memory_probe=lambda: HostMemory(11.0, 12.0), runner=runner).run_case(
        gw.case_set, case
    )
    assert run.refusal is None and run.evidence.status == driver.STATUS_VALID, run.evidence


def test_the_working_set_tripwire_is_the_ceiling_plus_the_pinned_files(world: World) -> None:  # noqa: F811
    real = candidates.find_candidate(candidates.GEMMA_CANDIDATE_ID)
    assert driver.working_set_tripwire_bytes(real, plan.evaluation_limits(real)) == (
        12 * GIB + 7_150_994_912
    )  # about 18.7 GiB for the real pair: 12 GiB commit ceiling plus the 6.66 GiB of pinned files
    gw = gemma_world(
        world
    )  # the stand-in pair is a few hundred bytes, so its tripwire sits just above the 12 GiB ceiling
    resource = plan.evaluation_limits(gw.candidate)
    tripwire = driver.working_set_tripwire_bytes(gw.candidate, resource)
    assert tripwire == 12 * GIB + gw.candidate.download_bytes > 12 * GIB + 100
    case = gw.case(contract.KIND_ADHERENCE)
    readings: list[bool] = []

    def runner(command: list[str], **opts: Any) -> ProcessOutcome:
        # A load whose working set is above the 12 GiB ceiling but explained by the mapped pinned files (the old working-set
        # kill would have cancelled the first Gemma case for nothing), then one that the ceiling and every pinned byte
        # cannot explain.
        opts["observe"](Child(7 * GIB, 12 * GIB + 100, (7 * GIB, tripwire + GIB)))
        readings.extend([bool(opts["cancel"]()), bool(opts["cancel"]())])
        return ProcessOutcome(None, cancelled=True, contained=True, memory_limit_enforced=True)

    run = gw.driver(runner=runner).run_case(gw.case_set, case)
    assert readings == [False, True]
    assert run.evidence.status == driver.STATUS_CANCELLED
    assert run.evidence.reason == "working_set_limit"
    assert run.evidence.peak_working_set_bytes > tripwire


def test_the_private_bytes_cap_still_stops_a_child_that_commits_past_the_ceiling(
    world: World,
) -> None:  # noqa: F811
    gw = gemma_world(world)
    case = gw.case(contract.KIND_ADHERENCE)
    stops: list[bool] = []

    def runner(command: list[str], **opts: Any) -> ProcessOutcome:
        opts["observe"](Child(13 * GIB, 12 * GIB + 100))
        stops.append(bool(opts["cancel"]()))
        stops.append(bool(opts["cancel"]()))  # the observer needs two consecutive readings
        return ProcessOutcome(None, cancelled=True, contained=True, memory_limit_enforced=True)

    run = gw.driver(runner=runner).run_case(gw.case_set, case)
    assert stops == [False, True]
    assert run.evidence.reason == "process_memory_cap"


def test_gemma_runs_under_its_own_timeout_and_the_operator_can_change_it(world: World) -> None:  # noqa: F811
    gemma = candidates.find_candidate(candidates.GEMMA_CANDIDATE_ID)
    lfm = candidates.find_candidate(candidates.LFM_CANDIDATE_ID)
    assert driver.default_limits(gemma).timeout_seconds == 300.0
    assert driver.default_limits(lfm).timeout_seconds == 180.0
    assert driver.default_limits(gemma, timeout_seconds=120.0).timeout_seconds == 120.0
    # The limit is part of the execution identity the owner approves, so a different timeout is a different digest.
    default = driver.execution_identity(gemma, driver.default_limits(gemma))
    other = driver.execution_identity(gemma, driver.default_limits(gemma, timeout_seconds=120.0))
    assert default["invocation_limits"]["timeout_seconds"] == 300.0
    assert default["execution_sha256"] != other["execution_sha256"]
    # The driver itself defaults to the candidate's limits, not the generic ones.
    gw = gemma_world(world)
    kwargs = {key: value for key, value in gw.kwargs.items() if key != "limits"}
    assert driver.VisualDriver(gw.candidate, **kwargs)._limits.timeout_seconds == 300.0
    # The plan's own proposed limit (what a case is reported against) is not changed by this.
    assert plan.evaluation_limits(gemma).max_wall_seconds == 180.0


# ------------------------------------------------------------------------------------- Part 1: containment, strict path


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (
            ProcessOutcome(None, launch_error="containment unavailable: no job object"),
            "containment_unavailable",
        ),
        (
            ProcessOutcome(0, b"{}", contained=False, memory_limit_enforced=True),
            "containment_unverified",
        ),
        (
            ProcessOutcome(0, b"{}", contained=True, memory_limit_enforced=None),
            "containment_unverified",
        ),
        (
            ProcessOutcome(0, b"{}", contained=True, memory_limit_enforced=False),
            "containment_unverified",
        ),
        (ProcessOutcome(None, launch_error="boom"), "launch_failed"),
    ],
)
def test_a_launch_that_proves_no_containment_stops_the_set_instead_of_scoring_non_answers(
    world: World,
    outcome: ProcessOutcome,
    reason: str,  # noqa: F811
) -> None:
    gw = gemma_world(world)
    calls: list[int] = []

    def runner(command: list[str], **opts: Any) -> ProcessOutcome:
        calls.append(1)
        opts["observe"](Child(1, 1))
        return outcome

    run = gw.driver(runner=runner).run_cases(gw.case_set, gw.labels)
    assert calls == [1], "the same cause would fail every case: stop after the first"
    assert run.refusal == driver.Refusal(driver.REFUSED_LAUNCH, (reason,))
    assert run.report is None and not run.complete
    assert (
        run.evidence[0].status == driver.STATUS_LAUNCH_FAILED and run.evidence[0].reason == reason
    )


def test_a_gemma_child_that_cannot_be_observed_is_not_trusted(world: World) -> None:  # noqa: F811
    gw = gemma_world(world)
    case = gw.case(contract.KIND_ADHERENCE)

    def runner(command: list[str], **opts: Any) -> ProcessOutcome:  # never binds an observation
        return ProcessOutcome(0, b"{}", contained=True, memory_limit_enforced=True)

    run = gw.driver(runner=runner).run_case(gw.case_set, case)
    assert run.evidence.status == driver.STATUS_LAUNCH_FAILED
    assert run.evidence.reason == "child_not_observed"


def test_gemma_is_launched_with_a_verified_memory_limit_and_required_containment(
    world: World,
) -> None:  # noqa: F811
    gw = gemma_world(world)
    case = gw.case(contract.KIND_ADHERENCE)
    seen: dict[str, Any] = {}

    def runner(command: list[str], **opts: Any) -> ProcessOutcome:
        seen.update(opts)
        opts["observe"](Child(1, 1))
        return ProcessOutcome(0, b"x", contained=True, memory_limit_enforced=True)

    gw.driver(runner=runner).run_case(gw.case_set, case)
    assert seen["require_containment"] is True
    assert seen["memory_limit_mb"] == 12 * 1024
    assert seen["timeout_seconds"] == 60.0  # the world pins its own limits
    assert seen["max_stdout_bytes"] == 64 * 1024


# ---------------------------------------------------------------- Part 1: the closed flag list and the Jinja path (Gemma)


TEMPLATE_FLAGS = (
    "--chat-template",
    "--chat-template-file",
    "--chat-template-kwargs",
    "--reasoning",
    "--reasoning-format",
    "--reasoning-budget",
    "-rea",
)


def test_the_jinja_switch_is_the_only_template_control_and_it_names_no_template(
    world: World,
) -> None:  # noqa: F811
    gw = gemma_world(world)
    work = gw.tmp / "argv"
    work.mkdir()
    model = gw.staged / gw.candidate.model.filename
    projector = gw.staged / gw.candidate.projector.filename
    (work / "prompt.txt").write_text("question", encoding="utf-8")
    (work / "schema.json").write_text("{}", encoding="utf-8")
    image = next(gw.kwargs["assets_dir"].glob("*.png"))
    (work / "image_0.png").write_bytes(image.read_bytes())
    argv = build_visual_argv(
        model_path=model,
        projector_path=projector,
        prompt_file=work / "prompt.txt",
        schema_file=work / "schema.json",
        image_paths=[work / "image_0.png"],
        evaluation_root=gw.kwargs["evaluation_root"],
        work_dir=work,
        use_jinja=True,
    )
    assert argv.count("--jinja") == 1
    assert not set(argv) & set(TEMPLATE_FLAGS)
    assert not [token for token in argv if "template" in token.lower()]
    check_visual_argv(argv, use_jinja=True)
    for flag in TEMPLATE_FLAGS:
        for refused in ([*argv, flag, "x"], [*argv, flag]):
            with pytest.raises(VisualArgvRefused):
                check_visual_argv(refused, use_jinja=True)
    with pytest.raises(VisualArgvRefused, match="flag_repeated"):
        check_visual_argv([*argv, "--jinja"], use_jinja=True)
    assert "--jinja" in VISUAL_REFUSED_FLAGS  # refused for every caller that did not ask for it
    with pytest.raises(VisualArgvRefused, match="forbidden_flag"):
        check_visual_argv(argv)


def test_the_child_environment_cannot_inject_a_template_or_a_model_source(world: World) -> None:  # noqa: F811
    gw = gemma_world(world)
    case = gw.case(contract.KIND_ADHERENCE)
    hostile = {
        "SystemRoot": "C:/Windows",
        "LLAMA_ARG_CHAT_TEMPLATE": "{{ evil }}",
        "LLAMA_ARG_CHAT_TEMPLATE_FILE": "C:/x.jinja",
        "LLAMA_ARG_JINJA": "0",
        "LLAMA_ARG_HF_REPO": "someone/else",
        "LLAMA_ARG_MMPROJ": "C:/other.gguf",
        "LLAMA_ARG_MMPROJ_URL": "https://example.test/x.gguf",
        "LLAMA_CACHE": "C:/cache",
        "HF_TOKEN": "secret",
        "HF_ENDPOINT": "https://mirror.test",
    }
    seen: dict[str, Any] = {}

    def runner(command: list[str], **opts: Any) -> ProcessOutcome:
        seen["env"] = dict(opts["env"])
        opts["observe"](Child(1, 1))
        return ProcessOutcome(0, b"x", contained=True, memory_limit_enforced=True)

    gw.driver(runner=runner, environ=hostile).run_case(gw.case_set, case)
    env = seen["env"]
    llama = {name for name in env if name.startswith(("LLAMA_", "HF_"))}
    assert llama == {"LLAMA_ARG_OFFLINE", "HF_HUB_OFFLINE"}, llama
    assert env["LLAMA_ARG_OFFLINE"] == "1" and env["HF_HUB_OFFLINE"] == "1"
    assert env["CUDA_VISIBLE_DEVICES"] == "-1" and env["NO_PROXY"] == "*"


# --------------------------------------------------------------------------- Part 1: cleanup of the private work directory


def test_a_work_directory_left_behind_stops_the_next_case_and_is_never_deleted_for_the_operator(
    world: World,  # noqa: F811
) -> None:
    leftover = world.kwargs["evaluation_root"] / driver.WORK_NAME / "crashed"
    leftover.mkdir(parents=True)
    (leftover / "prompt.txt").write_text("private prompt", encoding="utf-8")
    run = world.driver().run_case(world.case_set, world.case(contract.KIND_ADHERENCE))
    assert run.refusal == driver.Refusal(driver.REFUSED_SCRATCH, ("work_directory_not_empty",))
    assert run.evidence.status == driver.STATUS_NOT_RUN
    assert world.launches == []
    assert (leftover / "prompt.txt").read_text(encoding="utf-8") == "private prompt"
    assert not (world.kwargs["evaluation_root"] / driver.LOCK_NAME).exists()


def test_a_work_directory_that_cannot_be_removed_is_reported_not_hidden(
    world: World,
    monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    monkeypatch.setattr(driver.shutil, "rmtree", lambda *args, **kwargs: None)
    monkeypatch.setattr(driver.time, "sleep", lambda seconds: None)
    visual = world.driver()
    assert visual.cleanup_complete is True
    run = visual.run_case(world.case_set, world.case(contract.KIND_ADHERENCE))
    assert run.evidence.status == driver.STATUS_VALID
    assert visual.cleanup_complete is False
    document = driver.evidence_document(
        driver.EvaluationRun((run.evidence,)),
        plan_sha256="0" * 64,
        case_set_sha256="0" * 64,
        candidate=world.candidate,
        cleanup_complete=visual.cleanup_complete,
    )
    assert document["cleanup_complete"] is False
    again = visual.run_case(world.case_set, world.case(contract.KIND_ADHERENCE))
    assert again.refusal is not None and again.refusal.reasons == ("work_directory_not_empty",)
    shutil.rmtree(world.kwargs["evaluation_root"] / driver.WORK_NAME, ignore_errors=True)


def test_a_clean_run_reports_cleanup_complete(world: World) -> None:  # noqa: F811
    visual = world.driver()
    run = visual.run_cases(world.case_set, world.labels)
    document = driver.evidence_document(
        run, plan_sha256="0" * 64, case_set_sha256="0" * 64, candidate=world.candidate,
        cleanup_complete=visual.cleanup_complete,
    )  # fmt: skip
    assert document["cleanup_complete"] is True


# ------------------------------------------------------------------------------ Part 1: the evidence file is checked first


def digest_for_default_candidate() -> str:
    return str(plan.build_plan(candidates.find_candidate(cli.DEFAULT_CANDIDATE))["plan_sha256"])


def test_the_cli_checks_where_the_evidence_goes_before_launching_anything(
    world: World,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the driver must not be built")

    monkeypatch.setattr(driver, "VisualDriver", boom)
    digest = digest_for_default_candidate()
    repo = Path(__file__).resolve().parents[2]
    managed = world.tmp / "ManagedAi"
    managed.mkdir()
    for destination, needle in (
        (world.tmp / "missing-folder" / "evidence.json", "directory_missing"),
        (repo / "evidence.json", "evaluation_root_inside_a_git_working_tree"),
        (managed / "evidence.json", "evaluation_root_is_the_ai_assist_root"),
    ):
        status = cli.main(cli_args(world, digest, "--evidence-out", str(destination)))
        assert status == 2
        err = capsys.readouterr().err
        assert "evidence_path_refused" in err and needle in err
        assert not destination.exists()
    same = world.tmp / "same.json"
    status = cli.main(
        cli_args(world, digest, "--evidence-out", str(same), "--diagnostics-out", str(same))
    )
    assert status == 2 and "different files" in capsys.readouterr().err


def test_a_failed_evidence_write_is_reported_after_the_run(
    world: World,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = Path.open

    def failing(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if self.name == "evidence.json" and "x" in mode:
            raise PermissionError("denied")
        return original(self, mode, *args, **kwargs)

    class Quiet:
        cleanup_complete = True
        turn_format = "legacy"

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def run_cases(self, case_set: Any, labels: Any) -> driver.EvaluationRun:
            return driver.EvaluationRun((), complete=True)

    monkeypatch.setattr(driver, "VisualDriver", Quiet)
    monkeypatch.setattr(Path, "open", failing)
    (world.tmp / "ack.json").write_text("{}", encoding="utf-8")
    status = cli.main(cli_args(world, digest_for_default_candidate()))
    assert status == 1 and "evidence_write_failed" in capsys.readouterr().err
