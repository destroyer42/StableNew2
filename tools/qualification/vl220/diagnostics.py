"""Diagnostic mode for the visual harness (PR-AI-VL-222, decision D23): raw answers and bounded runtime output, built-in
synthetic sets only.

Until now the driver kept no answer text and no runtime output, so a near-zero score could not be explained. This module lets
the driver *capture* both, under one narrow rule: the case set must be exactly one of the built-in synthetic sets
(``synthetic.build_synthetic_set``): same case document, same label document, labeler ``synthetic_by_construction``, every
asset digest the pinned one. A scene drawn by this repository from a fixed table carries nothing private, so its answer and the
runtime's chatter about it are safe to keep. For any other case set :class:`DiagnosticCapture` cannot be constructed
(:class:`DiagnosticsRefused`), the driver then has nothing to record into, and the earlier rule stands: no answer text and no
runtime output reach any file.

The capture is written next to the evidence file, outside Git (:func:`write_diagnostics` refuses an AI Assist root or a Git
working tree), never into the repository. It is a second, separate document: the evidence file stays free of answer text.

The module also defines the one extra request kind of the diagnostic, the *control*: an unconstrained free-text "describe this
image" for two synthetic scenes, with no JSON schema, so perception can be told apart from structured-output behavior. A control
is not a case and is never scored.
"""

from __future__ import annotations

import functools
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.qualification.vl220 import contract, staging, synthetic

DIAGNOSTICS_SCHEMA = "stablenew.vl220.diagnostics/1"

#: Per request: the answer, the first and last bytes of the runtime's stderr and a few selected lines. The runtime's
#: informative lines (template, image tokens, grammar) are printed while it loads, so the head matters as much as the tail.
ANSWER_BYTES = 16 * 1024
STDERR_HEAD_BYTES = 12 * 1024
STDERR_TAIL_BYTES = 8 * 1024
MAX_FACT_LINES = 48
FACT_LINE_CHARS = 300
MAX_REQUESTS = 64

_FACT_PATTERN = re.compile(
    r"template|image|token|mtmd|clip|grammar|sampler|encod|decod|warn|error|failed|n_ctx|embd|vision|slice|projector|bos|eos",
    re.IGNORECASE,
)

REFUSED_NOT_BUILTIN = "diagnostics_only_for_builtin_synthetic_sets"
REFUSED_LABELER = "diagnostics_need_synthetic_by_construction_labels"
REFUSED_PATH = "diagnostics_path_refused"
REFUSED_EXISTS = "diagnostics_file_exists"

REQUEST_CASE = "case"
REQUEST_CONTROL = "control"


class DiagnosticsRefused(ValueError):
    """Raw answers and runtime output may not be captured for this case set (or written there). ``code`` is stable."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@functools.cache
def builtin_digests() -> dict[str, tuple[str, str]]:
    """Set id to ``(case document digest, label document digest)`` of every built-in synthetic set, computed from the tables."""

    out: dict[str, tuple[str, str]] = {}
    for set_id in synthetic.BUILTIN_SCALES:
        _, case_doc, label_doc = synthetic.build_synthetic_set(set_id)
        out[set_id] = (contract.digest(case_doc), contract.digest(label_doc))
    return out


def refusal_for(case_doc: Any, label_doc: Any) -> str:
    """``""`` when ``(case_doc, label_doc)`` is exactly a built-in synthetic set, otherwise the stable refusal code.

    The case document digest covers every asset's pinned SHA-256, size and origin, so matching it is matching the asset digests;
    the driver separately proves each image on disk against those pins before it runs it."""

    try:
        if (
            not isinstance(label_doc, dict)
            or label_doc.get("labeler") != contract.LABELER_SYNTHETIC
        ):
            return REFUSED_LABELER
        if not isinstance(case_doc, dict):
            return REFUSED_NOT_BUILTIN
        expected = builtin_digests().get(str(case_doc.get("set_id")))
        if expected is None:
            return REFUSED_NOT_BUILTIN
        if (contract.digest(case_doc), contract.digest(label_doc)) != expected:
            return REFUSED_NOT_BUILTIN
    except (TypeError, ValueError):
        return REFUSED_NOT_BUILTIN
    return ""


# ------------------------------------------------------------------------------------------------------------- controls


@dataclass(frozen=True, slots=True)
class ControlRequest:
    """One unscored free-text request about a built-in synthetic image. It has no schema, no kind and no label."""

    request_id: str
    asset_id: str


def control_requests(set_id: str) -> tuple[ControlRequest, ...]:
    """The two control requests of a built-in set: a free-text description of ``des-1`` and ``des-2``."""

    if set_id not in synthetic.BUILTIN_SCALES:
        raise KeyError(set_id)
    return (
        ControlRequest("control-describe-1", "des-1"),
        ControlRequest("control-describe-2", "des-2"),
    )


# ------------------------------------------------------------------------------------------------------------- capture


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def stderr_facts(text: str) -> list[str]:
    """Up to :data:`MAX_FACT_LINES` informative lines (template, image, token, grammar, warning, error), each bounded."""

    facts: list[str] = []
    for line in text.splitlines():
        if _FACT_PATTERN.search(line):
            facts.append(line.strip()[:FACT_LINE_CHARS])
            if len(facts) >= MAX_FACT_LINES:
                break
    return facts


class DiagnosticCapture:
    """Collects, in memory, the answer and bounded runtime output of each request of one built-in synthetic set.

    Constructing it is the permission check: it raises :class:`DiagnosticsRefused` unless the case and label documents are
    exactly a built-in synthetic set. The driver records into it only if it was given one."""

    def __init__(self, case_doc: Any, label_doc: Any) -> None:
        code = refusal_for(case_doc, label_doc)
        if code:
            raise DiagnosticsRefused(code)
        self._set_id = str(case_doc["set_id"])
        self._case_digest = contract.digest(case_doc)
        self._entries: list[dict[str, Any]] = []

    @property
    def set_id(self) -> str:
        return self._set_id

    def record(
        self,
        *,
        request_id: str,
        request_kind: str,
        kind: str,
        status: str,
        reason: str,
        exit_code: int | None,
        stdout: bytes,
        stderr: bytes,
    ) -> None:
        if len(self._entries) >= MAX_REQUESTS:
            return
        err = _decode(stderr)
        head = _decode(stderr[:STDERR_HEAD_BYTES])
        tail = _decode(stderr[-STDERR_TAIL_BYTES:]) if len(stderr) > STDERR_HEAD_BYTES else ""
        self._entries.append(
            {
                "request_id": request_id,
                "request_kind": request_kind,
                "kind": kind,
                "status": status,
                "reason": reason,
                "exit_code": exit_code,
                "answer_text": _decode(stdout[:ANSWER_BYTES]),
                "answer_bytes": len(stdout),
                "stderr_bytes": len(stderr),
                "stderr_head": head,
                "stderr_tail": tail,
                "stderr_facts": stderr_facts(err),
            }
        )

    def document(
        self, *, plan_sha256: str, evidence_file: str, turn_format: str = "legacy"
    ) -> dict[str, Any]:
        return {
            "schema": DIAGNOSTICS_SCHEMA,
            "plan_sha256": plan_sha256,
            "turn_format": turn_format,
            "set_id": self._set_id,
            "case_set_sha256": self._case_digest,
            "labeler": contract.LABELER_SYNTHETIC,
            "evidence_file": evidence_file,
            "requests": list(self._entries),
        }


def write_diagnostics(path: Path, document: dict[str, Any]) -> None:
    """Write the capture next to the evidence, refusing any location that is not outside Git and the AI Assist root, and
    never overwriting."""

    target = Path(path)
    refused = staging.root_refusal(target.parent)
    if refused:
        raise DiagnosticsRefused(REFUSED_PATH, refused)
    if not target.parent.is_dir():
        raise DiagnosticsRefused(REFUSED_PATH, "directory_missing")
    try:
        with target.open("x", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise DiagnosticsRefused(REFUSED_EXISTS) from exc


__all__ = [
    "ANSWER_BYTES",
    "DIAGNOSTICS_SCHEMA",
    "REFUSED_EXISTS",
    "REFUSED_LABELER",
    "REFUSED_NOT_BUILTIN",
    "REFUSED_PATH",
    "REQUEST_CASE",
    "REQUEST_CONTROL",
    "STDERR_HEAD_BYTES",
    "STDERR_TAIL_BYTES",
    "ControlRequest",
    "DiagnosticCapture",
    "DiagnosticsRefused",
    "builtin_digests",
    "control_requests",
    "refusal_for",
    "stderr_facts",
    "write_diagnostics",
]
