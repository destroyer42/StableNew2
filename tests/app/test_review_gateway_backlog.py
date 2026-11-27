"""PHONE-FAST (b): gone or failing rows never block, the window rolls, and new outputs publish on job completion."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from PIL import Image

from src.app.review_gateway_client import GatewayClient
from src.app.review_gateway_publish import GatewayPublisher
from src.app.runtime_stack import build_review_gateway_sync
from src.app.site_output_library import key_for
from tests.app.test_review_gateway_sync import RUN, Env
from tests.helpers.review_gateway_fakes import SECRET

DAY = 86400


@pytest.fixture
def env(tmp_path):
    environment = Env(tmp_path)
    environment.large.unlink()
    environment.small.unlink()
    yield environment
    environment.close()


def image(env, name: str, *, age_s: float = 0) -> str:
    """Write one PNG whose file time is ``age_s`` ago; returns its library key."""

    path = env.root / RUN / name
    Image.new("RGB", (64, 48), (len(name) * 7 % 255, 80, 120)).save(path)
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))
    return key_for(f"{RUN}/{name}")


def indexed(env, count: int) -> None:
    env.library.start(refresh=True)
    deadline = time.monotonic() + 30
    while True:
        with env.library.store.connection() as db:
            ready = db.execute("SELECT count(*) FROM media WHERE enriched = 1").fetchone()[0]
        if ready >= count:
            return
        assert time.monotonic() < deadline, "the index did not see the files"
        time.sleep(0.02)


def publish(env, publisher=None, *, limit: int = 8, **options):
    return (publisher or env.publisher).publish(
        GatewayClient(env.gateway, SECRET), limit=limit, cancel=Event(), **options
    )


def state(env, key: str) -> str | None:
    row = env.ledger.published(key)
    return None if row is None else row["state"]


def stop_indexing(env, monkeypatch) -> None:
    """Keep rows for files removed after indexing, as a stale index does."""

    env.library.close()
    deadline = time.monotonic() + 30
    while env.library.store.running:
        env.library.store.wake.set()
        assert time.monotonic() < deadline
        time.sleep(0.02)
    monkeypatch.setattr(env.library, "start", lambda **_: None)


def stale_index(env, monkeypatch, count: int) -> None:
    indexed(env, count)
    cancel = env.library.store.cancel
    if cancel is not None:
        cancel.set()
    stop_indexing(env, monkeypatch)


def test_rows_whose_file_is_gone_are_marked_and_never_block_older_rows(env, monkeypatch):
    older = image(env, "older.png", age_s=600)
    gone = [image(env, f"gone{index}.png", age_s=index) for index in range(3)]
    stale_index(env, monkeypatch, 4)
    for index in range(3):
        (env.root / RUN / f"gone{index}.png").unlink()
    assert publish(env, limit=1).published == 1
    assert state(env, older) == "published"
    assert [state(env, key) for key in gone] == ["missing"] * 3


def test_a_missing_row_is_looked_at_again_after_a_day(env, monkeypatch):
    clock = [datetime.now(UTC)]
    publisher = GatewayPublisher(env.library, env.ledger, transcode=None, now=lambda: clock[0])
    key = image(env, "back.png")
    stale_index(env, monkeypatch, 1)
    path = env.root / RUN / "back.png"
    held = path.read_bytes()
    stat = path.stat()
    path.rename(path.with_suffix(".away"))
    publish(env, publisher)
    assert state(env, key) == "missing"
    path.with_suffix(".away").rename(path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.read_bytes() == held
    assert [k for k, _ in publisher.candidates(8)] == []
    clock[0] += timedelta(days=1, minutes=1)
    assert [k for k, _ in publisher.candidates(8)] == [key]


def test_a_published_row_whose_file_is_gone_keeps_its_ledger_state(env, monkeypatch):
    key = image(env, "kept.png")
    indexed(env, 1)
    assert publish(env).published == 1
    with env.ledger._transaction() as db:
        db.execute("UPDATE published SET version = 'changed' WHERE library_id = ?", (key,))
    stale_index(env, monkeypatch, 1)
    (env.root / RUN / "kept.png").unlink()
    publish(env)
    assert state(env, key) == "published"  # the applier still resolves decisions through it


def test_a_row_that_fails_is_set_aside_so_older_rows_publish(env, monkeypatch):
    older = image(env, "older.png", age_s=600)
    newer = image(env, "newer.png")
    indexed(env, 2)
    original = env.publisher._publish_one

    def failing(client, key, item, cancel, allow_transcode):
        if key == newer:
            raise OSError("unreadable")
        return original(client, key, item, cancel, allow_transcode)

    monkeypatch.setattr(env.publisher, "_publish_one", failing)
    assert publish(env, limit=1).pending == 1
    assert publish(env, limit=1).published == 1
    assert state(env, older) == "published"


def _meta(env, name: str, when: datetime) -> None:
    env.ledger.set_meta({name: str(int(when.timestamp() * 1_000_000))})


def test_the_window_rolls_once_the_publisher_has_caught_up(env):
    now = datetime.now(UTC)
    _meta(env, "publish_since", now - timedelta(days=40))
    old = image(env, "old.png", age_s=10 * DAY)
    indexed(env, 1)
    # Never caught up: nothing since the first window is lost.
    assert [k for k, _ in env.publisher.candidates(8)] == [old]
    publish(env)
    assert env.publisher.candidates(8) == []
    # Caught up now, so the window is the last three days.
    assert env.publisher.window_start() >= int((time.time() - 3.1 * DAY) * 1_000_000)


def test_the_window_reaches_back_to_the_last_time_it_caught_up(env):
    now = datetime.now(UTC)
    _meta(env, "publish_since", now - timedelta(days=40))
    _meta(env, "publish_caught_up_at", now - timedelta(days=10))
    assert env.publisher.window_start() == int((now - timedelta(days=11)).timestamp() * 1_000_000)


def test_newer_than_leaves_the_backlog_alone(env):
    image(env, "backlog.png", age_s=3600)
    fresh = image(env, "fresh.png")
    indexed(env, 2)
    since = int((time.time() - 900) * 1_000_000)
    assert [k for k, _ in env.publisher.candidates(8, newer_than=since)] == [fresh]


def test_a_completed_job_publishes_its_outputs_at_once_while_the_next_one_runs(tmp_path):
    clock = [1000.0]
    environment = Env(tmp_path, busy=lambda: True, monotonic=lambda: clock[0])
    try:
        environment.sync.run_cycle()  # spends the busy slot
        for index in range(3):
            image(environment, f"fresh{index}.png")
        indexed(environment, 5)
        before = len(environment.gateway.manifests)
        environment.sync.run_cycle()
        assert len(environment.gateway.manifests) == before  # still inside the busy interval
        environment.sync.notify_job_completed()
        environment.sync.run_cycle()
        assert len(environment.gateway.manifests) == 5
    finally:
        environment.close()


def test_the_running_app_tells_the_worker_when_a_job_completes(tmp_path):
    handlers = []

    class Jobs:
        def register_completion_handler(self, handler):
            handlers.append(handler)

    class App:
        job_service = Jobs()

    sync = build_review_gateway_sync(
        App(), state_dir=tmp_path / "state", records_path=tmp_path / "records.jsonl"
    )
    assert len(handlers) == 1
    handlers[0](object(), object())
    assert sync.fresh_outputs_wanted()
