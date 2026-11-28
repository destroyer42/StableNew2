"""PHONE-CORE PS-1: the staging fixtures and the promotion check, against a real gateway on loopback.

The phone app is served over HTTP as the check reaches it; the sync app is called in process, as the PC.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.app.review_gateway_client import GatewayClient, Response
from tests.review_gateway_service.conftest import SCHEMA_PATH, SECRET
from tools import review_gateway_promote as promote
from tools import review_gateway_stage as stage
from tools import review_gateway_targets as targets

ROOT = Path(__file__).resolve().parents[2]
SHA = "0123456789abcdef0123456789abcdef01234567"


class InProcess:
    """The sync listener as the client's transport."""

    def __init__(self, client) -> None:
        self.client = client

    def request(self, method, path, *, headers, body, timeout, limit) -> Response:
        reply = self.client.request(method, path, headers=headers, content=body)
        return Response(reply.status_code, reply.content)


class Local:
    def __init__(self, root: Path, *, label: str = "Staging", commit: str = SHA) -> None:
        import uvicorn
        from review_gateway.app import Gateway
        from review_gateway.config import Settings
        from starlette.testclient import TestClient

        root.mkdir(parents=True)
        (root / "sync_secret").write_text(SECRET + "\n", encoding="utf-8")
        (root / "sync_secret").chmod(0o600)
        (root / "release").mkdir()
        (root / "release" / "source.json").write_text(
            json.dumps({"commit": commit}), encoding="utf-8"
        )
        self.gateway = Gateway(
            Settings(
                data_dir=root / "data",
                media_dir=root / "media",
                secret_file=root / "sync_secret",
                schema_file=SCHEMA_PATH,
                sync_host="127.0.0.1",
                release_dir=root / "release",
                deploy_dir=root / "deploy",
                deploy_switch_file=root / "remote-deploy",
                environment_label=label,
            )
        )
        self.store = self.gateway.store
        self.http = TestClient(self.gateway.sync_app(), base_url="https://gateway.test")
        self.sync = GatewayClient(InProcess(self.http), SECRET)
        config = uvicorn.Config(
            self.gateway.phone_app(), host="127.0.0.1", port=0, log_level="warning", lifespan="off"
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            assert time.monotonic() < deadline and self.thread.is_alive(), "no gateway"
            time.sleep(0.02)
        self.url = f"http://127.0.0.1:{self.server.servers[0].sockets[0].getsockname()[1]}"

    def close(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)
        self.http.close()

    def active_devices(self) -> list:
        return [device for device in self.store.devices() if not device["revoked_at"]]


@pytest.fixture
def local(tmp_path) -> Iterator[Local]:
    gateway = Local(tmp_path / "gateway")
    try:
        yield gateway
    finally:
        gateway.close()


def served_tree(_sha: str, destination: Path) -> None:
    """``<sha>``'s page files, standing in for git: the very files the local gateway serves."""

    from review_gateway.static_files import STATIC_DIR

    shutil.copytree(STATIC_DIR, destination, dirs_exist_ok=True)


def run_check(local: Local, sha: str = SHA, tree=served_tree) -> int:
    return promote.main([sha], sync=local.sync, phone_url=local.url, tree=tree)


# --- the check ------------------------------------------------------------------------------------------------


def test_a_healthy_staging_gateway_passes_and_leaves_no_phone_or_pending_record(
    local, capsys
) -> None:
    from review_gateway.static_files import STATIC_DIR

    assert run_check(local) == promote.EXIT_PASS

    out = capsys.readouterr().out.rstrip().splitlines()
    assert out[-1] == "PASS"
    assert any("labelled 'Staging'" in line for line in out)
    assert "ok: a seeded item round-trips a decision" in out
    if not (STATIC_DIR / "sw.js").is_file():
        assert any(line.startswith("skipped:") and "sw.js" in line for line in out)
    assert local.active_devices() == []
    page = local.sync.outbox(None)
    assert page["records"] == []


def test_another_commit_fails_before_anything_is_written(local, capsys) -> None:
    assert run_check(local, "f" * 40) == promote.EXIT_FAIL

    assert capsys.readouterr().out.rstrip().splitlines()[-1].startswith("FAIL: staging runs")
    assert local.store.status()["items"] == 0 and local.store.devices() == []


def test_a_page_that_is_not_the_commits_fails(local, capsys) -> None:
    def changed(sha: str, destination: Path) -> None:
        served_tree(sha, destination)
        with (destination / "core" / "main.js").open("ab") as stream:
            stream.write(b"// changed\n")

    assert run_check(local, tree=changed) == promote.EXIT_FAIL
    assert "FAIL: the page's version is" in capsys.readouterr().out
    assert local.store.devices() == []


def test_a_gateway_without_a_label_fails(tmp_path, capsys) -> None:
    unlabelled = Local(tmp_path / "unlabelled", label="")
    try:
        assert run_check(unlabelled) == promote.EXIT_FAIL
        assert "environment label" in capsys.readouterr().out
        assert unlabelled.store.devices() == []
    finally:
        unlabelled.close()


def test_a_missing_service_worker_fails_and_the_temporary_phone_is_still_revoked(
    local, capsys
) -> None:
    from review_gateway.static_files import STATIC_DIR

    if (STATIC_DIR / "sw.js").is_file():
        pytest.skip("this gateway serves a worker; the passing check covers it")
    expected = promote.expected_page(SHA, "Staging", served_tree)[0]
    original = promote.expected_page
    try:
        promote.expected_page = lambda *_args: (expected, True)  # the commit has sw.js
        assert run_check(local) == promote.EXIT_FAIL
    finally:
        promote.expected_page = original
    assert "FAIL: /sw.js answered 404" in capsys.readouterr().out
    assert len(local.store.devices()) == 1 and local.active_devices() == []


def test_an_unreachable_phone_page_fails(local, capsys) -> None:
    assert (
        promote.main([SHA], sync=local.sync, phone_url="http://127.0.0.1:1", tree=served_tree)
        == promote.EXIT_FAIL
    )
    assert "is Tailscale on?" in capsys.readouterr().out


def test_the_commits_page_files_are_read_byte_for_byte_from_git(tmp_path) -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()

    promote.static_tree(head, tmp_path)

    for name in ("index.html", "core/main.js", "features/status/status.css"):
        stored = subprocess.run(
            ["git", "cat-file", "blob", f"{head}:{promote.STATIC_PATH}/{name}"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        assert (tmp_path / name).read_bytes() == stored, name
    version, _worker = promote.expected_page(head, "Staging")
    assert re.fullmatch(r"[0-9a-f]{12}", version)


@pytest.mark.parametrize("sha", ["main", "HEAD", "--output=x", "A" * 40])
def test_only_a_full_commit_id_is_checked(capsys, sha) -> None:
    assert promote.main([sha]) == promote.EXIT_USAGE


# --- production is refused ------------------------------------------------------------------------------------


@pytest.fixture
def no_settings(monkeypatch) -> None:
    def never(*_args, **_kwargs):
        raise AssertionError("settings were read")

    monkeypatch.setattr(targets, "staging_client", never)
    monkeypatch.setattr(targets, "staging_settings", never)


@pytest.mark.parametrize("command", [["seed"], ["reset"], ["pair"]])
def test_the_stage_tool_refuses_production(no_settings, capsys, command) -> None:
    assert stage.main(["--target", "production", *command]) == stage.EXIT_REFUSED
    captured = capsys.readouterr()
    assert "never addresses production" in captured.err and captured.out == ""


def test_the_promotion_check_refuses_production(no_settings, capsys) -> None:
    assert promote.main(["--target", "production", SHA]) == promote.EXIT_USAGE
    assert "staging only" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["--target", "prod", "seed"], ["reset", "--ct", "121; reboot"]])
def test_the_stage_tool_takes_only_a_known_target_and_a_container_number(no_settings, argv) -> None:
    assert stage.main(argv) == stage.EXIT_USAGE


def test_reset_prints_a_line_that_stops_on_an_unlabelled_gateway(no_settings, capsys) -> None:
    assert stage.main(["reset"]) == stage.EXIT_OK
    line = stage.reset_command(121)
    assert line in capsys.readouterr().out
    # set -e and the label check come before anything is stopped or deleted.
    assert line.index("set -e") < line.index("environment_label") < line.index("systemctl stop")
    assert line.index("systemctl stop") < line.index("-delete")
    assert stage.main(["reset", "--ct", "120"]) == stage.EXIT_REFUSED


# --- fixtures -------------------------------------------------------------------------------------------------


def test_seed_fills_the_review_sections_and_can_run_again(local, capsys) -> None:
    assert stage.main(["seed"], client=local.sync) == stage.EXIT_OK
    items = local.store.status()["items"]

    assert stage.main(["seed"], client=local.sync) == stage.EXIT_OK

    assert items == local.store.status()["items"] == len(stage.fixture_items(local.sync.health()))
    sections = local.store.sections({})
    shown = json.dumps(sections)
    for source in ("pipeline", "testing", "reprocess", "video"):
        assert source in shown, source
    assert "published 1 rating set" in capsys.readouterr().out


def test_pair_prints_a_code_that_pairs_a_phone(local, capsys) -> None:
    class Url:
        def load(self):
            return local.url

    assert stage.main(["pair"], client=local.sync, phone_store=Url()) == stage.EXIT_OK
    out = capsys.readouterr().out
    code = re.search(r"^ {4}([0-9A-Z]{4}-[0-9A-Z]{4})$", out, re.MULTILINE)[1]
    phone = promote.Phone(local.url)

    phone.json("POST", "/api/pair", {"code": code, "label": "phone"})

    assert phone.json("GET", "/api/session")["scopes"] == ["review", "queue"]
    assert SECRET not in out
