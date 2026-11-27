"""RG-170 on the PC: registered rating sets out, submitted ratings back, against the real gateway app in process.

The gateway runs over an ASGI test client and the video encoder is a stub (Linux CI has no FFmpeg): no network, GPU or
display. All names and text are placeholders.
"""

from __future__ import annotations

import csv
import json
import uuid
from collections.abc import Mapping
from pathlib import Path
from threading import Event
from typing import Any, BinaryIO

import pytest
from PIL import Image, PngImagePlugin

from src.app import review_gateway_ratings
from src.app.review_gateway_client import GatewayClient, Response
from src.app.review_gateway_ratings import (
    HEARTBEAT_SECONDS,
    RatingTaskSync,
    encode_rating_image,
    encode_rating_video,
)
from src.app.review_gateway_store import SyncLedger
from src.video.video_eval_rating_task import register_rating_task
from tests.review_gateway_service.conftest import SECRET, FakeClock, Rig

NOW = "2026-11-27T12:00:00Z"


class AppTransport:
    """The gateway's sync app behind the client's transport interface."""

    def __init__(self, rig: Rig) -> None:
        self.client = rig.client(rig.gateway.sync_app())
        self.calls: list[tuple[str, str]] = []
        self.fail: set[str] = set()

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: bytes | BinaryIO | None,
        timeout: float,
        limit: int,
    ) -> Response:
        self.calls.append((method, path))
        if path in self.fail:
            self.fail.remove(path)
            return Response(500, b"")
        data = body if body is None or isinstance(body, bytes) else body.read()
        reply = self.client.request(method, path, headers=dict(headers), content=data)
        return Response(reply.status_code, reply.content)


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.clock = FakeClock()
        self.rig = Rig(tmp_path / "gateway", self.clock)
        self.ledger = SyncLedger(tmp_path / "state" / "ledger.sqlite3")
        self.folder = tmp_path / "state" / "rating_tasks"
        self.root = tmp_path / "private-eval" / "blind"
        self.root.mkdir(parents=True)
        self.encoded: list[Path] = []
        self.time = 0.0
        self.transport = AppTransport(self.rig)
        self.client = GatewayClient(self.transport, SECRET)
        self.ratings = RatingTaskSync(
            self.folder, self.ledger, video_encoder=self._encode, monotonic=lambda: self.time
        )
        self.client.health()

    def _encode(self, source: Path, target: Path, cancelled: Any) -> bool:
        self.encoded.append(source)
        target.write_bytes(b"stripped:" + source.name.encode())
        return True

    def step(self, *, busy: bool = False) -> None:
        self.ratings.step(self.client, busy=busy, cancel=Event())

    def phone(self) -> str:
        """Pair a phone on the gateway and bind it in the PC ledger, as a sync cycle would."""

        device_id = self.rig.pair()
        offer_id = str(uuid.uuid4())
        self.ledger.add_offer(offer_id, ("review",), "Pixel", "2027-01-01T00:00:00Z", "{}")
        assert self.ledger.bind_device(device_id, offer_id, "Pixel", NOW)
        return device_id

    def tasks(self) -> list[dict[str, Any]]:
        return self.rig.phone.get("/api/rating/tasks").json()["tasks"]

    def task(self, task_id: str) -> dict[str, Any]:
        return self.rig.phone.get(f"/api/rating/tasks/{task_id}").json()

    def answer_and_submit(self, task_id: str, answers: list[tuple[str, str, dict]]) -> None:
        for item_id, clip_id, values in answers:
            reply = self.rig.phone.post(
                f"/api/rating/tasks/{task_id}/answers",
                json={"item_id": item_id, "clip_id": clip_id, "values": values, "notes": ""},
            )
            assert reply.status_code == 200, reply.text
        reply = self.rig.phone.post(
            f"/api/rating/tasks/{task_id}/submit", json={"idempotency_key": uuid.uuid4().hex}
        )
        assert reply.status_code == 200, reply.text

    # -- a two-pair A/B set shaped like the desktop's folder -------------------------------------------------------

    def register_pairs(self, task_id: str = "demo-pairs", **changes: Any) -> Path:
        sheet = self.root / f"{task_id}.csv"
        sheet.write_text(
            "pair,case_id,motion_better,notes\np01,caseone,,\np02,casetwo,,\n", encoding="utf-8"
        )
        key = {
            "key": {c: {"A": "arm-secret-x", "B": "arm-secret-y"} for c in ("caseone", "casetwo")}
        }
        (self.root / "key.json").write_text(json.dumps(key), encoding="utf-8")
        clips = {}
        for name in ("p01_A", "p01_B", "p02_A", "p02_B"):
            (self.root / f"{name}.mp4").write_bytes(b"original-with-metadata:" + name.encode())
            clips[name] = f"{name}.mp4"
        Image.new("RGB", (40, 30), "#224466").save(self.root / "source.png")
        spec = {
            "schema": "stablenew.rating-set.v1",
            "task_id": task_id,
            "title": "Demo A/B",
            "kind": "pairs",
            "created_at": NOW,
            "root": str(self.root),
            "criteria": [
                {
                    "criterion_id": "motion_better",
                    "label": "Better motion",
                    "type": "choice",
                    "required": True,
                }
            ],
            "items": [
                {
                    "item_id": item,
                    "context": "a request",
                    "reference": "source.png",
                    "clips": [
                        {"clip_id": c, "label": c, "path": clips[f"{item}_{c}"]} for c in "AB"
                    ],
                }
                for item in ("p01", "p02")
            ],
            "result": {"adapter": "pairwise_csv", "sheet": sheet.name, "key": "key.json"},
        }
        spec.update(changes)
        return register_rating_task(spec, self.folder)

    def rows(self, task_id: str = "demo-pairs") -> list[dict[str, str]]:
        with (self.root / f"{task_id}.csv").open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))


@pytest.fixture
def env(tmp_path: Path):
    environment = Env(tmp_path)
    yield environment
    environment.rig.close()


PAIR_ANSWERS = [("p01", "", {"motion_better": "A"}), ("p02", "", {"motion_better": "B"})]


def test_a_registered_set_reaches_the_phone_without_paths_names_or_arms(env: Env) -> None:
    env.register_pairs()
    env.step()
    env.phone()

    [listed] = env.tasks()
    assert (listed["task_id"], listed["state"], listed["total"]) == ("demo-pairs", "open", 2)
    shown = env.task("demo-pairs")
    text = json.dumps(shown)
    for secret in ("private-eval", "arm-secret", "caseone", ".mp4", "source.png", "key.json"):
        assert secret not in text, secret

    clip = shown["items"][0]["clips"][0]["media"]
    body = env.rig.phone.get(f"/rating-media/demo-pairs/{clip['sha256']}").content
    assert body == b"stripped:p01_A.mp4"  # the rendition, never the original bytes
    assert clip["content_type"] == "video/mp4"
    assert shown["items"][0]["reference"]["content_type"] == "image/webp"


def test_an_unchanged_set_is_not_sent_again_until_the_heartbeat(env: Env) -> None:
    env.register_pairs()
    env.step()
    env.transport.calls.clear()

    env.step()
    assert [call for call in env.transport.calls if call[0] != "GET"] == []

    env.time += HEARTBEAT_SECONDS
    env.step()
    assert ("POST", "/sync/v1/rating-tasks") in env.transport.calls
    assert not any(method == "PUT" for method, _path in env.transport.calls)
    assert len(env.encoded) == 4  # renditions are cached


def test_nothing_is_transcoded_while_a_job_runs(env: Env) -> None:
    env.register_pairs()
    env.step(busy=True)
    assert env.encoded == []
    env.phone()
    assert env.tasks() == []
    env.step()
    assert len(env.tasks()) == 1


def test_a_gateway_without_rating_tasks_is_sent_nothing(env: Env) -> None:
    env.register_pairs()
    env.client.features = frozenset({"item_batch"})
    env.transport.calls.clear()
    env.step()
    assert env.transport.calls == []


def test_submitted_ratings_fill_the_sheet_and_the_phone_gets_the_reveal(env: Env) -> None:
    env.register_pairs()
    env.step()
    env.phone()
    env.answer_and_submit("demo-pairs", PAIR_ANSWERS)
    assert [row["motion_better"] for row in env.rows()] == ["", ""]

    env.step()

    assert [row["motion_better"] for row in env.rows()] == ["A", "B"]
    shown = env.task("demo-pairs")
    assert shown["state"] == "done"
    assert shown["reveal"][0]["columns"] == ["Criterion", "arm-secret-x", "arm-secret-y", "Same"]


def test_a_lost_acknowledgement_is_answered_again_without_a_second_write(env: Env) -> None:
    env.register_pairs()
    env.step()
    env.phone()
    env.answer_and_submit("demo-pairs", PAIR_ANSWERS)
    env.transport.fail.add("/sync/v1/rating-acknowledgements")
    with pytest.raises(review_gateway_ratings.GatewayError):
        env.step()
    before = (env.root / "demo-pairs.csv").stat().st_mtime_ns

    env.step()

    assert (env.root / "demo-pairs.csv").stat().st_mtime_ns == before
    assert env.task("demo-pairs")["state"] == "done"


def test_a_desk_judgment_refuses_the_submission_with_its_reason(env: Env) -> None:
    env.register_pairs()
    env.step()
    env.phone()
    env.answer_and_submit("demo-pairs", PAIR_ANSWERS)
    sheet = env.root / "demo-pairs.csv"
    sheet.write_text(sheet.read_text(encoding="utf-8").replace("caseone,,", "caseone,B,"), "utf-8")

    env.step()

    shown = env.task("demo-pairs")
    assert (shown["state"], shown["reason_code"]) == ("refused", "already_rated")
    assert [row["motion_better"] for row in env.rows()] == ["B", ""]


def test_a_phone_the_pc_revoked_cannot_write_ratings(env: Env) -> None:
    env.register_pairs()
    env.step()
    device_id = env.phone()
    env.answer_and_submit("demo-pairs", PAIR_ANSWERS)
    env.ledger.revoke_device(device_id, NOW)

    env.step()

    assert env.task("demo-pairs")["reason_code"] == "revoked_device"
    assert [row["motion_better"] for row in env.rows()] == ["", ""]


def test_a_set_rated_at_the_desk_shows_done_and_never_appears_if_not_yet_sent(env: Env) -> None:
    env.register_pairs()
    env.step()
    env.register_pairs("demo-late")
    for task_id in ("demo-pairs", "demo-late"):
        (env.root / f"{task_id}.csv").write_text(
            "pair,case_id,motion_better,notes\np01,caseone,A,\np02,casetwo,A,\n", encoding="utf-8"
        )
    env.time += HEARTBEAT_SECONDS
    env.step()
    env.phone()

    [only] = env.tasks()
    assert (only["task_id"], only["state"]) == ("demo-pairs", "done")
    assert "PC" in only["note"]


def test_removing_a_registration_withdraws_the_task(env: Env) -> None:
    path = env.register_pairs()
    env.step()
    env.phone()
    path.unlink()

    env.step()

    assert env.tasks() == []


def test_a_follow_up_pick_is_registered_only_after_the_reveal(env: Env) -> None:
    env.register_pairs(
        follow_up={
            "task_id": "demo-pick",
            "title": "Which runs next?",
            "context": "Pick the next arm.",
            "options": [{"value": "x", "label": "X"}, {"value": "y", "label": "Y"}],
            "result": {"adapter": "answer_file", "path": "pick.txt"},
        }
    )
    env.step()
    env.phone()
    assert [task["task_id"] for task in env.tasks()] == ["demo-pairs"]
    env.answer_and_submit("demo-pairs", PAIR_ANSWERS)

    env.step()

    assert (env.folder / "demo-pick.json").is_file()
    assert {task["task_id"]: task["state"] for task in env.tasks()} == {
        "demo-pairs": "done",
        "demo-pick": "open",
    }
    env.answer_and_submit("demo-pick", [("q1", "", {"pick": "y"})])
    env.step()
    assert (env.root / "pick.txt").read_text(encoding="utf-8") == "y\n"


def test_a_broken_registration_or_missing_clip_does_not_stop_the_others(env: Env) -> None:
    # "demo-gone" sorts first, so the working set is only reached if its failure is contained.
    path = env.register_pairs("demo-gone")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["items"][0]["clips"][0]["path"] = "gone.mp4"
    path.write_text(json.dumps(data), encoding="utf-8")
    (env.folder / "broken.json").write_text("{", encoding="utf-8")
    env.register_pairs()

    env.step()
    env.phone()

    assert [task["task_id"] for task in env.tasks()] == ["demo-pairs"]


def test_a_set_whose_key_cannot_reveal_it_never_reaches_the_phone(env: Env) -> None:
    # A registration file dropped straight into the folder skips register_rating_task's check.
    env.register_pairs()
    (env.root / "key.json").write_text(json.dumps({"caseone": {}}), encoding="utf-8")

    env.step()
    env.phone()

    assert env.tasks() == []


def test_a_key_broken_after_publishing_refuses_the_submission_and_writes_nothing(env: Env) -> None:
    env.register_pairs()
    env.step()
    env.phone()
    env.answer_and_submit("demo-pairs", PAIR_ANSWERS)
    (env.root / "key.json").write_text(json.dumps({"key": {}}), encoding="utf-8")

    env.step()

    shown = env.task("demo-pairs")
    assert (shown["state"], shown["reason_code"]) == ("refused", "write_failed")
    assert [row["motion_better"] for row in env.rows()] == ["", ""]


# --- renditions -----------------------------------------------------------------------------------------------------


def test_a_reference_picture_loses_its_embedded_metadata(tmp_path: Path) -> None:
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "arm-secret prompt")
    source = tmp_path / "source.png"
    Image.new("RGB", (2000, 1000), "#101010").save(source, pnginfo=info)
    target = tmp_path / "rendition.webp"

    assert encode_rating_image(source, target)

    assert b"arm-secret" not in target.read_bytes()
    with Image.open(target) as image:
        assert max(image.size) == 1280 and "parameters" not in image.info


def test_a_clip_is_always_re_encoded_with_its_metadata_dropped(tmp_path, monkeypatch) -> None:
    from src.pipeline import video as pipeline_video
    from src.utils import managed_process

    commands: list[list[str]] = []

    def run(command, **options):
        commands.append([str(part) for part in command])
        Path(command[-1]).write_bytes(b"mp4")
        return managed_process.ProcessOutcome(returncode=0)

    monkeypatch.setattr(pipeline_video, "resolve_ffmpeg_executable", lambda: Path("ffmpeg"))
    monkeypatch.setattr(managed_process, "run_bounded", run)
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")

    assert encode_rating_video(source, tmp_path / "out.mp4", lambda: False)

    [command] = commands
    for pair in (
        ("-map_metadata", "-1"),
        ("-map_chapters", "-1"),
        ("-crf", "18"),
        ("-c:v", "libx264"),
    ):
        assert command[command.index(pair[0]) + 1] == pair[1]
    assert "copy" not in command


def test_without_ffmpeg_a_clip_set_is_not_published(tmp_path, monkeypatch) -> None:
    from src.pipeline import video as pipeline_video

    monkeypatch.setattr(pipeline_video, "resolve_ffmpeg_executable", lambda: None)
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")
    assert not encode_rating_video(source, tmp_path / "out.mp4", lambda: False)


# --- the sync worker and composition --------------------------------------------------------------------------------


def test_a_sync_cycle_publishes_registered_sets(env: Env, tmp_path: Path) -> None:
    from src.app.review_gateway_apply import RecordApplier
    from src.app.review_gateway_store import GatewaySettingsStore
    from src.app.review_gateway_sync import ReviewGatewaySync

    def xor(data: bytes) -> bytes:
        return bytes(byte ^ 0x5A for byte in data)

    worker = ReviewGatewaySync(
        settings_store=GatewaySettingsStore(tmp_path / "settings.bin", protect=xor, unprotect=xor),
        ledger=env.ledger,
        publisher_factory=lambda: None,
        applier=RecordApplier(env.ledger, tmp_path, tmp_path / "records.jsonl", active_inputs=set),
        transport_factory=lambda _settings: env.transport,
    )
    worker.attach_rating_tasks(env.ratings)
    worker.configure("gateway.lan", "ab" * 32, SECRET)
    env.register_pairs()

    worker.run_cycle()

    assert worker.status().state == "idle"
    env.phone()
    assert [task["task_id"] for task in env.tasks()] == ["demo-pairs"]


def test_the_app_composes_the_rating_folder_beside_the_ledger(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from src.app.runtime_stack import build_review_gateway_sync

    app = SimpleNamespace(_config_manager=None, job_service=SimpleNamespace(runner=None))
    sync = build_review_gateway_sync(
        app, state_dir=tmp_path / "state", records_path=tmp_path / "records.jsonl"
    )

    assert sync._ratings.folder == tmp_path / "state" / "rating_tasks"


def test_phone_copies_on_the_pc_are_removed_once_a_set_is_finished_or_withdrawn(env: Env) -> None:
    def cached() -> int:
        return len(list((env.folder / "cache").glob("*")))

    env.register_pairs()
    other = env.register_pairs("demo-other")  # the same clips and picture, so the same copies
    env.step()
    env.step()
    assert cached() == 5  # four clips and one picture
    env.phone()
    env.answer_and_submit("demo-pairs", PAIR_ANSWERS)

    env.step()
    assert cached() == 5  # still needed by the other set

    other.unlink()
    env.step()
    assert cached() == 0
