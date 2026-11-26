"""RG-140: phone actions on the PC against a fake gateway, admitted through the real JobService and repository.

Hermetic: temp output root and job database, a fake compiler that returns ordinary NJRs, a runner that must never be
called directly, and the fake gateway that validates every PC payload against the sync schema.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from src.app.review_gateway_actions import (
    ActionRefused,
    AppActionCompiler,
    Caps,
    CompiledAction,
    GatewayActions,
)
from src.app.review_gateway_apply import RecordApplier
from src.app.review_gateway_protocol import utc_text
from src.app.review_gateway_publish import GatewayPublisher
from src.app.review_gateway_store import GatewaySettingsStore, SyncLedger
from src.app.review_gateway_sync import ReviewGatewaySync
from src.app.runtime_stack import _gateway_actions
from src.app.site_media_files import SiteOutputError
from src.app.site_output_library import OutputLibrary
from src.app.site_phone_admission import PhonePreviewInput, admit_phone_records
from src.app.site_phone_queue import PHONE_SUBMISSION, PhoneQueueView, gateway_owner
from src.controller.job_service import JobService
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.pipeline.policy_warnings import (
    ACCEPTED_WARNINGS_KEY,
    SURFACE_PHONE,
    PolicyWarning,
    with_pending_warnings,
)
from src.queue.job_model import JobPriority
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.helpers.job_helpers import make_test_njr
from tests.helpers.review_gateway_fakes import SECRET, FakeGateway

RUN = "20261126_101500_portraits"
FINGERPRINT = "ab" * 32
WARNING = PolicyWarning(
    "image_model_family_unverified",
    "C:\\Users\\owner\\Forge\\models\\Stable-diffusion\\juggernautXL.safetensors",
    "juggernautXL.safetensors is not classified.",
    "StableNew could not tell which family it is.",
    "Put it in C:\\Users\\owner\\Forge\\models\\Stable-diffusion and refresh.",
    "sdxl_target",
)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class FakeCompiler:
    """Returns ordinary NJRs as the real compilers would; records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[int, ...]]] = []
        self.model = "juggernautXL.safetensors"
        self.warnings: tuple[PolicyWarning, ...] = (WARNING,)
        self.fail: BaseException | None = None
        self.current: BaseException | None = None

    def compile(self, action, path, digest, seeds):
        self.calls.append((action, digest, seeds))
        if self.fail is not None:
            raise self.fail
        count = len(seeds) or 1
        records = tuple(make_test_njr(prompt="private prompt") for _ in range(count))

        def require_current() -> None:
            if self.current is not None:
                raise self.current

        return CompiledAction(
            records,
            (f"Checkpoint {self.model}.",),
            self.warnings,
            (action, self.model, digest, str(count)),
            reprocess=False,
            kind="followup" if action == "more_like_this" else "rework",
            require_current=require_current,
        )


def _codec_store(path: Path) -> GatewaySettingsStore:
    def xor(data: bytes) -> bytes:
        return bytes(byte ^ 0x5A for byte in data)

    return GatewaySettingsStore(path, protect=xor, unprotect=xor)


class Env:
    def __init__(self, tmp_path: Path, *, caps: Caps = Caps()) -> None:
        self.root = (tmp_path / "output").resolve()
        (self.root / RUN).mkdir(parents=True)
        self.image = self.root / RUN / "portrait.png"
        Image.new("RGB", (64, 48), "#557733").save(self.image)
        self.ledger = SyncLedger(tmp_path / "state" / "ledger.sqlite3")
        self.gateway = FakeGateway()
        self.library = OutputLibrary(self.root, "review-gateway", lambda: None)
        self.repository = JobRepository(tmp_path / "jobs.sqlite3")
        self.runner = Mock(is_running=lambda: True)
        self.runner.run_njr.side_effect = AssertionError("a phone job reached the runner directly")
        self.jobs = JobService(JobQueue(repository=self.repository), runner=self.runner)
        self.submitted: list[tuple[tuple, SubmissionPolicy | None]] = []
        real_submit = self.jobs.submit_njrs

        def spy(records, policy=None, experiment_snapshots=None):
            self.submitted.append((tuple(records), policy))
            return real_submit(records, policy, experiment_snapshots)

        self.jobs.submit_njrs = spy  # type: ignore[method-assign]
        self.view = PhoneQueueView(self.repository, self.jobs)
        self.compiler = FakeCompiler()
        self.clock = Clock()

        def admit(owner, receipt, compiled, warnings, runs_next):
            return admit_phone_records(
                self.jobs,
                self.view,
                owner,
                receipt,
                compiled.kind,
                compiled.records,
                warnings,
                reprocess=compiled.reprocess,
                policy=SubmissionPolicy(
                    priority=JobPriority.HIGH if runs_next else JobPriority.NORMAL
                ),
                claim={"channel": "review_gateway"},
            )

        self.actions = GatewayActions(
            self.ledger,
            self.compiler,
            admit,
            owner_of=gateway_owner,
            caps=caps,
            clock=self.clock,
        )
        applier = RecordApplier(
            self.ledger,
            self.root,
            tmp_path / "learning.jsonl",
            active_inputs=set,
            actions=self.actions,
        )
        self.sync = ReviewGatewaySync(
            settings_store=_codec_store(tmp_path / "state" / "settings.bin"),
            ledger=self.ledger,
            publisher_factory=lambda: GatewayPublisher(self.library, self.ledger, transcode=None),
            applier=applier,
            transport_factory=lambda _settings: self.gateway,
        )
        self.sync.configure("192.168.1.50", FINGERPRINT, SECRET)
        deadline = time.monotonic() + 30
        while not self.gateway.manifests:
            assert time.monotonic() < deadline, "the image was not published"
            self.sync.run_cycle()
        self.library_id, manifest = next(iter(self.gateway.manifests.items()))
        self.sha = manifest["item"]["sha256"]

    def pair(self, *, allow_queue: bool = True, device_id: str = "phone-device-01") -> str:
        self.sync.create_pairing("Pixel", allow_queue=allow_queue)
        self.sync.run_cycle()
        self.gateway.enroll(self.gateway.offers[-1], device_id)
        self.sync.run_cycle()
        return device_id

    def request(self, action: str = "fix_face", **params) -> dict:
        return self.gateway.action(self.library_id, self.sha, action, **params)

    def answer(self, record: dict) -> dict:
        self.sync.run_cycle()
        found = [ack for ack in self.gateway.acks if ack["record_id"] == record["record_id"]]
        assert found, "record was not acknowledged"
        return found[-1]

    def confirm(self, prepared: dict, revision: str, action: str = "fix_face", **extra) -> dict:
        return self.gateway.action(
            self.library_id,
            self.sha,
            action,
            step="confirm",
            prepared_record=prepared["record_id"],
            summary_revision=revision,
            **extra,
        )

    def admitted(self) -> list:
        return [job for records, _policy in self.submitted for job in records]

    def close(self) -> None:
        self.sync.stop(timeout=0)
        self.library.close()
        self.ledger.close()


@pytest.fixture
def env(tmp_path):
    environment = Env(tmp_path)
    environment.pair()
    yield environment
    environment.close()


def _summary(ack: dict) -> dict:
    return ack["receipt"]["action_summary"]


def test_prepare_shows_a_summary_and_admits_nothing(env):
    ack = env.answer(env.request("fix_face"))

    assert ack["outcome"] == "applied"
    summary = _summary(ack)
    assert summary["action"] == "fix_face" and summary["title"] == "Fix face"
    assert summary["job_count"] == 1
    assert summary["queue_position"] == "next"
    assert summary["lines"][-1] == "Runs next, after the current job."
    [warning] = summary["warnings"]
    assert warning["code"] == "image_model_family_unverified"
    assert warning["subject"] == "juggernautXL.safetensors"
    assert "owner" not in json.dumps(summary)  # the warning's paths were reduced to their last part
    assert env.compiler.calls == [("fix_face", env.sha, ())]
    assert env.submitted == [] and env.repository.get_job_entries([]) == {}


def test_confirm_admits_once_through_submit_njrs_at_the_front(env):
    prepared = env.request("fix_face")
    revision = _summary(env.answer(prepared))["revision"]

    ack = env.answer(env.confirm(prepared, revision))

    assert ack["outcome"] == "applied"
    [job_id] = ack["receipt"]["job_ids"]
    [(records, policy)] = env.submitted
    assert [record.job_id for record in records] == [job_id]
    assert policy.priority is JobPriority.HIGH
    stored = env.repository.get_job_model(job_id)
    assert stored.priority is JobPriority.HIGH
    metadata = records[0].provenance.metadata
    claim = metadata[PHONE_SUBMISSION]
    assert claim["owner"] == gateway_owner("phone-device-01")
    assert claim["kind"] == "rework" and claim["channel"] == "review_gateway"
    assert claim["receipt"] == prepared["record_id"].replace("-", "")
    [accepted] = metadata[ACCEPTED_WARNINGS_KEY]
    assert (accepted["code"], accepted["surface"]) == (WARNING.code, SURFACE_PHONE)
    env.runner.run_njr.assert_not_called()  # RG-100 invariant 6

    again = env.answer(env.confirm(prepared, revision))  # a second Queue tap for the same summary
    assert again["outcome"] == "duplicate"
    assert again["receipt"]["job_ids"] == [job_id]
    assert len(env.submitted) == 1


def test_more_like_this_makes_new_seeds_at_the_back_of_the_queue(env):
    prepared = env.request("more_like_this", count=3)
    summary = _summary(env.answer(prepared))
    assert (summary["job_count"], summary["queue_position"]) == (3, "last")

    ack = env.answer(env.confirm(prepared, summary["revision"], "more_like_this"))

    assert len(ack["receipt"]["job_ids"]) == 3
    [(_records, policy)] = env.submitted
    assert policy.priority is JobPriority.NORMAL
    seeds = [call[2] for call in env.compiler.calls]
    assert len(seeds) == 2 and all(len(group) == 3 for group in seeds)
    assert seeds[0] != seeds[1]  # fresh seeds at confirm; the revision does not depend on them


def test_more_like_this_defaults_to_four_seeds(env):
    assert _summary(env.answer(env.request("more_like_this")))["job_count"] == 4


def test_a_review_only_phone_is_refused_before_anything_compiles(tmp_path):
    environment = Env(tmp_path)
    try:
        environment.pair(allow_queue=False)
        ack = environment.answer(environment.request("fix_face"))
        assert (ack["outcome"], ack["reason_code"]) == ("refused", "not_granted")
        assert environment.compiler.calls == []
    finally:
        environment.close()


def test_the_pairing_offer_names_the_queue_grant_only_when_ticked(tmp_path):
    environment = Env(tmp_path)
    try:
        environment.pair(allow_queue=False)
        environment.pair(allow_queue=True, device_id="phone-device-02")
        assert [offer["scopes"] for offer in environment.gateway.offers] == [
            ["review"],
            ["review", "queue"],
        ]
        assert environment.ledger.device("phone-device-02").scopes == ("review", "queue")
    finally:
        environment.close()


def test_a_changed_file_is_refused_before_anything_compiles(env):
    Image.new("RGB", (64, 48), "#000000").save(env.image)

    ack = env.answer(env.request("fix_hands"))

    assert ack["reason_code"] == "digest_mismatch"
    assert env.compiler.calls == []


def test_a_reserved_action_is_refused(env):
    ack = env.answer(env.request("another_model"))

    assert (ack["outcome"], ack["reason_code"]) == ("refused", "invalid_record")
    assert env.compiler.calls == []


def test_a_changed_summary_is_shown_again_and_can_be_confirmed(env):
    prepared = env.request("fix_both")
    first = _summary(env.answer(prepared))
    env.compiler.model = "ponyXL.safetensors"  # the recipe changed on the PC meanwhile

    refused = env.answer(env.confirm(prepared, first["revision"], "fix_both"))

    assert (refused["outcome"], refused["reason_code"]) == ("refused", "summary_changed")
    fresh = refused["receipt"]["action_summary"]
    assert fresh["revision"] != first["revision"]
    assert "Checkpoint ponyXL.safetensors." in fresh["lines"]
    assert env.submitted == []

    retried = env.gateway.action(
        env.library_id,
        env.sha,
        "fix_both",
        step="confirm",
        prepared_record=refused["record_id"],
        summary_revision=fresh["revision"],
    )
    assert env.answer(retried)["outcome"] == "applied"
    assert len(env.submitted) == 1


def test_a_revision_the_pc_never_showed_is_refused(env):
    prepared = env.request("fix_face")
    env.answer(prepared)

    ack = env.answer(env.confirm(prepared, "0" * 64))

    assert ack["reason_code"] == "summary_changed"
    assert env.submitted == []


def test_a_confirm_needs_a_live_prepare_of_the_same_phone_item_and_action(env):
    prepared = env.request("fix_face")
    revision = _summary(env.answer(prepared))["revision"]
    env.pair(device_id="phone-device-02")

    unknown = env.gateway.action(
        env.library_id,
        env.sha,
        "fix_face",
        step="confirm",
        prepared_record="7d0e4b3e-2f0a-4c55-9a62-0b8a7f1c2d3e",
        summary_revision=revision,
    )
    other_phone = env.gateway.action(
        env.library_id,
        env.sha,
        "fix_face",
        device_id="phone-device-02",
        step="confirm",
        prepared_record=prepared["record_id"],
        summary_revision=revision,
    )
    other_action = env.confirm(prepared, revision, "fix_hands")
    for record in (unknown, other_phone, other_action):
        assert env.answer(record)["reason_code"] == "prepare_required"

    env.clock.now += timedelta(minutes=31)
    assert env.answer(env.confirm(prepared, revision))["reason_code"] == "prepare_required"
    assert env.submitted == []


def test_compiler_refusals_are_closed_codes_and_never_stall_the_outbox(env, caplog):
    env.compiler.fail = SiteOutputError("detector_unavailable")
    known = env.request("fix_hands")
    assert env.answer(known)["receipt"] == {"detail": "detector_unavailable"}

    env.compiler.fail = RuntimeError("C:\\Users\\owner\\secret.png is broken")
    broken = env.request("fix_face")
    after = env.gateway.decide(env.library_id, env.sha, "keep")
    env.sync.run_cycle()

    ack = next(a for a in env.gateway.acks if a["record_id"] == broken["record_id"])
    assert (ack["reason_code"], ack["receipt"]) == (
        "action_unavailable",
        {"detail": "compile_failed"},
    )
    assert any(a["record_id"] == after["record_id"] for a in env.gateway.acks)
    assert "secret" not in caplog.text and "owner" not in json.dumps(env.gateway.acks)


def test_a_source_that_changed_before_admission_is_refused(env):
    prepared = env.request("fix_face")
    revision = _summary(env.answer(prepared))["revision"]
    env.compiler.current = ActionRefused("source_changed")

    ack = env.answer(env.confirm(prepared, revision))

    assert (ack["reason_code"], ack["receipt"]) == (
        "admission_refused",
        {"detail": "source_changed"},
    )
    assert env.submitted == []


def test_nothing_is_admitted_while_the_app_is_shutting_down(env):
    prepared = env.request("fix_face")
    revision = _summary(env.answer(prepared))["revision"]
    env.jobs.queue.request_dispatch_fence()

    ack = env.answer(env.confirm(prepared, revision))

    assert (ack["reason_code"], ack["receipt"]["detail"]) == (
        "admission_refused",
        "app_shutting_down",
    )
    assert env.submitted == []


@pytest.mark.parametrize(
    "caps, action, params, step",
    [
        (Caps(prepares_per_day=1), "fix_face", {}, "second_prepare"),
        (Caps(jobs_per_request=2), "more_like_this", {"count": 3}, "prepare"),
        (Caps(jobs_per_day=2), "more_like_this", {"count": 3}, "confirm"),
    ],
)
def test_caps_refuse_per_request_and_per_day(tmp_path, caps, action, params, step):
    environment = Env(tmp_path, caps=caps)
    try:
        environment.pair()
        prepared = environment.request(action, **params)
        first = environment.answer(prepared)
        if step == "prepare":
            assert first["reason_code"] == "cap_exceeded"
            return
        if step == "second_prepare":
            assert environment.answer(environment.request(action))["reason_code"] == "cap_exceeded"
            return
        confirmed = environment.confirm(prepared, _summary(first)["revision"], action)
        assert environment.answer(confirmed)["reason_code"] == "cap_exceeded"
        assert environment.submitted == []
    finally:
        environment.close()


def test_the_daily_window_rolls(tmp_path):
    environment = Env(tmp_path, caps=Caps(prepares_per_day=1))
    try:
        environment.pair()
        environment.answer(environment.request("fix_face"))
        environment.clock.now += timedelta(hours=25)
        assert environment.answer(environment.request("fix_face"))["outcome"] == "applied"
    finally:
        environment.close()


def test_a_request_admitted_before_a_restart_is_not_admitted_again(env):
    """Deterministic job ids: the receipt is read back instead of a second admission (S8)."""

    owner = gateway_owner("phone-device-01")
    compiled = env.compiler.compile("fix_face", env.image, env.sha, ())

    def admit():
        return admit_phone_records(
            env.jobs,
            env.view,
            owner,
            "c" * 32,
            compiled.kind,
            compiled.records,
            (),
            reprocess=False,
            policy=SubmissionPolicy(priority=JobPriority.HIGH),
        )

    first = admit()
    assert admit() == first
    assert len(env.submitted) == 1


def test_no_payload_the_pc_sends_names_a_path(env):
    prepared = env.request("fix_face")
    revision = _summary(env.answer(prepared))["revision"]
    env.answer(env.confirm(prepared, revision))

    sent = json.dumps(env.gateway.acks)
    assert str(env.root) not in sent and env.root.as_posix() not in sent
    assert "\\\\" not in sent.replace("\\\\u", "")


# -- the application compiler ---------------------------------------------------------------------------------------


def test_the_app_compiler_refuses_what_it_cannot_verify(tmp_path):
    root = tmp_path.resolve()
    image = root / "plain.png"
    Image.new("RGB", (8, 8), "#123456").save(image)
    digest = __import__("hashlib").sha256(image.read_bytes()).hexdigest()
    compiler = AppActionCompiler(
        host=None, repository=Mock(get_job=lambda _id: None), output_root=root
    )

    with pytest.raises(ActionRefused) as video:
        compiler.compile("fix_face", root / "clip.mp4", digest, ())
    assert video.value.detail == "not_an_image"
    with pytest.raises(ActionRefused) as changed:
        compiler.compile("more_like_this", image, "0" * 64, (1,))
    assert changed.value.detail == "source_changed"
    with pytest.raises(SiteOutputError, match="followup_provenance_unverified"):
        compiler.compile("more_like_this", image, digest, (1,))


def test_the_app_compiler_describes_the_fix_from_the_compiled_job(tmp_path):
    job = make_test_njr(
        config={
            "model": "C:\\models\\juggernautXL.safetensors",
            "adetailer": {
                "adetailer_model": "face_yolov8n.pt",
                "adetailer_hands_model": "hand_yolov8s.pt",
            },
        },
        base_model="C:\\models\\juggernautXL.safetensors",
    )
    job = with_pending_warnings(job, (WARNING,))
    calls = []

    class Host:
        def compile_gateway_fix(self, path, digest, *, face, hands):
            calls.append((face, hands))
            return PhonePreviewInput(path.name, (job,), lambda: None)

    compiler = AppActionCompiler(Host(), repository=None, output_root=tmp_path)
    compiled = compiler.compile("fix_both", tmp_path / "a.png", "d" * 64, ())

    assert calls == [(True, True)]
    assert compiled.reprocess and compiled.kind == "rework"
    assert compiled.lines[0] == (
        "ADetailer face pass, then the hand pass on this exact image (face_yolov8n.pt, hand_yolov8s.pt)."
    )
    assert compiled.lines[2] == "Checkpoint juggernautXL.safetensors."


def test_runtime_composition_admits_through_job_service_only(tmp_path, monkeypatch):
    """The composed path: preview host compile -> GatewayActions -> admit_phone_records -> submit_njrs."""

    from src.app import site_phone_preview_host

    repository = JobRepository(tmp_path / "jobs.sqlite3")
    runner = Mock(is_running=lambda: True)
    runner.run_njr.side_effect = AssertionError("runner reached directly")
    service = JobService(JobQueue(repository=repository), runner=runner)
    submitted = []
    real = service.submit_njrs

    def spy(records, policy=None, experiment_snapshots=None):
        submitted.append(policy)
        return real(records, policy, experiment_snapshots)

    service.submit_njrs = spy  # type: ignore[method-assign]
    job = make_test_njr()

    def fake_fix(self, path, digest, *, face, hands):
        return PhonePreviewInput(path.name, (job,), lambda: None)

    monkeypatch.setattr(site_phone_preview_host.PhonePreviewHost, "compile_gateway_fix", fake_fix)
    monkeypatch.setattr(
        "src.controller.reprocess_admission.require_njr_operation", lambda _njr: None
    )
    ledger = SyncLedger(tmp_path / "ledger.sqlite3")
    try:
        app = SimpleNamespace(job_service=service)
        actions = _gateway_actions(app, ledger, tmp_path, tmp_path / "learning.jsonl")
        assert isinstance(actions, GatewayActions)
        assert _gateway_actions(SimpleNamespace(), ledger, tmp_path, tmp_path / "x") is None

        from src.app.review_gateway_protocol import parse_record

        def record(params):
            return parse_record(
                {
                    "record_id": str(__import__("uuid").uuid4()),
                    "idempotency_key": __import__("uuid").uuid4().hex,
                    "device_id": "phone-device-01",
                    "created_at": utc_text(datetime.now(UTC)),
                    "target": {"library_id": "a" * 32, "sha256": "b" * 64},
                    "kind": "action_request",
                    "action_request": {"action": "fix_face", "params": params},
                }
            )

        prepare = record({"step": "prepare"})
        prepared = actions.handle(prepare, tmp_path / "a.png")
        revision = prepared.receipt["action_summary"]["revision"]
        confirmed = actions.handle(
            record(
                {
                    "step": "confirm",
                    "prepared_record": prepare.record_id,
                    "summary_revision": revision,
                }
            ),
            tmp_path / "a.png",
        )
        assert confirmed.outcome == "applied", confirmed
        assert [policy.priority for policy in submitted] == [JobPriority.HIGH]
        runner.run_njr.assert_not_called()
    finally:
        ledger.close()


# -- the ADetailer passes and the preview host --------------------------------------------------------------------


def test_adetailer_passes_keep_a_usable_recorded_detector_and_switch_the_passes():
    from src.controller.review_batch_service import AdetailerPasses

    recorded = {"adetailer_model": "face_yolov8s.pt", "enable_hands_pass": True, "steps": 12}
    fallback = {"adetailer_hands_model": "mediapipe_hands"}

    face_only = AdetailerPasses(face=("face_yolov8n.pt", "face_yolov8s.pt")).apply(
        recorded, fallback
    )
    assert face_only["enable_face_pass"] is True
    assert face_only["enable_hands_pass"] is False and face_only["ad_hands_enabled"] is False
    assert face_only["adetailer_model"] == "face_yolov8s.pt" and face_only["steps"] == 12

    both = AdetailerPasses(face=("face_yolov8n.pt",), hands=("hand_yolov8n.pt",)).apply(
        recorded, fallback
    )
    assert both["adetailer_model"] == "face_yolov8n.pt"  # the recorded one is not listed
    assert both["adetailer_hands_model"] == "hand_yolov8n.pt"
    assert both["enable_hands_pass"] is True and both["ad_hands_enabled"] is True


def test_adetailer_passes_need_the_adetailer_stage_alone():
    from src.controller.review_batch_service import AdetailerPasses, prepare_review_batch

    with pytest.raises(ValueError):
        prepare_review_batch(
            Mock(), image_paths=["a.png"], stages=["adetailer", "upscale"], fallback_config={},
            adetailer_passes=AdetailerPasses(face=("face_yolov8n.pt",)),
        )  # fmt: skip
    with pytest.raises(ValueError):
        prepare_review_batch(
            Mock(), image_paths=["a.png"], stages=["adetailer"], fallback_config={},
            adetailer_passes=AdetailerPasses(),
        )  # fmt: skip


@pytest.mark.parametrize(
    "detectors, face, hands, code",
    [
        ((), True, False, "adetailer_unavailable"),
        (("face_yolov8n.pt",), False, True, "detector_unavailable"),
        (("hand_yolov8n.pt",), True, True, "detector_unavailable"),
    ],
)
def test_the_preview_host_refuses_a_fix_the_backend_cannot_run(
    tmp_path, detectors, face, hands, code
):
    from src.app.site_phone_preview_host import PhonePreviewHost

    app = SimpleNamespace(
        _is_shutting_down=False,
        _ui_dispatch=lambda callback: callback(),
        _build_reprocess_config=lambda stages: {"adetailer": {}},
        _extract_reprocess_baseline_from_image=lambda path: {"model": "sdxl_base.safetensors"},
        app_state=SimpleNamespace(adetailer_detectors=list(detectors)),
    )
    host = PhonePreviewHost(app, Mock(), tmp_path / "records.jsonl")

    with pytest.raises(SiteOutputError, match=code):
        host.compile_gateway_fix(tmp_path / "a.png", "d" * 64, face=face, hands=hands)
