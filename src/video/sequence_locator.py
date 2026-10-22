"""Find a sequence job's checkpoint ledger when its result did not record one (PR-VID-SEQ-331A).

A failed or finished sequence records ``ledger_path`` in its result. A cancelled one records no result at all, but its
run folder still holds ``sequence_state.json``, and that folder is named after the job (the runner builds it from the
job id's first twelve characters). The locator reads only those folders, never the whole output tree, and trusts a file
only when the ledger inside it names this very job; the resume itself then re-verifies the checkpoint as it always did.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final

from src.state.output_routing import KNOWN_OUTPUT_ROUTE_DIRS
from src.video.sequence_ledger import LEDGER_FILE_NAME

#: A ledger is small JSON; anything larger is not one of ours.
MAX_LEDGER_BYTES: Final = 8 * 1024 * 1024
#: The runner's folder label for a job that belongs to no PromptPack: ``job_id[:12]`` with unsafe characters replaced.
FOLDER_TOKEN_LENGTH: Final = 12


def folder_token(job_id: str) -> str:
    return "".join(
        c if c.isalnum() or c in ("-", "_") else "_" for c in str(job_id)[:FOLDER_TOKEN_LENGTH]
    )


def _route_directories(root: Path) -> Iterable[Path]:
    yield root
    for name in KNOWN_OUTPUT_ROUTE_DIRS:
        yield root / name


def _ledger_names_job(path: Path, job_id: str) -> bool:
    try:
        if path.stat().st_size > MAX_LEDGER_BYTES:
            return False
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and str(data.get("job_id") or "") == str(job_id)


def locate_ledger(job_id: str, output_roots: Iterable[str | os.PathLike[str]]) -> str | None:
    """The ``sequence_state.json`` of ``job_id`` under ``output_roots`` (and their route folders), or ``None``."""

    token = folder_token(job_id)
    if not token:
        return None
    seen: set[Path] = set()
    for raw in output_roots:
        try:
            root = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        for directory in _route_directories(root):
            if directory in seen or not directory.is_dir():
                continue
            seen.add(directory)
            try:
                with os.scandir(directory) as entries:
                    names = [e.name for e in entries if token in e.name and e.is_dir()]
            except OSError:
                continue
            for name in sorted(names):
                candidate = directory / name / LEDGER_FILE_NAME
                if candidate.is_file() and _ledger_names_job(candidate, job_id):
                    return str(candidate)
    return None


__all__ = ["folder_token", "locate_ledger"]
