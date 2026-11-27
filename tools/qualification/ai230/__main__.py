"""``python -m tools.qualification.ai230``: operator-run measurement of slot suggestions against a LOOPBACK Ollama model.

Commands:

* ``cases``  - list the case ids and kinds (no model, no network).
* ``run``    - send every case to the model named by ``--model`` at ``--base-url`` (loopback only), score each answer with the
  production validator and judges and write counts and codes to ``--out``.

``run`` is never part of CI and never runs on its own: it needs the operator to start the model and to name it. It sends
exactly what AI Assist's Remote Preview sends (the same prompt and the same JSON schema), refuses any host that is not a
loopback address, and writes no goal, sentence, slot name or suggested value. Nothing here is qualification evidence: it is a
repeatable way to compare models and prompt changes on the same cases.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from src.ai_assist.argv import RunLimits, Sampling
from src.ai_assist.contracts import AssistRequest
from src.ai_assist.framing import build_json_schema, render_prompt
from tools.qualification.ai230.slot_cases import CASES, run_cases, summarize

TIMEOUT_SECONDS = 300
MAX_RESPONSE_BYTES = 1_000_000


class Refused(ValueError):
    """Fixed operator-facing copy."""


def loopback_url(base_url: str) -> str:
    """``base_url`` if its host is a loopback address, else :class:`Refused`. No name resolution is performed."""

    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    if parsed.scheme != "http":
        raise Refused("Only an http loopback address is allowed.")
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise Refused("Only a loopback address (localhost, 127.0.0.1 or ::1) is allowed.")
    return base_url.rstrip("/")


def ollama_generate(base_url: str, model: str) -> Callable[[AssistRequest], str]:
    """A ``request -> raw text`` callable that posts the production body to a loopback Ollama ``/api/generate``."""

    root = loopback_url(base_url)
    limits, sampling = RunLimits(), Sampling()

    def generate(request: AssistRequest) -> str:
        body = json.dumps(
            {
                "model": model,
                "prompt": render_prompt(request),
                "format": build_json_schema(request),
                "stream": False,
                "think": False,
                "options": {
                    "num_ctx": limits.context_tokens,
                    "num_predict": limits.max_new_tokens,
                    "temperature": sampling.temperature,
                    "top_p": sampling.top_p,
                    "top_k": sampling.top_k,
                    "presence_penalty": sampling.presence_penalty,
                    "seed": sampling.seed,
                },
            },
            ensure_ascii=True,
        ).encode("ascii")
        http = urllib.request.Request(  # noqa: S310 - loopback http only, checked above
            f"{root}/api/generate", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(http, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise Refused("The response was too large.")
        document = json.loads(raw)
        text = document.get("response") if isinstance(document, dict) else None
        if not isinstance(text, str) or document.get("done") is not True:
            raise Refused("The model did not finish an answer.")
        return text

    return generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.qualification.ai230", description=__doc__
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("cases", help="list the cases")
    run = sub.add_parser("run", help="run the cases against a loopback Ollama model")
    run.add_argument("--model", required=True, help="the Ollama model reference to measure")
    run.add_argument("--base-url", default="http://127.0.0.1:11434")
    run.add_argument(
        "--out", type=Path, required=True, help="where to write the counts-and-codes result"
    )
    args = parser.parse_args(argv)
    if args.command == "cases":
        for case in CASES:
            sys.stdout.write(f"{case.case_id}\t{case.kind}\n")
        return 0
    try:
        generate = ollama_generate(args.base_url, args.model)
    except Refused as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    results = run_cases(generate)
    document = {
        **summarize(results),
        "model": args.model,
        "results": [
            {
                "case": r.case_id,
                "kind": r.kind,
                "code": r.code,
                "reason": r.reason,
                "returned": r.returned,
                "offered": r.offered,
                "rejected": r.rejected,
                "reject_reasons": dict(r.reject_reasons),
                "seconds": r.seconds,
            }
            for r in results
        ],
    }
    args.out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(summarize(results), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
