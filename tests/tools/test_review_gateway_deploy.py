"""DEPLOY-2, PC side: ask the gateway to deploy a commit over the authenticated sync channel and wait for the result."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.app.review_gateway_client import GatewayClient, GatewayUnavailable, Response
from tools import review_gateway_deploy as tool

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (ROOT / "docs" / "schemas" / "stablenew.review-gateway-sync.v1.json").read_text(
        encoding="utf-8"
    )
)
NEW = "ab" * 20
OLD = "cd" * 20
SECRET = "pc-side-test-secret-0123456789-abcdefgh"


def validate(name: str, payload: object) -> None:
    Draft202012Validator({"$defs": SCHEMA["$defs"], "$ref": f"#/$defs/{name}"}).validate(payload)


def last(request_id: str | None, outcome: str, **extra) -> dict:
    return {
        "action": "deploy",
        "request_id": request_id,
        "target": NEW,
        "old_commit": OLD,
        "new_commit": NEW if outcome == "deployed" else None,
        "outcome": outcome,
        "schema_changed": False,
        "finished_at": None if outcome == "running" else "2026-11-26T15:01:00Z",
        **extra,
    }


class Gateway:
    """A scripted sync listener: the first POST answers ``post``; each status GET pops the next scripted state."""

    def __init__(self, post: tuple[int, dict] = (202, {}), states: list | None = None) -> None:
        self.post = post
        self.states = list(states or [])
        self.requests: list[tuple[str, str, dict, bytes | None]] = []
        self.request_id: str | None = None

    def request(self, method, path, *, headers, body, timeout, limit) -> Response:
        self.requests.append((method, path, dict(headers), body))
        assert headers["Authorization"] == f"Bearer {SECRET}"
        if method == "POST" and path == "/sync/v1/deploy-requests":
            payload = json.loads(body)
            validate("deploy_request", payload)
            self.request_id = payload["request_id"]
            status, reply = self.post
            reply = reply or {"status": "accepted", "request_id": self.request_id}
            return Response(status, json.dumps(reply).encode())
        if method == "GET" and path == "/sync/v1/deploy-status":
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            if state == "down":
                raise GatewayUnavailable("gateway_unreachable")
            if isinstance(state, tuple):
                return Response(state[0], b"")
            document = {
                "schema_version": "stablenew.review-gateway-sync.v1",
                "type": "deploy_status",
                "remote_deploy": "enabled",
                "deployed_commit": OLD,
                "pending": None,
                "last": None,
            }
            document.update(state(self.request_id) if callable(state) else state)
            validate("deploy_status", document)
            return Response(200, json.dumps(document).encode())
        raise AssertionError((method, path))


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def run(gateway: Gateway, *argv: str) -> tuple[int, Clock]:
    clock = Clock()
    code = tool.main(
        list(argv),
        client=GatewayClient(gateway, SECRET),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    return code, clock


def test_a_deploy_is_requested_and_followed_to_its_outcome(capsys) -> None:
    gateway = Gateway(
        states=[
            lambda rid: {"pending": {"request_id": rid, "target_sha": NEW}},
            lambda rid: {"last": last(rid, "running")},
            "down",  # the gateway restarts into the new release
            lambda rid: {"deployed_commit": NEW, "last": last(rid, "deployed")},
        ]
    )

    code, _ = run(gateway, "request", NEW)

    assert code == 0
    out = capsys.readouterr().out
    assert f"{OLD[:12]} -> {NEW[:12]}" in out and out.rstrip().endswith("outcome: deployed")
    methods = [(method, path) for method, path, _, _ in gateway.requests]
    assert methods[0] == ("POST", "/sync/v1/deploy-requests")
    assert all(entry == ("GET", "/sync/v1/deploy-status") for entry in methods[1:])


def test_the_result_of_another_request_is_never_taken_for_this_one(capsys) -> None:
    gateway = Gateway(
        states=[
            {"last": last("11111111-1111-4111-8111-111111111111", "deployed")},
            lambda rid: {"last": last(rid, "rolled_back")},
        ]
    )

    code, _ = run(gateway, "request", NEW)

    assert code == tool.EXIT_REFUSED
    assert capsys.readouterr().out.rstrip().endswith("outcome: rolled_back")


def test_a_schema_change_tells_the_owner_to_update_the_pc_too(capsys) -> None:
    gateway = Gateway(states=[lambda rid: {"last": last(rid, "deployed", schema_changed=True)}])

    assert run(gateway, "request", NEW)[0] == 0
    assert "update StableNew on the PC" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("post", "message"),
    [
        ((409, {"error": "remote_deploy_disabled"}), "review-gateway-deploy remote on"),
        ((409, {"error": "deploy_pending"}), "another deploy request is waiting"),
        ((404, {"error": "not_found"}), "does not offer remote deploy yet"),
        ((422, {"error": "invalid_payload"}), "refused the request"),
    ],
)
def test_a_refused_request_says_why_and_does_not_wait(capsys, post, message) -> None:
    gateway = Gateway(post=post, states=[{}])

    code, _ = run(gateway, "request", NEW)

    assert code == tool.EXIT_REFUSED
    assert message in capsys.readouterr().out
    assert len(gateway.requests) == 1


@pytest.mark.parametrize("sha", ["main", NEW.upper(), NEW[:39], "origin/main"])
def test_only_a_full_commit_sha_is_sent(capsys, sha) -> None:
    gateway = Gateway(states=[{}])

    assert run(gateway, "request", sha)[0] == tool.EXIT_USAGE
    assert gateway.requests == []


def test_waiting_ends_after_the_time_limit(capsys) -> None:
    gateway = Gateway(states=[lambda rid: {"last": last(rid, "running")}])

    code, clock = run(gateway, "request", NEW, "--timeout", "120")

    assert code == tool.EXIT_TIMEOUT
    assert 120 <= clock.now <= 120 + tool.POLL_SECONDS
    assert "still running" in capsys.readouterr().out


def test_no_wait_returns_once_the_gateway_has_the_request(capsys) -> None:
    gateway = Gateway(states=[{}])

    assert run(gateway, "request", NEW, "--no-wait")[0] == 0
    assert len(gateway.requests) == 1


def test_status_prints_the_switch_the_commit_and_the_last_result(capsys) -> None:
    gateway = Gateway(states=[{"last": last(None, "deployed")}])

    assert run(gateway, "status")[0] == 0
    out = capsys.readouterr().out
    assert "remote deploy: enabled" in out and f"deployed: {OLD}" in out and "last: deployed" in out


def test_an_old_gateway_without_the_route_is_reported(capsys) -> None:
    gateway = Gateway(states=[(404,)])

    assert run(gateway, "status")[0] == tool.EXIT_REFUSED
    assert "does not offer remote deploy yet" in capsys.readouterr().out


def test_the_tool_reads_only_the_pc_settings_and_uses_the_pinned_transport(
    monkeypatch, tmp_path
) -> None:
    from src.app import review_gateway_store

    captured = {}

    class Store:
        def load(self):
            return review_gateway_store.GatewaySettings.build("192.0.2.10:9443", "0" * 64, SECRET)

    class Transport:
        def __init__(self, settings) -> None:
            captured["settings"] = settings

    monkeypatch.setattr(tool, "GatewaySettingsStore", Store)
    monkeypatch.setattr(tool, "PinnedHttpsTransport", Transport)

    client = tool.default_client()

    assert isinstance(client, GatewayClient)
    assert captured["settings"].host == "192.0.2.10" and captured["settings"].port == 9443


def test_without_gateway_settings_the_tool_says_where_to_enter_them(monkeypatch, capsys) -> None:
    class Store:
        def load(self):
            return None

    monkeypatch.setattr(tool, "GatewaySettingsStore", Store)

    assert tool.main(["status"]) == tool.EXIT_USAGE
    assert "Phone review gateway" in capsys.readouterr().err
