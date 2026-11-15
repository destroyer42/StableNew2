# ruff: noqa: F811
"""PR-AI-VL-223 (decision D24): the turn-format A/B and the varied adherence set.

Nothing here runs a model. The fake child of the AI-VL-222 tests stands in for ``llama-mtmd-cli.exe``.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.tools.test_ai_vl220_invocation import (  # noqa: F401  (world is a fixture)
    RUN2_PLAN_DIGEST,
    World,
    cli_args,
    good_argv,
    make_files,
    world,
)
from tests.tools.test_ai_vl222_diagnostic import (  # noqa: F401  (diag_world is a fixture)
    diag_world,
    launched,
    load,
    oracle,
)
from tools.qualification.vl220 import __main__ as cli
from tools.qualification.vl220 import (
    contract,
    diagnostics,
    driver,
    plan,
    prompts,
    scoring,
    synthetic,
    visual_argv,
)

REPO = Path(__file__).resolve().parents[2]
SET_VARIED = synthetic.SET_ID_512_VARIED
SET_VARIED_CASE_SHA256 = (
    "1306b33d2f17"  # prefix only here; the full pin is asserted against the table below
)


# ================================================================================================= H7: the varied adherence set


def test_the_varied_set_has_its_own_pins_and_the_first_two_sets_are_unchanged() -> None:
    _, case_doc, label_doc = synthetic.build_synthetic_set(SET_VARIED)
    assert case_doc["set_id"] == SET_VARIED == "vl220-synthetic-512-2"
    digests = diagnostics.builtin_digests()
    assert digests[SET_VARIED] == (contract.digest(case_doc), contract.digest(label_doc))
    assert contract.digest(case_doc).startswith(SET_VARIED_CASE_SHA256)
    others = {digests[synthetic.SET_ID], digests[synthetic.SET_ID_512]}
    assert digests[SET_VARIED] not in others
    # The two earlier sets keep the exact pins that earlier runs and tests froze (see the AI-VL-222 tests).
    assert contract.digest(synthetic.build_synthetic_set(synthetic.SET_ID)[1]).startswith(
        "9c11172fa6af"
    )
    assert contract.digest(synthetic.build_synthetic_set(synthetic.SET_ID_512)[1]).startswith(
        "33c0f6e16497"
    )


def test_the_varied_set_asks_every_adherence_pattern_once() -> None:
    case_set, labels, _, _ = load(SET_VARIED)
    adherence = [case for case in case_set.cases if case.kind == contract.KIND_ADHERENCE]
    patterns = [
        tuple(labels.references[case.case_id]["answers"][key] for key, _ in case.elements)
        for case in adherence
    ]
    assert sorted(patterns) == [(False, False), (False, True), (True, False), (True, True)]
    # Every other kind is drawn exactly as in the 512-pixel set.
    base, _, _, _ = load(synthetic.SET_ID_512)
    assert [case.case_id for case in case_set.cases if case.kind != contract.KIND_ADHERENCE] == [
        case.case_id for case in base.cases if case.kind != contract.KIND_ADHERENCE
    ]
    assert len(case_set.cases) == 14 and len(synthetic.build_synthetic_set(SET_VARIED)[0]) == 16


def _constant_adherence(
    case_set: contract.CaseSet, labels: contract.LabelSet, pattern: tuple[bool, bool]
) -> float:
    responses = oracle(case_set, labels)
    for case in case_set.cases:
        if case.kind == contract.KIND_ADHERENCE:
            responses[case.case_id] = json.dumps(
                {
                    "schema": contract.RESPONSE_SCHEMA,
                    "status": "ok",
                    "kind": case.kind,
                    "answers": [
                        {"id": key, "value": value}
                        for (key, _), value in zip(case.elements, pattern, strict=True)
                    ],
                }
            )
    return float(scoring.score_run(case_set, labels, responses)[contract.DIM_ADHERENCE])


@pytest.mark.parametrize("pattern", [(True, False), (False, True), (True, True), (False, False)])
def test_no_constant_adherence_answer_beats_one_half_on_the_varied_set(
    pattern: tuple[bool, bool],
) -> None:
    case_set, labels, _, _ = load(SET_VARIED)
    assert _constant_adherence(case_set, labels, pattern) <= 0.5


def test_the_first_sets_could_be_beaten_by_a_constant_answer_which_is_why_they_cannot_support_a_claim() -> (
    None
):
    case_set, labels, _, _ = load(synthetic.SET_ID_512)
    assert _constant_adherence(case_set, labels, (True, False)) == 1.0


def test_the_by_construction_answers_score_perfectly_on_the_varied_set() -> None:
    case_set, labels, _, _ = load(SET_VARIED)
    responses = oracle(case_set, labels)
    for case in case_set.cases:
        assert contract.validate_response(case, responses[case.case_id]).status == "valid", (
            case.case_id
        )
    report = scoring.score_run(case_set, labels, responses)
    assert report[contract.DIM_ADHERENCE] == 1.0 and report[contract.DIM_CONSISTENCY] == 1.0
    assert report[contract.DIM_BEFORE_AFTER] == 1.0
    assert report[contract.DIM_STRUCTURED]["valid_rate"] == 1.0
    assert report[contract.DIM_HALLUCINATION] == {
        "unsupported_mention_rate": 0.0,
        "object_recall": 1.0,
    }


def test_the_varied_set_prompts_and_schemas_pin_each_id_in_order() -> None:
    case_set, _, _, _ = load(SET_VARIED)
    for case in case_set.cases:
        text = prompts.render_visual_prompt(case)
        assert "<true or false>" in text or case.kind not in (
            contract.KIND_ADHERENCE,
            contract.KIND_CONSISTENCY,
        )
        assert not re.search(r"reference|ground.?truth|label", text, re.IGNORECASE)
        if case.elements:
            schema = contract.build_response_schema(case.kind, case)
            answers = schema["oneOf"][0]["properties"]["answers"]
            ids = [part["properties"]["id"]["const"] for part in answers["prefixItems"]]
            assert ids == [key for key, _ in case.elements]


# ================================================================================================= the closed argv list


def _kwargs(tmp_path: Path) -> dict[str, Any]:
    files = make_files(tmp_path)
    return {
        "model_path": files.model, "projector_path": files.projector, "prompt_file": files.prompt,
        "schema_file": files.schema, "image_paths": files.images, "evaluation_root": files.root,
        "work_dir": files.work,
    }  # fmt: skip


def test_the_jinja_turn_format_adds_exactly_one_switch_and_nothing_else(tmp_path: Path) -> None:
    kwargs = _kwargs(tmp_path)
    legacy = visual_argv.build_visual_argv(**kwargs)
    jinja = visual_argv.build_visual_argv(**kwargs, use_jinja=True)
    assert visual_argv.build_visual_argv(**kwargs, use_jinja=False) == legacy
    assert "--jinja" not in legacy and jinja.count("--jinja") == 1
    assert [token for token in jinja if token != "--jinja"] == legacy
    assert visual_argv.argv_shape_digest(jinja) != visual_argv.argv_shape_digest(legacy)
    visual_argv.check_visual_argv(jinja, use_jinja=True)
    visual_argv.check_visual_argv(legacy)
    # The free-text control composes with the variant and changes nothing else.
    free = visual_argv.build_visual_argv(
        **{**kwargs, "schema_file": None}, free_text=True, use_jinja=True
    )
    assert "--jinja" in free and "--json-schema-file" not in free
    visual_argv.check_visual_argv(free, free_text=True, use_jinja=True)


def test_the_default_turn_format_still_refuses_the_jinja_switch(tmp_path: Path) -> None:
    kwargs = _kwargs(tmp_path)
    jinja = visual_argv.build_visual_argv(**kwargs, use_jinja=True)
    for fmt in ({}, {"use_jinja": False}):
        with pytest.raises(visual_argv.VisualArgvRefused) as refused:
            visual_argv.check_visual_argv(jinja, **fmt)
        assert refused.value.code == "forbidden_flag"
    assert (
        "--jinja" in visual_argv.VISUAL_REFUSED_FLAGS
        and "--jinja" not in visual_argv.VISUAL_ALLOWED_FLAGS
    )
    assert len(visual_argv.VISUAL_ALLOWED_FLAGS) == 22


def test_the_jinja_turn_format_needs_the_switch_once_and_only_once(tmp_path: Path) -> None:
    kwargs = _kwargs(tmp_path)
    legacy = visual_argv.build_visual_argv(**kwargs)
    with pytest.raises(visual_argv.VisualArgvRefused) as missing:
        visual_argv.check_visual_argv(legacy, use_jinja=True)
    assert missing.value.code == "gemma_template_flag_required"
    with pytest.raises(visual_argv.VisualArgvRefused) as twice:
        visual_argv.check_visual_argv([*legacy, "--jinja", "--jinja"], use_jinja=True)
    assert twice.value.code == "flag_repeated"


@pytest.mark.parametrize(
    "flag",
    [
        "--chat-template-kwargs", "--reasoning", "-rea", "--reasoning-budget", "--reasoning-format", "--chat-template",
        "--chat-template-file", "--no-jinja", "--system-prompt", "-p", "--log-disable", "--mmproj-url", "-hf",
    ],
)  # fmt: skip
def test_no_template_or_thinking_argument_is_accepted_even_in_the_jinja_turn_format(
    flag: str, tmp_path: Path
) -> None:
    argv = visual_argv.build_visual_argv(**_kwargs(tmp_path), use_jinja=True)
    for tail in ([flag], [flag, '{"enable_thinking":false}'], [flag, "off"]):
        with pytest.raises(visual_argv.VisualArgvRefused):
            visual_argv.check_visual_argv([*argv, *tail], use_jinja=True)
    assert good_argv is not None


def test_production_argv_is_untouched_and_still_refuses_the_switch() -> None:
    from src.ai_assist import argv as production

    assert "--jinja" in production.FORBIDDEN_FLAGS or "--jinja" not in production.ALLOWED_FLAGS
    source = (REPO / "src" / "ai_assist" / "argv.py").read_text(encoding="utf-8")
    assert "turn_format" not in source and "TURN_JINJA" not in source


# ================================================================================================= the plan


def test_the_plan_covers_the_ab_and_leaves_the_earlier_sections_exactly_as_they_were() -> None:
    current = plan.build_plan()
    section = current["template_ab"]
    assert section["decision"] == "D24" and section["set_id"] == SET_VARIED
    assert section["default_turn_format"] == "legacy" and section["qualified"] is False
    assert section["variants"]["legacy"]["flags_added"] == []
    assert section["variants"]["jinja"]["flags_added"] == ["--jinja"]
    assert {"--chat-template-kwargs", "--reasoning"} <= set(section["refused_by_name"])
    assert section["invocations_per_variant"] == 14 + 2 and section["invocations"] == 2 * (14 + 2)
    case_set, _, case_doc, label_doc = load(SET_VARIED)
    entry = section["set"]
    assert entry["case_set_sha256"] == contract.digest(case_doc)
    assert entry["label_set_sha256"] == contract.digest(label_doc)
    assert set(entry["requests"]) == {case.case_id for case in case_set.cases}
    for case in case_set.cases:
        assert entry["requests"][case.case_id]["schema_sha256"] == contract.digest(
            contract.build_response_schema(case.kind, case)
        )
    # The diagnostic section is the one the second run executed against: removing the new section gives that plan back.
    body = copy.deepcopy({key: value for key, value in current.items() if key != "plan_sha256"})
    del body["template_ab"]
    assert contract.digest(body) == RUN2_PLAN_DIGEST
    assert set(current["diagnostic"]["sets"]) == {synthetic.SET_ID, synthetic.SET_ID_512}
    assert current["diagnostic"]["invocation_unchanged"]["jinja"] == "refused"


# ================================================================================================= the driver


def _capture(set_id: str) -> diagnostics.DiagnosticCapture:
    _, _, case_doc, label_doc = load(set_id)
    return diagnostics.DiagnosticCapture(case_doc, label_doc)


def test_a_non_default_turn_format_is_refused_without_a_capture_and_launches_nothing(
    diag_world: World,
) -> None:
    visual = diag_world.driver(use_jinja=True)
    run = visual.run_case(diag_world.case_set, diag_world.case(contract.KIND_DESCRIBE))
    assert run.refusal is not None and run.refusal.code == driver.REFUSED_TURN_FORMAT
    assert run.evidence.status == driver.STATUS_NOT_RUN and diag_world.launches == []
    whole = visual.run_cases(diag_world.case_set, diag_world.labels)
    assert not whole.complete and whole.refusal is not None
    assert diag_world.launches == []


def test_the_driver_default_turn_format_is_legacy_and_launches_without_the_switch(
    diag_world: World,
) -> None:
    visual = diag_world.driver()
    assert visual.turn_format == "legacy"
    assert (
        visual.run_case(diag_world.case_set, diag_world.case(contract.KIND_DESCRIBE)).refusal
        is None
    )
    assert "--jinja" not in launched(diag_world)[-1]["argv"]


def test_with_a_capture_the_jinja_turn_launches_the_switch_and_nothing_new(
    diag_world: World,
) -> None:
    visual = diag_world.driver(capture=_capture(synthetic.SET_ID), use_jinja=True)
    scored = visual.run_cases(diag_world.case_set, diag_world.labels)
    controls = visual.run_controls(
        diag_world.case_set, diagnostics.control_requests(synthetic.SET_ID)
    )
    assert scored.complete and controls.complete
    seen = launched(diag_world)
    assert len(seen) == 13 + 2
    for line in seen:
        argv = line["argv"]
        assert argv.count("--jinja") == 1
        flags = {
            token
            for token in argv
            if token.startswith("-") and not token.lstrip("-").replace(".", "").isdigit()
        }
        assert flags <= visual_argv.VISUAL_ALLOWED_FLAGS | {"--jinja"}
        assert (
            "-p" not in argv and "--chat-template-kwargs" not in argv and "--reasoning" not in argv
        )
        assert (
            argv[argv.index("-ngl") + 1] == "0"
            and "--no-mmproj-offload" in argv
            and "--offline" in argv
        )
    document = driver.evidence_document(
        scored,
        plan_sha256="0" * 64,
        case_set_sha256="1" * 64,
        candidate=diag_world.candidate,
        controls=controls,
        turn_format="jinja",
    )
    assert document["turn_format"] == "jinja"
    legacy = driver.evidence_document(
        scored, plan_sha256="0" * 64, case_set_sha256="1" * 64, candidate=diag_world.candidate
    )
    assert legacy["turn_format"] == "legacy"


def test_the_capture_document_records_the_turn_format(diag_world: World) -> None:
    capture = _capture(synthetic.SET_ID)
    diag_world.driver(capture=capture, use_jinja=True).run_case(
        diag_world.case_set, diag_world.case(contract.KIND_DESCRIBE)
    )
    jinja = capture.document(plan_sha256="0" * 64, evidence_file="e.json", turn_format="jinja")
    assert jinja["turn_format"] == "jinja"
    assert capture.document(plan_sha256="0" * 64, evidence_file="e.json")["turn_format"] == "legacy"


# ================================================================================================= the CLI


def _patch_driver(diag_world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "find_candidate", lambda _name: diag_world.candidate)
    real = driver.VisualDriver

    def build(candidate: Any, **k: Any) -> Any:
        return real(
            candidate,
            **{**diag_world.kwargs, "capture": k["capture"], "use_jinja": k["use_jinja"]},
        )

    monkeypatch.setattr(driver, "VisualDriver", build)


def test_the_cli_refuses_the_jinja_turn_without_a_diagnostics_file_or_with_other_cases(
    diag_world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_driver(diag_world, monkeypatch)
    digest = plan.build_plan(diag_world.candidate)["plan_sha256"]
    (diag_world.tmp / "ack.json").write_text("{}", encoding="utf-8")
    assert (
        cli.main(cli_args(diag_world, digest, "--generation-idle", "--turn-format", "jinja")) == 2
    )
    assert driver.REFUSED_TURN_FORMAT in capsys.readouterr().err
    out = diag_world.tmp / "diagnostics"
    out.mkdir()
    other = diag_world.tmp / "cases.json"
    other.write_text("{}", encoding="utf-8")
    args = cli_args(
        diag_world, digest, "--generation-idle", "--turn-format", "jinja",
        "--diagnostics-out", str(out / "d.json"), "--cases", str(other), "--labels", str(other),
    )  # fmt: skip
    assert cli.main(args) == 2 and driver.REFUSED_TURN_FORMAT in capsys.readouterr().err
    assert diag_world.launches == [] and not (diag_world.tmp / "evidence.json").exists()


def test_the_cli_runs_the_jinja_turn_for_a_builtin_set_and_records_it(
    diag_world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_driver(diag_world, monkeypatch)
    digest = plan.build_plan(diag_world.candidate)["plan_sha256"]
    (diag_world.tmp / "ack.json").write_text("{}", encoding="utf-8")
    out = diag_world.tmp / "diagnostics"
    out.mkdir()
    args = cli_args(
        diag_world, digest, "--generation-idle", "--controls", "--turn-format", "jinja",
        "--diagnostics-out", str(out / "jinja.diagnostics.json"),
    )  # fmt: skip
    assert cli.main(args) == 0, capsys.readouterr().err
    evidence = json.loads((diag_world.tmp / "evidence.json").read_text(encoding="utf-8"))
    captured = json.loads((out / "jinja.diagnostics.json").read_text(encoding="utf-8"))
    assert evidence["turn_format"] == "jinja" and captured["turn_format"] == "jinja"
    assert evidence["complete"] is True and len(captured["requests"]) == 15
    assert all(line["argv"].count("--jinja") == 1 for line in launched(diag_world))
    assert "ANSWER-MARKER" not in json.dumps(evidence)


def test_the_cli_default_turn_format_is_legacy_and_the_choices_are_closed(
    diag_world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_driver(diag_world, monkeypatch)
    digest = plan.build_plan(diag_world.candidate)["plan_sha256"]
    (diag_world.tmp / "ack.json").write_text("{}", encoding="utf-8")
    assert cli.main(cli_args(diag_world, digest, "--generation-idle")) == 0, capsys.readouterr().err
    evidence = json.loads((diag_world.tmp / "evidence.json").read_text(encoding="utf-8"))
    assert evidence["turn_format"] == "legacy"
    assert all("--jinja" not in line["argv"] for line in launched(diag_world))
    with pytest.raises(SystemExit):
        cli.main(cli_args(diag_world, digest, "--turn-format", "chatml"))


# ================================================================================================= the work package


def test_the_work_package_records_the_digest_the_commands_the_proof_and_the_limits() -> None:
    text = (REPO / plan.TEMPLATE_AB_DOCUMENT).read_text(encoding="utf-8")
    digest = plan.build_plan()["plan_sha256"]
    assert text.count(digest) >= 4 and RUN2_PLAN_DIGEST in text
    assert "run 3 result" in text.lower() and "qualified" in text
    for line in (
        "write-synthetic --set vl220-synthetic-512-2",
        "--turn-format legacy",
        "--turn-format jinja",
        "run3-512v-legacy.json",
        "run3-512v-jinja.diagnostics.json",
    ):
        assert line in text, line
    # The source proof names the files and the reason the thinking argument cannot be requested.
    for reference in (
        "common/arg.cpp:3583-3600",
        "tools/mtmd/mtmd-cli.cpp:354-362",
        "common/chat.h:274",
    ):
        assert reference in text, reference
    assert "cannot be requested through `llama-mtmd-cli`" in text
    assert "stick figures" in text and "32" in text
    section = plan.build_plan()["template_ab"]
    assert section["invocations"] == 32


def test_the_contract_documents_record_the_variant_as_evaluation_only_and_run_once() -> None:
    for relative in (plan.INVOCATION_DOCUMENT, plan.EVALUATION_DOCUMENT):
        text = (REPO / relative).read_text(encoding="utf-8")
        assert plan.build_plan()["plan_sha256"] in text and "AI-VL-223" in text, relative
    invocation = (REPO / plan.INVOCATION_DOCUMENT).read_text(encoding="utf-8")
    assert "evaluation-only" in invocation and "run once" in invocation
    assert "`qualified` stays false" in invocation


# ================================================================================================= main's use_jinja (PR-AI-VL-230)


def test_the_lfm_jinja_variant_runs_under_the_same_conditions_as_the_legacy_turn(
    diag_world: World,
) -> None:
    from src.utils.managed_process import run_bounded

    seen: list[dict[str, Any]] = []

    def spy(command: list[str], **kwargs: Any) -> Any:
        seen.append(kwargs)
        return run_bounded(command, **kwargs)

    describe = diag_world.case(contract.KIND_DESCRIBE)
    diag_world.driver(runner=spy).run_case(diag_world.case_set, describe)
    capture = _capture(synthetic.SET_ID)
    diag_world.driver(runner=spy, capture=capture, use_jinja=True).run_case(
        diag_world.case_set, describe
    )
    legacy, jinja = seen
    assert "--jinja" not in launched(diag_world)[0]["argv"]
    assert launched(diag_world)[1]["argv"].count("--jinja") == 1
    # Gemma's stricter containment and memory-cap options are Gemma-only: neither LFM variant gets them.
    assert "require_containment" not in legacy and "require_containment" not in jinja
    assert set(legacy) == set(jinja)


def test_gemma_keeps_its_own_template_and_its_strict_checks() -> None:
    from tools.qualification.vl220 import candidates

    gemma = candidates.find_candidate(candidates.GEMMA_CANDIDATE_ID)
    lfm = candidates.find_candidate(candidates.LFM_CANDIDATE_ID)
    common: dict[str, Any] = {
        "evaluation_root": REPO,
        "ai_root": REPO,
        "assets_dir": REPO,
        "acknowledgement": None,
        "activity": None,
    }
    assert driver.VisualDriver(gemma, **common).turn_format == "jinja"
    assert driver.VisualDriver(lfm, **common).turn_format == "legacy"
    assert driver.VisualDriver(lfm, use_jinja=True, **common).turn_format == "jinja"
    assert driver.VisualDriver(gemma, use_jinja=False, **common).turn_format == "jinja"


def test_the_cli_refuses_a_legacy_turn_for_gemma_before_anything_runs(
    diag_world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    from tools.qualification.vl220 import candidates

    gemma = candidates.find_candidate(candidates.GEMMA_CANDIDATE_ID)
    digest = plan.build_plan(gemma)["plan_sha256"]
    (diag_world.tmp / "ack.json").write_text("{}", encoding="utf-8")
    args = [
        "--candidate", candidates.GEMMA_CANDIDATE_ID,
        *cli_args(diag_world, digest, "--generation-idle", "--turn-format", "legacy"),
    ]  # fmt: skip
    assert cli.main(args) == 2
    assert "gemma_renders_its_own_template" in capsys.readouterr().err
    assert diag_world.launches == [] and not (diag_world.tmp / "evidence.json").exists()
