"""PHONE-FAST: no published image body carries a PC path (RG-100 invariant 3); prompt and settings text stay."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest
from PIL import Image

from src.app.review_gateway_client import GatewayClient
from src.app.review_gateway_scrub import Unclean, scrub_image
from src.app.site_output_library import key_for
from src.utils.image_metadata import (
    build_contract_kv,
    extract_embedded_metadata,
    write_image_metadata,
)
from tests.app.test_review_gateway_backlog import indexed
from tests.app.test_review_gateway_sync import RUN, Env
from tests.helpers.review_gateway_fakes import SECRET

PLANTED = "C:\\Users\\private-person\\StableNew\\output"
MARKERS = (b"private-person", b"Users", b"C:\\", b"C:/")


@pytest.fixture
def env(tmp_path):
    environment = Env(tmp_path)
    environment.large.unlink()
    environment.small.unlink()
    yield environment
    environment.close()


def make_image(path: Path, *, prompt: str = "a lighthouse at dusk") -> None:
    """An image tagged the way StableNew tags its outputs, with the paths its records hold."""

    Image.new("RGB", (64, 48), "#446688").save(path)
    payload = {
        "job_id": "job-1",
        "generation": {"prompt": prompt, "steps": 20, "model": "SDXL\\base.safetensors"},
        "artifact": {
            "primary_path": f"{PLANTED}\\run\\a.png",
            "manifest_path": f"{PLANTED}\\run\\manifests\\a.json",
            "output_paths": [f"{PLANTED}\\run\\a.png"],
        },
        "stage_manifest": {
            "stage": "txt2img",
            "config": {"init": f"{PLANTED.replace(chr(92), '/')}/source.png"},
            "note": f"made from {PLANTED}\\source.png today",
        },
    }
    kv = build_contract_kv(payload, job_id="job-1", run_id=RUN, stage="txt2img")
    assert write_image_metadata(path, kv)
    # Only the large payload is compressed; either way the file names the PC before it is published.
    assert extract_embedded_metadata(path).payload["artifact"]["manifest_path"].startswith("C:")


def publish(env):
    return env.publisher.publish(GatewayClient(env.gateway, SECRET), limit=8, cancel=Event())


def sent(env, key: str) -> bytes:
    return env.gateway.media[env.gateway.manifests[key]["item"]["sha256"]]


def pixels(path_or_bytes) -> bytes:
    import io

    source = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes) else path_or_bytes
    with Image.open(source) as image:
        return image.convert("RGB").tobytes()


@pytest.mark.parametrize(
    "name, prompt",
    [
        ("plain.png", "a lighthouse at dusk"),
        ("compressed.png", "lighthouse " * 20000),
        ("a.jpg", "a lighthouse"),
    ],
    ids=["png", "compressed-png", "jpeg"],
)
def test_no_published_image_body_carries_a_pc_path(env, tmp_path, name, prompt):
    path = env.root / RUN / name
    make_image(path, prompt=prompt)
    before = path.read_bytes()
    indexed(env, 1)
    assert publish(env).published == 1

    key = key_for(f"{RUN}/{name}")
    manifest = env.gateway.manifests[key]
    for entry in manifest["media"].values():
        body = env.gateway.media[entry["sha256"]]
        assert not [marker for marker in MARKERS if marker in body]
    assert "private-person" not in json.dumps(manifest)

    clean = sent(env, key)
    copy = tmp_path / f"clean{path.suffix}"
    copy.write_bytes(clean)
    metadata = extract_embedded_metadata(copy)
    assert metadata.status == "ok", metadata
    assert metadata.payload["generation"]["prompt"] == prompt
    assert metadata.payload["generation"]["model"] == "SDXL\\base.safetensors"
    assert "manifest_path" not in metadata.payload["artifact"]
    assert metadata.payload["stage_manifest"]["note"] == "made from source.png today"
    assert pixels(clean) == pixels(before)  # nothing is re-encoded
    assert path.read_bytes() == before  # the PC's own file is never rewritten
    file_sha = hashlib.sha256(before).hexdigest()
    assert env.ledger.file_digest(key, manifest["item"]["sha256"]) == file_sha


def test_the_same_file_gives_the_same_bytes(tmp_path):
    path = tmp_path / "a.png"
    make_image(path, prompt="lighthouse " * 20000)
    data = path.read_bytes()
    assert scrub_image(data) == scrub_image(data) != data


def test_an_image_without_paths_is_sent_as_it_is(env):
    path = env.root / RUN / "plain.png"
    Image.new("RGB", (64, 48), "#123456").save(path)
    indexed(env, 1)
    assert publish(env).published == 1
    assert sent(env, key_for(f"{RUN}/plain.png")) == path.read_bytes()


def test_unreadable_metadata_keeps_the_image_on_the_pc():
    with pytest.raises(Unclean):
        scrub_image(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x05tEXtbroke" + b"\x00" * 4)


def test_an_image_sent_before_stays_the_same_item_when_its_rendition_is_added(env):
    path = env.root / RUN / "old.png"
    make_image(path)
    indexed(env, 1)
    key = key_for(f"{RUN}/old.png")
    file_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with env.library.store.connection() as db:
        version = db.execute("SELECT version FROM media WHERE key = ?", (key,)).fetchone()[0]
    env.ledger.mark_published(
        key, version, f"{RUN}/old.png", file_sha, "image", "published", "2026-11-26T00:00:00Z"
    )
    assert publish(env).published == 1
    assert env.gateway.manifests[key]["item"]["sha256"] == file_sha


@pytest.mark.parametrize("verdict", ["keep", "delete"])
def test_a_decision_on_the_cleaned_image_applies_to_the_pcs_file(env, verdict):
    path = env.root / RUN / "decided.png"
    make_image(path)
    file_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    indexed(env, 1)
    assert publish(env).published == 1
    key = key_for(f"{RUN}/decided.png")
    public = env.gateway.manifests[key]["item"]["sha256"]
    assert public != file_sha
    device = env.pair()
    env.gateway.outbox.append(
        {
            "record_id": str(uuid.uuid4()),
            "idempotency_key": "k" * 16,
            "device_id": device,
            "created_at": datetime.now(UTC).isoformat(),
            "target": {"library_id": key, "sha256": public},
            "kind": "decision",
            "decision": {"verdict": verdict, "favorite": False},
        }
    )
    env.sync.run_cycle()
    assert env.gateway.acks[-1]["outcome"] == "applied"
    assert env.disposition(path, file_sha)
    assert path.exists() == (verdict == "keep")
