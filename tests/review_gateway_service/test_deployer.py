"""DEPLOY-1: the console deployer for the review gateway (docs/work_packages/DEPLOY-PROXMOX_containers.md).

Hermetic: an injected system layer stands in for systemctl, ln, install.sh, GitHub and the health probes, so every reason
code is exercised on Windows CI without root, network or symbolic links. Archives are real gzip tarballs.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import shutil
import sqlite3
import sys
import tarfile
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.review_gateway_service.conftest import ROOT, SCHEMA_VERSION

DEPLOY_ROOT = ROOT / "services" / "deploy"
if str(DEPLOY_ROOT) not in sys.path:
    sys.path.insert(0, str(DEPLOY_ROOT))

import stablenew_deploy as deploy  # noqa: E402

OLD = "1" * 40
NEW = "2" * 40
OLDER = "0" * 40
TOP = f"StableNew2-{NEW}"
SCHEMA_NAME = f"{SCHEMA_VERSION}.json"
SECRET = "deploy-test-secret-0123456789-abcdefgh"
CERT_DER = b"not-a-real-certificate-but-base64-able"
SPECIAL = {tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE}


def schema_text(version: str = SCHEMA_VERSION, extra: str = "") -> str:
    return json.dumps({"$defs": {"schema_version": {"const": version}}, "extra": extra})


def tarball(members: Sequence[tuple[str, Any]], *, comment: str | None = NEW) -> bytes:
    """``members``: (name, bytes) for a file, (name, None) for a directory, (name, TarInfo-type) for anything else."""

    buffer = io.BytesIO()
    headers = {"comment": comment} if comment is not None else {}
    with tarfile.open(
        fileobj=buffer, mode="w:gz", format=tarfile.PAX_FORMAT, pax_headers=headers
    ) as tar:
        for name, content in members:
            info = tarfile.TarInfo(name)
            if content in SPECIAL:
                info.type = content
                info.linkname = "/etc/shadow"
                tar.addfile(info)
            elif isinstance(content, bytes):
                info.size = len(content)
                info.mode = 0o777  # never copied: the deployer sets its own modes
                tar.addfile(info, io.BytesIO(content))
            else:
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
    return buffer.getvalue()


def good_members(top: str = TOP) -> list[tuple[str, Any]]:
    return [
        (f"{top}/", None),
        (f"{top}/README.md", b"not extracted"),
        (f"{top}/src/main.py", b"not extracted"),
        (f"{top}/services/", None),
        (f"{top}/services/review_gateway/", None),
        (f"{top}/services/review_gateway/install.sh", b"#!/usr/bin/env bash\n"),
        (f"{top}/services/review_gateway/review_gateway/", None),
        (f"{top}/services/review_gateway/review_gateway/app.py", b"# app\n"),
        (f"{top}/services/deploy/", None),
        (f"{top}/services/deploy/stablenew_deploy.py", b"# deployer\n"),
        (f"{top}/docs/schemas/{SCHEMA_NAME}", schema_text().encode()),
        (f"{top}/docs/schemas/other.json", b"{}"),
    ]


class Result:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeSystem:
    """Records every command; simulates the installer, systemd, the ``current`` link, GitHub and the probes."""

    def __init__(self, layout: deploy.Layout) -> None:
        self.layout = layout
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str]] = []
        self.urls: list[str] = []
        self.links: dict[str, Path] = {}
        self.active = True
        self.locked = False
        self.clock = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
        self.slept = 0.0
        # GitHub: (base, head) -> compare status; sha -> commit JSON.
        self.compare: dict[tuple[str, str], str] = {(NEW, "main"): "ahead", (OLD, NEW): "ahead"}
        self.commits: dict[str, Any] = {
            NEW: {
                "commit": {"verification": {"verified": True}},
                "committer": {"login": "web-flow"},
            }
        }
        self.github_down = False
        self.archive = tarball(good_members())
        # Installer behaviour: "switch" (normal), "fail_before" (no switch), "fail_after" (switched, then exit 1).
        self.install = "switch"
        self.migrate = False
        self.new_schema = schema_text()
        self.unhealthy: set[str] = set()
        self.admin_fails: set[str] = set()
        self.probes: list[tuple[str, Mapping[str, str], str | None]] = []
        self.installed_release: Path | None = None

    # --- commands -------------------------------------------------------------------------------------------------
    def run(
        self, argv: Sequence[str], *, env: Mapping[str, str] | None = None, timeout: float
    ) -> Result:
        argv = [str(part) for part in argv]
        self.calls.append(argv)
        self.envs.append(dict(env or {}))
        assert timeout > 0
        if argv[0] == "bash" and argv[1].endswith("install.sh"):
            return self._install(Path(argv[1]), dict(env or {}))
        if argv[:2] == ["systemctl", "is-active"]:
            return Result(0 if self.active else 3)
        if argv[:2] == ["systemctl", "stop"]:
            self.active = False
            return Result()
        if argv[:2] in (["systemctl", "start"], ["systemctl", "restart"]):
            self.active = True
            return Result()
        if argv[:2] == ["systemctl", "daemon-reload"]:
            return Result()
        if argv[:2] == ["ln", "-sfn"]:
            self.links[argv[3]] = Path(argv[2])
            return Result()
        if argv[0] == "install" and argv[1:3] == ["-m", "0644"]:
            shutil.copyfile(argv[3], argv[4])
            return Result()
        if argv[0] == str(self.layout.admin):
            current = self.read_link(self.layout.current)
            return Result(1 if current is not None and current.name in self.admin_fails else 0)
        raise AssertionError(f"unexpected command {argv}")

    def _install(self, script: Path, env: dict[str, str]) -> Result:
        source = script.parent
        assert (source / "review_gateway" / "app.py").is_file()
        assert (source.parent / "deploy" / "stablenew_deploy.py").is_file()
        assert (source.parent.parent / "docs" / "schemas" / SCHEMA_NAME).is_file()
        if self.install == "fail_before":
            return Result(1, stderr="install: pip failed")
        release = self.layout.releases / "20261126T120500Z-42"
        make_release(
            release, env.get("SOURCE_COMMIT"), self.new_schema, env.get("SOURCE_ARCHIVE_SHA256")
        )
        database = deploy.read_settings(self.layout.config).database
        if database.exists():
            backup = self.layout.backups / f"{release.name}.sqlite3"
            backup.parent.mkdir(parents=True, exist_ok=True)
            with (
                contextlib.closing(sqlite3.connect(database)) as src,
                contextlib.closing(sqlite3.connect(backup)) as dst,
            ):
                src.backup(dst)
            if self.migrate:
                with contextlib.closing(sqlite3.connect(database)) as db:
                    db.execute("ALTER TABLE outbox ADD COLUMN action TEXT")
                    db.execute(
                        "INSERT INTO outbox VALUES ('after-migration', 'action', 'fix_face')"
                    )
                    db.commit()
        self.links[str(self.layout.current)] = release
        self.installed_release = release
        self.active = True
        return Result(1 if self.install == "fail_after" else 0, stdout=f"release: {release}\n")

    # --- links, GitHub, probes ------------------------------------------------------------------------------------
    def read_link(self, path: Path) -> Path | None:
        return self.links.get(str(path))

    def get_json(self, url: str) -> tuple[int, Any]:
        self.urls.append(url)
        if self.github_down:
            raise OSError("network unreachable")
        api = deploy.GITHUB_API + "/"
        assert url.startswith(api), url
        path = url[len(api) :]
        if path.startswith("compare/"):
            base, head = path[len("compare/") :].split("...")
            status = self.compare.get((base, head))
            return (404, {"message": "Not Found"}) if status is None else (200, {"status": status})
        if path.startswith("commits/"):
            sha = path[len("commits/") :]
            return (
                (200, self.commits[sha]) if sha in self.commits else (422, {"message": "No commit"})
            )
        raise AssertionError(url)

    def download(self, url: str, destination: Path, limit: int) -> str:
        self.urls.append(url)
        if len(self.archive) > limit:
            raise deploy.DeployFailure("download_failed", "the archive is larger than the limit")
        destination.write_bytes(self.archive)
        return hashlib.sha256(self.archive).hexdigest()

    def probe(self, url: str, *, headers: Mapping[str, str], pin: str | None) -> tuple[int, bytes]:
        self.probes.append((url, dict(headers), pin))
        current = self.read_link(self.layout.current)
        if not self.active or current is None or current.name in self.unhealthy:
            raise OSError("connection refused")
        if url.endswith("/sync/v1/health"):
            version = json.loads((current / "app" / "schema" / SCHEMA_NAME).read_text())["$defs"][
                "schema_version"
            ]
            return 200, json.dumps({"status": "ok", "schema_version": version["const"]}).encode()
        return 200, b"<!doctype html>"

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        if self.locked:
            raise deploy.DeployFailure("deploy_in_progress", "another deploy is running")
        yield

    def sleep(self, seconds: float) -> None:
        self.slept += seconds
        self.clock += timedelta(seconds=seconds)

    def now(self) -> datetime:
        return self.clock


def make_release(
    release: Path, commit: str | None, schema: str, archive_sha: str | None = None
) -> None:
    (release / "app" / "schema").mkdir(parents=True)
    (release / "app" / "schema" / SCHEMA_NAME).write_text(schema, encoding="utf-8")
    (release / "app" / "review-gateway.service").write_text(
        f"[Unit]\n# {release.name}\n", encoding="utf-8"
    )
    if commit is not None:
        source = {
            "commit": commit,
            "archive_sha256": archive_sha,
            "installed_at": "2026-11-26T12:00:00Z",
        }
        (release / "source.json").write_text(json.dumps(source), encoding="utf-8")


@pytest.fixture
def rig(tmp_path: Path) -> tuple[deploy.Layout, FakeSystem]:
    layout = deploy.Layout(
        prefix=tmp_path / "opt",
        config=tmp_path / "etc" / "config.toml",
        state=tmp_path / "state",
        admin=tmp_path / "bin" / "review-gateway-admin",
        unit_file=tmp_path / "systemd" / "review-gateway.service",
    )
    (tmp_path / "etc").mkdir()
    (tmp_path / "systemd").mkdir()
    data = tmp_path / "data"
    data.mkdir()
    secret = tmp_path / "etc" / "sync_secret"
    secret.write_text(SECRET + "\n", encoding="utf-8")
    cert = tmp_path / "etc" / "sync.crt"
    import base64

    cert.write_text(
        "-----BEGIN CERTIFICATE-----\n"
        + base64.b64encode(CERT_DER).decode()
        + "\n-----END CERTIFICATE-----\n",
        encoding="ascii",
    )
    layout.config.write_text(
        "\n".join(
            [
                f'data_dir = "{data.as_posix()}"',
                f'media_dir = "{(tmp_path / "media").as_posix()}"',
                f'secret_file = "{secret.as_posix()}"',
                'sync_host = "192.0.2.10"',
                "sync_port = 9443",
                f'sync_tls_cert = "{cert.as_posix()}"',
                f'sync_tls_key = "{(tmp_path / "etc" / "sync.key").as_posix()}"',
                'immich_url = ""',
                'phone_host = "127.0.0.1"',
                "phone_port = 8443",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with contextlib.closing(sqlite3.connect(data / "gateway.sqlite3")) as db:
        db.execute("CREATE TABLE outbox (record_id TEXT PRIMARY KEY, kind TEXT)")
        db.execute("INSERT INTO outbox VALUES ('before', 'decision')")
        db.commit()
    old = layout.releases / "20261125T000000Z-1"
    make_release(old, OLD, schema_text())
    system = FakeSystem(layout)
    system.links[str(layout.current)] = old
    return layout, system


def run(rig: tuple[deploy.Layout, FakeSystem], sha: str = NEW, **options: Any) -> deploy.Outcome:
    layout, system = rig
    return deploy.deploy(sha, system=system, layout=layout, **options)


def history(layout: deploy.Layout) -> list[dict[str, Any]]:
    return [json.loads(line) for line in layout.history.read_text(encoding="utf-8").splitlines()]


def installer_calls(system: FakeSystem) -> list[list[str]]:
    return [call for call in system.calls if call[0] == "bash"]


def outbox_ids(layout: deploy.Layout) -> list[str]:
    with contextlib.closing(
        sqlite3.connect(layout.prefix.parent / "data" / "gateway.sqlite3")
    ) as db:
        return sorted(row[0] for row in db.execute("SELECT record_id FROM outbox"))


def columns(layout: deploy.Layout) -> list[str]:
    with contextlib.closing(
        sqlite3.connect(layout.prefix.parent / "data" / "gateway.sqlite3")
    ) as db:
        return [row[1] for row in db.execute("PRAGMA table_info(outbox)")]


# --- refusals before anything changes ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sha",
    ["", "abc", "2" * 39, "2" * 41, "G" * 40, "A" * 40, "main", "-" + "2" * 39, "2" * 39 + "\n"],
)
def test_only_a_full_lowercase_commit_sha_is_accepted(rig, sha: str) -> None:
    outcome = run(rig, sha)

    assert outcome.code == "bad_sha"
    assert outcome.exit_code == deploy.EXIT_CODES["bad_sha"]
    assert rig[1].urls == [] and rig[1].calls == []


@pytest.mark.parametrize("status", ["behind", "diverged", None])
def test_a_commit_that_is_not_on_main_is_refused(rig, status: str | None) -> None:
    # "diverged" is what GitHub reports for a commit that exists only in a fork (cross-fork object reference, F1).
    layout, system = rig
    if status is None:
        del system.compare[(NEW, "main")]
    else:
        system.compare[(NEW, "main")] = status

    outcome = run(rig)

    assert outcome.code == "not_on_main"
    assert installer_calls(system) == [] and not any("codeload" in url for url in system.urls)
    assert history(layout)[-1]["outcome"] == "not_on_main"


def test_github_unreachable_is_its_own_refusal(rig) -> None:
    rig[1].github_down = True

    assert run(rig).code == "github_unavailable"


def test_the_urls_are_fixed_and_carry_only_the_sha(rig) -> None:
    layout, system = rig

    assert run(rig).code == "deployed"

    assert system.urls == [
        f"https://api.github.com/repos/destroyer42/StableNew2/compare/{NEW}...main",
        f"https://api.github.com/repos/destroyer42/StableNew2/compare/{OLD}...{NEW}",
        f"https://api.github.com/repos/destroyer42/StableNew2/commits/{NEW}",
        f"https://codeload.github.com/destroyer42/StableNew2/tar.gz/{NEW}",
    ]


@pytest.mark.parametrize("status", ["behind", "diverged"])
def test_an_older_commit_is_refused_unless_the_console_allows_a_downgrade(rig, status: str) -> None:
    layout, system = rig
    system.compare[(OLD, NEW)] = status

    refused = run(rig)
    assert refused.code == "downgrade" and installer_calls(system) == []

    allowed = run(rig, allow_downgrade=True)
    assert allowed.code == "deployed"


def test_the_deployed_commit_again_is_already_current(rig) -> None:
    layout, system = rig
    system.compare[(OLD, NEW)] = "identical"

    outcome = run(rig)

    assert outcome.code == "already_current" and outcome.exit_code == 0
    assert installer_calls(system) == []


def test_a_release_without_a_recorded_commit_skips_the_forward_check_once(rig) -> None:
    layout, system = rig
    (layout.releases / "20261125T000000Z-1" / "source.json").unlink()

    outcome = run(rig)

    assert outcome.code == "deployed"
    assert not any(f"compare/{OLD}" in url for url in system.urls)
    assert history(layout)[-1]["old_commit"] is None


@pytest.mark.parametrize(
    "commit",
    [
        {"commit": {"verification": {"verified": False}}, "committer": {"login": "web-flow"}},
        {"commit": {"verification": {"verified": True}}, "committer": {"login": "someone"}},
        {"commit": {"verification": {"verified": True}}, "committer": None},
        {"commit": {}, "committer": {"login": "web-flow"}},
    ],
)
def test_a_commit_github_did_not_sign_as_a_merge_is_refused(rig, commit: dict) -> None:
    layout, system = rig
    system.commits[NEW] = commit

    assert run(rig).code == "not_github_signed"
    assert installer_calls(system) == []


def test_a_second_deploy_while_one_runs_is_refused(rig) -> None:
    rig[1].locked = True

    outcome = run(rig)

    assert outcome.code == "deploy_in_progress"
    assert rig[1].urls == []


def test_an_archive_over_the_size_limit_is_refused(rig) -> None:
    layout, system = rig
    system.archive = b"x" * (deploy.ARCHIVE_LIMIT + 1)

    assert run(rig).code == "download_failed"
    assert installer_calls(system) == []


# --- archive validation (F5) ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        (f"{TOP}/services/review_gateway/../../../../etc/cron.d/x", b"x"),
        ("/etc/cron.d/x", b"x"),
        (f"{TOP}/services/review_gateway/link", tarfile.SYMTYPE),
        (f"{TOP}/services/review_gateway/hard", tarfile.LNKTYPE),
        (f"{TOP}/services/deploy/fifo", tarfile.FIFOTYPE),
        (f"{TOP}/services/deploy/dev", tarfile.CHRTYPE),
        (f"{TOP}/services/review_gateway\\..\\x", b"x"),
    ],
)
def test_archive_members_that_could_escape_or_are_not_plain_files_are_refused(rig, bad) -> None:
    layout, system = rig
    system.archive = tarball([*good_members(), bad])

    outcome = run(rig)

    assert outcome.code == "bad_archive", outcome
    assert installer_calls(system) == []
    assert not (layout.state / "staging").exists() or not any((layout.state / "staging").iterdir())


def test_an_archive_for_another_commit_is_refused(rig) -> None:
    layout, system = rig
    system.archive = tarball(good_members(f"StableNew2-{OLD}"), comment=OLD)

    assert run(rig).code == "bad_archive"


def test_an_archive_without_the_service_is_refused(rig) -> None:
    layout, system = rig
    system.archive = tarball([(f"{TOP}/README.md", b"x")])

    assert run(rig).code == "bad_archive"


def test_only_the_service_the_deployer_and_the_schema_are_extracted(tmp_path: Path) -> None:
    archive = tmp_path / "a.tar.gz"
    archive.write_bytes(tarball(good_members()))
    target = tmp_path / "out"

    deploy.extract(archive, target, NEW)

    files = sorted(
        path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()
    )
    assert files == [
        f"docs/schemas/{SCHEMA_NAME}",
        "services/deploy/stablenew_deploy.py",
        "services/review_gateway/install.sh",
        "services/review_gateway/review_gateway/app.py",
    ]


# --- install, health, rollback ----------------------------------------------------------------------------------


def test_a_good_deploy_runs_the_new_installer_with_only_the_validated_values(rig) -> None:
    layout, system = rig

    outcome = run(rig)

    assert outcome.code == "deployed" and outcome.exit_code == 0
    (call,) = installer_calls(system)
    env = system.envs[system.calls.index(call)]
    assert call[0] == "bash" and Path(call[1]).as_posix().endswith(
        "/services/review_gateway/install.sh"
    )
    assert env["SOURCE_COMMIT"] == NEW
    assert env["SOURCE_ARCHIVE_SHA256"] == hashlib.sha256(system.archive).hexdigest()
    assert set(env) == {"PATH", "LANG", "SOURCE_COMMIT", "SOURCE_ARCHIVE_SHA256"}
    record = history(layout)[-1]
    assert (
        record["outcome"] == "deployed"
        and record["old_commit"] == OLD
        and record["new_commit"] == NEW
    )
    assert record["new_release"] == "20261126T120500Z-42" and record["trigger"] == "console"
    assert record["schema_changed"] is False
    assert not any((layout.state / "staging").iterdir())
    assert json.loads(layout.last.read_text(encoding="utf-8")) == record


def test_the_health_check_pins_the_certificate_and_checks_the_schema_version(rig) -> None:
    layout, system = rig

    assert run(rig).code == "deployed"

    sync = [probe for probe in system.probes if probe[0].endswith("/sync/v1/health")]
    phone = [probe for probe in system.probes if probe[0] == "http://127.0.0.1:8443/"]
    assert sync and phone
    url, headers, pin = sync[-1]
    assert url == "https://192.0.2.10:9443/sync/v1/health"
    assert headers == {"Authorization": f"Bearer {SECRET}"}
    assert pin == hashlib.sha256(CERT_DER).hexdigest()
    assert phone[-1][2] is None and "Authorization" not in phone[-1][1]


def test_a_failed_health_check_rolls_back_without_touching_unchanged_tables(rig) -> None:
    layout, system = rig
    system.unhealthy = {"20261126T120500Z-42"}

    outcome = run(rig)

    assert outcome.code == "rolled_back"
    assert outcome.exit_code == deploy.EXIT_CODES["rolled_back"]
    assert system.read_link(layout.current) == layout.releases / "20261125T000000Z-1"
    assert "# 20261125T000000Z-1" in layout.unit_file.read_text(encoding="utf-8")
    assert ["systemctl", "daemon-reload"] in system.calls and system.active
    record = history(layout)[-1]
    assert record["database_restored"] is False and record["reason"] == "health_check_failed"
    assert system.slept >= deploy.HEALTH_TIMEOUT - deploy.HEALTH_INTERVAL


def test_a_rollback_after_a_migration_restores_the_database(rig) -> None:
    layout, system = rig
    system.unhealthy = {"20261126T120500Z-42"}
    system.migrate = True

    outcome = run(rig)

    assert outcome.code == "rolled_back"
    assert history(layout)[-1]["database_restored"] is True
    assert columns(layout) == ["record_id", "kind"]
    assert outbox_ids(layout) == ["before"]


def test_a_database_the_new_release_did_not_change_is_kept_on_rollback(rig) -> None:
    layout, system = rig
    system.admin_fails = {"20261126T120500Z-42"}

    assert run(rig).code == "rolled_back"
    assert outbox_ids(layout) == ["before"] and columns(layout) == ["record_id", "kind"]


def test_an_installer_that_fails_after_switching_is_rolled_back(rig) -> None:
    layout, system = rig
    system.install = "fail_after"

    outcome = run(rig)

    assert outcome.code == "rolled_back"
    assert history(layout)[-1]["reason"] == "install_failed"
    assert system.read_link(layout.current) == layout.releases / "20261125T000000Z-1"


def test_an_installer_that_fails_before_switching_leaves_the_old_release_running(rig) -> None:
    layout, system = rig
    system.install = "fail_before"
    system.active = False  # the installer had stopped the service

    outcome = run(rig)

    assert outcome.code == "install_failed"
    assert system.read_link(layout.current) == layout.releases / "20261125T000000Z-1"
    assert ["systemctl", "start", "review-gateway"] in system.calls and system.active


def test_a_rollback_whose_old_release_is_also_unhealthy_is_reported(rig) -> None:
    layout, system = rig
    system.unhealthy = {"20261126T120500Z-42", "20261125T000000Z-1"}

    outcome = run(rig)

    assert outcome.code == "rollback_failed"
    assert outcome.exit_code == deploy.EXIT_CODES["rollback_failed"]


def test_a_schema_change_warns_and_does_not_block(rig) -> None:
    layout, system = rig
    system.new_schema = schema_text(extra="a new record kind")

    outcome = run(rig)

    assert outcome.code == "deployed"
    assert history(layout)[-1]["schema_changed"] is True
    assert any("PC app" in line for line in outcome.lines)


# --- console rollback and status --------------------------------------------------------------------------------


def test_console_rollback_switches_to_the_previous_release_and_keeps_the_database(rig) -> None:
    layout, system = rig
    system.migrate = True
    assert run(rig).code == "deployed"

    outcome = deploy.rollback(system=system, layout=layout)

    assert outcome.code == "reverted" and outcome.exit_code == 0
    assert system.read_link(layout.current) == layout.releases / "20261125T000000Z-1"
    assert "after-migration" in outbox_ids(layout)
    assert history(layout)[-1]["database_restored"] is False


def test_console_rollback_can_restore_the_database_when_asked(rig) -> None:
    layout, system = rig
    system.migrate = True
    assert run(rig).code == "deployed"

    outcome = deploy.rollback(system=system, layout=layout, restore_database=True)

    assert outcome.code == "reverted"
    assert outbox_ids(layout) == ["before"]


def test_console_rollback_without_a_previous_release_is_refused(rig) -> None:
    layout, system = rig

    outcome = deploy.rollback(system=system, layout=layout)

    assert outcome.code == "no_previous_release"
    assert system.read_link(layout.current) == layout.releases / "20261125T000000Z-1"


def test_status_names_the_deployed_commit_and_the_last_result(rig, capsys) -> None:
    layout, system = rig
    assert run(rig).code == "deployed"

    assert deploy.main(["status"], system=system, layout=layout) == 0

    out = capsys.readouterr().out
    assert f"commit:   {NEW}" in out and "20261126T120500Z-42" in out
    assert "previous: 20261125T000000Z-1" in out and "last:     deployed" in out


def test_the_command_line_takes_a_bare_sha_and_prints_the_outcome(rig, capsys) -> None:
    layout, system = rig

    code = deploy.main([NEW], system=system, layout=layout)

    assert code == 0
    assert capsys.readouterr().out.rstrip().endswith("outcome: deployed")


def test_the_command_line_allows_a_downgrade_only_with_the_flag(rig) -> None:
    layout, system = rig
    system.compare[(OLD, NEW)] = "behind"

    assert deploy.main([NEW], system=system, layout=layout) == deploy.EXIT_CODES["downgrade"]
    assert deploy.main(["deploy", "--allow-downgrade", NEW], system=system, layout=layout) == 0


def test_every_outcome_has_its_own_exit_code() -> None:
    failures = {code: value for code, value in deploy.EXIT_CODES.items() if value != 0}

    assert len(set(failures.values())) == len(failures)
    assert {code for code, value in deploy.EXIT_CODES.items() if value == 0} == {
        "deployed",
        "already_current",
        "reverted",
        "status",
    }


# --- the real system layer ----------------------------------------------------------------------------------------


def test_the_pin_check_compares_the_der_certificate_digest() -> None:
    deploy.check_pin(CERT_DER, hashlib.sha256(CERT_DER).hexdigest())
    with pytest.raises(OSError):
        deploy.check_pin(CERT_DER, "0" * 64)
    with pytest.raises(OSError):
        deploy.check_pin(None, hashlib.sha256(CERT_DER).hexdigest())


def test_a_download_stream_is_cut_off_at_the_limit(tmp_path: Path) -> None:
    target = tmp_path / "a"
    digest = deploy.copy_limited(io.BytesIO(b"abc" * 10), target, limit=30)
    assert digest == hashlib.sha256(b"abc" * 10).hexdigest()

    with pytest.raises(deploy.DeployFailure) as refused:
        deploy.copy_limited(io.BytesIO(b"abc" * 11), target, limit=30)
    assert refused.value.code == "download_failed"


def test_the_deployer_uses_only_the_standard_library_and_python_311() -> None:
    source = (DEPLOY_ROOT / "stablenew_deploy.py").read_text(encoding="utf-8")
    tree = ast.parse(source, feature_version=(3, 11))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert name.split(".")[0] in sys.stdlib_module_names, name
    # Never a shell: every command is an argument list.
    assert "shell=True" not in source and "os.system" not in source and "os.popen" not in source


# --- the installer's part (install.sh) ----------------------------------------------------------------------------

INSTALLER = ROOT / "services" / "review_gateway" / "install.sh"


def installer() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def at(script: str, fragment: str) -> int:
    assert fragment in script, fragment
    return script.index(fragment)


def test_the_installer_ships_the_deployer_in_every_release() -> None:
    script = installer()

    assert 'DEPLOYER="$SOURCE/../deploy/stablenew_deploy.py"' in script
    assert at(script, '[ -f "$DEPLOYER" ] || fail') < at(script, "python3 -m venv")
    assert 'install -m 0644 "$DEPLOYER" "$APP/deploy/stablenew_deploy.py"' in script


def test_the_installer_accepts_only_hexadecimal_source_values() -> None:
    script = installer()

    assert "SOURCE_COMMIT must be 40 lowercase hexadecimal characters" in script
    assert "SOURCE_ARCHIVE_SHA256 must be 64 lowercase hexadecimal characters" in script
    assert at(script, "SOURCE_COMMIT must be") < at(script, 'install -d -m 0755 "$RELEASE"')
    assert '"$RELEASE/source.json"' in script


def test_the_installer_backs_up_the_database_after_stopping_and_before_switching() -> None:
    script = installer()

    stop = at(script, "systemctl stop review-gateway")
    backup = at(script, '"$DEPLOY_STATE/backups/$(basename "$RELEASE").sqlite3"')
    switch = at(script, 'ln -sfn "$RELEASE" "$PREFIX/current"')
    assert stop < backup < switch
    assert ".backup(" in script


def test_the_installer_writes_an_isolated_root_deploy_command() -> None:
    script = installer()

    assert "/usr/local/sbin/review-gateway-deploy" in script
    assert r'-I $PREFIX/current/app/deploy/stablenew_deploy.py "\$@"' in script
    assert 'install -d -m 0700 "$DEPLOY_STATE"' in script


def test_the_installer_keeps_only_the_backups_of_the_releases_it_keeps() -> None:
    script = installer()

    cleanup = script[at(script, "# Keep the new release and the one before it") :]
    assert '"$DEPLOY_STATE"/backups/' in cleanup
