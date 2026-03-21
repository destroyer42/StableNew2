#!/usr/bin/env python
"""
StableNew Snapshot & Repo Inventory Tool.

Creates a timestamped shareable repo snapshot zip plus a simple inventory JSON
for cases where an external reviewer or AI agent does not have direct repo
access.

Run from repo root:
    python tools/stablenew_snapshot_and_inventory.py
"""

from __future__ import annotations

import fnmatch
import json
import os
import sys
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = ROOT / "snapshots"


DEFAULT_EXCLUDES = {
    ".git",
    ".idea",
    ".vscode",
    ".mypy_cache",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    "node_modules",
    ".DS_Store",
    "snapshots",
    "logs",
    "output",
    "archive_tmp",
    "runs",
    "htmlcov",
    "archive",
}

DEFAULT_EXCLUDED_EXTS = {
    ".log",
    ".tmp",
    ".pyc",
    ".pyo",
    ".pyd",
}


@dataclass
class FileEntry:
    path: str
    size_bytes: int
    mtime_iso: str


@dataclass
class RepoInventory:
    repo_root: str
    created_at: str
    snapshot_zip: str
    file_count: int
    total_size_bytes: int
    excludes: list[str]
    excluded_exts: list[str]
    files: list[FileEntry]


def load_gitignore_patterns(repo_root: Path) -> list[str]:
    gitignore = repo_root / ".gitignore"
    patterns: list[str] = []
    if gitignore.exists():
        with gitignore.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
    return patterns


def is_gitignored(path: Path, repo_root: Path, gitignore_patterns: list[str]) -> bool:
    rel = path.relative_to(repo_root).as_posix()
    for pattern in gitignore_patterns:
        if pattern.endswith("/") and rel.startswith(pattern.rstrip("/")):
            return True
        if fnmatch.fnmatch(rel, pattern):
            return True
    return False


def is_excluded(path: Path, repo_root: Path, gitignore_patterns: list[str] | None = None) -> bool:
    rel = path.relative_to(repo_root)
    for part in rel.parts:
        if part in DEFAULT_EXCLUDES:
            return True
    if path.suffix.lower() in DEFAULT_EXCLUDED_EXTS:
        return True
    if gitignore_patterns and is_gitignored(path, repo_root, gitignore_patterns):
        return True
    return False


def gather_files(repo_root: Path) -> list[FileEntry]:
    entries: list[FileEntry] = []
    gitignore_patterns = load_gitignore_patterns(repo_root)
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        if is_excluded(path, repo_root, gitignore_patterns):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append(
            FileEntry(
                path=path.relative_to(repo_root).as_posix(),
                size_bytes=stat.st_size,
                mtime_iso=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            )
        )
    return entries


def create_snapshot_zip(repo_root: Path, snapshot_dir: Path) -> Path:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_path = snapshot_dir / f"StableNew-snapshot-{timestamp}.zip"

    gitignore_patterns = load_gitignore_patterns(repo_root)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in repo_root.rglob("*"):
            if not path.is_file():
                continue
            if is_excluded(path, repo_root, gitignore_patterns):
                continue
            archive.write(path, arcname=path.relative_to(repo_root).as_posix())
    return zip_path


def write_inventory(repo_root: Path, snapshot_zip: Path, entries: list[FileEntry]) -> Path:
    inventory = RepoInventory(
        repo_root=str(repo_root),
        created_at=datetime.now().isoformat(timespec="seconds"),
        snapshot_zip=str(snapshot_zip),
        file_count=len(entries),
        total_size_bytes=sum(entry.size_bytes for entry in entries),
        excludes=sorted(DEFAULT_EXCLUDES),
        excluded_exts=sorted(DEFAULT_EXCLUDED_EXTS),
        files=entries,
    )
    inventory_path = snapshot_zip.with_name("repo_inventory.json")
    with inventory_path.open("w", encoding="utf-8") as handle:
        json.dump(asdict(inventory), handle, ensure_ascii=False, indent=2)
    return inventory_path


def main() -> int:
    print("============================================")
    print(" StableNew Snapshot & Repo Inventory Tool")
    print("============================================")
    print(f"[INFO] Repo root: {ROOT}")
    print("[INFO] Building file list...")

    entries = gather_files(ROOT)
    print(f"[INFO] Tracked files: {len(entries)}")

    snapshot_zip = create_snapshot_zip(ROOT, SNAPSHOT_DIR)
    inventory_path = write_inventory(ROOT, snapshot_zip, entries)

    print("")
    print("[DONE] Snapshot and inventory successfully created.")
    print(f"       Snapshot:  {snapshot_zip}")
    print(f"       Inventory: {inventory_path}")
    print("")
    print("Use the zip + JSON together when sharing the repo for external analysis.")
    print("")

    if os.name == "nt" and sys.stdin is None:
        os.system("pause")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
