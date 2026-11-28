"""Fill the staging gateway with fixtures, make a pairing code for it, or wipe it (PHONE-CORE PS-1).

    python -m tools.review_gateway_stage seed
    python -m tools.review_gateway_stage pair [--admin]
    python -m tools.review_gateway_stage reset [--ct 121]

It talks to staging only: ``--target production`` is refused, and so are staging settings that share production's
address, certificate or secret. The fixtures are generated here (the shapes of the PHONE-CORE browser tests' seeder):
small one-colour images in several review sections, a named batch, a rework beside its original, a desk input, a video
placeholder that does not play, a rating set, a choice catalog and a PC status. Nothing comes from the PC's library.

``reset`` deletes nothing itself: the sync API cannot wipe a gateway. It prints one line for the Proxmox host's shell,
which does nothing unless that container's gateway is labelled as an environment other than production.

Exit codes: 0 done; 1 refused or failed; 2 usage or no staging settings; 4 the gateway is unreachable.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
import zlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from src.app import review_gateway_protocol as protocol
from src.app.review_gateway_client import (
    GatewayClient,
    GatewayError,
    GatewayUnauthorized,
    GatewayUnavailable,
)
from tools import review_gateway_targets as targets

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_UNREACHABLE = 4
STAGING_CT = 121

_COLOURS = (
    (200, 60, 60),
    (60, 160, 70),
    (60, 90, 200),
    (200, 170, 40),
    (150, 60, 170),
    (40, 170, 170),
)
_PACK_RUN = "20260101_100000_stage_pack"
_BATCH = {"batch_id": "5a9e0000-0000-4000-8000-000000000001", "name": "Staging batch"}


def png(width: int, height: int, colour: tuple[int, int, int]) -> bytes:
    """A decodable one-colour PNG with a darker band, so items differ visibly."""

    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter: none
        shade = 0.6 if height // 3 <= y < 2 * height // 3 else 1.0
        rows += bytes(int(part * shade) for part in colour) * width

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows)))
        + chunk(b"IEND", b"")
    )


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _media(data: bytes, content_type: str) -> dict[str, Any]:
    return {"sha256": _digest(data), "bytes": len(data), "content_type": content_type}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def image_item(
    library_id: str, *, run_id: str, source: str, colour: int, **fields: Any
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """One image item's manifest and its bytes by digest. The same name gives the same ``(library_id, sha256)``."""

    tint = _COLOURS[colour % len(_COLOURS)]
    blobs = {
        "thumb_320": png(32, 48, tint),
        "preview_1080": png(120, 180, tint),
        # Bytes after IEND keep it decodable and give each item its own digest.
        "original": png(240, 360, tint) + library_id.encode(),
    }
    manifest = {
        "schema_version": protocol.SCHEMA_VERSION,
        "type": "item_manifest",
        "item": {"library_id": library_id, "sha256": _digest(blobs["original"])},
        "kind": "image",
        "run_id": run_id,
        "created_at": _now(),
        "media": {name: _media(data, "image/png") for name, data in blobs.items()},
        "display": {
            "model": "staging-fixture",
            "prompt_excerpt": "a <b>lighthouse</b>",
            "seed": 42,
        },
        "source": source,
        **fields,
    }
    return manifest, {_digest(data): data for data in blobs.values()}


def video_item(library_id: str) -> tuple[dict[str, Any], dict[str, bytes]]:
    """A video item whose video bytes are placeholders: the page's layout and actions show, playback does not."""

    blobs = {
        "thumb_320": png(32, 48, _COLOURS[2]),
        "mobile_video": b"staging-mobile-clip" * 16,
        "original": b"staging-original-clip" * 16,
    }
    types = {"thumb_320": "image/png", "mobile_video": "video/mp4", "original": "video/mp4"}
    manifest = {
        "schema_version": protocol.SCHEMA_VERSION,
        "type": "item_manifest",
        "item": {"library_id": library_id, "sha256": _digest(blobs["original"])},
        "kind": "video",
        "duration_s": 5.0,
        "run_id": "20260101_130000_stage_clip",
        "created_at": _now(),
        "media": {name: _media(data, types[name]) for name, data in blobs.items()},
        "display": {"model": "wan-fixture", "prompt_excerpt": "a lighthouse", "seed": 7},
        "source": "video",
    }
    return manifest, {_digest(data): data for data in blobs.values()}


def fixture_items(features: frozenset[str]) -> list[tuple[dict[str, Any], dict[str, bytes]]]:
    """The fixture set. Optional manifest parts are sent only to a gateway whose health lists them."""

    items = []
    for number in range(1, 7):
        extra = {"batch": _BATCH} if number <= 4 and "item_batch" in features else {}
        if number == 1 and "item_info" in features:
            extra["info"] = {"model_name": "staging-fixture", "pack": "Fixtures", "seed": "42"}
        items.append(
            image_item(
                f"stage-pipeline-{number:02d}",
                run_id=_PACK_RUN,
                source="pipeline",
                colour=number,
                **extra,
            )
        )
    for number, source in enumerate(("testing", "testing", "learning", "other"), 1):
        items.append(
            image_item(
                f"stage-{source}-{number:02d}",
                run_id=f"20260101_110000_stage_{source}",
                source=source,
                colour=number + 2,
            )
        )
    original = items[4][0]["item"]
    for library_id, colour, field, feature in (
        ("stage-rework-01", 3, "parent", "item_parent"),
        ("stage-deskjob-01", 4, "input", "item_input"),
    ):
        if feature in features:
            items.append(
                image_item(
                    library_id,
                    run_id="20260101_120000_stage_reprocess",
                    source="reprocess",
                    colour=colour,
                    **{field: original},
                )
            )
    items.append(video_item("stage-video-0001"))
    return items


def publish(client: GatewayClient, manifest: Mapping[str, Any], blobs: Mapping[str, bytes]) -> str:
    state, missing = client.post_manifest(manifest)
    for digest in sorted(missing):
        client.upload_media(digest, blobs[digest], len(blobs[digest]))
    return state


def rating_task() -> tuple[dict[str, Any], dict[str, tuple[bytes, str]]]:
    reference = png(120, 180, _COLOURS[0])
    clips = {"A": b"staging-clip-a" * 16, "B": b"staging-clip-b" * 16}
    task = {
        "schema_version": protocol.SCHEMA_VERSION,
        "type": "rating_task",
        "task_id": "stage-pairs",
        "title": "Staging A/B",
        "kind": "pairs",
        "state": "open",
        "instructions": "Fixtures: the clips do not play.",
        "created_at": _now(),
        "criteria": [
            {"criterion_id": "motion", "label": "Better motion", "type": "choice", "required": True}
        ],
        "items": [
            {
                "item_id": item_id,
                "context": "a placeholder request",
                "reference": _media(reference, "image/png"),
                "clips": [
                    {"clip_id": name, "label": name, "media": _media(data, "video/mp4")}
                    for name, data in clips.items()
                ],
            }
            for item_id in ("p01", "p02")
        ],
    }
    blobs = {_digest(reference): reference, **{_digest(data): data for data in clips.values()}}
    return task, blobs


def choice_catalog() -> dict[str, Any]:
    return {
        "schema_version": protocol.SCHEMA_VERSION,
        "type": "choice_catalog",
        "published_at": _now(),
        "models": [{"id": "staging-model", "label": "Staging model", "warnings": []}],
        "warnings": [],
        "ratios": [{"id": "2x3", "label": "2:3"}],
        "video": {"available": True, "label": "Staging video"},
        "image_backend_ready": True,
        "truncated": False,
    }


def seed(client: GatewayClient) -> int:
    """Publish the fixtures. Running it again is harmless: purged items stay purged until a ``reset``."""

    features = client.health()
    states = [publish(client, manifest, blobs) for manifest, blobs in fixture_items(features)]
    print(f"published {len(states)} items ({states.count('purged')} already purged)")
    if "rating_tasks" in features:
        task, blobs = rating_task()
        _state, missing = client.post_rating_task(task)
        for digest in sorted(missing):
            client.upload_rating_media(digest, blobs[digest], len(blobs[digest]))
        print("published 1 rating set")
    if "deferred_actions" in features and client.send_choice_catalog(choice_catalog()):
        print("published the choice catalog")
    status = protocol.pc_status(
        head_sha="1" * 40,
        origin_main_sha="1" * 40,
        commits_behind=0,
        queue_state="idle",
        queued=0,
        remote_update_enabled=False,
    )
    if client.send_pc_status(status):
        print("published a PC status")
    return EXIT_OK


def pair(client: GatewayClient, *, admin: bool, phone_url: str | None) -> int:
    scopes = ("review", "queue", "admin") if admin else ("review", "queue")
    offer = protocol.new_pairing_offer(label="Staging phone", scopes=scopes)
    if not client.send_pairing_offer(offer.payload()):
        print("The gateway refused the pairing offer.")
        return EXIT_REFUSED
    print(f"Open {phone_url or 'the staging phone address'} and enter this code within 5 minutes:")
    print(f"    {protocol.display_code(offer.code)}")
    print(f"grants: {', '.join(scopes)}")
    return EXIT_OK


def reset_command(ct: int) -> str:
    """One line for the Proxmox host. It stops before anything unless the container is labelled (not production)."""

    return (
        f"pct exec {ct} -- sh -c 'set -e; "
        'grep -Eq "^environment_label *= *\\"[^\\"]+\\"" /etc/review-gateway/config.toml; '
        "systemctl stop review-gateway; "
        "find /var/lib/review-gateway/data /var/lib/review-gateway/media -mindepth 1 -delete; "
        "systemctl start review-gateway; echo wiped'"
    )


def reset(ct: int) -> int:
    print("The sync API cannot wipe a gateway. Paste this into the Proxmox host's shell:\n")
    print(f"    {reset_command(ct)}\n")
    print(
        "It prints 'wiped'. It deletes staging's items, decisions and paired phones; the sync secret, the"
    )
    print("certificate and the settings stay. Then run seed again and pair the phone again.")
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None,
    *,
    client: GatewayClient | None = None,
    phone_store: targets.StagingPhoneStore | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.review_gateway_stage", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument(
        "--target", choices=targets.TARGETS, default=targets.STAGING, help="staging only"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed", help="publish the fixtures")
    pairing = commands.add_parser("pair", help="make a pairing code for a phone")
    pairing.add_argument("--admin", action="store_true", help="also grant the Update screen")
    wipe = commands.add_parser("reset", help="how to wipe staging at its console")
    wipe.add_argument("--ct", type=int, default=STAGING_CT, help="the staging container's id")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return EXIT_USAGE if exit_.code else EXIT_OK
    if args.target != targets.STAGING:
        print(
            "Refused: this tool writes fixtures and wipes data; it never addresses production.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    if args.command == "reset":
        if args.ct <= 0 or args.ct == 120:  # CT 120 is production (DEPLOY-PROXMOX)
            print("Refused: that is not the staging container.", file=sys.stderr)
            return EXIT_REFUSED
        return reset(args.ct)
    try:
        client = client or targets.staging_client()
        if args.command == "seed":
            return seed(client)
        phone_url = (phone_store or targets.StagingPhoneStore()).load()
        return pair(client, admin=args.admin, phone_url=phone_url)
    except targets.NoSettings:
        print(f"No staging gateway settings: {targets.CONFIGURE_HINT}", file=sys.stderr)
        return EXIT_USAGE
    except targets.TargetMixup as error:
        print(error, file=sys.stderr)
        return EXIT_USAGE
    except GatewayUnauthorized:
        print(f"The gateway refused the sync secret: run {targets.CONFIGURE_HINT} again.")
        return EXIT_REFUSED
    except GatewayUnavailable:
        print("The staging gateway is unreachable from this PC.")
        return EXIT_UNREACHABLE
    except GatewayError as error:
        print(f"The gateway answered unexpectedly: {error}")
        return EXIT_REFUSED
    except (OSError, ValueError) as error:
        print(f"The staging settings cannot be read: {error}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
