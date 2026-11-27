"""PHONE-FAST: no published video body carries a PC path (RG-100 invariant 3), and the PC's file is untouched."""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest

from src.app.review_gateway_client import GatewayClient
from src.app.review_gateway_publish import GatewayPublisher, ffmpeg_mobile_transcode
from src.app.site_output_library import Preview, key_for
from src.pipeline.video import resolve_ffmpeg_executable
from src.video.container_metadata import write_video_container_metadata
from tests.app.test_review_gateway_backlog import indexed
from tests.app.test_review_gateway_sync import RUN, Env
from tests.helpers.review_gateway_fakes import SECRET

PLANTED = "C:\\Users\\private-person\\StableNew\\output"
MARKERS = (b"private-person", b"Users", b"C:\\", b"manifest", b"workflow")


@pytest.fixture
def env(tmp_path):
    environment = Env(tmp_path)
    environment.large.unlink()
    environment.small.unlink()
    yield environment
    environment.close()


def publish(env, publisher=None):
    client = GatewayClient(env.gateway, SECRET)
    return (publisher or env.publisher).publish(client, limit=8, cancel=Event())


def make_clip(path: Path) -> None:
    """A tiny MP4 tagged the way StableNew tags its videos, plus stream and chapter-free extras."""

    tool = resolve_ffmpeg_executable()
    if tool is None:
        pytest.skip("FFmpeg is unavailable")
    subprocess.run(
        [str(tool), "-f", "lavfi", "-i", "testsrc=size=64x48:rate=8:duration=1"]
        + ["-metadata:s:v:0", f"handler_name={PLANTED}", "-y", str(path)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    assert write_video_container_metadata(
        path,
        {
            "stage": "video_workflow",
            "prompt": "a lighthouse",
            "manifest_path": f"{PLANTED}\\manifests\\clip.json",
            "source_image_path": f"{PLANTED}\\source.png",
        },
        additional_tags={"workflow": f"{PLANTED}\\workflow.json"},
    )
    assert b"private-person" in path.read_bytes()


def test_no_published_video_body_carries_a_pc_path(env):
    clip = env.root / RUN / "clip.mp4"
    make_clip(clip)
    before = clip.read_bytes()
    publisher = GatewayPublisher(env.library, env.ledger, transcode=ffmpeg_mobile_transcode)
    indexed(env, 1)
    assert publish(env, publisher).published == 1

    key = key_for(f"{RUN}/clip.mp4")
    manifest = env.gateway.manifests[key]
    bodies = [env.gateway.media[entry["sha256"]] for entry in manifest["media"].values()]
    for body in bodies:
        assert not [marker for marker in MARKERS if marker in body]
    assert "private-person" not in json.dumps(manifest)
    assert clip.read_bytes() == before  # the PC's own file is never rewritten
    public = manifest["item"]["sha256"]
    assert public == manifest["media"]["original"]["sha256"]
    file_sha = hashlib.sha256(before).hexdigest()
    assert public != file_sha
    assert env.ledger.file_digest(key, public) == file_sha


def test_the_mobile_copy_is_stripped_too(tmp_path):
    clip = tmp_path / "clip.mp4"
    make_clip(clip)
    target = tmp_path / "mobile.mp4"
    with clip.open("rb") as source:
        assert ffmpeg_mobile_transcode(source, target, lambda: False)
    assert not [marker for marker in MARKERS if marker in target.read_bytes()]


def fake_strip(source, target: Path, _cancelled) -> bool:
    target.write_bytes(source.read().replace(b"private-person", b""))
    return True


def video(env, monkeypatch) -> tuple[str, Path]:
    # A poster needs a real clip; it is not what these two tests are about.
    monkeypatch.setattr(
        env.library, "grid_preview", lambda *_a, **_k: Preview("image/jpeg", b"thumb")
    )
    path = env.root / RUN / "fake.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42 private-person " * 50)
    return key_for(f"{RUN}/fake.mp4"), path


def test_a_video_that_cannot_be_stripped_waits(env, monkeypatch):
    key, _path = video(env, monkeypatch)
    publisher = GatewayPublisher(env.library, env.ledger, transcode=None, strip=lambda *_: False)
    indexed(env, 1)
    result = publish(env, publisher)
    assert (result.published, result.pending) == (0, 1)
    assert key not in env.gateway.manifests


@pytest.mark.parametrize("verdict", ["keep", "delete"])
def test_a_decision_on_the_stripped_copy_applies_to_the_pcs_file(env, monkeypatch, verdict):
    key, path = video(env, monkeypatch)
    file_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    env.publisher = GatewayPublisher(env.library, env.ledger, transcode=None, strip=fake_strip)
    indexed(env, 1)
    assert publish(env, env.publisher).published == 1
    public = env.gateway.manifests[key]["item"]["sha256"]
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
