"""Operator terminal tool for Offline AI Assist: local files only, never a download, never an execution.

    python -m tools.ai_assist_admin describe-runtime <archive.zip> --build-id ID --upstream-repository URL \\
        --upstream-tag TAG --license-spdx SPDX --executable llama-cli.exe
    python -m tools.ai_assist_admin import-runtime <archive.zip> --build-id ID
    python -m tools.ai_assist_admin import-model <model.gguf> --model-id ID
    python -m tools.ai_assist_admin record-attestation --statement "outbound firewall rule name"
    python -m tools.ai_assist_admin activate --build-id ID --model-id ID
    python -m tools.ai_assist_admin status

``describe-runtime`` reads the archive and prints a manifest build entry for a reviewed pull request; it extracts and runs
nothing. The import commands verify against the committed manifests (``config/managed_ai_runtime.json`` and
``config/ai_model_registry.json``) and refuse anything they do not pin. AI Assist Preview is enabled only in the application
(Prompt tab, "AI Preview..."), by an explicit operator confirmation, never from here.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from src.ai_assist.attestation import record_attestation
from src.ai_assist.manifests import (
    ImportRefused,
    describe_runtime_archive,
    import_model,
    import_runtime,
    load_model_registry,
    load_runtime_manifest,
    record_active,
    verify_installation,
)
from src.ai_assist.paths import resolve_ai_root
from src.ai_assist.status import (
    MODEL_REGISTRY_PATH,
    RUNTIME_MANIFEST_PATH,
    preview_state,
    read_status,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="AI directory (default: STABLENEW_AI_DIR or per-user)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    describe = sub.add_parser(
        "describe-runtime", help="print a manifest build entry computed from a local archive"
    )
    describe.add_argument("archive", type=Path)
    describe.add_argument("--build-id", required=True)
    describe.add_argument("--upstream-repository", required=True)
    describe.add_argument("--upstream-tag", required=True)
    describe.add_argument("--license-spdx", required=True)
    describe.add_argument(
        "--executable", required=True, help="relative path of the CLI binary inside the archive"
    )
    describe.add_argument("--asset-name", default=None)
    runtime = sub.add_parser("import-runtime", help="verify and unpack a pinned runtime archive")
    runtime.add_argument("archive", type=Path)
    runtime.add_argument("--build-id", required=True)
    model = sub.add_parser("import-model", help="verify and copy a registered model file")
    model.add_argument("file", type=Path)
    model.add_argument("--model-id", required=True)
    attest = sub.add_parser(
        "record-attestation", help="record that an outbound firewall restriction exists"
    )
    attest.add_argument("--statement", required=True)
    activate = sub.add_parser(
        "activate", help="point the installation at an imported runtime and model"
    )
    activate.add_argument("--build-id", required=True)
    activate.add_argument("--model-id", required=True)
    sub.add_parser(
        "status", help="print the installation and Preview status (no hashing, no execution)"
    )
    return parser


def _emit(document: object) -> None:
    print(json.dumps(document, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = resolve_ai_root(args.root)
    try:
        if args.command == "describe-runtime":
            _emit(
                describe_runtime_archive(
                    args.archive,
                    build_id=args.build_id,
                    upstream_repository=args.upstream_repository,
                    upstream_tag=args.upstream_tag,
                    license_spdx=args.license_spdx,
                    executable=args.executable,
                    asset_name=args.asset_name,
                )
            )
            return 0
        runtime = load_runtime_manifest(RUNTIME_MANIFEST_PATH)
        registry = load_model_registry(MODEL_REGISTRY_PATH)
        if args.command == "import-runtime":
            build = runtime.find(args.build_id)
            if build is None:
                print(
                    "refused: build_not_pinned (pin it in config/managed_ai_runtime.json by reviewed change)"
                )
                return 2
            print(f"imported runtime to {import_runtime(args.archive, build, root)}")
        elif args.command == "import-model":
            entry = next((e for e in registry.entries if e.model_id == args.model_id), None)
            if entry is None:
                print("refused: model_not_registered")
                return 2
            print(f"imported model to {import_model(args.file, entry, root)}")
        elif args.command == "record-attestation":
            print(f"recorded attestation at {record_attestation(root, args.statement)}")
            print("This is the operator's statement; StableNew does not verify the firewall.")
        elif args.command == "activate":
            build = runtime.find(args.build_id)
            entry = next((e for e in registry.entries if e.model_id == args.model_id), None)
            if build is None or entry is None:
                print("refused: unknown_build_or_model")
                return 2
            record_active(root, build, entry)
            verification = verify_installation(root, runtime, registry, allow_candidate=True)
            if not verification.ok:
                print(f"activated, but verification failed: {verification.reason}")
                return 1
            print(
                "activated; any AI Assist Preview enablement was voided (re-enable it in the application)."
            )
        else:
            status = read_status(root, runtime, registry)
            view = preview_state(status)
            _emit(
                {
                    "state": status.state,
                    "summary": status.summary,
                    "trust": view.trust,
                    "missing": view.missing,
                    "can_enable_preview": view.can_enable,
                    "egress": status.egress,
                    "blockers": list(status.blockers),
                    "actions": list(status.actions),
                }
            )
    except ImportRefused as exc:
        print(f"refused: {exc}")
        return 2
    except (OSError, ValueError) as exc:
        print(f"failed: {type(exc).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
