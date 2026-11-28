"""RG-160 on the PC: a request made while the PC was away is admitted when it arrives, once, or refused for a reason
that is certain; and the choices the phone is told about hold names only, never paths.

Hermetic, as ``test_review_gateway_actions``: real JobService and repository, a fake compiler and a fake gateway.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from src.app.review_gateway_catalog import ChoiceCatalog
from src.app.review_gateway_client import GatewayClient
from src.app.review_gateway_protocol import encode_json
from src.app.review_gateway_store import SyncLedger
from src.app.site_media_files import SiteOutputError
from src.app.site_phone_queue import PHONE_SUBMISSION, gateway_owner, phone_job_id
from src.pipeline.policy_warnings import ACCEPTED_WARNINGS_KEY, PolicyWarning
from src.queue.job_model import JobPriority
from tests.app import test_review_gateway_actions as actions_tests
from tests.helpers.review_gateway_fakes import SECRET, FakeGateway, validate_def


class Env(actions_tests.Env):
    """The actions rig with a compiler whose readiness the test sets."""

    def __init__(self, tmp_path) -> None:
        super().__init__(tmp_path)
        self.not_ready: set[str] = set()
        self.compiler.ready = lambda action: action not in self.not_ready
        self.actions.admitted = self.admitted_jobs
        self.pair()

    def admitted_jobs(self, owner: str, receipt: str) -> list[str]:
        found = self.view.receipt(owner, receipt)
        return list(found["job_ids"]) if found["state"] == "admitted" else []

    def queued(self, action: str = "fix_face", **params) -> dict:
        return self.request(action, step="queue", **params)

    def acks(self, record: dict) -> list[dict]:
        return [ack for ack in self.gateway.acks if ack["record_id"] == record["record_id"]]

    def later(self, seconds: float = 30) -> None:
        self.clock.now += timedelta(seconds=seconds)
        self.sync.run_cycle()


@pytest.fixture
def env(tmp_path):
    environment = Env(tmp_path)
    yield environment
    environment.close()


# --- admission without a summary first ------------------------------------------------------------------------------


def test_a_deferred_fix_is_admitted_on_arrival_ahead_of_normal_work(env) -> None:
    record = env.queued("fix_face")

    ack = env.answer(record)

    [job] = env.admitted()
    assert ack["outcome"] == "applied"
    assert ack["receipt"]["job_ids"] == [job.job_id]
    assert [w["title"] for w in ack["receipt"]["action_summary"]["warnings"]]
    assert env.submitted[0][1].priority is JobPriority.HIGH
    # "One tap, warnings after": the tap accepted them, and they are frozen into the job.
    assert job.provenance.metadata[ACCEPTED_WARNINGS_KEY]
    assert job.provenance.metadata[PHONE_SUBMISSION]["deferred"] == "true"
    validate_def(ack, "acknowledgement")


def test_a_confirmed_action_is_not_marked_deferred(env) -> None:
    prepared = env.request("fix_face")
    revision = env.answer(prepared)["receipt"]["action_summary"]["revision"]
    env.answer(env.confirm(prepared, revision))

    [job] = env.admitted()
    assert "deferred" not in job.provenance.metadata[PHONE_SUBMISSION]


@pytest.mark.parametrize(
    "action, params, jobs, priority",
    [
        ("more_like_this", {"count": 3}, 3, JobPriority.NORMAL),
        ("another_model", {"choice": "m-pony"}, 1, JobPriority.NORMAL),
        ("prompt_tweak", {"text": "smiling"}, 1, JobPriority.NORMAL),
        ("make_video", {}, 1, JobPriority.NORMAL),
    ],
)
def test_every_phone_action_can_be_deferred(env, action, params, jobs, priority) -> None:
    ack = env.answer(env.queued(action, **params))

    assert ack["outcome"] == "applied"
    assert len(ack["receipt"]["job_ids"]) == jobs == len(env.admitted())
    assert env.submitted[0][1].priority is priority


def test_a_deferred_rework_remembers_what_it_reworks(env) -> None:
    ack = env.answer(env.queued("fix_hands"))

    assert env.ledger.rework_original(ack["receipt"]["job_ids"][0]) == (env.library_id, env.sha)


def test_a_chosen_model_that_is_gone_is_refused(env) -> None:
    ack = env.answer(env.queued("another_model", choice="m-gone"))

    assert (ack["outcome"], ack["reason_code"]) == ("refused", "action_unavailable")
    assert ack["receipt"] == {"detail": "choice_unavailable"}
    assert env.admitted() == []


def test_a_source_that_changed_is_refused(env) -> None:
    record = env.queued()
    env.image.write_bytes(b"something else")

    ack = env.answer(record)

    assert (ack["outcome"], ack["reason_code"]) == ("refused", "digest_mismatch")


def test_a_phone_without_the_queue_grant_is_refused_even_while_not_ready(env) -> None:
    env.ledger.set_device_queue("phone-device-01", False)
    env.not_ready.add("fix_face")

    assert env.answer(env.queued())["reason_code"] == "not_granted"


# --- waiting instead of refusing -------------------------------------------------------------------------------------


def test_a_request_waits_while_the_backend_lists_are_not_loaded(env) -> None:
    env.not_ready.add("fix_face")
    record = env.queued()

    env.sync.run_cycle()
    env.later()

    assert env.acks(record) == [] and env.admitted() == []
    assert env.compiler.calls == []
    assert env.ledger.outcome(record["record_id"]) is None

    env.not_ready.clear()
    env.later()
    assert env.acks(record)[-1]["outcome"] == "applied"
    assert len(env.admitted()) == 1


def test_a_waiting_request_does_not_hold_up_a_ready_one_or_a_decision(env) -> None:
    env.not_ready.add("fix_face")
    waiting = env.queued()
    clip = env.queued("make_video")
    decision = env.gateway.decide(env.library_id, env.sha, "keep")

    env.sync.run_cycle()

    assert env.acks(waiting) == []
    assert env.acks(clip)[-1]["outcome"] == "applied"
    assert [a["outcome"] for a in env.gateway.acks if a["record_id"] == decision["record_id"]]


@pytest.mark.parametrize("code", ["preview_unavailable", "app_shutting_down"])
def test_a_busy_or_closing_app_is_waited_for(env, code) -> None:
    env.compiler.fail = SiteOutputError(code)
    record = env.queued("make_video")

    env.sync.run_cycle()
    assert env.acks(record) == []

    env.compiler.fail = None
    env.later()
    assert env.acks(record)[-1]["outcome"] == "applied"


def test_a_shutting_down_queue_at_admission_is_waited_for(env) -> None:
    env.compiler.current = SiteOutputError("app_shutting_down")
    record = env.queued("make_video")

    env.sync.run_cycle()

    assert env.acks(record) == [] and env.admitted() == []


def test_an_online_prepare_still_answers_when_the_app_is_busy(env) -> None:
    env.compiler.fail = SiteOutputError("preview_unavailable")

    ack = env.answer(env.request("fix_face"))

    assert ack["receipt"] == {"detail": "app_busy"}


# --- exactly once ----------------------------------------------------------------------------------------------------


def test_a_restart_between_admission_and_the_answer_admits_once(env) -> None:
    record = env.queued("fix_face")
    env.answer(record)
    [job] = env.admitted()
    # The PC stopped before it could write down or send its answer, and the image has gone since.
    with env.ledger._transaction() as db:
        db.execute("DELETE FROM records")
        db.execute("DELETE FROM rework_jobs")
    env.gateway.acks.clear()
    env.gateway.outbox.append(record)
    env.image.unlink()

    ack = env.answer(record)

    assert ack["outcome"] == "applied"
    assert ack["receipt"] == {"job_ids": [job.job_id]}
    assert len(env.submitted) == 1
    assert env.ledger.rework_original(job.job_id) == (env.library_id, env.sha)
    receipt = record["record_id"].replace("-", "")
    assert job.job_id == phone_job_id(gateway_owner("phone-device-01"), receipt, 0)


def test_the_same_request_twice_admits_once(env) -> None:
    first = env.queued(key="k" * 32)
    env.answer(first)
    second = env.queued(key="k" * 32)

    ack = env.answer(second)

    assert ack["outcome"] == "duplicate"
    assert len(env.submitted) == 1


def test_every_outbox_page_is_followed(env) -> None:
    env.not_ready.add("fix_face")
    env.gateway.page_size = 2
    for _ in range(25):  # more pages than one ordinary cycle used to read
        env.queued()
    decision = env.gateway.decide(env.library_id, env.sha, "keep")

    env.sync.run_cycle()

    assert [a for a in env.gateway.acks if a["record_id"] == decision["record_id"]]


# --- the choice catalog ----------------------------------------------------------------------------------------------

MODELS = ("sdxl\\juggernautXL.safetensors [abc123]", "ponyXL.safetensors")
MODEL_WARNING = PolicyWarning(
    "image_model_unqualified",
    "ponyXL.safetensors",
    "ponyXL.safetensors is not qualified.",
    "Nobody has confirmed it renders correctly.",
    "Put the VAE in D:\\Forge\\models\\VAE and refresh.",
    "forge.dependency_gate",
)


class Source:
    def __init__(self) -> None:
        self.models: tuple[str, ...] | Exception = MODELS
        self.video = "Wan2.2 I2V"
        self.warnings = {MODELS[1]: MODEL_WARNING}

    def catalog(self, ledger, clock) -> ChoiceCatalog:
        def models():
            if isinstance(self.models, Exception):
                raise self.models
            return self.models

        return ChoiceCatalog(
            ledger,
            models=models,
            warning_of=self.warnings.get,
            video=lambda: self.video,
            clock=clock,
        )


@pytest.fixture
def parts(tmp_path):
    ledger = SyncLedger(tmp_path / "ledger.sqlite3")
    source = Source()
    clock = actions_tests.Clock()
    yield source, source.catalog(ledger, clock), ledger, clock
    ledger.close()


def test_the_catalog_names_what_the_phone_can_choose(parts) -> None:
    _source, catalog, _ledger, _clock = parts

    body = catalog.payload()

    validate_def(body, "choice_catalog")
    from src.app.review_gateway_actions import ASPECT_RATIOS, model_choice_id

    assert [entry["label"] for entry in body["models"]] == [
        "ponyXL.safetensors",
        "juggernautXL.safetensors [abc123]",
    ]
    assert body["models"][1]["id"] == model_choice_id(MODELS[0])
    assert body["models"][0]["warnings"] == [0] and body["models"][1]["warnings"] == []
    assert body["warnings"][0]["title"] == "ponyXL.safetensors is not qualified."
    assert [ratio["id"] for ratio in body["ratios"]] == [entry[0] for entry in ASPECT_RATIOS]
    assert body["video"] == {"available": True, "label": "Wan2.2 I2V"}
    assert (body["image_backend_ready"], body["truncated"]) == (True, False)


def test_no_path_crosses_in_the_catalog(parts) -> None:
    source, catalog, _ledger, _clock = parts
    source.models = (*MODELS, "C:\\Users\\owner\\models\\secretXL.safetensors")

    text = json.dumps(catalog.payload())

    for fragment in ("C:", "D:", "\\\\", "owner", "sdxl\\\\", "Forge\\\\models", "/"):
        assert fragment not in text, fragment


def test_no_video_workflow_is_said_so(parts) -> None:
    source, catalog, _ledger, _clock = parts
    source.video = ""

    assert catalog.payload()["video"] == {"available": False}


@pytest.mark.parametrize("now", [(), SiteOutputError("preview_unavailable")])
def test_a_session_without_forge_keeps_the_last_model_list(parts, now) -> None:
    source, catalog, ledger, clock = parts
    first = catalog.payload()
    source.models = now
    clock.now += timedelta(days=2)

    later = Source.catalog(source, ledger, clock).payload()  # a new session over the same ledger

    assert later["models"] == first["models"]
    assert later["image_backend_ready"] is False
    assert later["models_as_of"] == first["models_as_of"]


def test_a_pc_that_never_listed_models_still_offers_the_rest(parts) -> None:
    source, catalog, _ledger, _clock = parts
    source.models = ()

    body = catalog.payload()

    validate_def(body, "choice_catalog")
    assert (body["models"], body["image_backend_ready"]) == ([], False)
    assert "models_as_of" not in body


def test_a_large_catalog_stays_under_the_transport_limit(parts) -> None:
    source, catalog, _ledger, _clock = parts
    names = tuple(f"model-{n:04d}-" + "x" * 140 + ".safetensors" for n in range(300))
    source.models = names
    source.warnings = {
        name: PolicyWarning(
            "image_model_unqualified", name, f"{n} " + "t" * 400, "w" * 900, "f" * 900, "g"
        )
        for n, name in enumerate(names)
    }

    body = catalog.payload()

    validate_def(body, "choice_catalog")
    assert len(encode_json(body)) < 64 * 1024
    assert body["truncated"] is True and 0 < len(body["models"]) <= 200


# --- sending the catalog ---------------------------------------------------------------------------------------------


class Ticks:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def sending(env, parts):
    source, catalog, _ledger, _clock = parts
    ticks = Ticks()
    env.sync._monotonic = ticks
    env.sync._catalog = catalog
    env.gateway.features = ["deferred_actions"]
    return env, source, ticks


def cycle(env, ticks, seconds: float) -> None:
    ticks.now += seconds
    env.sync.run_cycle()


def test_the_catalog_is_sent_when_it_changes_and_now_and_then(sending) -> None:
    env, source, ticks = sending
    cycle(env, ticks, 100)
    cycle(env, ticks, 20)
    assert len(env.gateway.catalogs) == 1

    source.video = ""
    cycle(env, ticks, 20)
    assert len(env.gateway.catalogs) == 2

    cycle(env, ticks, 700)  # unchanged, but a rebuilt gateway must get it back
    assert len(env.gateway.catalogs) == 3


def test_the_catalog_is_sent_again_after_a_reconnect(sending) -> None:
    env, _source, ticks = sending
    cycle(env, ticks, 100)
    env.gateway.fail_next = 503
    cycle(env, ticks, 5)
    cycle(env, ticks, 5)

    assert len(env.gateway.catalogs) == 2


def test_an_older_gateway_is_not_sent_the_catalog(sending) -> None:
    env, _source, ticks = sending
    env.gateway.features = ["item_batch"]
    cycle(env, ticks, 100)

    assert env.gateway.catalogs == []


def test_a_catalog_that_cannot_be_built_does_not_stop_the_sync(sending) -> None:
    env, _source, ticks = sending

    def broken():
        raise RuntimeError("no app")

    env.sync._catalog.payload = broken
    decision = env.gateway.decide(env.library_id, env.sha, "keep")
    cycle(env, ticks, 100)

    assert env.sync.status().state == "idle"
    assert [a for a in env.gateway.acks if a["record_id"] == decision["record_id"]]


def test_the_client_reports_a_gateway_that_refuses_the_catalog() -> None:
    gateway = FakeGateway()
    gateway.offers_catalog = False

    assert GatewayClient(gateway, SECRET).send_choice_catalog({"type": "choice_catalog"}) is False


# --- the running application -------------------------------------------------------------------------------------------


class Host:
    def __init__(self, models=("a.safetensors",), detectors=("face_yolov8n.pt",)) -> None:
        self.models, self.detectors = models, detectors

    def gateway_models(self):
        return self.models

    def gateway_detectors(self):
        return self.detectors


@pytest.mark.parametrize(
    "action, models, detectors, ready",
    [
        ("fix_face", ("a",), (), False),
        ("fix_both", (), ("face.pt",), True),
        ("another_model", (), ("face.pt",), False),
        ("another_model", ("a",), (), True),
        ("make_video", (), (), True),
        ("prompt_tweak", (), (), True),
        ("more_like_this", (), (), True),
        ("aspect_ratio", (), (), True),
    ],
)
def test_only_actions_that_need_a_backend_list_wait_for_it(
    tmp_path, action, models, detectors, ready
) -> None:
    from src.app.review_gateway_actions import AppActionCompiler

    compiler = AppActionCompiler(Host(models, detectors), repository=None, output_root=tmp_path)

    assert compiler.ready(action) is ready


def test_the_running_app_composes_the_admitted_lookup_and_the_catalog(env, tmp_path) -> None:
    from types import SimpleNamespace

    from src.app import runtime_stack

    app = SimpleNamespace(job_service=env.jobs)
    actions = runtime_stack._gateway_actions(app, env.ledger, env.root, tmp_path / "r.jsonl")
    assert actions.admitted("0" * 64, "1" * 32) == []

    catalog = runtime_stack._gateway_catalog(app, env.ledger, env.root)
    body = catalog.payload()  # no Tk app behind it: nothing listed, nothing raised
    validate_def(body, "choice_catalog")
    assert body["image_backend_ready"] is False
