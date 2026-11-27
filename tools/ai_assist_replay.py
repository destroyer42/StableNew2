"""Measure AI Assist refusal and malformed-answer rates (ASSIST-FIX). Prints counts and outcome codes only.

    python -m tools.ai_assist_replay score                  # the local event log: what happened
    python -m tools.ai_assist_replay offline                # the logged outcome mix replayed on synthetic fixtures
    python -m tools.ai_assist_replay live --packs DIR       # plan only: no network
    python -m tools.ai_assist_replay live --packs DIR --owner-approved

The event log holds no prompt text (owner decision D7), so the logged requests cannot be re-sent.

``offline`` is a mechanics check, not a model measurement: it feeds the current service a synthetic answer of each
logged outcome class and reports both ends (the model then behaves, or repeats itself).

``live`` rebuilds cases in memory from PromptPacks in the logged kind mix and sends each one twice to the approved
remote worker: once with the previous contract (refusal branch, no retry) and once with the current one. It uses the
worker's GPU and sends pack text to it, so it needs the owner's approval. It never prints, stores or logs prompt or
answer text, and it works from a temporary AI root, so the owner's event log and settings are only read.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from src.ai_assist import framing
from src.ai_assist.argv import RunLimits, Sampling
from src.ai_assist.contracts import (
    MAX_REFUSAL_REASON_CHARS,
    SUGGESTION_SCHEMA_ID,
    AiCancelToken,
    AssistRequest,
    OutcomeCode,
    SuggestionKind,
)
from src.ai_assist.image import prepare_image
from src.ai_assist.manifests import load_model_registry, load_runtime_manifest
from src.ai_assist.paths import events_path, resolve_ai_root
from src.ai_assist.remote import RemoteAssist
from src.ai_assist.remote_preview import (
    DEFAULT_MODEL,
    ENDPOINT,
    RUNTIME_VERSION,
    RemoteApproval,
    read_remote_settings,
    write_remote_approval,
)
from src.ai_assist.remote_transport import Transport, loopback_request
from src.ai_assist.service import AiAssistService, ServicePolicy
from src.ai_assist.status import MODEL_REGISTRY_PATH, RUNTIME_MANIFEST_PATH
from src.ai_assist.validators import validate_output
from src.gui.models.prompt_pack_model import MatrixConfig
from src.gui_v2.ai_slot_proposal import build_proposal_request
from src.gui_v2.ai_slot_variety import build_variety_request, judge_variety, matrix_state
from src.promptpacks.storage import load_prompt_pack_document

ANSWERED = ("suggestion", "refused_by_model", "malformed")
#: The 104 requests of the 2026-11-14..25 log, by kind.
LOGGED_MIX = {
    SuggestionKind.SLOT_VARIETY: 70,
    SuggestionKind.PLAN_PROPOSAL: 18,
    SuggestionKind.TARGET_FIT_ADVICE: 6,
    SuggestionKind.PROMPT_REWRITE: 6,
    SuggestionKind.SLOT_PROPOSAL: 4,
}
_GOALS = (
    "more variety that fits the existing values",
    "bolder and more vivid choices in the same style",
    "different moods and lighting for the same scene",
    "more specific details of the same subject",
)
_TARGETS = ("sdxl_model_a", "sdxl_model_b", "flux_model")
_WORKFLOWS = ("video_workflow_a", "video_workflow_b")
_STAGES = ("txt2img", "upscale", "video")
_MARKUP = re.compile(r"<[^>]*>|\[\[[^\]]*\]\]")


# -- counting ----------------------------------------------------------------------------------------------------------


def summarize(rows: Iterable[tuple[str, str, str]]) -> dict[str, Any]:
    """Counts for ``(kind, outcome, reason)`` rows. ``answered`` leaves out infrastructure outcomes (D11)."""

    rows = list(rows)
    outcomes = Counter(outcome for _kind, outcome, _reason in rows)
    answered = sum(outcomes[name] for name in ANSWERED)

    def rate(count: int, of: int) -> float:
        return round(100.0 * count / of, 1) if of else 0.0

    return {
        "requests": len(rows),
        "answered": answered,
        "outcomes": dict(sorted(outcomes.items())),
        "refused_pct_of_all": rate(outcomes["refused_by_model"], len(rows)),
        "refused_pct_of_answered": rate(outcomes["refused_by_model"], answered),
        "malformed_pct_of_all": rate(outcomes["malformed"], len(rows)),
        "malformed_pct_of_answered": rate(outcomes["malformed"], answered),
        "failures": {
            f"{kind}:{outcome}:{reason}": count
            for (kind, outcome, reason), count in sorted(Counter(rows).items())
            if outcome != "suggestion"
        },
    }


def read_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for candidate in (path.with_name(path.name + ".1"), path):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue  # a torn final line
            if isinstance(record, dict) and record.get("outcome") and record.get("kind"):
                events.append(record)
    return events


def _row(event: dict[str, Any]) -> tuple[str, str, str]:
    return str(event["kind"]), str(event["outcome"]), str(event.get("reason") or "")


def score(events: list[dict[str, Any]]) -> dict[str, Any]:
    attempts = Counter(str(event["attempts"]) for event in events if "attempts" in event)
    return {
        "all": summarize(map(_row, events)),
        "remote": summarize(_row(e) for e in events if e.get("provider") == "remote"),
        "attempts": dict(attempts),
        "first_attempt_malformed": sum(1 for e in events if e.get("first_reason")),
    }


# -- shared service setup ----------------------------------------------------------------------------------------------


def _service(root: Path, remote: RemoteAssist) -> AiAssistService:
    return AiAssistService(
        root=root,
        runtime_manifest=load_runtime_manifest(RUNTIME_MANIFEST_PATH),
        registry=load_model_registry(MODEL_REGISTRY_PATH),
        activity_provider=lambda: None,  # read only by the local path, which then refuses
        remote=remote,
        policy=ServicePolicy(allow_preview=False, strict_offline=True),
    )


# -- offline -----------------------------------------------------------------------------------------------------------


def synthetic_request(kind: SuggestionKind, request_id: str) -> AssistRequest:
    if kind is SuggestionKind.PROMPT_REWRITE:
        return AssistRequest(request_id, kind, positive_text="a red barn <lora:barn:0.8>")
    if kind is SuggestionKind.TARGET_FIT_ADVICE:
        return AssistRequest(request_id, kind, positive_text="a barn", allowed_targets=_TARGETS)
    if kind is SuggestionKind.WORKFLOW_CHOICE:
        return AssistRequest(request_id, kind, positive_text="a barn", allowed_workflows=_WORKFLOWS)
    if kind is SuggestionKind.PLAN_PROPOSAL:
        return AssistRequest(
            request_id,
            kind,
            goal_text="a poster",
            allowed_targets=_TARGETS,
            allowed_workflows=_WORKFLOWS,
            allowed_stages=_STAGES,
        )
    if kind is SuggestionKind.SLOT_VARIETY:
        return AssistRequest(
            request_id,
            kind,
            goal_text="more light",
            matrix_slots=(("lighting", ("soft light",)),),
        )
    return AssistRequest(
        request_id,
        SuggestionKind.SLOT_PROPOSAL,
        goal_text="more mood",
        positive_text="a barn in a field",
        insertion_points=("a barn|HERE|",),
    )


def fixture_answer(request: AssistRequest, outcome: str, reason: str) -> tuple[str, str]:
    """A synthetic ``(answer, done_reason)`` standing in for one logged outcome class."""

    head: dict[str, Any] = {
        "schema": SUGGESTION_SCHEMA_ID,
        "status": "ok",
        "kind": request.kind.value,
    }
    step = {
        "stage": "txt2img",
        "target": _TARGETS[0],
        "workflow": None,
        "count": 1,
        "rationale": "r",
    }
    payload: dict[str, Any] = {
        SuggestionKind.PROMPT_REWRITE: {"positive": request.positive_text, "negative": ""},
        SuggestionKind.TARGET_FIT_ADVICE: {"target": _TARGETS[0]},
        SuggestionKind.WORKFLOW_CHOICE: {"workflow": _WORKFLOWS[0]},
        SuggestionKind.PLAN_PROPOSAL: {"steps": [step]},
        SuggestionKind.SLOT_VARIETY: {
            "slots": [{"slot": "lighting", "values": ["dusk glow"], "rationale": "r"}]
        },
        SuggestionKind.SLOT_PROPOSAL: {
            "proposals": [
                {
                    "slot_name": "weather",
                    "values": ["fog", "rain", "snow"],
                    "insertion_point": 0,
                    "rationale": "r",
                }
            ]
        },
    }.get(request.kind, {})
    if outcome == "suggestion":
        return json.dumps({**head, **payload}), "stop"
    if outcome == "refused_by_model":
        return (
            json.dumps(
                {"schema": SUGGESTION_SCHEMA_ID, "status": "refused", "refusal_reason": "no"}
            ),
            "stop",
        )
    if reason == "not_json":
        return json.dumps({**head, **payload})[:40], "length"
    if reason == "target_not_in_closed_list" and request.kind is SuggestionKind.PLAN_PROPOSAL:
        return json.dumps({**head, "steps": [{**step, "target": None}]}), "stop"
    if reason == "kind_mismatch":
        return json.dumps({**head, **payload, "kind": "other"}), "stop"
    if reason == "protected_tokens_changed":
        return json.dumps({**head, "positive": "a red barn", "negative": ""}), "stop"
    return "{", "stop"


class _ScriptedWorker:
    """A stand-in transport: answers ``/api/generate`` from the current script. No network."""

    def __init__(self, identity: RemoteApproval) -> None:
        self.identity = identity
        self.script: list[tuple[str, str]] = []

    def __call__(
        self, path: str, body: bytes | None, token: AiCancelToken, timeout: float, limit: int
    ) -> tuple[int, bytes]:
        if path == "/api/version":
            return 200, json.dumps({"version": self.identity.version}).encode()
        if path == "/api/tags":
            model = {"name": self.identity.model, "digest": self.identity.digest}
            return 200, json.dumps({"models": [model]}).encode()
        answer, done = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        document = {
            "model": self.identity.model_reference,
            "done": True,
            "done_reason": done,
            "response": answer,
        }
        return 200, json.dumps(document).encode()


def offline(events: list[dict[str, Any]]) -> dict[str, Any]:
    identity = RemoteApproval(ENDPOINT, DEFAULT_MODEL, "0" * 64, RUNTIME_VERSION)
    result: dict[str, Any] = {"before": summarize(map(_row, events))}
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        write_remote_approval(root, identity)
        worker = _ScriptedWorker(identity)
        service = _service(root, RemoteAssist(root, transport=worker))
        for scenario, behaves in (
            ("after_if_model_complies", True),
            ("after_if_model_repeats", False),
        ):
            rows: list[tuple[str, str, str]] = []
            for number, event in enumerate(events):
                kind, outcome, reason = _row(event)
                if outcome not in ANSWERED:
                    rows.append((kind, outcome, reason))  # infrastructure: unchanged by this work
                    continue
                request = synthetic_request(SuggestionKind(kind), f"r{number}")
                logged = fixture_answer(request, outcome, reason)
                valid = fixture_answer(request, "suggestion", "")
                # A refusal object and a null plan target are outside the new schema, so a worker that honours the
                # schema cannot send them at all. Any other failure can happen once and then meets the retry.
                excluded = reason == "status_refused" or (
                    reason == "target_not_in_closed_list" and kind == "plan_proposal"
                )
                worker.script = (
                    [logged] if not behaves else [valid] if excluded else [logged, valid]
                )
                answer = service.run(request)
                rows.append((kind, answer.code.value, answer.reason))
            result[scenario] = summarize(rows)
    return result


# -- live --------------------------------------------------------------------------------------------------------------


def _pack_material(folder: Path) -> tuple[list[tuple[str, str]], list[Any]]:
    """``(prompt rows, matrix slot lists)`` from native packs. Held in memory only."""

    prompts: list[tuple[str, str]] = []
    matrices: list[Any] = []
    for path in sorted(folder.glob("*.json")):
        try:
            pack = load_prompt_pack_document(path)["pack_data"]
        except Exception:  # noqa: BLE001 - not a native pack; its text must not reach the console
            continue
        for row in pack.get("slots") or []:
            positive = str(row.get("text") or "").strip()
            if positive:
                prompts.append((positive, str(row.get("negative") or "").strip()))
        slots = matrix_state(MatrixConfig.from_mapping(pack.get("matrix")).slots)
        if any(slot.editable for slot in slots):
            matrices.append(slots)
    return prompts, matrices


def build_cases(
    folder: Path, mix: dict[SuggestionKind, int], *, seed: int = 1
) -> list[tuple[AssistRequest, Any]]:
    """``(request, matrix slots or None)`` cases, deterministic for a folder and seed."""

    prompts, matrices = _pack_material(folder)
    if not prompts or not matrices:
        raise SystemExit("The pack folder needs native packs with prompt rows and matrix slots.")
    rng = random.Random(seed)
    cases: list[tuple[AssistRequest, Any]] = []
    for kind, wanted in mix.items():
        made = 0
        for _ in range(wanted * 20):
            if made == wanted:
                break
            number = f"live-{len(cases)}"
            positive, negative = rng.choice(prompts)
            slots = rng.choice(matrices)
            goal = rng.choice(_GOALS)
            try:
                if kind is SuggestionKind.SLOT_VARIETY:
                    names = [slot.name for slot in slots if slot.editable]
                    chosen = names[: rng.randint(1, min(3, len(names)))]
                    request = build_variety_request(
                        number, goal, slots, content_class="sensitive", selected=chosen, per_slot=3
                    )
                elif kind is SuggestionKind.SLOT_PROPOSAL:
                    request, _points = build_proposal_request(
                        number, goal, _MARKUP.sub("", positive), slots, content_class="sensitive"
                    )
                elif kind is SuggestionKind.PLAN_PROPOSAL:
                    request = AssistRequest(
                        number,
                        kind,
                        content_class="sensitive",
                        goal_text=_MARKUP.sub("", positive)[:900],
                        allowed_targets=_TARGETS,
                        allowed_workflows=_WORKFLOWS,
                        allowed_stages=_STAGES,
                    )
                elif kind is SuggestionKind.TARGET_FIT_ADVICE:
                    request = AssistRequest(
                        number,
                        kind,
                        positive,
                        negative,
                        content_class="sensitive",
                        allowed_targets=_TARGETS,
                    )
                else:
                    request = AssistRequest(
                        number, kind, positive, negative, content_class="sensitive"
                    )
                framing.render_prompt(request)
            except ValueError:  # over a bound or a reserved marker: draw another
                continue
            cases.append((request, slots if kind is SuggestionKind.SLOT_VARIETY else None))
            made += 1
    return cases


def motion_cases(images: Sequence[Path], repeats: int = 5) -> list[tuple[AssistRequest, Any]]:
    """The new motion-phrase kind, which has no previous contract: ``repeats`` requests for each picture."""

    cases: list[tuple[AssistRequest, Any]] = []
    for path in images:
        picture = prepare_image(path)
        for number in range(repeats):
            request = AssistRequest(
                f"motion-{len(cases)}",
                SuggestionKind.MOTION_PHRASE,
                positive_text=_GOALS[number % len(_GOALS)],
                image_jpeg=picture,
            )
            cases.append((request, None))
    return cases


def previous_prompt(prompt: str) -> str:
    """The frame as sent before ASSIST-FIX (``ai_assist.frame/1``): same text plus the offered refusal."""

    head, marker, data = prompt.partition(framing.BEGIN_MARKER)
    lines = head.replace("(ai_assist.frame/2)", "(ai_assist.frame/1)").split("\n")
    for index, line in enumerate(lines):
        if line.startswith('Set status to "ok" and'):
            lines[index] = (
                'For a suggestion, set status to "ok" and'
                + line[len('Set status to "ok" and') :]
                + ' If you cannot or will not help, set status to "refused" and provide a short refusal_reason.'
            )
    return "\n".join(lines) + marker + data


def previous_schema(request: AssistRequest, schema: dict[str, Any]) -> dict[str, Any]:
    """The two-branch schema sent before ASSIST-FIX, with the open plan step."""

    if request.kind is SuggestionKind.PLAN_PROPOSAL:
        step = dict(schema["properties"]["steps"]["items"]["oneOf"][0])
        step["properties"] = {
            **step["properties"],
            "stage": {"enum": list(request.allowed_stages)},
            "target": {"enum": [*request.allowed_targets, None]},
            "workflow": {"enum": [*request.allowed_workflows, None]},
        }
        steps = {**schema["properties"]["steps"], "items": step}
        schema = {**schema, "properties": {**schema["properties"], "steps": steps}}
    refused = {
        "type": "object",
        "properties": {
            "schema": {"const": SUGGESTION_SCHEMA_ID},
            "status": {"const": "refused"},
            "refusal_reason": {"type": "string", "maxLength": MAX_REFUSAL_REASON_CHARS},
        },
        "required": ["schema", "status", "refusal_reason"],
        "additionalProperties": False,
    }
    return {"oneOf": [schema, refused]}


def previous_transport(request: AssistRequest, transport: Transport) -> Transport:
    def send(
        path: str, body: bytes | None, token: AiCancelToken, timeout: float, limit: int
    ) -> tuple[int, bytes]:
        if path == "/api/generate" and body is not None:
            payload = json.loads(body)
            payload["prompt"] = previous_prompt(payload["prompt"])
            payload["format"] = previous_schema(request, payload["format"])
            body = json.dumps(payload, ensure_ascii=True).encode("ascii")
        return transport(path, body, token, timeout, limit)

    return send


def _usable(request: AssistRequest, slots: Any, suggestion: Any) -> bool:
    """Whether a slot-variety answer holds at least one value the application would offer. Catches an answer that
    satisfies the shape but is useless, which a grammar without a refusal branch can produce."""

    if slots is None or suggestion is None:
        return True
    return any(
        not row.reason for row in judge_variety(suggestion, slots, is_visible=lambda _text: True)
    )


def run_live(
    cases: Sequence[tuple[AssistRequest, Any]],
    identity: RemoteApproval,
    *,
    transport: Transport = loopback_request,
    progress: Callable[[str], None] = lambda _text: None,
) -> dict[str, Any]:
    arms: dict[str, list[tuple[str, str, str]]] = {"before": [], "after": []}
    usable = Counter()
    seconds = Counter()
    first_attempt_malformed = 0
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        write_remote_approval(root, identity)
        service = _service(root, RemoteAssist(root, transport=transport))
        infrastructure_in_a_row = 0
        for number, (request, slots) in enumerate(cases, 1):
            kind = request.kind.value
            if request.kind is SuggestionKind.MOTION_PHRASE:  # new kind: nothing to compare with
                answer = service.run(request)
                arms.setdefault("motion", []).append((kind, answer.code.value, answer.reason))
                continue
            old = RemoteAssist(root, transport=previous_transport(request, transport))
            started = time.monotonic()
            sent = old.run(identity, request, AiCancelToken(), RunLimits(), Sampling())
            seconds["before"] += time.monotonic() - started
            code, reason, suggestion = sent.code, sent.reason, None
            if code is None:
                checked = validate_output(sent.stdout, request)
                code, reason, suggestion = checked.code, checked.reason, checked.suggestion
            assert code is not None
            arms["before"].append((kind, code.value, reason))
            usable["before"] += code is OutcomeCode.SUGGESTION and _usable(
                request, slots, suggestion
            )

            started = time.monotonic()
            answer = service.run(request)
            seconds["after"] += time.monotonic() - started
            arms["after"].append((kind, answer.code.value, answer.reason))
            first_attempt_malformed += bool(answer.details.get("first_reason"))
            usable["after"] += answer.ok and _usable(request, slots, answer.suggestion)

            infrastructure_in_a_row = (
                0 if answer.code.value in ANSWERED else infrastructure_in_a_row + 1
            )
            if infrastructure_in_a_row >= 3:
                progress(f"stopped at case {number}: the worker is not answering")
                break
            if number % 10 == 0:
                progress(f"{number}/{len(cases)} cases")
    return {
        **{name: summarize(rows) for name, rows in arms.items()},
        "usable_suggestions": dict(usable),
        "after_first_attempt_malformed": first_attempt_malformed,
        "worker_seconds": {name: round(value, 1) for name, value in seconds.items()},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.ai_assist_replay", description=__doc__.split("\n\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("score", "offline"):
        command = commands.add_parser(name)
        command.add_argument("--events", type=Path, help="default: this user's AI Assist event log")
    live = commands.add_parser("live")
    live.add_argument(
        "--packs", type=Path, required=True, help="folder of native PromptPacks (read only)"
    )
    live.add_argument(
        "--motion-image",
        type=Path,
        action="append",
        default=[],
        help="also ask for motion phrases from this picture (repeatable; the picture is sent to the worker)",
    )
    live.add_argument("--seed", type=int, default=1)
    live.add_argument("--limit", type=int, help="at most this many cases of each kind")
    live.add_argument("--out", type=Path, help="also write the counts to this JSON file")
    live.add_argument("--owner-approved", action="store_true", help="send the cases to the worker")
    args = parser.parse_args(argv)

    if args.command != "live":
        events = read_events(args.events or events_path(resolve_ai_root(None)))
        if not events:
            print("No AI Assist events found.", file=sys.stderr)
            return 1
        report = score(events) if args.command == "score" else offline(events)
        print(json.dumps(report, indent=2))
        return 0

    mix = {kind: min(count, args.limit or count) for kind, count in LOGGED_MIX.items()}
    cases = build_cases(args.packs, mix, seed=args.seed) + motion_cases(args.motion_image)
    planned = dict(Counter(request.kind.value for request, _slots in cases))
    print(json.dumps({"cases": len(cases), "by_kind": planned, "arms": ["before", "after"]}))
    if not args.owner_approved:
        print("Plan only; nothing was sent. Add --owner-approved after the owner's OK.")
        return 0
    identity = read_remote_settings(resolve_ai_root(None)).approval
    if identity is None:
        print("No approved remote model is selected.", file=sys.stderr)
        return 2
    report = run_live(cases, identity, progress=lambda text: print(text, file=sys.stderr))
    report["model"] = identity.model
    report["seed"] = args.seed
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
