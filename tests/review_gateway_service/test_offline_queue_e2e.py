"""RG-160 end to end: the real gateway app, the real PC sync worker, JobService and repository, in one process.

The PC is away, three requests are made on the phone from the catalog, one is cancelled, and the PC comes back first
without its image backend and then with it.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from src.app.review_gateway_actions import GatewayActions, admission_claim
from src.app.review_gateway_apply import RecordApplier
from src.app.review_gateway_catalog import ChoiceCatalog
from src.app.review_gateway_publish import GatewayPublisher
from src.app.review_gateway_store import SyncLedger
from src.app.review_gateway_sync import ReviewGatewaySync
from src.app.site_output_library import OutputLibrary
from src.app.site_phone_admission import admit_phone_records
from src.app.site_phone_queue import PhoneQueueView, gateway_owner
from src.controller.job_service import JobService
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.queue.job_model import JobPriority
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.app.test_review_gateway_actions import FINGERPRINT, FakeCompiler, _codec_store
from tests.review_gateway_service.conftest import SECRET
from tests.review_gateway_service.test_deploy_trigger import _AsgiTransport

RUN = "20261126_101500_portraits"


class Pc:
    """The PC side as composed in the app, over the real gateway's sync listener."""

    def __init__(self, tmp_path: Path, rig) -> None:
        self.root = (tmp_path / "output").resolve()
        (self.root / RUN).mkdir(parents=True)
        Image.new("RGB", (64, 48), "#557733").save(self.root / RUN / "portrait.png")
        self.ledger = SyncLedger(tmp_path / "state" / "ledger.sqlite3")
        self.repository = JobRepository(tmp_path / "jobs.sqlite3")
        runner = Mock(is_running=lambda: True)
        runner.run_njr.side_effect = AssertionError("a phone job reached the runner directly")
        self.jobs = JobService(JobQueue(repository=self.repository), runner=runner)
        view = PhoneQueueView(self.repository, self.jobs)
        self.admitted: list = []
        self.forge_up = False
        self.compiler = FakeCompiler()
        self.compiler.warnings = ()
        self.compiler.ready = lambda action: self.forge_up or not action.startswith(
            ("fix_", "another")
        )
        self.now = datetime.now(UTC)
        real_submit = self.jobs.submit_njrs

        def spy(records, policy=None, experiment_snapshots=None):
            self.admitted.extend((record.job_id, policy.priority) for record in records)
            return real_submit(records, policy, experiment_snapshots)

        self.jobs.submit_njrs = spy  # type: ignore[method-assign]

        def admit(owner, receipt, compiled, warnings, runs_next):
            return admit_phone_records(
                self.jobs,
                view,
                owner,
                receipt,
                compiled.kind,
                compiled.records,
                warnings,
                reprocess=compiled.reprocess,
                policy=SubmissionPolicy(
                    priority=JobPriority.HIGH if runs_next else JobPriority.NORMAL
                ),
                claim=admission_claim(compiled),
            )

        def admitted(owner, receipt):
            found = view.receipt(owner, receipt)
            return found["job_ids"] if found["state"] == "admitted" else []

        actions = GatewayActions(
            self.ledger,
            self.compiler,
            admit,
            owner_of=gateway_owner,
            clock=lambda: self.now,
            admitted=admitted,
        )
        catalog = ChoiceCatalog(
            self.ledger,
            models=lambda: ("juggernautXL.safetensors", "ponyXL.safetensors")
            if self.forge_up
            else (),
            warning_of=lambda _name: None,
            video=lambda: "Wan2.2 I2V",
        )
        library = OutputLibrary(self.root, "review-gateway", lambda: None)
        self.ticks = 1000.0
        self.sync = ReviewGatewaySync(
            settings_store=_codec_store(tmp_path / "state" / "settings.bin"),
            ledger=self.ledger,
            publisher_factory=lambda: GatewayPublisher(library, self.ledger, transcode=None),
            applier=RecordApplier(
                self.ledger,
                self.root,
                tmp_path / "learning.jsonl",
                active_inputs=set,
                actions=actions,
            ),
            transport_factory=lambda _settings: _AsgiTransport(rig.client(rig.gateway.sync_app())),
            monotonic=lambda: self.ticks,
            catalog=catalog,
        )
        self.sync.configure("192.168.1.50", FINGERPRINT, SECRET)

    def cycle(self) -> None:
        self.ticks += 60
        self.now += timedelta(seconds=60)
        self.sync.run_cycle()
        assert self.sync.status().state == "idle", self.sync.status().state

    def pair(self, rig) -> None:
        code = self.sync.create_pairing("Pixel").replace("-", "")
        self.cycle()
        assert rig.phone.post("/api/pair", json={"code": code}).status_code == 200
        self.cycle()

    def close(self) -> None:
        self.ledger.close()


@pytest.fixture
def world(rig, tmp_path):
    rig.clock.now = datetime.now(UTC)  # pairing offers carry the PC's real time
    pc = Pc(tmp_path / "pc", rig)
    pc.pair(rig)
    deadline = time.monotonic() + 30
    while not rig.phone.get("/api/runs").json()["runs"]:
        assert time.monotonic() < deadline, "the image was not published"
        pc.cycle()
    [item] = rig.phone.get(f"/api/runs/{RUN}").json()["items"]
    yield rig, pc, {"library_id": item["library_id"], "sha256": item["sha256"]}
    pc.close()


def request(rig, item, action, **params) -> str:
    response = rig.phone.post(
        "/api/actions",
        json={
            **item,
            "action": action,
            "params": {"step": "queue", **params},
            "idempotency_key": uuid.uuid4().hex,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["record_id"]


def shown(rig) -> dict[str, dict]:
    return {
        entry["record_id"]: entry for entry in rig.phone.get("/api/requests").json()["requests"]
    }


def test_requests_made_while_the_pc_is_away_run_when_it_returns(world) -> None:
    rig, pc, item = world
    # A session with the image backend publishes its list, then the PC goes away.
    pc.forge_up = True
    pc.cycle()
    pc.forge_up = False
    rig.clock.advance(hours=5)
    status = rig.phone.get("/api/status").json()
    assert status["pc_seen_at"] < status["now"]
    models = rig.phone.get("/api/catalog").json()["catalog"]["models"]
    assert [model["label"] for model in models] == [
        "juggernautXL.safetensors",
        "ponyXL.safetensors",
    ]

    fix = request(rig, item, "fix_face")
    dropped = request(rig, item, "more_like_this", count=2)
    clip = request(rig, item, "make_video", text="turns to the window")
    assert rig.phone.post(f"/api/actions/{dropped}/cancel").json()["state"] == "cancelled"
    assert [entry["state"] for entry in shown(rig).values()] == ["pending", "cancelled", "pending"]

    # The PC returns; its image backend is not connected yet. The clip needs none and is not held up.
    pc.cycle()
    listed = shown(rig)
    assert listed[clip]["state"] == "applied"
    assert (listed[fix]["state"], listed[fix]["delivered"]) == ("pending", True)
    assert rig.phone.get("/api/status").json()["image_backend_ready"] is False
    assert [priority for _job, priority in pc.admitted] == [JobPriority.NORMAL]

    pc.forge_up = True
    pc.cycle()
    pc.cycle()

    listed = shown(rig)
    assert listed[fix]["state"] == "applied"
    assert listed[dropped]["state"] == "cancelled"
    assert [priority for _job, priority in pc.admitted] == [JobPriority.NORMAL, JobPriority.HIGH]
    jobs = [job for job, _priority in pc.admitted]
    assert listed[clip]["receipt"]["job_ids"] == jobs[:1]
    assert listed[fix]["receipt"]["job_ids"] == jobs[1:]
    assert len({job.job_id for job in pc.jobs.queue.list_jobs()}) == 2
    assert rig.phone.get("/api/status").json()["waiting"] == 0
    [original] = rig.phone.get(f"/api/runs/{RUN}").json()["items"]
    assert (original["state"], original["waiting"]) == ("rework", [])


def test_waiting_requests_that_cannot_run_are_refused_with_the_reason(world) -> None:
    rig, pc, item = world
    gone = request(rig, item, "another_model", choice="0000000000000000")
    pc.forge_up = True
    pc.cycle()

    entry = shown(rig)[gone]

    assert (entry["state"], entry["reason_code"]) == ("refused", "action_unavailable")
    assert entry["receipt"] == {"detail": "choice_unavailable"}
    assert pc.admitted == []


def test_a_delete_cancels_what_waits_for_the_image(world) -> None:
    rig, pc, item = world
    waiting = request(rig, item, "fix_face")
    rig.decide(item, "delete")
    pc.forge_up = True
    pc.cycle()

    assert shown(rig)[waiting]["state"] == "cancelled"
    assert pc.admitted == []
