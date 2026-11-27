"""The AI Assist replay tool (ASSIST-FIX): counts only, no network without the owner's approval."""

from __future__ import annotations

import json
from pathlib import Path

from src.ai_assist import framing
from src.ai_assist.contracts import AssistRequest, SuggestionKind
from src.ai_assist.remote_preview import DEFAULT_MODEL, ENDPOINT, RUNTIME_VERSION, RemoteApproval
from tools import ai_assist_replay as replay

CANARY = "zzcanary"
IDENTITY = RemoteApproval(ENDPOINT, DEFAULT_MODEL, "0" * 64, RUNTIME_VERSION)


def event(kind="slot_variety", outcome="suggestion", reason="", **more):
    return {"kind": kind, "outcome": outcome, "reason": reason, "provider": "remote", **more}


EVENTS = [
    *[event() for _ in range(6)],
    event(outcome="refused_by_model", reason="status_refused"),
    event(outcome="malformed", reason="not_json"),
    event("plan_proposal", "malformed", "target_not_in_closed_list"),
    event(outcome="generation_active", reason="generation_running"),
]


def packs(folder: Path) -> Path:
    document = {
        "schema_version": 1,
        "pack_data": {
            "slots": [
                {"index": 0, "text": f"{CANARY} barn in a field, soft light", "negative": ""}
            ],
            "matrix": {
                "enabled": True,
                "slots": [{"name": "lighting", "values": [f"{CANARY} glow"]}],
            },
        },
        "preset_data": {},
    }
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "one.json").write_text(json.dumps(document), encoding="utf-8")
    return folder


def test_score_counts_rates_over_all_and_over_answered_requests() -> None:
    report = replay.score(EVENTS)["all"]
    assert (report["requests"], report["answered"]) == (10, 9)
    assert report["refused_pct_of_all"] == 10.0 and report["malformed_pct_of_all"] == 20.0
    assert report["malformed_pct_of_answered"] == 22.2


def test_offline_reports_both_ends_and_leaves_infrastructure_outcomes_alone() -> None:
    report = replay.offline(EVENTS)
    best, worst = report["after_if_model_complies"], report["after_if_model_repeats"]
    assert best["outcomes"] == {"generation_active": 1, "suggestion": 9}
    assert worst["outcomes"] == report["before"]["outcomes"]


def test_live_without_approval_sends_nothing_and_prints_no_prompt_text(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(replay, "run_live", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert replay.main(["live", "--packs", str(packs(tmp_path / "p")), "--limit", "2"]) == 0
    printed = capsys.readouterr().out
    assert "nothing was sent" in printed and CANARY not in printed


def test_live_arms_send_the_two_contracts_and_report_counts_only(tmp_path) -> None:
    worker = replay._ScriptedWorker(IDENTITY)
    bodies: list[dict] = []
    refusal = json.dumps(
        {"schema": "ai_assist.suggestion/1", "status": "refused", "refusal_reason": CANARY}
    )
    answer = replay.fixture_answer(
        replay.synthetic_request(SuggestionKind.SLOT_VARIETY, "a"), "suggestion", ""
    )

    def transport(path, body, token, timeout, limit):
        if path == "/api/generate":
            bodies.append(json.loads(body))
            worker.script = [(refusal, "stop") if "oneOf" in bodies[-1]["format"] else answer]
        return worker(path, body, token, timeout, limit)

    cases = replay.build_cases(packs(tmp_path / "p"), {SuggestionKind.SLOT_VARIETY: 1})
    report = replay.run_live(cases, IDENTITY, transport=transport)
    assert report["before"]["outcomes"] == {"refused_by_model": 1}
    assert report["after"]["outcomes"] == {"suggestion": 1}
    before, after = bodies
    assert "ai_assist.frame/1" in before["prompt"] and 'status to "refused"' in before["prompt"]
    assert "refus" not in after["prompt"].lower() and "oneOf" not in after["format"]
    assert CANARY not in json.dumps(report)


def test_the_previous_prompt_matches_the_frame_before_this_change() -> None:
    """Pins the before arm to the shipped ASSIST-FIX parent, without needing Git history at run time."""

    request = AssistRequest("p", SuggestionKind.TARGET_FIT_ADVICE, "a barn", allowed_targets=("m",))
    old = replay.previous_prompt(framing.render_prompt(request))
    assert (
        'For a suggestion, set status to "ok" and use the schema id and kind given above. Set target to one exact '
        'identifier from Allowed targets. If you cannot or will not help, set status to "refused" and provide a '
        "short refusal_reason.\n"
    ) in old
    assert old.endswith(framing.render_prompt(request).split(framing.BEGIN_MARKER)[1])
