"""LAUNCH-UPDATE-2 on the PC: the ``admin_request`` record, the ``pc_status`` publish and the remote hand-off.

Hermetic: a fake gateway, fake Git runners and the real LAUNCH-UPDATE-1 service with an injected preflight, queue and
updater launch. Nothing touches a real checkout, starts a process or restarts anything.
"""

from __future__ import annotations

import ast
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.app import live_update as lu
from src.app import review_gateway_protocol as protocol
from src.app.live_update_remote import CheckoutProbe, RemoteUpdate
from src.app.live_update_service import LiveUpdateService
from src.app.review_gateway_apply import IN_PROGRESS, Applied, RecordApplier
from src.app.review_gateway_store import GatewaySettingsStore, SyncLedger
from src.app.review_gateway_sync import STATUS_HEARTBEAT_SECONDS, ReviewGatewaySync
from tests.helpers.review_gateway_fakes import SECRET, FakeGateway, validate, validate_def

OLD = "a" * 40
NEW = "b" * 40
OTHER = "c" * 40
FINGERPRINT = "ab" * 32
SRC = Path(__file__).resolve().parents[2] / "src"


def _now_text(**delta: float) -> str:
    return protocol.utc_text(datetime.now(UTC) + timedelta(**delta))


# -- codec ------------------------------------------------------------------------------------------------------------


def _admin_raw(**changes):
    record = {
        "record_id": str(uuid.uuid4()),
        "idempotency_key": uuid.uuid4().hex,
        "device_id": "phone-device-01",
        "created_at": "2026-11-26T12:00:00.000Z",
        "kind": "admin_request",
        "admin_request": {"action": "update_and_restart", "expected_sha": NEW},
    }
    record.update(changes)
    return record


def test_an_admin_request_parses_to_a_record_without_a_target():
    raw = _admin_raw()
    validate_def(raw, "outbox_record")

    record = protocol.parse_record(raw)

    assert isinstance(record, protocol.AdminRecord)
    assert (record.action, record.expected_sha, record.kind) == (
        "update_and_restart",
        NEW,
        "admin_request",
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"admin_request": {"action": "update_and_restart", "expected_sha": NEW.upper()}},
        {"admin_request": {"action": "update_and_restart", "expected_sha": NEW[:12]}},
        {"admin_request": {"action": "update_and_restart", "expected_sha": "main"}},
        {"admin_request": {"action": "update_and_restart", "expected_sha": "--upload-pack=x"}},
        {"admin_request": {"action": "deploy", "expected_sha": NEW}},
        {"admin_request": {"action": "update_and_restart", "expected_sha": NEW, "ref": "main"}},
        {"target": {"library_id": "b" * 32, "sha256": "d" * 64}},
        {"decision": {"verdict": "keep", "favorite": False}},
    ],
)
def test_a_malformed_admin_request_is_refused_by_the_codec_and_the_schema(changes):
    raw = _admin_raw(**changes)

    with pytest.raises(protocol.ProtocolError):
        protocol.parse_record(raw)
    with pytest.raises(AssertionError):
        validate_def(raw, "outbox_record")


def test_item_records_still_need_a_target():
    raw = {
        "record_id": str(uuid.uuid4()),
        "idempotency_key": uuid.uuid4().hex,
        "device_id": "phone-device-01",
        "created_at": "2026-11-26T12:00:00.000Z",
        "kind": "decision",
        "decision": {"verdict": "keep", "favorite": False},
    }
    with pytest.raises(protocol.ProtocolError):
        protocol.parse_record(raw)
    with pytest.raises(AssertionError):
        validate_def(raw, "outbox_record")


def test_the_update_lists_match_the_schema():
    defs = validate.__globals__["SCHEMA"]["$defs"]

    assert set(defs["update_reason"]["enum"]) == protocol.UPDATE_REASONS
    assert protocol.UPDATE_REASONS <= protocol.REASON_CODES
    assert set(defs["admin_request"]["properties"]["action"]["enum"]) == protocol.ADMIN_ACTIONS
    receipt = defs["update_receipt"]["properties"]
    assert set(receipt["status"]["enum"]) == protocol.UPDATE_STATUSES
    assert set(receipt["health"]["enum"]) == protocol.UPDATE_HEALTH
    assert set(receipt["source"]["enum"]) == protocol.UPDATE_SOURCES
    status = defs["pc_status"]["properties"]
    assert set(status["queue"]["properties"]["state"]["enum"]) == protocol.QUEUE_STATES
    assert set(status["update"]["properties"]["state"]["enum"]) == protocol.UPDATE_STATES
    assert set(status["update"]["properties"]["phase"]["enum"]) == protocol.UPDATE_PHASES
    assert defs["commit_sha"]["pattern"] == f"^{protocol.GIT_SHA.pattern}$"
    # Every reason LAUNCH-UPDATE-1 can write (service and updater script) reaches the phone as a closed code.
    assert set(lu.REASON_TEXT) <= protocol.UPDATE_REASONS


def test_the_update_receipt_carries_commit_ids_and_codes_only():
    receipt = protocol.update_receipt(
        {
            "status": "applied",
            "reason": "",
            "source": "remote",
            "old_sha": OLD,
            "new_sha": NEW,
            "target_sha": NEW,
            "health": "unconfirmed",
            "detail": r"C:\Users\someone\StableNew-main git said: secret",
            "record_id": str(uuid.uuid4()),
            "finished_at": "2026-11-26T12:05:00Z",
            "restart_at": 123.0,
            "update_id": "f" * 32,
        }
    )

    assert receipt == {
        "status": "applied",
        "source": "remote",
        "old_sha": OLD,
        "new_sha": NEW,
        "target_sha": NEW,
        "health": "unconfirmed",
        "finished_at": "2026-11-26T12:05:00.000Z",
    }
    validate_def(receipt, "update_receipt")


def test_an_exited_health_and_an_unknown_reason_are_closed():
    rolled = protocol.update_receipt(
        {"status": "refused", "reason": "rolled_back", "health": "exited:11", "new_sha": OLD}
    )
    assert rolled["health"] == "exited" and rolled["reason_code"] == "rolled_back"
    with pytest.raises(protocol.ProtocolError):
        protocol.update_receipt({"status": "refused", "reason": "something C:/new"})
    with pytest.raises(protocol.ProtocolError):
        protocol.update_receipt({"status": "refused"})
    with pytest.raises(protocol.ProtocolError):
        protocol.update_receipt({"status": "restarting"})


def test_pc_status_is_valid_and_refuses_what_the_contract_does_not_allow():
    body = protocol.pc_status(
        head_sha=OLD,
        origin_main_sha=NEW,
        commits_behind=3,
        fetched_at=datetime(2026, 11, 26, 12, tzinfo=UTC),
        queue_state="running",
        queued=4,
        remote_update_enabled=True,
        last_result={"status": "already_current", "reason": "already_current", "old_sha": OLD},
    )
    validate_def(body, "pc_status")
    validate(body)
    assert body["last_result"] == {
        "status": "already_current",
        "reason_code": "already_current",
        "old_sha": OLD,
    }
    for bad in (
        {"head_sha": "main"},
        {"queue_state": "busy"},
        {"queued": -1},
        {"update_phase": "draining"},
    ):
        with pytest.raises(protocol.ProtocolError):
            protocol.pc_status(
                **{"queue_state": "idle", "queued": 0, "remote_update_enabled": False, **bad}
            )


def test_the_admin_scope_is_offered_only_when_asked_for():
    assert "admin" in protocol.SCOPES
    assert protocol.new_pairing_offer().scopes == ("review",)


# -- the record applier ----------------------------------------------------------------------------------------------


class FakeAdmin:
    def __init__(self, answer=None) -> None:
        self.answer = answer
        self.seen: list[protocol.AdminRecord] = []

    def handle(self, record):
        self.seen.append(record)
        return self.answer(record) if callable(self.answer) else self.answer


def _ledger_with(tmp_path: Path, scopes: tuple[str, ...], *, revoked: bool = False) -> SyncLedger:
    ledger = SyncLedger(tmp_path / "ledger.sqlite3")
    offer_id = str(uuid.uuid4())
    ledger.add_offer(offer_id, scopes, "Pixel", _now_text(minutes=5), "{}")
    assert ledger.bind_device("phone-device-01", offer_id, "Pixel", _now_text())
    if revoked:
        ledger.revoke_device("phone-device-01", _now_text())
    return ledger


def _applier(tmp_path: Path, ledger: SyncLedger, admin=None) -> RecordApplier:
    return RecordApplier(
        ledger, tmp_path / "out", tmp_path / "records.jsonl", active_inputs=set, admin=admin
    )


@pytest.mark.parametrize(
    ("scopes", "revoked", "reason"),
    [
        (("review", "queue"), False, "not_granted"),
        (("review", "queue", "admin"), True, "revoked_device"),
    ],
)
def test_the_pc_refuses_an_admin_request_without_its_own_admin_grant(
    tmp_path, scopes, revoked, reason
):
    ledger = _ledger_with(tmp_path, scopes, revoked=revoked)
    admin = FakeAdmin()
    applier = _applier(tmp_path, ledger, admin)

    result = applier.handle(_admin_raw())

    assert (result.outcome, result.reason) == ("refused", reason)
    assert admin.seen == []  # never reaches the update service


def test_a_device_the_pc_never_bound_is_refused(tmp_path):
    applier = _applier(tmp_path, SyncLedger(tmp_path / "ledger.sqlite3"), FakeAdmin())

    result = applier.handle(_admin_raw(device_id="someone-else-01"))

    assert (result.outcome, result.reason) == ("refused", "revoked_device")


def test_without_a_remote_update_handler_the_request_is_refused(tmp_path):
    ledger = _ledger_with(tmp_path, ("review", "queue", "admin"))

    result = _applier(tmp_path, ledger).handle(_admin_raw())

    assert (result.outcome, result.reason) == ("refused", "update_unavailable")


def test_an_update_in_progress_is_neither_recorded_nor_final(tmp_path):
    ledger = _ledger_with(tmp_path, ("review", "queue", "admin"))
    admin = FakeAdmin(None)
    applier = _applier(tmp_path, ledger, admin)
    raw = _admin_raw()

    assert applier.handle(raw).outcome == IN_PROGRESS
    assert applier.handle(raw).outcome == IN_PROGRESS
    assert ledger.outcome(raw["record_id"]) is None
    assert len(admin.seen) == 2

    receipt = {"update": {"status": "applied", "old_sha": OLD, "new_sha": NEW}}
    admin.answer = lambda record: Applied(record.record_id, "applied", receipt=receipt)
    final = applier.handle(raw)
    assert final.outcome == "applied"
    assert ledger.outcome(raw["record_id"]).receipt == receipt
    # A record re-sent with the same key repeats the first receipt instead of updating twice.
    duplicate = applier.handle(_admin_raw(idempotency_key=raw["idempotency_key"]))
    assert (duplicate.outcome, duplicate.receipt) == ("duplicate", receipt)
    assert len(admin.seen) == 3


# -- the remote hand-off ---------------------------------------------------------------------------------------------


class FakeQueue:
    def __init__(self) -> None:
        self.held = False

    def hold_dispatch_for_update(self, *, reason: str) -> bool:
        self.held = True
        return True

    def release_update_hold(self) -> bool:
        self.held = False
        return True


class Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class Spawned:
    """Collects worker targets so a test runs them when it chooses (``run``), or at once (``inline``)."""

    def __init__(self, *, inline: bool = False) -> None:
        self.inline = inline
        self.targets: list = []

    def __call__(self, target, name: str) -> None:
        if self.inline:
            target()
        else:
            self.targets.append(target)

    def run(self) -> None:
        targets, self.targets = self.targets, []
        for target in targets:
            target()


class NoGit:
    def __call__(self, args):
        raise AssertionError(f"unexpected git call {args}")


@pytest.fixture
def remote(tmp_path):
    clock = Clock()
    store = lu.LiveUpdateStore(tmp_path / "state")
    launched: list[lu.UpdaterLaunch] = []
    checks: list[str | None] = []
    preflight = {"result": lambda sha: lu.Preflight(True, "", OLD, sha or NEW, commits_ahead=2)}

    def run_preflight(sha):
        checks.append(sha)
        return preflight["result"](sha)

    service = LiveUpdateService(
        store=store,
        preflight=run_preflight,
        queue=FakeQueue(),
        busy=lambda: False,
        launch_updater=launched.append,
        repo_root=tmp_path / "repo",
        pid=4242,
        clock=clock,
        sleep=clock.sleep,
    )
    spawn = Spawned()
    probe = CheckoutProbe(NoGit(), git_lock=service.git_lock, spawn=Spawned(), clock=clock)
    handler = RemoteUpdate(
        service,
        checkout=probe,
        queue_state=lambda: ("running", 2),
        spawn=spawn,
        clock=clock,
    )
    return {
        "handler": handler,
        "service": service,
        "store": store,
        "launched": launched,
        "checks": checks,
        "preflight": preflight,
        "spawn": spawn,
        "clock": clock,
    }


def _record(clock: Clock, sha: str = NEW, age: float = 0.0) -> protocol.AdminRecord:
    return protocol.parse_record(
        _admin_raw(
            created_at=protocol.utc_text(datetime.fromtimestamp(clock() - age, UTC)),
            admin_request={"action": "update_and_restart", "expected_sha": sha},
        )
    )


def test_the_switch_off_is_answered_remote_update_disabled(remote):
    record = _record(remote["clock"])

    assert remote["handler"].handle(record) is None  # started on a worker, never on the sync thread
    remote["spawn"].run()
    answer = remote["handler"].handle(record)

    assert (answer.outcome, answer.reason) == ("refused", "remote_update_disabled")
    assert answer.receipt["update"]["reason_code"] == "remote_update_disabled"
    assert remote["checks"] == [] and remote["launched"] == []


def test_a_moved_main_is_answered_target_moved(remote):
    remote["service"].set_allow_remote(True)
    remote["preflight"]["result"] = lambda sha: lu.Preflight(False, lu.TARGET_MOVED, OLD, OTHER)
    record = _record(remote["clock"])

    remote["handler"].handle(record)
    remote["spawn"].run()
    answer = remote["handler"].handle(record)

    assert remote["checks"] == [NEW]  # the phone's commit is the only value passed on
    assert (answer.outcome, answer.reason) == ("refused", "target_moved")
    assert answer.receipt["update"] == {
        "status": "refused",
        "reason_code": "target_moved",
        "source": "remote",
        "old_sha": OLD,
        "new_sha": OLD,
        "target_sha": OTHER,
        "finished_at": answer.receipt["update"]["finished_at"],
    }
    assert remote["launched"] == []


def test_an_accepted_request_stays_open_across_the_restart_and_is_answered_after_it(remote):
    remote["service"].set_allow_remote(True)
    record = _record(remote["clock"])
    handler = remote["handler"]

    assert handler.handle(record) is None
    remote["spawn"].run()
    assert remote["service"].exit_requested and len(remote["launched"]) == 1
    assert handler.handle(record) is None  # restarting: still unanswered
    status = handler.status_payload()
    validate_def(status, "pc_status")
    assert status["update"] == {
        "state": "in_progress",
        "phase": "restarting",
        "record_id": record.record_id,
    }

    # The next app: a fresh service over the same state folder finds the updater's result.
    store = remote["store"]
    intent = store.read("intent.json")
    assert intent["record_id"] == record.record_id and intent["source"] == "remote"
    store.write(
        "result.json",
        {
            "update_id": intent["update_id"],
            "status": "applied",
            "reason": "",
            "new_sha": NEW,
            "health": "unconfirmed",
            "detail": "",
            "finished_at": "2026-11-26T12:05:00Z",
        },
    )
    next_service = LiveUpdateService(
        store=store,
        preflight=lambda sha: pytest.fail("no preflight after the restart"),
        queue=FakeQueue(),
        busy=lambda: False,
        launch_updater=lambda launch: pytest.fail("no second launch"),
        repo_root=Path("unused"),
        pid=4343,
        clock=remote["clock"],
    )
    next_handler = RemoteUpdate(
        next_service,
        checkout=handler.checkout,
        queue_state=lambda: ("idle", 2),
        spawn=Spawned(),
        clock=remote["clock"],
    )
    assert next_handler.handle(record) is None  # the receipt is not collected yet
    next_service.collect_result()
    answer = next_handler.handle(record)

    assert answer.outcome == "applied" and answer.reason == ""
    assert answer.receipt["update"]["health"] == "unconfirmed"
    assert (answer.receipt["update"]["old_sha"], answer.receipt["update"]["new_sha"]) == (OLD, NEW)
    after = next_handler.status_payload()
    validate_def(after, "pc_status")
    assert after["update"] == {"state": "idle"}
    assert after["last_result"]["health"] == "unconfirmed"


def test_a_second_request_during_an_update_is_refused_in_progress(remote):
    remote["service"].set_allow_remote(True)
    first, second = _record(remote["clock"]), _record(remote["clock"])

    remote["handler"].handle(first)
    remote["spawn"].run()
    remote["handler"].handle(second)
    remote["spawn"].run()
    answer = remote["handler"].handle(second)

    assert (answer.outcome, answer.reason) == ("refused", "update_in_progress")
    assert len(remote["launched"]) == 1


def test_an_old_request_is_refused_as_expired(remote):
    remote["service"].set_allow_remote(True)
    answer = remote["handler"].handle(_record(remote["clock"], age=3 * 3600))

    assert (answer.outcome, answer.reason) == ("refused", "request_expired")
    assert remote["spawn"].targets == [] and remote["checks"] == []


def test_the_status_carries_shas_and_counts_only(remote):
    remote["service"].set_allow_remote(True)
    status = remote["handler"].status_payload()

    validate_def(status, "pc_status")
    assert status["queue"] == {"state": "running", "queued": 2}
    assert status["remote_update_enabled"] is True
    assert status["checkout"] == {}  # nothing fetched yet
    text = repr(status)
    assert "\\" not in text and "repo" not in text


# -- the checkout probe ----------------------------------------------------------------------------------------------


class ScriptedGit:
    def __init__(self, *, head=OLD, origin=NEW, fetch_code=0, behind="3") -> None:
        self.calls: list[list[str]] = []
        self.head, self.origin, self.fetch_code, self.behind = head, origin, fetch_code, behind

    def __call__(self, args):
        self.calls.append(list(args))
        if args[:1] == ["fetch"]:
            return lu.GitResult(self.fetch_code, "", "")
        if args == ["rev-parse", "HEAD"]:
            return lu.GitResult(0, self.head, "")
        if args == ["rev-parse", "refs/remotes/origin/main"]:
            return lu.GitResult(0, self.origin, "")
        if args[:2] == ["rev-list", "--count"]:
            return lu.GitResult(0, self.behind, "")
        raise AssertionError(args)


def test_the_probe_fetches_at_most_every_fifteen_minutes_and_never_on_the_caller():
    clock = Clock()
    git = ScriptedGit()
    spawn = Spawned()
    probe = CheckoutProbe(git, git_lock=threading.Lock(), spawn=spawn, clock=clock)

    assert probe.snapshot().head_sha == ""  # the first call only schedules the refresh
    assert git.calls == []
    spawn.run()
    state = probe.snapshot()
    assert (state.head_sha, state.origin_main_sha, state.commits_behind) == (OLD, NEW, 3)
    assert ["fetch", "--no-tags", "--quiet", "origin", "main"] in git.calls
    assert spawn.targets == []  # fresh: no second refresh

    clock.now += 14 * 60
    probe.snapshot()
    assert spawn.targets == []
    clock.now += 2 * 60
    probe.snapshot()
    assert len(spawn.targets) == 1


def test_the_probe_waits_while_an_update_holds_the_git_lock():
    lock = threading.Lock()
    git = ScriptedGit()
    probe = CheckoutProbe(git, git_lock=lock, spawn=Spawned(inline=True), clock=Clock())

    with lock:
        probe.refresh()
    assert git.calls == []
    probe.invalidate()
    probe.refresh()
    assert git.calls


def test_a_failed_fetch_keeps_the_last_fetch_time():
    clock = Clock()
    git = ScriptedGit()
    probe = CheckoutProbe(git, git_lock=threading.Lock(), spawn=Spawned(), clock=clock)
    first = probe.refresh()
    git.fetch_code = 128
    clock.now += 3600
    second = probe.refresh()

    assert second.fetched_at == first.fetched_at
    assert second.origin_main_sha == NEW  # the last fetched origin/main is still reported


# -- the sync worker ---------------------------------------------------------------------------------------------------


class _Monotonic:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _codec_store(path: Path) -> GatewaySettingsStore:
    def xor(data: bytes) -> bytes:
        return bytes(byte ^ 0x5A for byte in data)

    return GatewaySettingsStore(path, protect=xor, unprotect=xor)


class StaticRemote:
    def __init__(self) -> None:
        self.payload = protocol.pc_status(
            head_sha=OLD,
            origin_main_sha=NEW,
            queue_state="idle",
            queued=0,
            remote_update_enabled=True,
        )
        self.answers: dict[str, object] = {}
        self.handled: list[str] = []

    def status_payload(self):
        return self.payload

    def handle(self, record):
        self.handled.append(record.record_id)
        return self.answers.get(record.record_id)


@pytest.fixture
def worker(tmp_path):
    gateway = FakeGateway()
    ledger = SyncLedger(tmp_path / "ledger.sqlite3")
    applier = RecordApplier(ledger, tmp_path / "out", tmp_path / "records.jsonl", active_inputs=set)
    clock = _Monotonic()
    sync = ReviewGatewaySync(
        settings_store=_codec_store(tmp_path / "settings.bin"),
        ledger=ledger,
        publisher_factory=lambda: None,
        applier=applier,
        transport_factory=lambda _settings: gateway,
        monotonic=clock,
    )
    sync.configure("192.168.1.50", FINGERPRINT, SECRET)
    yield sync, gateway, ledger, clock
    ledger.close()


def test_the_admin_offer_carries_the_admin_grant_only_when_asked(worker):
    sync, gateway, ledger, _clock = worker
    sync.create_pairing("Pixel")
    sync.create_pairing("Pixel", allow_update=True)
    sync.run_cycle()

    assert [offer["scopes"] for offer in gateway.offers] == [
        ["review", "queue"],
        ["review", "queue", "admin"],
    ]
    device = gateway.enroll(gateway.offers[-1])
    sync.run_cycle()
    assert "admin" in ledger.device(device).scopes


def test_no_status_is_sent_until_remote_update_is_attached(worker):
    sync, gateway, _ledger, _clock = worker
    sync.run_cycle()
    assert gateway.statuses == []


def test_the_status_is_sent_when_it_changes_and_as_a_heartbeat(worker):
    sync, gateway, _ledger, clock = worker
    remote = StaticRemote()
    sync.attach_remote_update(remote)

    sync.run_cycle()
    sync.run_cycle()
    assert len(gateway.statuses) == 1
    remote.payload = {**remote.payload, "queue": {"state": "running", "queued": 1}}
    sync.run_cycle()
    assert len(gateway.statuses) == 2
    clock.now += STATUS_HEARTBEAT_SECONDS + 1
    sync.run_cycle()
    assert len(gateway.statuses) == 3


def test_an_older_gateway_without_the_status_route_does_not_break_sync(worker):
    sync, gateway, _ledger, _clock = worker
    gateway.offers_pc_status = False
    sync.attach_remote_update(StaticRemote())

    sync.run_cycle()
    sync.run_cycle()

    assert sync.status().state == "idle"
    assert gateway.calls.count(("PUT", "/sync/v1/pc-status")) == 1  # asked again only later


def test_an_update_in_progress_is_not_acknowledged_until_it_has_a_receipt(worker):
    sync, gateway, ledger, _clock = worker
    sync.create_pairing("Pixel", allow_update=True)
    sync.run_cycle()
    gateway.enroll(gateway.offers[-1])
    remote = StaticRemote()
    sync.attach_remote_update(remote)
    record = gateway.update_request(NEW)

    sync.run_cycle()
    sync.run_cycle()
    assert gateway.acks == []
    assert remote.handled == [record["record_id"]] * 2
    assert ledger.outcome(record["record_id"]) is None

    remote.answers[record["record_id"]] = Applied(
        record["record_id"],
        "applied",
        receipt={
            "update": protocol.update_receipt(
                {"status": "applied", "old_sha": OLD, "new_sha": NEW, "health": "unconfirmed"}
            )
        },
    )
    sync.run_cycle()
    (ack,) = gateway.acks
    assert ack["outcome"] == "applied"
    assert ack["receipt"]["update"] == {
        "status": "applied",
        "old_sha": OLD,
        "new_sha": NEW,
        "health": "unconfirmed",
    }


# -- invariants -------------------------------------------------------------------------------------------------------


def test_the_remote_module_names_no_queue_runner_or_job_service():
    tree = ast.parse((SRC / "app" / "live_update_remote.py").read_text(encoding="utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom | ast.Import)
        for alias in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert not {"JobService", "run_njr", "submit_njrs", "JobQueue"} & (names | imported)
    assert not any(str(module).startswith("src.queue") for module in imported)


def test_the_composed_queue_view_is_counts_only(remote):
    from types import SimpleNamespace

    from src.app.runtime_stack import build_remote_update
    from src.queue.job_model import JobStatus

    class Queue:
        paused = False
        jobs = {JobStatus.QUEUED: ["j1", "j2", "j3"], JobStatus.RUNNING: []}

        def list_jobs(self, status_filter=None):
            return list(self.jobs.get(status_filter, []))

        def is_paused(self):
            return self.paused

    queue = Queue()
    runner = SimpleNamespace(current_job_id=None)
    app = SimpleNamespace(job_service=SimpleNamespace(job_queue=queue, runner=runner))
    built = build_remote_update(app, remote["service"], spawn=Spawned())

    assert built.status_payload()["queue"] == {"state": "idle", "queued": 3}
    queue.paused = True
    assert built.status_payload()["queue"] == {"state": "paused", "queued": 3}
    runner.current_job_id = "job-1"
    assert built.status_payload()["queue"] == {"state": "running", "queued": 3}
    unknown = build_remote_update(SimpleNamespace(), remote["service"], spawn=Spawned())
    assert unknown.status_payload()["queue"] == {"state": "unknown", "queued": 0}


@pytest.mark.parametrize("reason", [lu.NOT_GITHUB_SIGNED, lu.GITHUB_UNAVAILABLE])
def test_the_signature_refusals_reach_the_phone_with_their_own_words(reason):
    receipt = protocol.update_receipt({"status": "refused", "reason": reason, "source": "remote"})

    validate_def(receipt, "update_receipt")
    assert receipt["reason_code"] == reason
    static = SRC.parent / "services" / "review_gateway" / "review_gateway" / "static"
    page = static / "features" / "status" / "status.js"
    assert f"\n  {reason}:" in page.read_text(encoding="utf-8")
