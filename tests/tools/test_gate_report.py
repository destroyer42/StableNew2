"""The phone open-time report: the figures, the client's paging and the tool, against the real gateway in process."""

from __future__ import annotations

import json
from datetime import UTC, timedelta, timezone

import pytest

from src.app.review_gateway_client import GatewayClient, GatewayError, Response
from tests.app.test_review_gateway_ratings import AppTransport
from tests.review_gateway_service.conftest import SECRET, FakeClock, Rig
from tools import gate_report

EASTERN = timezone(timedelta(hours=-5))


def row(at: str, ms: int, source: str = "network", size: int | None = 86_000) -> dict:
    return {"at": at, "ms": ms, "source": source, "bytes": size}


def test_each_local_day_has_its_median_p90_and_cache_hit_share() -> None:
    # 02:00Z is still the evening before, five hours behind UTC.
    rows = [row("2026-11-28T02:00:00.000000Z", 900)]
    rows += [
        row("2026-11-28T15:00:00.000000Z", ms, source, size)
        for ms, source, size in [
            (100, "prefetch", 80_000),
            (200, "cache", 90_000),
            (300, "network", 100_000),
            (400, "network", None),
            (500, "unknown", None),
        ]
    ]

    days = gate_report.summarize(rows, EASTERN)

    assert [day["day"] for day in days] == ["2026-11-27", "2026-11-28", "all"]
    assert days[1] == {
        "day": "2026-11-28",
        "views": 5,
        "median_ms": 300,
        "p90_ms": 500,
        "network": 2,
        "cache": 1,
        "prefetch": 1,
        "unknown": 1,
        "cache_hit_share": 0.5,  # of the four whose source is known
        "median_bytes": 90_000,
    }
    assert days[2]["views"] == 6
    assert days[2]["median_ms"] == 350


def test_the_p90_is_a_time_that_was_measured() -> None:
    rows = [row("2026-11-28T15:00:00.000000Z", ms) for ms in range(10, 210, 10)]

    (day, _total) = gate_report.summarize(rows, UTC)

    assert day["p90_ms"] == 180  # the 18th of 20: at least nine in ten were this fast or faster
    assert day["median_ms"] == 105


def test_a_day_with_nothing_known_has_no_share_or_size() -> None:
    (day, _total) = gate_report.summarize(
        [row("2026-11-28T15:00:00.000000Z", 5, "unknown", None)], UTC
    )

    assert day["cache_hit_share"] is None
    assert day["median_bytes"] is None


def test_no_rows_is_no_days() -> None:
    assert gate_report.summarize([], UTC) == []


class Scripted:
    def __init__(self, *replies: tuple[int, object]) -> None:
        self.replies = list(replies)
        self.paths: list[str] = []

    def request(self, method, path, *, headers, body, timeout, limit) -> Response:
        assert method == "GET" and headers["Authorization"] == f"Bearer {SECRET}"
        self.paths.append(path)
        status, reply = self.replies.pop(0)
        return Response(status, json.dumps(reply).encode())


def test_the_client_follows_the_cursor_to_the_last_page() -> None:
    first = {"rows": [row("2026-11-28T15:00:00.000000Z", 1)], "next_cursor": 7}
    last = {"rows": [row("2026-11-28T15:00:00.000000Z", 2)], "next_cursor": None}
    transport = Scripted((200, first), (200, last))

    found = GatewayClient(transport, SECRET).open_timings()

    assert found is not None and [entry["ms"] for entry in found] == [1, 2]
    assert transport.paths == [
        "/sync/v1/open-timings?cursor=0",
        "/sync/v1/open-timings?cursor=7",
    ]


@pytest.mark.parametrize(
    "reply",
    [
        [],
        {"rows": []},
        {"rows": {}, "next_cursor": None},
        {"rows": [], "next_cursor": 0},  # a cursor that does not move would never end
        {"rows": [], "next_cursor": True},
        {"rows": [{"at": "2026-11-28T15:00:00Z", "ms": 1}], "next_cursor": None},
        {"rows": [row("not a time", 1)], "next_cursor": None},
        {"rows": [row("2026-11-28T15:00:00", 1)], "next_cursor": None},
        {"rows": [row("2026-11-28T15:00:00Z", -1)], "next_cursor": None},
        {"rows": [row("2026-11-28T15:00:00Z", 1, "disk")], "next_cursor": None},
        {"rows": [row("2026-11-28T15:00:00Z", 1, "cache", -5)], "next_cursor": None},
    ],
)
def test_the_client_refuses_a_reply_it_does_not_understand(reply) -> None:
    with pytest.raises(GatewayError, match="invalid_gateway_response"):
        GatewayClient(Scripted((200, reply)), SECRET).open_timings()


def test_an_older_gateway_offers_no_timings() -> None:
    assert GatewayClient(Scripted((404, {})), SECRET).open_timings() is None


def test_the_report_reads_what_a_phone_sent_to_the_gateway(tmp_path, capsys) -> None:
    rig = Rig(tmp_path / "gateway", FakeClock())
    try:
        rig.pair()
        samples = [
            {"ms": 120, "source": "prefetch", "bytes": 86_000},
            {"ms": 480, "source": "network", "bytes": 90_000},
        ]
        sent = rig.phone.post(
            "/api/timings", json={"idempotency_key": "k" * 32, "samples": samples}
        )
        assert sent.status_code == 200, sent.text

        code = gate_report.main([], client=GatewayClient(AppTransport(rig), SECRET))
    finally:
        rig.close()

    out = capsys.readouterr().out
    assert code == gate_report.EXIT_OK
    lines = [line.split() for line in out.splitlines()]
    # views, median, p90, cache-hit share, network, cache, prefetch, unknown, median KB
    assert ["all", "2", "300", "480", "50%", "1", "0", "1", "0", "88"] in lines


def test_the_report_can_be_read_as_json(capsys) -> None:
    reply = {"rows": [row("2026-11-28T15:00:00.000000Z", 5)], "next_cursor": None}

    code = gate_report.main(["--json"], client=GatewayClient(Scripted((200, reply)), SECRET))

    assert code == 0
    assert [day["day"] for day in json.loads(capsys.readouterr().out)][-1] == "all"


@pytest.mark.parametrize(
    ("reply", "code", "words"),
    [
        ((200, {"rows": [], "next_cursor": None}), 0, "No open times"),
        ((404, {}), 1, "not offer"),
        ((401, {}), 1, "sync secret"),
        ((500, {}), 1, "unexpectedly"),
    ],
)
def test_the_report_says_why_there_is_nothing_to_show(reply, code, words, capsys) -> None:
    assert gate_report.main([], client=GatewayClient(Scripted(reply), SECRET)) == code
    assert words in capsys.readouterr().out
