"""Verified copy-only legacy migration with per-asset recovery. Originals and failed staging stay intact."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import stat
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .paths import canonical_path, io_path, rename_without_replace

logger = logging.getLogger(__name__)
_RETRY_DELAYS = (0.1, 0.25)


@dataclass(frozen=True)
class MigrationIssue:
    asset_id: str
    phase: str
    source: str
    destination: str
    staging: str | None
    error: str
    winerror: int | None
    attempts: int

    def describe(self) -> str:
        return (
            f"{self.asset_id}: {self.phase} failed: {self.error} (rename attempts: {self.attempts}).\n"
            f"Source: {self.source}\nDestination: {self.destination}\nRetained staging: {self.staging or '(none)'}\n"
            "Close applications using these files, check folder permissions and free space, then Retry Legacy "
            "Migration. An existing destination must be inspected; it will never be overwritten or removed."
        )


@dataclass
class MigrationReport:
    migrated: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    failures: list[MigrationIssue] = field(default_factory=list)

    def summary(self) -> str:
        state = "Legacy migration incomplete" if self.failures else "Legacy migration checked"
        return (
            f"{state}: {len(self.migrated)} migrated, {len(self.already_present)} already verified, "
            f"{len(self.failures)} failed/skipped. "
            + (
                "New imports remain available; legacy originals and staging are retained."
                if self.failures
                else ""
            )
        )

    def details(self) -> str:
        return self.summary() + "\n\n" + "\n\n".join(issue.describe() for issue in self.failures)


@dataclass
class _Attempt:
    phase: str = "read sidecar"
    staging: Path | None = None
    renames: int = 0


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with io_path(path, force=True).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _linked(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _existing_copy(destination: Path, source: Path) -> bool:
    if not destination.exists() and not _linked(destination):
        return False
    marker = destination / "migration.json"
    if (
        not _linked(destination)
        and marker.is_file()
        and not _linked(marker)
        and not _linked(destination / "sidecar.json")
    ):
        record = json.loads(io_path(marker).read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError(f"Invalid migration marker: {marker}")
        hashes = record.get("files")
        if record.get("source") == str(source.resolve()) and isinstance(hashes, dict) and hashes:
            for name, sha in hashes.items():
                relative = Path(name)
                path = destination / relative
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or _linked(path)
                    or not canonical_path(path.resolve()).is_relative_to(
                        canonical_path(destination.resolve())
                    )
                    or not path.is_file()
                    or _digest(path) != sha
                ):
                    break
            else:
                sidecar = json.loads(
                    io_path(destination / "sidecar.json").read_text(encoding="utf-8")
                )
                if isinstance(sidecar, dict) and sidecar.get("asset_id") == destination.name:
                    return True
    raise FileExistsError(f"Photo workspace collision or changed migration copy: {destination}")


def _publish(staged: Path, destination: Path, source: Path, attempt: _Attempt) -> bool:
    for index in range(len(_RETRY_DELAYS) + 1):
        if _existing_copy(destination, source):
            return False
        attempt.renames += 1
        try:
            rename_without_replace(staged, destination)
            return True
        except OSError as exc:
            if _existing_copy(destination, source):
                return False
            # Native Windows repro: held child -> 5; held directory -> 32. 5 can also be permanent ACL denial.
            # Limit that ambiguity to three attempts, then retain and report. Other errors are not retried.
            if getattr(exc, "winerror", None) not in {5, 32, 33} or index == len(_RETRY_DELAYS):
                raise
            time.sleep(_RETRY_DELAYS[index])
    raise AssertionError("unreachable")


def _migrate_asset(sidecar: Path, target_root: Path, attempt: _Attempt) -> bool:
    source = sidecar.parent
    if _linked(source) or _linked(sidecar):
        raise ValueError(f"Legacy asset contains a link: {source}")
    sidecar_digest = _digest(sidecar)
    payload = json.loads(io_path(sidecar, force=True).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") not in {None, "1.0"}:
        raise ValueError(f"Unsupported legacy Photo Optimize sidecar: {sidecar}")
    asset_id = payload.get("asset_id")
    if not asset_id or asset_id != source.name:
        raise ValueError(f"Invalid legacy asset identity: {sidecar}")
    destination = target_root / "assets" / asset_id
    attempt.phase = "check destination"
    if _existing_copy(destination, source):
        return False
    paths = list(source.rglob("*"))
    if any(_linked(path) for path in paths):
        raise ValueError(f"Legacy asset contains a link: {source}")
    attempt.phase = "copy and verify"
    staged = target_root / "migration_staging" / uuid.uuid4().hex
    attempt.staging = staged
    if _linked(staged.parent):
        raise ValueError(f"Migration staging root is a link: {staged.parent}")
    shutil.copytree(io_path(source, force=True), io_path(staged, force=True))
    hashes = {}
    for path in paths:
        if path.is_file():
            relative = path.relative_to(source)
            sha = _digest(path)
            if _digest(staged / relative) != sha:
                raise OSError(f"Photo migration verification failed: {path}")
            if relative != Path("sidecar.json"):
                hashes[str(relative)] = sha

    attempt.phase = "route current paths"

    def routed(raw):
        path = Path(raw)
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            relative = canonical_path(path.resolve()).relative_to(canonical_path(source.resolve()))
        except ValueError:
            return raw
        if not io_path(staged / relative).is_file():
            raise FileNotFoundError(f"Legacy current photo is missing: {raw}")
        return str(io_path(destination / relative))

    payload["managed_original_path"] = routed(payload["managed_original_path"])
    baseline = payload.setdefault("baseline", {})
    if not isinstance(baseline, dict):
        raise ValueError(f"Invalid legacy baseline: {sidecar}")
    if baseline.get("working_image_path"):
        baseline["working_image_path"] = routed(baseline["working_image_path"])
    io_path(staged / "sidecar.json", force=True).write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    io_path(staged / "migration.json", force=True).write_text(
        json.dumps({"source": str(source.resolve()), "files": hashes}, indent=2), encoding="utf-8"
    )
    if _digest(sidecar) != sidecar_digest or any(
        _digest(source / name) != sha for name, sha in hashes.items()
    ):
        raise OSError(f"Legacy photo changed during migration; retry after it is idle: {sidecar}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    attempt.phase = "publish verified copy"
    return _publish(staged, destination, source, attempt)


def migrate_assets(legacy_root: Path, target_root: Path) -> MigrationReport:
    """Recover each recognized asset independently; never delete originals, destinations or old staging."""
    report = MigrationReport()
    try:
        if legacy_root.resolve() == target_root.resolve():
            return report
        assets = legacy_root / "assets"
        try:
            assets.stat()
        except FileNotFoundError:
            return report
        sources = sorted(assets.iterdir())
    except OSError as exc:
        report.failures.append(
            MigrationIssue(
                "(legacy scan)",
                "scan",
                str(legacy_root),
                str(target_root),
                None,
                str(exc),
                getattr(exc, "winerror", None),
                0,
            )
        )
        return report
    for source in sources:
        sidecar = source / "sidecar.json"
        attempt = _Attempt()
        try:
            try:
                is_file = stat.S_ISREG(sidecar.stat().st_mode)
            except FileNotFoundError:
                continue
            if not is_file:
                continue
            copied = _migrate_asset(sidecar, target_root, attempt)
            (report.migrated if copied else report.already_present).append(source.name)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            issue = MigrationIssue(
                source.name,
                attempt.phase,
                str(source),
                str(target_root / "assets" / source.name),
                str(attempt.staging) if attempt.staging else None,
                str(exc),
                getattr(exc, "winerror", None),
                attempt.renames,
            )
            report.failures.append(issue)
            logger.warning("Photo legacy migration incomplete: %s", issue.describe())
    return report
