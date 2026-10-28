"""Read-only revision token for a recommendation's existing JSONL source."""

from pathlib import Path


def evidence_revision(path: str | Path) -> tuple[int, int, int] | None:
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size
