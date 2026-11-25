"""AI-230f: the slot-suggestion case set, scorer and loopback driver, on synthetic data only.

No model runs and nothing touches the network: the generator is a fake that reads the production request and answers from its
closed lists, and the HTTP call is replaced by a recorder.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from src.ai_assist.contracts import AssistRequest, OutcomeCode, SuggestionKind
from src.ai_assist.framing import (
    PHRASE_EXAMPLE,
    PROPOSAL_EXAMPLE,
    VARIETY_EXAMPLE,
    build_json_schema,
)
from src.ai_assist.remote import _ollama_prompt
from tools.qualification.ai230 import __main__ as driver
from tools.qualification.ai230.slot_cases import (
    CASES,
    KIND_PHRASE,
    KIND_PROPOSAL,
    KIND_VARIETY,
    CaseResult,
    build_case_request,
    run_cases,
    score_case,
    summarize,
)

SCHEMA = "ai_assist.suggestion/1"
MARK = "zzmark"


def _good(request: AssistRequest) -> str:
    """A well-formed answer built only from the request's closed lists, with values no case already holds."""

    if request.kind is SuggestionKind.SLOT_VARIETY:
        slots = [
            {
                "slot": name,
                "values": [f"{MARK} {name} {n}" for n in range(request.variety_per_slot)],
                "rationale": "fits the goal",
            }
            for name, _values in request.matrix_slots
        ]
        return json.dumps({"schema": SCHEMA, "status": "ok", "kind": request.kind.value, "slots": slots})
    if request.kind is SuggestionKind.PHRASE_SLOT:
        phrase_slots = [
            {
                "slot_name": f"{MARK}slot",
                "values": [f"{MARK} one", f"{MARK} two"],
                "rationale": "fits the goal",
            }
        ]
        return json.dumps(
            {
                "schema": SCHEMA,
                "status": "ok",
                "kind": request.kind.value,
                "phrase_slots": phrase_slots,
            }
        )
    proposals = [
        {
            "slot_name": f"{MARK}slot",
            "values": [f"{MARK} one", f"{MARK} two", f"{MARK} three"],
            "insertion_point": 0,
            "rationale": "fits the goal",
        }
    ]
    return json.dumps(
        {"schema": SCHEMA, "status": "ok", "kind": request.kind.value, "proposals": proposals}
    )


def test_case_ids_are_unique_and_cover_every_kind() -> None:
    ids = [case.case_id for case in CASES]
    assert len(ids) == len(set(ids))
    assert {case.kind for case in CASES} == {KIND_VARIETY, KIND_PROPOSAL, KIND_PHRASE}
    assert sum(case.kind == KIND_PHRASE for case in CASES) >= 4
    assert sum(case.kind == KIND_VARIETY for case in CASES) >= 5
    assert sum(case.kind == KIND_PROPOSAL for case in CASES) >= 5


def test_every_case_builds_a_production_request() -> None:
    for case in CASES:
        request = build_case_request(case)
        expected = {
            KIND_VARIETY: SuggestionKind.SLOT_VARIETY,
            KIND_PROPOSAL: SuggestionKind.SLOT_PROPOSAL,
            KIND_PHRASE: SuggestionKind.PHRASE_SLOT,
        }[case.kind]
        assert request.kind is expected
        assert request.goal_text == case.goal
        # the frame carries the worked example, so the measured prompt is the shipped prompt
        prompt = _ollama_prompt(request)
        example = {
            KIND_VARIETY: VARIETY_EXAMPLE,
            KIND_PROPOSAL: PROPOSAL_EXAMPLE,
            KIND_PHRASE: PHRASE_EXAMPLE,
        }[case.kind]
        assert example in prompt


def test_a_good_generator_gets_offers_for_every_case() -> None:
    results = run_cases(_good)
    assert [r.case_id for r in results] == [c.case_id for c in CASES]
    assert all(r.code == OutcomeCode.SUGGESTION.value for r in results)
    assert all(r.offered > 0 and r.rejected == 0 for r in results)
    summary = summarize(results)
    for kind in (KIND_VARIETY, KIND_PROPOSAL, KIND_PHRASE):
        assert summary["kinds"][kind]["valid"] == summary["kinds"][kind]["cases"]
        assert summary["kinds"][kind]["cases_with_an_offer"] == summary["kinds"][kind]["cases"]


def test_repeating_an_existing_value_is_counted_as_a_rejection() -> None:
    case = next(c for c in CASES if c.case_id == "var-lighting-photo")
    request = build_case_request(case)
    document = {
        "schema": SCHEMA,
        "status": "ok",
        "kind": request.kind.value,
        "slots": [
            {"slot": "lighting", "values": ["Soft Light", "soft lights", "rim light"], "rationale": "x"}
        ],
    }
    result = score_case(case, json.dumps(document))
    assert result.code == OutcomeCode.SUGGESTION.value
    assert (result.returned, result.offered, result.rejected) == (3, 1, 2)
    reasons = dict(result.reject_reasons)
    assert reasons == {"duplicate_existing": 1, "near_duplicate_existing": 1}


def test_bad_answers_are_classified_not_repaired() -> None:
    case = CASES[0]
    assert score_case(case, "not json at all").code == OutcomeCode.MALFORMED.value
    refusal = json.dumps(
        {"schema": SCHEMA, "status": "refused", "refusal_reason": "cannot help with that"}
    )
    assert score_case(case, refusal).code == OutcomeCode.REFUSED_BY_MODEL.value
    wrong_kind = json.dumps({"schema": SCHEMA, "status": "ok", "kind": "prompt_rewrite"})
    assert score_case(case, wrong_kind).code == OutcomeCode.MALFORMED.value


def test_a_generator_that_raises_is_recorded_and_the_run_continues() -> None:
    calls: list[str] = []

    def flaky(request: AssistRequest) -> str:
        calls.append(request.request_id)
        if len(calls) == 2:
            raise RuntimeError("secret detail that must not be recorded")
        return _good(request)

    results = run_cases(flaky)
    assert len(results) == len(CASES)
    assert results[1].code == OutcomeCode.UNAVAILABLE.value
    assert results[1].reason == "generator_error"
    assert "secret detail" not in repr(results)
    assert sum(r.code == OutcomeCode.SUGGESTION.value for r in results) == len(CASES) - 1


def test_results_hold_no_authored_or_model_text() -> None:
    results = run_cases(_good)
    blob = repr(results) + json.dumps(summarize(results), sort_keys=True)
    assert MARK not in blob
    # case ids are fixed labels, not content; take them out so a slot name inside a label is not mistaken for a leak
    labelled = blob
    for case in CASES:
        labelled = labelled.replace(case.case_id, "")
    for case in CASES:
        assert case.goal == "" or case.goal not in labelled
        assert case.sentence == "" or case.sentence not in labelled
        assert case.phrase == "" or case.phrase not in labelled
        for name, values in case.slots:
            assert name not in labelled
            assert all(value not in labelled for value in values)


def test_summarize_counts_each_outcome() -> None:
    results = (
        CaseResult("a", KIND_VARIETY, OutcomeCode.SUGGESTION.value, returned=3, offered=2, rejected=1,
                   reject_reasons=(("duplicate_existing", 1),)),
        CaseResult("b", KIND_VARIETY, OutcomeCode.REFUSED_BY_MODEL.value),
        CaseResult("c", KIND_PROPOSAL, OutcomeCode.MALFORMED.value, "not_json"),
        CaseResult("d", KIND_PROPOSAL, OutcomeCode.UNAVAILABLE.value),
    )
    summary = summarize(results)
    variety, proposal = summary["kinds"][KIND_VARIETY], summary["kinds"][KIND_PROPOSAL]
    assert (variety["cases"], variety["valid"], variety["refused"], variety["offered"]) == (2, 1, 1, 2)
    assert variety["reject_reasons"] == {"duplicate_existing": 1}
    assert (proposal["malformed"], proposal["other"], proposal["valid"]) == (1, 1, 0)


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434", "http://127.0.0.1:11434/"],
)
def test_loopback_addresses_are_accepted(url: str) -> None:
    assert driver.loopback_url(url) == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:11434",
        "http://192.168.1.20:11434",
        "http://0.0.0.0:11434",
        "http://example.com:11434",
        "http://127.0.0.1.example.com:11434",
        "http://localhost.example.com",
        "ftp://127.0.0.1",
        "127.0.0.1:11434",
        "",
    ],
)
def test_anything_else_is_refused(url: str) -> None:
    with pytest.raises(driver.Refused):
        driver.loopback_url(url)


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        return self._raw if limit < 0 else self._raw[:limit]


def _post_recorder(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    sent: list[tuple[str, dict[str, Any]]] = []

    def fake_urlopen(http: Any, timeout: float = 0) -> _Response:
        sent.append((http.full_url, json.loads(http.data.decode("ascii"))))
        return _Response(payload)

    monkeypatch.setattr(driver.urllib.request, "urlopen", fake_urlopen)
    return sent


def test_the_driver_posts_the_production_body(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _post_recorder(monkeypatch, {"response": "{}", "done": True})
    request = build_case_request(CASES[0])
    text = driver.ollama_generate("http://127.0.0.1:11434", "some-model")(request)
    assert text == "{}"
    (url, body), = sent
    assert url == "http://127.0.0.1:11434/api/generate"
    assert body["model"] == "some-model"
    assert body["prompt"] == _ollama_prompt(request)
    assert body["format"] == build_json_schema(request)
    assert body["stream"] is False and body["think"] is False
    assert "keep_alive" not in body  # GPU residency is the owner's call; the driver never changes it
    assert set(body["options"]) == {
        "num_ctx",
        "num_predict",
        "temperature",
        "top_p",
        "top_k",
        "presence_penalty",
        "seed",
    }


def test_an_unfinished_answer_is_not_scored(monkeypatch: pytest.MonkeyPatch) -> None:
    _post_recorder(monkeypatch, {"response": "{", "done": False})
    generate: Callable[[AssistRequest], str] = driver.ollama_generate(
        "http://127.0.0.1:11434", "some-model"
    )
    with pytest.raises(driver.Refused):
        generate(build_case_request(CASES[0]))


def test_the_driver_refuses_a_remote_host_before_building_anything() -> None:
    with pytest.raises(driver.Refused):
        driver.ollama_generate("http://10.0.0.5:11434", "some-model")
    assert driver.main(["run", "--model", "m", "--base-url", "http://10.0.0.5:11434", "--out", "x.json"]) == 2


def test_the_cases_command_lists_ids_without_a_model(capsys: pytest.CaptureFixture[str]) -> None:
    assert driver.main(["cases"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert [line.split("\t")[0] for line in lines] == [case.case_id for case in CASES]


def test_a_full_run_writes_counts_and_codes_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(driver, "ollama_generate", lambda _url, _model: _good)
    out = tmp_path / "result.json"
    assert driver.main(["run", "--model", "m", "--out", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["schema"] == "stablenew.ai230.slot_cases.v1"
    assert document["model"] == "m"
    assert len(document["results"]) == len(CASES)
    text = out.read_text(encoding="utf-8") + capsys.readouterr().out
    assert MARK not in text
    assert all(case.goal == "" or case.goal not in text for case in CASES)
