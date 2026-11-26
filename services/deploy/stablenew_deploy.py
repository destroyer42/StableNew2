"""Deploy a commit of StableNew's ``main`` to the review gateway container, check it and roll back by itself.

Runs as root with the container's own Python (3.11 or newer, standard library only), through the wrapper the installer
writes: ``/usr/local/sbin/review-gateway-deploy``. Design, threat model and owner decisions:
``docs/work_packages/DEPLOY-PROXMOX_containers.md``. Operator steps: ``docs/runbooks/review_gateway.md``.

    review-gateway-deploy <sha>                      deploy a commit of main
    review-gateway-deploy deploy --allow-downgrade <sha>
    review-gateway-deploy status
    review-gateway-deploy rollback [--restore-database]
    review-gateway-deploy remote on|off              the PC's sync-channel trigger (on by default)
    review-gateway-deploy from-request               run by review-gateway-deploy.path, not by hand

The commit SHA is the only input that reaches the network, and only as part of fixed GitHub URLs. Before anything live
changes the deployer checks that the commit is on ``main`` (a SHA alone does not prove that: GitHub serves fork commits
under the parent repository's URLs), that it is not older than the deployed commit, and that GitHub signed it as a
merge. It then extracts only the service, this deployer and the sync schema, runs that commit's ``install.sh``, checks
both listeners and the schema version, and on failure switches back to the previous release.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.client
import json
import os
import re
import shutil
import sqlite3
import ssl
import stat
import subprocess
import sys
import tarfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import IO, Any, Protocol

REPOSITORY = "destroyer42/StableNew2"
GITHUB_API = f"https://api.github.com/repos/{REPOSITORY}"
CODELOAD = f"https://codeload.github.com/{REPOSITORY}/tar.gz"
SCHEMA_NAME = "stablenew.review-gateway-sync.v1.json"
SERVICE = "review-gateway"
#: Members extracted from the archive (below its top directory); everything else is skipped.
EXTRACT = ("services/review_gateway/", "services/deploy/", f"docs/schemas/{SCHEMA_NAME}")
ARCHIVE_LIMIT = 256 * 1024 * 1024
EXTRACTED_LIMIT = 64 * 1024 * 1024
HEALTH_TIMEOUT = 45.0
HEALTH_INTERVAL = 3.0
NETWORK_TIMEOUT = 30.0
INSTALL_TIMEOUT = 900.0
COMMAND_TIMEOUT = 60.0
INSTALL_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
USER_AGENT = "stablenew-deploy"
REQUEST_LIMIT = 512
REQUEST_KEYS = frozenset({"request_id", "target_sha", "requested_at"})

SHA = re.compile(r"[0-9a-f]{40}")

#: One exit code per outcome, so scripts and the PC tool can tell them apart.
EXIT_CODES = {
    "deployed": 0,
    "already_current": 0,
    "reverted": 0,
    "status": 0,
    "usage": 2,
    "bad_sha": 3,
    "deploy_in_progress": 4,
    "github_unavailable": 5,
    "not_on_main": 6,
    "downgrade": 7,
    "not_github_signed": 8,
    "download_failed": 9,
    "bad_archive": 10,
    "install_failed": 11,
    "rolled_back": 12,
    "rollback_failed": 13,
    "no_previous_release": 14,
    "not_installed": 15,
    "remote_deploy_disabled": 16,
    "bad_request": 17,
    "no_request": 0,
}


class DeployFailure(Exception):
    """A refusal or failure with its reason code; nothing past the step that raised it has run."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Layout:
    """Where the gateway lives in the container (``install.sh``); tests point it at a temporary directory."""

    prefix: Path = Path("/opt/review-gateway")
    config: Path = Path("/etc/review-gateway/config.toml")
    state: Path = Path("/var/lib/review-gateway-deploy")
    admin: Path = Path("/usr/local/bin/review-gateway-admin")
    unit_file: Path = Path("/etc/systemd/system/review-gateway.service")
    switch: Path = Path("/etc/review-gateway/remote-deploy")

    @property
    def current(self) -> Path:
        return self.prefix / "current"

    @property
    def releases(self) -> Path:
        return self.prefix / "releases"

    @property
    def backups(self) -> Path:
        return self.state / "backups"

    @property
    def history(self) -> Path:
        return self.state / "history.jsonl"

    @property
    def last(self) -> Path:
        return self.state / "last.json"

    @property
    def inbox(self) -> Path:
        return self.state / "inbox"

    @property
    def staging(self) -> Path:
        return self.state / "staging"


@dataclass(frozen=True)
class GatewaySettings:
    """The few settings the health check needs, read from the gateway's own ``config.toml``."""

    data_dir: Path
    secret_file: Path
    sync_host: str
    sync_port: int
    phone_host: str
    phone_port: int
    sync_tls_cert: Path | None

    @property
    def database(self) -> Path:
        return self.data_dir / "gateway.sqlite3"


def read_settings(path: Path) -> GatewaySettings:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        cert = raw.get("sync_tls_cert")
        return GatewaySettings(
            data_dir=Path(raw.get("data_dir", "/var/lib/review-gateway/data")),
            secret_file=Path(raw["secret_file"]),
            sync_host=str(raw["sync_host"]),
            sync_port=int(raw.get("sync_port", 9443)),
            phone_host=str(raw.get("phone_host", "127.0.0.1")),
            phone_port=int(raw.get("phone_port", 8443)),
            sync_tls_cert=Path(cert) if cert else None,
        )
    except (
        OSError,
        UnicodeError,
        tomllib.TOMLDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise DeployFailure("not_installed", f"cannot read {path}: {error}") from error


class Completed(Protocol):
    returncode: int
    stdout: str
    stderr: str


class System(Protocol):
    """Everything that touches the machine or the network; ``RealSystem`` in the container, a fake in tests."""

    def run(
        self, argv: Sequence[str], *, env: Mapping[str, str] | None = None, timeout: float
    ) -> Completed: ...

    def read_link(self, path: Path) -> Path | None: ...

    def get_json(self, url: str) -> tuple[int, Any]: ...

    def download(self, url: str, destination: Path, limit: int) -> str: ...

    def probe(
        self, url: str, *, headers: Mapping[str, str], pin: str | None
    ) -> tuple[int, bytes]: ...

    def lock(self) -> contextlib.AbstractContextManager[None]: ...

    def sleep(self, seconds: float) -> None: ...

    def now(self) -> datetime: ...


@dataclass
class Outcome:
    code: str
    lines: list[str] = field(default_factory=list)
    record: dict[str, Any] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.code]


# --- GitHub ----------------------------------------------------------------------------------------------------------


def _github(system: System, path: str) -> tuple[int, Any]:
    try:
        return system.get_json(f"{GITHUB_API}/{path}")
    except (OSError, ValueError) as error:
        raise DeployFailure("github_unavailable", f"GitHub did not answer: {error}") from error


def _compare(system: System, base: str, head: str) -> str | None:
    """GitHub's ``base...head`` status (``ahead`` means head contains base), or None when GitHub knows no such pair."""

    status, body = _github(system, f"compare/{base}...{head}")
    if status in (404, 422):
        return None
    if status != 200 or not isinstance(body, dict):
        raise DeployFailure("github_unavailable", f"GitHub answered {status} for a comparison")
    value = body.get("status")
    return value if isinstance(value, str) else None


def verify_target(
    system: System, target: str, deployed: str | None, *, allow_downgrade: bool
) -> bool:
    """Raise unless ``target`` may be deployed; True when it is already the deployed commit."""

    if _compare(system, target, "main") not in ("identical", "ahead"):
        raise DeployFailure("not_on_main", f"{target} is not on main")
    if deployed is not None:
        relation = _compare(system, deployed, target)
        if relation == "identical":
            return True
        if relation != "ahead" and not allow_downgrade:
            raise DeployFailure(
                "downgrade",
                f"{target} is not newer than the deployed {deployed}; "
                "at the console use: deploy --allow-downgrade <sha>",
            )
    status, body = _github(system, f"commits/{target}")
    if status != 200 or not isinstance(body, dict):
        raise DeployFailure("not_github_signed", f"GitHub answered {status} for the commit")
    commit = body.get("commit") if isinstance(body.get("commit"), dict) else {}
    verification = (
        commit.get("verification") if isinstance(commit.get("verification"), dict) else {}
    )
    committer = body.get("committer") if isinstance(body.get("committer"), dict) else {}
    if verification.get("verified") is not True or committer.get("login") != "web-flow":
        raise DeployFailure("not_github_signed", f"{target} is not a merge GitHub signed")
    return False


# --- archive -----------------------------------------------------------------------------------------------------------


def copy_limited(stream: IO[bytes], destination: Path, limit: int) -> str:
    """Copy at most ``limit`` bytes and return their SHA-256; a longer stream is refused."""

    digest = hashlib.sha256()
    total = 0
    with destination.open("wb") as out:
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise DeployFailure("download_failed", f"the archive is larger than {limit} bytes")
            digest.update(chunk)
            out.write(chunk)
    return digest.hexdigest()


def _member_path(name: str, top: str) -> PurePosixPath | None:
    """The member's path below ``top`` when it is one to extract; refuse any that could escape."""

    if "\\" in name or name.startswith("/") or "\x00" in name:
        raise DeployFailure("bad_archive", f"unsafe member name {name!r}")
    parts = PurePosixPath(name).parts
    if ".." in parts:
        raise DeployFailure("bad_archive", f"unsafe member name {name!r}")
    if not parts or parts[0] != top:
        raise DeployFailure("bad_archive", f"member outside {top}: {name!r}")
    inner = PurePosixPath(*parts[1:]) if len(parts) > 1 else None
    if inner is None:
        return None
    text = inner.as_posix()
    for prefix in EXTRACT:
        if text == prefix.rstrip("/") or text.startswith(prefix):
            return inner
    return None  # outside what is installed (its parent directories are created as needed)


def extract(archive: Path, target: Path, sha: str) -> None:
    """Extract the service, the deployer and the schema with modes 0644/0755; refuse links, devices and escapes."""

    top = f"StableNew2-{sha}"
    total = 0
    try:
        with tarfile.open(archive, mode="r:gz") as tar:
            members = tar.getmembers()
            comment = tar.pax_headers.get("comment")
            if comment is not None and comment != sha:
                raise DeployFailure("bad_archive", f"the archive is for {comment}, not {sha}")
            for member in members:
                inner = _member_path(member.name, top)
                if inner is None:
                    continue
                if not (member.isfile() or member.isdir()):
                    raise DeployFailure(
                        "bad_archive", f"not a plain file or directory: {member.name!r}"
                    )
                path = target.joinpath(*inner.parts)
                if member.isdir():
                    path.mkdir(mode=0o755, parents=True, exist_ok=True)
                    continue
                total += member.size
                if total > EXTRACTED_LIMIT:
                    raise DeployFailure("bad_archive", "the extracted files are too large")
                path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    raise DeployFailure("bad_archive", f"cannot read {member.name!r}")
                with source, path.open("xb") as out:
                    shutil.copyfileobj(source, out)
                path.chmod(0o644)
    except (tarfile.TarError, EOFError, OSError) as error:
        raise DeployFailure("bad_archive", f"the archive cannot be read: {error}") from error
    for required in (
        "services/review_gateway/install.sh",
        "services/deploy/stablenew_deploy.py",
        f"docs/schemas/{SCHEMA_NAME}",
    ):
        if not target.joinpath(*required.split("/")).is_file():
            raise DeployFailure("bad_archive", f"the archive has no {required}")


# --- releases, database, health ----------------------------------------------------------------------------------------


def release_commit(release: Path | None) -> str | None:
    if release is None:
        return None
    try:
        value = json.loads((release / "source.json").read_text(encoding="utf-8")).get("commit")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and SHA.fullmatch(value) else None


def _schema_bytes(release: Path | None) -> bytes | None:
    if release is None:
        return None
    try:
        return (release / "app" / "schema" / SCHEMA_NAME).read_bytes()
    except OSError:
        return None


def _schema_version(release: Path) -> str | None:
    raw = _schema_bytes(release)
    try:
        return json.loads(raw)["$defs"]["schema_version"]["const"] if raw else None
    except (ValueError, KeyError, TypeError):
        return None


def _previous_release(layout: Layout, current: Path | None) -> Path | None:
    try:
        others = sorted(
            (path for path in layout.releases.iterdir() if path.is_dir() and path != current),
            key=lambda path: path.name,
        )
    except OSError:
        return None
    return others[-1] if others else None


def _tables(database: Path) -> list[tuple[Any, ...]]:
    with contextlib.closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)) as db:
        return list(db.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name"))


def restore_database(backup: Path, database: Path, *, only_if_changed: bool) -> bool:
    """Copy ``backup`` over the live database through SQLite (WAL-safe); True when it did."""

    if not backup.is_file() or not database.is_file():
        return False
    if only_if_changed and _tables(backup) == _tables(database):
        return False
    with (
        contextlib.closing(sqlite3.connect(backup)) as source,
        contextlib.closing(sqlite3.connect(database)) as live,
    ):
        source.backup(live)
    return True


def _health_once(
    system: System, layout: Layout, settings: GatewaySettings, release: Path
) -> str | None:
    """None when healthy, otherwise what failed."""

    if (
        system.run(
            ["systemctl", "is-active", "--quiet", SERVICE], timeout=COMMAND_TIMEOUT
        ).returncode
        != 0
    ):
        return "the service is not active"
    try:
        secret = settings.secret_file.read_text(encoding="utf-8").strip()
        pin = certificate_fingerprint(settings.sync_tls_cert) if settings.sync_tls_cert else None
    except (OSError, ValueError) as error:
        return f"cannot read the sync secret or certificate: {error}"
    scheme = "https" if pin else "http"
    try:
        status, body = system.probe(
            f"{scheme}://{settings.sync_host}:{settings.sync_port}/sync/v1/health",
            headers={"Authorization": f"Bearer {secret}"},
            pin=pin,
        )
        answer = json.loads(body) if status == 200 else {}
    except (OSError, ValueError) as error:
        return f"sync health: {error}"
    expected = _schema_version(release)
    if status != 200 or answer.get("status") != "ok" or answer.get("schema_version") != expected:
        return (
            f"sync health answered {status} {answer.get('schema_version')!r}, expected {expected!r}"
        )
    try:
        status, _ = system.probe(
            f"http://{settings.phone_host}:{settings.phone_port}/", headers={}, pin=None
        )
    except OSError as error:
        return f"phone app: {error}"
    if status != 200:
        return f"phone app answered {status}"
    if system.run([str(layout.admin), "status"], timeout=COMMAND_TIMEOUT).returncode != 0:
        return "review-gateway-admin status failed"
    return None


def health_check(
    system: System, layout: Layout, settings: GatewaySettings, release: Path
) -> str | None:
    deadline = system.now() + timedelta(seconds=HEALTH_TIMEOUT)
    while True:
        problem = _health_once(system, layout, settings, release)
        if problem is None or system.now() + timedelta(seconds=HEALTH_INTERVAL) > deadline:
            return problem
        system.sleep(HEALTH_INTERVAL)


def _switch_to(system: System, layout: Layout, release: Path) -> None:
    """Stop, point ``current`` at ``release``, reinstall its unit file, reload; the caller starts the service."""

    system.run(["systemctl", "stop", SERVICE], timeout=COMMAND_TIMEOUT)
    system.run(["ln", "-sfn", str(release), str(layout.current)], timeout=COMMAND_TIMEOUT)
    unit = release / "app" / "review-gateway.service"
    if unit.is_file():
        system.run(
            ["install", "-m", "0644", str(unit), str(layout.unit_file)], timeout=COMMAND_TIMEOUT
        )
    system.run(["systemctl", "daemon-reload"], timeout=COMMAND_TIMEOUT)


def _revert(
    system: System,
    layout: Layout,
    settings: GatewaySettings,
    *,
    failed: Path,
    previous: Path,
    restore: str,
) -> tuple[bool, bool, str | None]:
    """Switch back to ``previous``; ``restore`` is ``changed``, ``always`` or ``never``. (healthy, restored, problem)"""

    _switch_to(system, layout, previous)
    restored = False
    if restore != "never":
        backup = layout.backups / f"{failed.name}.sqlite3"
        try:
            restored = restore_database(
                backup, settings.database, only_if_changed=restore == "changed"
            )
        except sqlite3.Error as error:
            system.run(["systemctl", "start", SERVICE], timeout=COMMAND_TIMEOUT)
            return False, False, f"the database backup could not be restored: {error}"
    system.run(["systemctl", "start", SERVICE], timeout=COMMAND_TIMEOUT)
    problem = health_check(system, layout, settings, previous)
    return problem is None, restored, problem


# --- records -------------------------------------------------------------------------------------------------------------


def _stamp(system: System) -> str:
    return system.now().astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_last(layout: Layout, line: str) -> None:
    """``last.json`` is read by the gateway service (DEPLOY-2 status), so it is world-readable; it holds no secret."""

    layout.state.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = layout.last.with_name(layout.last.name + ".tmp")
    temporary.write_text(line + "\n", encoding="utf-8")
    temporary.chmod(0o644)
    os.replace(temporary, layout.last)


def _record(layout: Layout, record: dict[str, Any]) -> None:
    layout.state.mkdir(mode=0o755, parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True)
    with layout.history.open("a", encoding="utf-8") as history:
        history.write(line + "\n")
    _write_last(layout, line)


def _mark_running(layout: Layout, record: dict[str, Any]) -> None:
    _write_last(
        layout, json.dumps({**record, "outcome": "running", "finished_at": None}, sort_keys=True)
    )


# --- commands ------------------------------------------------------------------------------------------------------------


def deploy(
    target: str,
    *,
    system: System,
    layout: Layout = Layout(),
    allow_downgrade: bool = False,
    trigger: str = "console",
    request_id: str | None = None,
) -> Outcome:
    record: dict[str, Any] = {
        "action": "deploy",
        "trigger": trigger,
        "request_id": request_id,
        "target": target if SHA.fullmatch(target) else None,
        "allow_downgrade": allow_downgrade,
        "old_commit": None,
        "new_commit": None,
        "old_release": None,
        "new_release": None,
        "archive_sha256": None,
        "schema_changed": False,
        "database_restored": False,
        "reason": None,
    }
    outcome = Outcome("deployed", record=record)
    if not SHA.fullmatch(target):
        outcome.code = "bad_sha"
        outcome.lines.append("refused: the commit must be 40 lowercase hexadecimal characters")
        record.update(finished_at=_stamp(system), outcome=outcome.code)
        _record(layout, record)
        return outcome
    try:
        with system.lock():
            _deploy_locked(target, system, layout, allow_downgrade, outcome)
    except DeployFailure as failure:
        outcome.code = failure.code
        outcome.lines.append(f"refused: {failure.message}")
    record.update(
        started_at=record.get("started_at") or _stamp(system),
        finished_at=_stamp(system),
        outcome=outcome.code,
    )
    _record(layout, record)
    return outcome


def _deploy_locked(
    target: str, system: System, layout: Layout, allow_downgrade: bool, outcome: Outcome
) -> None:
    record = outcome.record
    record["started_at"] = _stamp(system)
    settings = read_settings(layout.config)
    old = system.read_link(layout.current)
    if old is None:
        raise DeployFailure(
            "not_installed", f"{layout.current} does not exist; install the gateway first"
        )
    deployed = release_commit(old)
    record.update(old_release=old.name, old_commit=deployed)
    _mark_running(layout, record)
    if deployed is None:
        outcome.lines.append(
            f"note: {old.name} has no recorded commit; the forward-only check is skipped once"
        )
    if verify_target(system, target, deployed, allow_downgrade=allow_downgrade):
        outcome.code = "already_current"
        outcome.lines.append(f"{target} is already deployed ({old.name})")
        return
    layout.staging.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = layout.staging / f"{target}-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(mode=0o700)
    try:
        archive = staging / "archive.tar.gz"
        try:
            record["archive_sha256"] = system.download(
                f"{CODELOAD}/{target}", archive, ARCHIVE_LIMIT
            )
        except OSError as error:
            raise DeployFailure(
                "download_failed", f"the archive could not be downloaded: {error}"
            ) from error
        source = staging / "source"
        extract(archive, source, target)
        outcome.lines.append(
            f"verified {target}: on main, newer than the deployed commit, signed by GitHub"
        )
        installed = system.run(
            ["bash", str(source / "services" / "review_gateway" / "install.sh")],
            env={
                "PATH": INSTALL_PATH,
                "LANG": "C.UTF-8",
                "SOURCE_COMMIT": target,
                "SOURCE_ARCHIVE_SHA256": record["archive_sha256"],
            },
            timeout=INSTALL_TIMEOUT,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    new = system.read_link(layout.current)
    if new is None or new == old:
        if (
            system.run(
                ["systemctl", "is-active", "--quiet", SERVICE], timeout=COMMAND_TIMEOUT
            ).returncode
            != 0
        ):
            system.run(["systemctl", "start", SERVICE], timeout=COMMAND_TIMEOUT)
        detail = (installed.stderr or installed.stdout).strip().splitlines()[-1:] or ["no output"]
        raise DeployFailure("install_failed", f"the installer did not switch releases: {detail[0]}")
    record.update(new_release=new.name, new_commit=release_commit(new))
    record["schema_changed"] = _schema_bytes(old) != _schema_bytes(new)
    problem = "the installer failed after switching" if installed.returncode != 0 else None
    reason = "install_failed" if problem else None
    if problem is None:
        problem = health_check(system, layout, settings, new)
        reason = "health_check_failed" if problem else None
    if problem is None:
        outcome.code = "deployed"
        outcome.lines.append(f"deployed {target} as {new.name} (previous {old.name})")
        if record["schema_changed"]:
            outcome.lines.append(
                "warning: the sync schema changed; update the PC app (StableNew) to this commit too"
            )
        return
    record["reason"] = reason
    outcome.lines.append(f"health check failed: {problem}; switching back to {old.name}")
    healthy, restored, again = _revert(
        system, layout, settings, failed=new, previous=old, restore="changed"
    )
    record["database_restored"] = restored
    if restored:
        outcome.lines.append("the database was restored from the backup taken before the switch")
    if healthy:
        outcome.code = "rolled_back"
        outcome.lines.append(f"rolled back to {old.name}")
    else:
        outcome.code = "rollback_failed"
        record["rollback_problem"] = again
        outcome.lines.append(f"rollback failed: {again}; journalctl -u {SERVICE}")


def rollback(
    *, system: System, layout: Layout = Layout(), restore_database: bool = False
) -> Outcome:
    record: dict[str, Any] = {
        "action": "rollback",
        "trigger": "console",
        "database_restored": False,
        "reason": None,
    }
    outcome = Outcome("reverted", record=record)
    record["started_at"] = _stamp(system)
    try:
        with system.lock():
            settings = read_settings(layout.config)
            current = system.read_link(layout.current)
            previous = _previous_release(layout, current)
            record.update(
                old_release=current.name if current else None,
                old_commit=release_commit(current),
                new_release=previous.name if previous else None,
                new_commit=release_commit(previous),
            )
            if current is None or previous is None:
                raise DeployFailure(
                    "no_previous_release", "there is no previous release to switch back to"
                )
            healthy, restored, problem = _revert(
                system,
                layout,
                settings,
                failed=current,
                previous=previous,
                restore="always" if restore_database else "never",
            )
            record["database_restored"] = restored
            if healthy:
                outcome.lines.append(f"switched back to {previous.name}")
                if not restore_database:
                    outcome.lines.append(
                        "the database was kept; if the older release fails on it, run rollback --restore-database"
                    )
            else:
                outcome.code = "rollback_failed"
                outcome.lines.append(f"the previous release is not healthy: {problem}")
    except DeployFailure as failure:
        outcome.code = failure.code
        outcome.lines.append(f"refused: {failure.message}")
    record.update(finished_at=_stamp(system), outcome=outcome.code)
    _record(layout, record)
    return outcome


def remote_enabled(layout: Layout) -> bool:
    """The console switch for DEPLOY-2; anything but ``enabled`` (or no file) is off."""

    try:
        with layout.switch.open("rb") as source:
            return source.read(64).strip() == b"enabled"
    except OSError:
        return False


def set_remote(layout: Layout, enabled: bool) -> None:
    layout.switch.parent.mkdir(parents=True, exist_ok=True)
    temporary = layout.switch.with_name(layout.switch.name + ".tmp")
    temporary.write_text("enabled\n" if enabled else "disabled\n", encoding="utf-8")
    temporary.chmod(0o644)
    os.replace(temporary, layout.switch)


def read_request(path: Path) -> tuple[str, str]:
    """The request the gateway service wrote. Never follows a link; always deleted, readable or not."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        if (
            path.is_symlink()
        ):  # O_NOFOLLOW does the same on Linux; this also covers Windows test runs
            raise DeployFailure("bad_request", "the request is a symbolic link")
        try:
            descriptor = os.open(path, flags)
        except OSError as error:
            raise DeployFailure("bad_request", f"the request cannot be opened: {error}") from error
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise DeployFailure("bad_request", "the request is not a regular file")
            raw = source.read(REQUEST_LIMIT + 1)
    finally:
        with contextlib.suppress(OSError):
            path.unlink()
    if len(raw) > REQUEST_LIMIT:
        raise DeployFailure("bad_request", "the request is too large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise DeployFailure("bad_request", "the request is not JSON") from error
    if not isinstance(value, dict) or set(value) != REQUEST_KEYS:
        raise DeployFailure("bad_request", "the request has other fields")
    request_id, target = value["request_id"], value["target_sha"]
    try:
        valid_id = isinstance(request_id, str) and str(uuid.UUID(request_id)) == request_id
    except ValueError:
        valid_id = False
    if not valid_id or not isinstance(target, str) or not SHA.fullmatch(target):
        raise DeployFailure("bad_request", "the request id or commit is malformed")
    return request_id, target


def from_request(*, system: System, layout: Layout = Layout()) -> Outcome:
    """Run the one waiting request from the PC (DEPLOY-2): the same checks as the console, never a downgrade."""

    path = layout.inbox / "request.json"
    if not path.exists() and not path.is_symlink():
        return Outcome("no_request", ["no deploy request is waiting"])
    try:
        request_id, target = read_request(path)
    except DeployFailure as failure:
        record = {
            "action": "deploy",
            "trigger": "remote",
            "request_id": None,
            "reason": failure.message,
        }
        record.update(started_at=_stamp(system), finished_at=_stamp(system), outcome=failure.code)
        _record(layout, record)
        return Outcome(failure.code, [f"refused: {failure.message}"], record)
    if not remote_enabled(layout):
        record = {
            "action": "deploy",
            "trigger": "remote",
            "request_id": request_id,
            "target": target,
        }
        record.update(
            started_at=_stamp(system), finished_at=_stamp(system), outcome="remote_deploy_disabled"
        )
        _record(layout, record)
        return Outcome(
            "remote_deploy_disabled",
            ["refused: remote deploy is off; at the console: review-gateway-deploy remote on"],
            record,
        )
    return deploy(target, system=system, layout=layout, trigger="remote", request_id=request_id)


def status(*, system: System, layout: Layout = Layout()) -> list[str]:
    current = system.read_link(layout.current)
    previous = _previous_release(layout, current)
    lines = [
        f"release:  {current.name if current else '(none)'}",
        f"commit:   {release_commit(current) or 'unknown'}",
        f"previous: {previous.name if previous else '(none)'} ({release_commit(previous) or 'unknown'})"
        if previous
        else "previous: (none)",
    ]
    try:
        last = json.loads(layout.last.read_text(encoding="utf-8"))
        lines.append(
            f"last:     {last.get('outcome')} {last.get('action')} {last.get('target') or ''} at {last.get('finished_at')}".rstrip()
        )
    except (OSError, ValueError):
        lines.append("last:     (no deploy recorded)")
    lines.append(f"remote:   {'enabled' if remote_enabled(layout) else 'disabled'}")
    return lines


# --- the real system ------------------------------------------------------------------------------------------------------


def certificate_fingerprint(path: Path) -> str:
    der = ssl.PEM_cert_to_DER_cert(path.read_text(encoding="ascii").strip())
    return hashlib.sha256(der).hexdigest()


def check_pin(der: bytes | None, fingerprint: str) -> None:
    """Refuse a peer whose certificate is not the pinned one, before anything (the secret) is sent."""

    if der is None or hashlib.sha256(der).hexdigest() != fingerprint:
        raise OSError("the sync certificate is not the pinned one")


class RealSystem:
    def __init__(self, layout: Layout) -> None:
        self.layout = layout

    def run(
        self, argv: Sequence[str], *, env: Mapping[str, str] | None = None, timeout: float
    ) -> Completed:
        return subprocess.run(
            list(argv),
            env=dict(env) if env is not None else None,
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
        )

    def read_link(self, path: Path) -> Path | None:
        if not path.is_symlink():
            return None
        return Path(os.path.realpath(path))

    def _open(self, url: str, accept: str) -> Any:
        request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": USER_AGENT})
        return urllib.request.urlopen(
            request, timeout=NETWORK_TIMEOUT, context=ssl.create_default_context()
        )

    def get_json(self, url: str) -> tuple[int, Any]:
        try:
            with self._open(url, "application/vnd.github+json") as response:
                return response.status, json.loads(response.read(4 * 1024 * 1024))
        except urllib.error.HTTPError as error:
            return error.code, None

    def download(self, url: str, destination: Path, limit: int) -> str:
        with self._open(url, "application/octet-stream") as response:
            return copy_limited(response, destination, limit)

    def probe(self, url: str, *, headers: Mapping[str, str], pin: str | None) -> tuple[int, bytes]:
        parsed = urllib.parse.urlsplit(url)
        host, port = parsed.hostname or "", parsed.port or 0
        if parsed.scheme == "https":
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE  # replaced by the pin below, as on the PC
            connection: http.client.HTTPConnection = http.client.HTTPSConnection(
                host, port, timeout=10, context=context
            )
            connection.connect()
            check_pin(connection.sock.getpeercert(binary_form=True), pin or "")  # type: ignore[union-attr]
        else:
            connection = http.client.HTTPConnection(host, port, timeout=10)
        try:
            connection.request("GET", parsed.path or "/", headers=dict(headers))
            response = connection.getresponse()
            return response.status, response.read(64 * 1024)
        finally:
            connection.close()

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        import fcntl  # Linux only; the container is Debian

        self.layout.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(self.layout.state / "lock", "w", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DeployFailure("deploy_in_progress", "another deploy is running") from None
            yield

    def sleep(self, seconds: float) -> None:
        import time

        time.sleep(seconds)

    def now(self) -> datetime:
        return datetime.now(UTC)


# --- command line ------------------------------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review-gateway-deploy", description=__doc__.split("\n\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("deploy", help="deploy a commit of main")
    run.add_argument("sha")
    run.add_argument(
        "--allow-downgrade", action="store_true", help="allow a commit older than the deployed one"
    )
    commands.add_parser(
        "status", help="the deployed commit, the previous release and the last result"
    )
    back = commands.add_parser("rollback", help="switch back to the previous release")
    back.add_argument(
        "--restore-database",
        action="store_true",
        help="also restore the database backup taken before this release",
    )
    switch = commands.add_parser(
        "remote", help="turn the PC's deploy trigger on or off (console only)"
    )
    switch.add_argument("state", choices=("on", "off"))
    commands.add_parser(
        "from-request", help="run the waiting request from the PC (the path unit runs this)"
    )
    return parser


def main(
    argv: Sequence[str] | None = None, *, system: System | None = None, layout: Layout = Layout()
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if (
        arguments
        and arguments[0] not in ("deploy", "status", "rollback", "remote", "from-request")
        and not arguments[0].startswith("-")
    ):
        arguments.insert(0, "deploy")
    try:
        args = _parser().parse_args(arguments)
    except SystemExit as exit_:
        return EXIT_CODES["usage"] if exit_.code else 0
    system = system or RealSystem(layout)
    if args.command == "status":
        print("\n".join(status(system=system, layout=layout)))
        return 0
    if args.command == "remote":
        set_remote(layout, args.state == "on")
        print(f"remote deploy from the PC is {'on' if args.state == 'on' else 'off'}")
        return 0
    if args.command == "from-request":
        outcome = from_request(system=system, layout=layout)
    elif args.command == "rollback":
        outcome = rollback(system=system, layout=layout, restore_database=args.restore_database)
    else:
        outcome = deploy(
            args.sha, system=system, layout=layout, allow_downgrade=args.allow_downgrade
        )
    for line in outcome.lines:
        print(line)
    print(f"outcome: {outcome.code}")
    return outcome.exit_code


if __name__ == "__main__":
    if os.name == "posix" and os.geteuid() != 0:
        print("review-gateway-deploy: run as root", file=sys.stderr)
        raise SystemExit(EXIT_CODES["usage"])
    raise SystemExit(main())
