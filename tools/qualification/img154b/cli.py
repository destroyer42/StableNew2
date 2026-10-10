"""D11 (154B): the default, non-live command line. It cannot start a process, select a model or send a request.

Subcommands (all offline or read-only):

* ``request``        the reconciled payload, its evidence anchors, and optionally a read-only re-verification against a
                     managed Forge source tree.
* ``layout-plan``    the isolated layout, served paths and storage cost for a proposed root (creates nothing).
* ``challenge``      the exact-case binding and challenge digest an owner would review (writes nothing).
* ``dry-run``        the one-case plan: stages, gates, thresholds and what is required before any live step.
* ``passphrase-verifier``  derives the salted verifier of an owner-chosen passphrase (prompts without echo).

The physical path is a different module (``physical``) and is not importable from here.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tools.qualification.img154.evidence import LEDGER_STAGES, redact_value
from tools.qualification.img154.manifest import build_manifest
from tools.qualification.img154.preflight import PreflightPolicy
from tools.qualification.img154b import authorization as au
from tools.qualification.img154b import request as rq
from tools.qualification.img154b import runtime as rt


def _request(args: argparse.Namespace) -> dict[str, Any]:
    plan = build_manifest()
    payload = rq.build_txt2img_payload(plan)
    findings = []
    verified: bool | None = None
    if args.forge_source is not None:
        findings = rq.verify_pinned_semantics(rq.forge_source_reader(args.forge_source))
        verified = not findings
    report = rq.semantics_report(findings, plan)
    return {
        "payload": payload.as_dict(),
        "semantics": report,
        "source_reverified": verified,
        "frozen_intent_values_changed": False,
    }


def _layout_plan(args: argparse.Namespace) -> dict[str, Any]:
    plan = build_manifest()
    layout = rt.plan_runtime_layout(args.qualification_root, plan)
    return {
        "layout": layout.as_dict(),
        "storage": rt.storage_cost(plan),
        "creates_anything": False,
        "isolated_copies": "three separately verified copies; sources are only ever read",
    }


def _challenge(args: argparse.Namespace) -> dict[str, Any]:
    plan = build_manifest()
    payload = rq.build_txt2img_payload(plan)
    from tools.qualification.img154 import probes

    code = au.CodeRevision.from_probe(probes.collect_code_revision())
    return {
        "binding": au.binding(plan, payload, code),
        "challenge": au.authorization_challenge(plan, payload, code),
        "required_statement": au.REQUIRED_STATEMENT,
        "confirmation_phrase_at_run_time": au.confirmation_phrase(plan, payload),
        "code_trusted": code.trusted,
        "writes_authorization": False,
        "note": "The owner records the authorization outside this package; no command here creates it.",
    }


def _passphrase_verifier(args: argparse.Namespace) -> dict[str, Any]:
    """Derive the salted verifier of an owner-chosen passphrase (read without echo; never stored or printed)."""

    first = getpass.getpass("Choose the owner passphrase (not echoed): ")
    second = getpass.getpass("Repeat it: ")
    if first != second or len(first) < au.MIN_PASSPHRASE_CHARS:
        raise SystemExit(
            f"the passphrases differ or are shorter than {au.MIN_PASSPHRASE_CHARS} characters"
        )
    salt = au.new_passphrase_salt()
    return {
        "passphrase_salt": salt,
        "passphrase_iterations": au.PASSPHRASE_ITERATIONS,
        "passphrase_verifier": au.derive_verifier(first, salt),
        "note": "Copy these three fields into the owner's record. The passphrase itself is never written anywhere.",
    }


def _dry_run(args: argparse.Namespace) -> dict[str, Any]:
    plan = build_manifest()
    payload = rq.build_txt2img_payload(plan)
    policy = PreflightPolicy()
    return {
        "mode": "preparation_only",
        "executes_anything": False,
        "attempt_identity": plan.attempt_identity(),
        "manifest_digest": plan.digest(),
        "payload_digest": payload.payload_digest,
        "stages": list(LEDGER_STAGES),
        "no_retry_no_replay": True,
        "policy": policy.as_dict(),
        "requires_before_any_live_step": [
            "separately recorded exact-case owner authorization (acceptance of the DIAG-GPU-130 residual risk included)",
            "the owner's passphrase, typed without echo (its salted verifier is part of the record)",
            "clean, identified code revision matching the authorization",
            "fresh preflight PREPARED_FOR_OWNER_REVIEW at the launch moment with a harness-acquired quiescent baseline",
            "complete served-file proof at the isolated paths",
            "all pinned request-semantics anchors verified against the managed source",
            "no competing or foreign runtime; the loopback qualification port free",
            "an interactive terminal, the environment opt-in and the typed exact-case phrase",
        ],
        "result_classes": [
            "PREFLIGHT_REFUSED",
            "LOADER_FAILED",
            "RESOURCE_ABORT_REQUESTED",
            "AMBIGUOUS_DISPATCH",
            "SYSTEM_OR_GPU_FAULT",
            "INSTRUMENTATION_GAP",
            "OUTPUT_VALIDATION_FAIL",
            "TECHNICAL_PASS_CONSTRAINED",
        ],
        "note": "A refused or inconclusive live preflight is an acceptable outcome.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="img154b",
        description="PR-IMG-MODELS-154B preparation commands (offline or read-only).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    request = sub.add_parser("request", help="the reconciled payload and its evidence")
    request.add_argument(
        "--forge-source",
        type=Path,
        default=None,
        help="managed Forge source dir to re-verify (read-only)",
    )
    plan = sub.add_parser(
        "layout-plan", help="the isolated layout for a proposed root; creates nothing"
    )
    plan.add_argument("--qualification-root", type=Path, required=True)
    sub.add_parser("challenge", help="the exact-case binding an owner would review; writes nothing")
    sub.add_parser("dry-run", help="the one-case plan and its gates")
    sub.add_parser(
        "passphrase-verifier",
        help="derive the salted verifier of an owner passphrase (prompts without echo)",
    )
    for item in sub.choices.values():
        item.add_argument(
            "--out", type=Path, default=None, help="write the redacted JSON report here"
        )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    handlers = {
        "request": _request,
        "layout-plan": _layout_plan,
        "challenge": _challenge,
        "dry-run": _dry_run,
        "passphrase-verifier": _passphrase_verifier,
    }
    result = redact_value(handlers[args.command](args))
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    sys.stdout.write(text + "\n")
    if args.command == "request" and result.get("source_reverified") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
