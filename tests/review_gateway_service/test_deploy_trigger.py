"""DEPLOY-2: the PC asks the gateway to deploy a commit; the root deployer picks the request up and re-checks everything.

Gateway side: ``POST /sync/v1/deploy-requests`` and ``GET /sync/v1/deploy-status`` on the sync listener only, behind the
console switch (on by default, owner decision 2). Root side: ``review-gateway-deploy from-request`` reads the one request
file without following links, deletes it, re-reads the switch and runs the same forward-only deploy as the console.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import pytest

from tests.review_gateway_service.conftest import ROOT, SCHEMA_VERSION, Rig
from tests.review_gateway_service.test_deployer import NEW, OLD, history, make_rig

DEPLOY_ROOT = ROOT / "services" / "deploy"
if str(DEPLOY_ROOT) not in sys.path:
    sys.path.insert(0, str(DEPLOY_ROOT))

import stablenew_deploy as deploy  # noqa: E402

REQUEST_ID = "3f2b8c1e-5d4a-4e7b-9c0d-1a2b3c4d5e6f"


@pytest.fixture
def deploy_rig(tmp_path: Path):
    return make_rig(tmp_path / "root")


@pytest.fixture
def gateway(tmp_path: Path, clock):
    switch = tmp_path / "etc" / "remote-deploy"
    switch.parent.mkdir()
    switch.write_text("enabled\n", encoding="utf-8")
    deploy_dir = tmp_path / "deploy"
    (deploy_dir / "inbox").mkdir(parents=True)
    release = tmp_path / "release"
    release.mkdir()
    (release / "source.json").write_text(json.dumps({"commit": OLD}), encoding="utf-8")
    instance = Rig(
        tmp_path / "gw",
        clock,
        deploy_switch_file=switch,
        deploy_dir=deploy_dir,
        release_dir=release,
    )
    yield instance
    instance.close()


def body(sha: str = NEW, request_id: str = REQUEST_ID, **extra) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "deploy_request",
        "request_id": request_id,
        "target_sha": sha,
        "requested_at": "2026-11-26T15:00:00Z",
        **extra,
    }


def inbox(rig: Rig) -> Path:
    return rig.settings.deploy_dir / "inbox" / "request.json"


# --- the gateway's routes --------------------------------------------------------------------------------------------


def test_a_request_is_handed_to_the_root_deployer_as_one_small_file(gateway) -> None:
    response = gateway.sync.post("/sync/v1/deploy-requests", json=body())

    assert response.status_code == 202, response.text
    assert response.json() == {"status": "accepted", "request_id": REQUEST_ID}
    assert json.loads(inbox(gateway).read_text(encoding="utf-8")) == {
        "request_id": REQUEST_ID,
        "target_sha": NEW,
        "requested_at": "2026-11-26T15:00:00Z",
    }
    assert [path.name for path in inbox(gateway).parent.iterdir()] == ["request.json"]


@pytest.mark.parametrize(
    "payload",
    [
        body(sha="main"),
        body(sha=("ab" * 20).upper()),
        body(sha=NEW + "\n"),
        body(request_id="not-a-uuid"),
        body(ref="refs/heads/main"),
        {k: v for k, v in body().items() if k != "target_sha"},
    ],
)
def test_anything_but_a_commit_sha_and_a_request_id_is_refused(gateway, payload) -> None:
    response = gateway.sync.post("/sync/v1/deploy-requests", json=payload)

    assert response.status_code == 422
    assert not inbox(gateway).exists()


def test_the_console_switch_off_refuses_without_writing_anything(gateway) -> None:
    gateway.settings.deploy_switch_file.write_text("disabled\n", encoding="utf-8")

    response = gateway.sync.post("/sync/v1/deploy-requests", json=body())

    assert response.status_code == 409 and response.json() == {"error": "remote_deploy_disabled"}
    assert not inbox(gateway).exists()


@pytest.mark.parametrize("content", [None, "", "yes", "enabled-ish", "ENABLED"])
def test_a_missing_or_unclear_switch_counts_as_off(gateway, content) -> None:
    if content is None:
        gateway.settings.deploy_switch_file.unlink()
    else:
        gateway.settings.deploy_switch_file.write_text(content, encoding="utf-8")

    assert gateway.sync.post("/sync/v1/deploy-requests", json=body()).status_code == 409


def test_a_second_request_while_one_waits_is_refused_and_a_repeat_is_accepted(gateway) -> None:
    assert gateway.sync.post("/sync/v1/deploy-requests", json=body()).status_code == 202

    repeat = gateway.sync.post("/sync/v1/deploy-requests", json=body())
    other = gateway.sync.post("/sync/v1/deploy-requests", json=body(request_id=str(uuid.uuid4())))

    assert repeat.status_code == 202
    assert other.status_code == 409 and other.json() == {"error": "deploy_pending"}


def test_the_routes_need_the_sync_secret(gateway) -> None:
    anonymous = gateway.client(gateway.gateway.sync_app())

    assert anonymous.post("/sync/v1/deploy-requests", json=body()).status_code == 401
    assert anonymous.get("/sync/v1/deploy-status").status_code == 401
    assert not inbox(gateway).exists()


def test_the_phone_app_has_no_deploy_route(gateway) -> None:
    for method, path in (("POST", "/sync/v1/deploy-requests"), ("GET", "/sync/v1/deploy-status")):
        response = gateway.phone.request(method, path, json=body() if method == "POST" else None)
        assert response.status_code == 404, path
    assert not inbox(gateway).exists()


def test_status_reports_the_switch_the_deployed_commit_and_the_waiting_request(gateway) -> None:
    gateway.sync.post("/sync/v1/deploy-requests", json=body())

    status = gateway.sync.get("/sync/v1/deploy-status").json()

    gateway.gateway.contract.validate("deploy_status", status)
    assert status["remote_deploy"] == "enabled"
    assert status["deployed_commit"] == OLD
    assert status["pending"] == {"request_id": REQUEST_ID, "target_sha": NEW}
    assert status["last"] is None


def test_status_passes_on_only_the_checked_fields_of_the_last_result(gateway) -> None:
    last = {
        "action": "deploy",
        "request_id": REQUEST_ID,
        "target": NEW,
        "old_commit": OLD,
        "new_commit": NEW,
        "outcome": "deployed",
        "schema_changed": True,
        "finished_at": "2026-11-26T15:01:00Z",
        "new_release": "20261126T150000Z-1",
        "rollback_problem": "<script>",
        "detail": "x" * 10_000,
    }
    (gateway.settings.deploy_dir / "last.json").write_text(json.dumps(last), encoding="utf-8")

    status = gateway.sync.get("/sync/v1/deploy-status").json()

    gateway.gateway.contract.validate("deploy_status", status)
    assert status["last"] == {
        "action": "deploy",
        "request_id": REQUEST_ID,
        "target": NEW,
        "old_commit": OLD,
        "new_commit": NEW,
        "outcome": "deployed",
        "schema_changed": True,
        "finished_at": "2026-11-26T15:01:00Z",
    }


def test_a_damaged_last_result_reads_as_none(gateway) -> None:
    (gateway.settings.deploy_dir / "last.json").write_text("{not json", encoding="utf-8")
    assert gateway.sync.get("/sync/v1/deploy-status").json()["last"] is None

    (gateway.settings.deploy_dir / "last.json").write_text(
        json.dumps({"outcome": "Bad Outcome!"}), encoding="utf-8"
    )
    assert gateway.sync.get("/sync/v1/deploy-status").json()["last"]["outcome"] is None


def test_the_schema_offers_both_payloads() -> None:
    schema = json.loads(
        (ROOT / "docs" / "schemas" / f"{SCHEMA_VERSION}.json").read_text(encoding="utf-8")
    )
    refs = {entry["$ref"] for entry in schema["oneOf"]}

    assert {"#/$defs/deploy_request", "#/$defs/deploy_status"} <= refs
    assert schema["$defs"]["deploy_request"]["properties"]["target_sha"] == {
        "$ref": "#/$defs/commit_sha"
    }
    assert schema["$defs"]["commit_sha"]["pattern"] == "^[0-9a-f]{40}$"
    assert schema["$defs"]["deploy_request"]["additionalProperties"] is False


# --- the root side: from-request and the switch -----------------------------------------------------------------------


def write_request(layout: deploy.Layout, payload: object, *, raw: bytes | None = None) -> Path:
    path = layout.inbox / "request.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw if raw is not None else json.dumps(payload).encode())
    return path


def remote(layout: deploy.Layout, state: str) -> None:
    layout.switch.parent.mkdir(parents=True, exist_ok=True)
    layout.switch.write_text(state + "\n", encoding="utf-8")


REQUEST = {"request_id": REQUEST_ID, "target_sha": NEW, "requested_at": "2026-11-26T15:00:00Z"}


def test_from_request_deploys_forward_only_and_records_the_request(deploy_rig) -> None:
    layout, system = deploy_rig
    remote(layout, "enabled")
    path = write_request(layout, REQUEST)

    outcome = deploy.from_request(system=system, layout=layout)

    assert outcome.code == "deployed"
    assert not path.exists()
    record = history(layout)[-1]
    assert (
        record["trigger"] == "remote"
        and record["request_id"] == REQUEST_ID
        and record["allow_downgrade"] is False
    )


def test_from_request_never_allows_a_downgrade(deploy_rig) -> None:
    layout, system = deploy_rig
    remote(layout, "enabled")
    system.compare[(OLD, NEW)] = "behind"
    write_request(layout, REQUEST)

    assert deploy.from_request(system=system, layout=layout).code == "downgrade"


def test_from_request_rereads_the_switch_itself(deploy_rig) -> None:
    layout, system = deploy_rig
    remote(layout, "disabled")
    path = write_request(layout, REQUEST)

    outcome = deploy.from_request(system=system, layout=layout)

    assert outcome.code == "remote_deploy_disabled"
    assert not path.exists() and system.urls == [] and system.calls == []
    assert history(layout)[-1]["request_id"] == REQUEST_ID


def test_from_request_without_a_request_does_nothing(deploy_rig) -> None:
    layout, system = deploy_rig
    remote(layout, "enabled")

    outcome = deploy.from_request(system=system, layout=layout)

    assert outcome.code == "no_request" and outcome.exit_code == 0
    assert system.urls == [] and not layout.history.exists()


@pytest.mark.parametrize(
    "raw",
    [
        b"{not json",
        json.dumps({**REQUEST, "extra": 1}).encode(),
        json.dumps({**REQUEST, "target_sha": "main"}).encode(),
        json.dumps({**REQUEST, "target_sha": "--upload-pack=x" + "0" * 25}).encode(),
        json.dumps({**REQUEST, "request_id": "../../etc"}).encode(),
        json.dumps([REQUEST]).encode(),
        b"x" * (deploy.REQUEST_LIMIT + 1),
    ],
)
def test_a_request_file_the_service_could_have_shaped_is_refused(deploy_rig, raw: bytes) -> None:
    layout, system = deploy_rig
    remote(layout, "enabled")
    path = write_request(layout, None, raw=raw)

    outcome = deploy.from_request(system=system, layout=layout)

    assert outcome.code == "bad_request"
    assert not path.exists() and system.urls == [] and system.calls == []


def test_a_request_that_is_a_link_is_refused_without_reading_its_target(
    deploy_rig, tmp_path: Path
) -> None:
    layout, system = deploy_rig
    remote(layout, "enabled")
    secret = tmp_path / "shadow"
    secret.write_text(json.dumps(REQUEST), encoding="utf-8")
    link = layout.inbox / "request.json"
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(secret, link)
    except OSError:
        pytest.skip("this Windows account cannot create symbolic links")

    outcome = deploy.from_request(system=system, layout=layout)

    assert outcome.code == "bad_request"
    assert not link.exists() and secret.exists() and system.urls == []


def test_the_console_turns_the_switch_on_and_off(deploy_rig, capsys) -> None:
    layout, system = deploy_rig

    assert deploy.main(["remote", "off"], system=system, layout=layout) == 0
    assert layout.switch.read_text(encoding="utf-8") == "disabled\n"
    assert deploy.main(["status"], system=system, layout=layout) == 0
    assert "remote:   disabled" in capsys.readouterr().out

    assert deploy.main(["remote", "on"], system=system, layout=layout) == 0
    assert layout.switch.read_text(encoding="utf-8") == "enabled\n"


def test_a_remote_deploy_marks_itself_running_before_it_starts(deploy_rig) -> None:
    layout, system = deploy_rig
    remote(layout, "enabled")
    write_request(layout, REQUEST)
    seen: list[dict] = []
    original = system.download

    def download(url, destination, limit):
        seen.append(json.loads(layout.last.read_text(encoding="utf-8")))
        return original(url, destination, limit)

    system.download = download

    assert deploy.from_request(system=system, layout=layout).code == "deployed"
    assert seen[0]["outcome"] == "running" and seen[0]["request_id"] == REQUEST_ID
    assert json.loads(layout.last.read_text(encoding="utf-8"))["outcome"] == "deployed"


# --- the installer's part ---------------------------------------------------------------------------------------------

GATEWAY = ROOT / "services" / "review_gateway"


def read(name: str) -> str:
    return (GATEWAY / name).read_text(encoding="utf-8")


def test_the_installer_turns_remote_deploy_on_once_and_never_overrides_the_console() -> None:
    script = read("install.sh")

    assert '[ -e "$ETC/remote-deploy" ] || printf \'enabled\\n\' > "$ETC/remote-deploy"' in script
    assert 'chmod 0644 "$ETC/remote-deploy"' in script


def test_the_installer_lets_the_service_write_only_the_inbox() -> None:
    script = read("install.sh")

    assert 'install -d -m 0755 "$DEPLOY_STATE"' in script
    assert 'install -d -m 0700 "$DEPLOY_STATE/backups"' in script
    assert 'install -d -m 0770 -o root -g "$SERVICE_USER" "$DEPLOY_STATE/inbox"' in script


def test_the_installer_enables_the_path_unit() -> None:
    script = read("install.sh")

    for unit in ("review-gateway-deploy.path", "review-gateway-deploy.service"):
        assert f'install -m 0644 "$APP/{unit}" /etc/systemd/system/{unit}' in script
    assert "systemctl enable --now review-gateway-deploy.path" in script


def test_the_path_unit_runs_only_the_fixed_command_as_root() -> None:
    path_unit = read("review-gateway-deploy.path")
    service = read("review-gateway-deploy.service")

    assert "PathExists=/var/lib/review-gateway-deploy/inbox/request.json" in path_unit
    assert "ExecStart=/usr/local/sbin/review-gateway-deploy from-request" in service
    assert "Type=oneshot" in service and "User=" not in service
    for name in ("review-gateway-deploy.path", "review-gateway-deploy.service"):
        assert b"\r\n" not in (GATEWAY / name).read_bytes()
    assert "*.path text eol=lf" in read(".gitattributes")


# --- end to end: the PC tool, the real gateway app and the root deployer -----------------------------------------------


class _AsgiTransport:
    """The PC client's transport onto the gateway's sync app in-process (TLS and the pin are tested elsewhere)."""

    def __init__(self, client) -> None:
        self.client = client

    def request(self, method, path, *, headers, body, timeout, limit):
        from src.app.review_gateway_client import Response

        reply = self.client.request(method, path, headers=dict(headers), content=body)
        return Response(reply.status_code, reply.content[: limit + 1])


def test_the_pc_tool_the_gateway_and_the_root_deployer_complete_one_deploy(
    tmp_path: Path, clock, capsys
) -> None:
    from src.app.review_gateway_client import GatewayClient
    from tests.review_gateway_service.conftest import SECRET
    from tools import review_gateway_deploy as tool

    layout, system = make_rig(tmp_path / "root")
    remote(layout, "enabled")
    layout.inbox.mkdir(parents=True)  # install.sh creates it root:review-gateway 0770
    rig = Rig(
        tmp_path / "gw",
        clock,
        deploy_switch_file=layout.switch,
        deploy_dir=layout.state,
        release_dir=system.read_link(layout.current),
    )
    try:
        client = GatewayClient(_AsgiTransport(rig.client(rig.gateway.sync_app())), SECRET)

        assert tool.main(["request", NEW, "--no-wait"], client=client) == 0
        assert (layout.inbox / "request.json").exists()

        assert deploy.from_request(system=system, layout=layout).code == "deployed"

        assert tool.main(["status"], client=client) == 0
        out = capsys.readouterr().out
        assert "remote deploy: enabled" in out and f"last: deployed deploy {NEW}" in out
        status = client.deploy_status()
        assert status["last"]["request_id"] == history(layout)[-1]["request_id"]
        assert status["pending"] is None
    finally:
        rig.close()
