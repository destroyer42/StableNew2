"""Operator terminal tool for AI Assist settings and local installation. Performs no network calls or inference.

    python -m tools.ai_assist_admin describe-runtime <archive.zip> --build-id ID --upstream-repository URL \\
        --upstream-tag TAG --license-spdx SPDX --executable llama-completion.exe
    python -m tools.ai_assist_admin import-runtime <archive.zip> --build-id ID
    python -m tools.ai_assist_admin import-model <model.gguf> --model-id ID
    python -m tools.ai_assist_admin record-attestation --statement "outbound firewall rule name" --build-id ID [--build-id ID]
    python -m tools.ai_assist_admin activate --build-id ID --model-id ID   # the build must be listed for the model
    python -m tools.ai_assist_admin status

``describe-runtime`` reads the archive and prints a manifest build entry for a reviewed pull request; it extracts and runs
nothing. The import commands verify against the committed manifests (``config/managed_ai_runtime.json`` and
``config/ai_model_registry.json``) and refuse anything they do not pin. Local Preview is enabled from the Prompt tab. Remote Preview has a separate, explicit identity approval.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from src.ai_assist.activation import ActivationRefused, activate
from src.ai_assist.attestation import read_covers, record_attestation
from src.ai_assist.manifests import (
    ImportRefused,
    describe_runtime_archive,
    import_model,
    import_runtime,
    load_model_registry,
    load_runtime_manifest,
)
from src.ai_assist.paths import resolve_ai_root
from src.ai_assist.remote_preview import (
    DEFAULT_MODEL,
    ENDPOINT,
    MODELS,
    RemoteApproval,
    disable_remote_preview,
    enable_remote_preview,
    revoke_remote_approval,
    write_remote_approval,
)
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
    attest.add_argument(
        "--build-id",
        action="append",
        required=True,
        dest="build_ids",
        help="pinned runtime build the firewall rule covers (repeat for several); its pinned executable name is recorded",
    )
    activate = sub.add_parser(
        "activate", help="point the installation at an imported runtime and model"
    )
    activate.add_argument("--build-id", required=True)
    activate.add_argument("--model-id", required=True)
    sub.add_parser(
        "status", help="print the installation and Preview status (no hashing, no execution)"
    )
    remote = sub.add_parser(
        "approve-remote-preview", help="approve the exact SSH-forwarded Ollama identity"
    )
    remote.add_argument("--endpoint", required=True, choices=(ENDPOINT,))
    remote.add_argument("--model", choices=MODELS, default=DEFAULT_MODEL)
    remote.add_argument(
        "--digest",
        required=True,
        help="64 lowercase hexadecimal digits from trusted Ollama metadata",
    )
    remote.add_argument("--version", required=True)
    remote.add_argument(
        "--accept-ssh-transfer",
        action="store_true",
        required=True,
        help="confirm prompts may be sent over the operator-managed SSH tunnel to this unqualified model",
    )
    sub.add_parser(
        "disable-remote-preview",
        help="select local-only mode while keeping valid remote approvals",
    )
    sub.add_parser("enable-remote-preview", help="enable the existing remote approvals")
    revoke = sub.add_parser(
        "revoke-remote-preview", help="revoke one model's Remote Preview approval"
    )
    revoke.add_argument("--model", required=True, choices=MODELS)
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
        if args.command == "approve-remote-preview":
            write_remote_approval(
                root, RemoteApproval(args.endpoint, args.model, args.digest, args.version)
            )
            print(
                "Remote Preview approved for the exact endpoint, model digest and runtime version."
            )
            return 0
        if args.command == "disable-remote-preview":
            disable_remote_preview(root)
            print("Remote Preview disabled. AI Assist uses the local provider.")
            return 0
        if args.command == "enable-remote-preview":
            enable_remote_preview(root)
            print("Remote Preview enabled. Select an approved model in AI Preview if needed.")
            return 0
        if args.command == "revoke-remote-preview":
            revoke_remote_approval(root, args.model)
            print("Remote Preview approval revoked for the named model.")
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
            covers: list[tuple[str, str]] = []
            for build_id in args.build_ids:
                pinned = runtime.find(build_id)
                if pinned is None:
                    print(f"refused: build_not_pinned ({build_id})")
                    return 2
                covers.append((build_id, Path(pinned.executable).name))
            written = record_attestation(root, args.statement, covers)
            print(f"recorded attestation at {written}")
            for build_id, executable in covers:
                print(f"  covers {build_id}: {executable}")
            print("This is the operator's statement; StableNew does not verify the firewall.")
        elif args.command == "activate":
            # The same function the in-app model selector uses: one activation authority (owner decision D20).
            try:
                activation = activate(
                    root, runtime, registry, build_id=args.build_id, model_id=args.model_id
                )
            except ActivationRefused as exc:
                print(f"refused: {exc.code}")
                return 2
            build = activation.build
            if not activation.verification.ok:
                print(f"activated, but verification failed: {activation.verification.reason}")
                return 1
            print(
                "activated. AI Assist Preview is enabled per model and runtime build: an earlier enablement of this exact "
                "pair still applies, any other pair must be enabled in the application."
            )
            print(
                "The firewall attestation must cover this build and its executable "
                f"({build.build_id}: {Path(build.executable).name}); record-attestation lists what it covers."
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
                    "attestation_covers": [
                        {"build_id": build_id, "executable": executable}
                        for build_id, executable in read_covers(root)
                    ],
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
