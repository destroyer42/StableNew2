"""N11 / RG-100 E1: prompts and secrets never reach the JSONL log, a diagnostics bundle or the gateway sync logs."""

from __future__ import annotations

import ast
import json
import logging
import re
import zipfile
from pathlib import Path

import pytest

from src.config import app_config
from src.utils.diagnostic_redaction import REDACTED, redact, redact_text
from src.utils.diagnostics_bundle_v2 import build_crash_bundle
from src.utils.logger import InMemoryLogHandler

SRC = Path(__file__).resolve().parents[2] / "src"
PROMPT = "zebra-quokka-marker in a moonlit field"
NEGATIVE = "blurry-walrus-marker, lowres"
SECRET = "s3cr3t-token-value-9f8e7d"


# -- redaction primitives -------------------------------------------------------------------------------------------


def test_prompt_and_secret_keys_are_redacted_at_any_depth():
    value = {
        "prompt": PROMPT,
        "negative_prompt": NEGATIVE,
        "prompt_pack_id": "pack-1",
        "prompt_source": "pack",
        "txt2img": {"prompt": PROMPT, "steps": 20, "global_negative_prompt": NEGATIVE},
        "settings": [
            {"api_key": SECRET},
            {"sync_secret": SECRET},
            {"Authorization": f"Bearer {SECRET}"},
        ],
        "positive_preview": PROMPT,
        "original_prompt": PROMPT,
        "token_count": 75,
    }

    redacted = redact(value)

    text = json.dumps(redacted)
    assert PROMPT not in text and NEGATIVE not in text and SECRET not in text
    assert redacted["prompt_pack_id"] == "pack-1" and redacted["prompt_source"] == "pack"
    assert redacted["txt2img"]["steps"] == 20 and redacted["token_count"] == 75
    assert redacted["prompt"] == REDACTED


@pytest.mark.parametrize(
    "message",
    [
        f"ORIGINAL POSITIVE: {PROMPT}",
        f"OPTIMIZED NEGATIVE: {NEGATIVE}",
        f"[executor/txt2img] final negative prompt='{NEGATIVE}'",
        f"[executor/img2img] final negative prompt (with global + aesthetic): '{NEGATIVE}'",
        f"[ok] Applied global positive terms (txt2img stage) - Enhanced: '{PROMPT}'",
        f"request failed api_key={SECRET} at host",
        f"headers: Authorization: Bearer {SECRET}",
    ],
)
def test_prompt_and_secret_text_in_messages_is_redacted(message):
    out = redact_text(message)
    assert PROMPT not in out and NEGATIVE not in out and SECRET not in out
    assert REDACTED in out


def test_ordinary_messages_are_unchanged():
    for message in (
        "Job status change",
        "PROMPT OPTIMIZER RESULT | pipeline=txt2img | positive_len=10->12",
    ):
        assert redact_text(message) == message


# -- the diagnostics bundle -----------------------------------------------------------------------------------------


class _JobService:
    def get_diagnostics_snapshot(self):
        return {
            "queue": {"current_job_id": "job-1"},
            "jobs": [
                {
                    "job_id": "job-1",
                    "status": "running",
                    "prompt": PROMPT,
                    "result_summary": {
                        "negative_prompt": NEGATIVE,
                        "replay_descriptor": {
                            "positive_prompt": PROMPT,
                            "curation": {"prompt": PROMPT},
                        },
                    },
                }
            ],
        }


def test_bundle_contains_no_prompt_or_secret(tmp_path, monkeypatch):
    log_path = tmp_path / "logs" / "stablenew.log.jsonl"
    log_path.parent.mkdir()
    historical = [
        {"message": f"ORIGINAL POSITIVE: {PROMPT}"},
        {"message": "Saving", "prompt": PROMPT, "negative_prompt": NEGATIVE},
        {"message": "sync", "sync_secret": SECRET},
    ]
    log_path.write_text(
        "\n".join(json.dumps(row) for row in historical) + "\nTraceback (not json)\n", "utf-8"
    )
    log_path.with_name(log_path.name + ".1").write_text(
        json.dumps({"message": f"Enhanced: '{PROMPT}'"}) + "\n"
    )
    monkeypatch.setattr(
        app_config, "_jsonl_log_config", app_config.JsonlFileLogConfig(enabled=True, path=log_path)
    )

    handler = InMemoryLogHandler(max_entries=10, level=logging.DEBUG)
    log = logging.getLogger("tests.n11.bundle")
    log.setLevel(logging.DEBUG)
    log.addHandler(handler)
    try:
        log.debug("ORIGINAL POSITIVE: %s", PROMPT)
        log.info(
            "job", extra={"json_payload": {"message": "job", "prompt": PROMPT, "api_key": SECRET}}
        )
        bundle = build_crash_bundle(
            reason="n11",
            log_handler=handler,
            job_service=_JobService(),
            output_dir=tmp_path / "bundles",
            context={"prompt": PROMPT, "token": SECRET},
            webui_tail={"stdout_tail": f"ORIGINAL POSITIVE: {PROMPT}", "stderr_tail": ""},
            image_roots=[tmp_path / "no-images"],
        )
    finally:
        log.removeHandler(handler)

    assert bundle is not None
    with zipfile.ZipFile(bundle) as zf:
        names = zf.namelist()
        contents = {name: zf.read(name).decode("utf-8", "replace") for name in names}
    assert "logs/stablenew.log.jsonl" in names and "logs/stablenew.log.jsonl.1" in names
    for name, text in contents.items():
        for forbidden in ("zebra-quokka-marker", "blurry-walrus-marker", SECRET):
            assert forbidden not in text, f"{forbidden!r} leaked into {name}"
    copied = contents["logs/stablenew.log.jsonl"].splitlines()
    assert (
        json.loads(copied[1])["message"] == "Saving" and json.loads(copied[1])["prompt"] == REDACTED
    )
    assert copied[3] == "Traceback (not json)"


# -- the JSONL log never receives prompt text ----------------------------------------------------------------------

_LOG_LEVELS = {"info", "warning", "error", "exception", "critical"}
_TEXT_NAME = re.compile(r"prompt|positive|negative|(^|_)neg($|_)|(^|_)pos($|_)", re.I)
_NOT_TEXT = re.compile(
    r"prompt_id|pack|count|chunk|len|changed|applied|enabled|optimizer|mode|source|policy|row|index|slot",
    re.I,
)


def _value_names(node: ast.AST):
    """Names whose *value* an argument passes on (``len(prompt)`` passes a number, not the prompt)."""

    if isinstance(node, ast.Call):
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name in {
            "len",
            "bool",
            "type",
            "id",
            "hash",
            "isinstance",
            "sorted",
            "list",
        } or name.endswith("count"):
            return
        for arg in [*node.args, *(kw.value for kw in node.keywords)]:
            yield from _value_names(arg)
        if isinstance(func, ast.Attribute):
            yield from _value_names(func.value)
    elif isinstance(node, ast.Name):
        yield node.id
    elif isinstance(node, ast.Attribute):
        yield node.attr
    elif isinstance(node, ast.Subscript):
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            yield key.value
        else:
            yield from _value_names(node.value)
    elif isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                yield from _value_names(part.value)
    else:
        for child in ast.iter_child_nodes(node):
            yield from _value_names(child)


def test_no_info_or_higher_log_call_carries_prompt_text():
    offenders = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in _LOG_LEVELS:
                continue
            receiver = node.func.value
            receiver_name = (
                receiver.id if isinstance(receiver, ast.Name) else getattr(receiver, "attr", "")
            )
            if "log" not in receiver_name.lower():
                continue
            arguments = list(node.args[1:])
            if node.args and isinstance(node.args[0], ast.JoinedStr):
                arguments.insert(0, node.args[0])
            names = {n for arg in arguments for n in _value_names(arg)}
            carried = sorted(n for n in names if _TEXT_NAME.search(n) and not _NOT_TEXT.search(n))
            if carried:
                offenders.append(f"{path.relative_to(SRC.parent)}:{node.lineno} {carried}")
    assert offenders == [], "prompt text logged at INFO or above (use DEBUG):\n" + "\n".join(
        offenders
    )


def test_a_bundle_copies_only_the_newest_part_of_an_oversized_log(tmp_path):
    from src.utils.diagnostics_bundle_v2 import _redacted_log_tail

    log_path = tmp_path / "stablenew.log.jsonl"
    rows = [json.dumps({"message": f"row {i:05d}", "prompt": PROMPT}) for i in range(2000)]
    log_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    text = _redacted_log_tail(log_path, limit=10_000)

    lines = text.splitlines()
    assert json.loads(lines[0])["event"] == "bundle_log_cut"
    assert json.loads(lines[-1])["message"] == "row 01999"
    assert all(json.loads(line) for line in lines)  # no partial first line
    assert PROMPT not in text and len(text) < 20_000
