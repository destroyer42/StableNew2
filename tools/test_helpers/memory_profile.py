from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def create_memprof_dir(*, base_dir: str | Path | None = None, prefix: str = "memprof_") -> Path:
    """Create a temp directory for ad hoc memory-profiling assets.

    By default this uses the system temp directory instead of the current
    working directory so profiling runs do not litter the repo root.
    """

    parent = Path(base_dir) if base_dir is not None else Path(tempfile.gettempdir())
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(parent)))


def write_memprof_plugin(
    plugin_source: str,
    *,
    base_dir: str | Path | None = None,
    prefix: str = "memprof_",
    filename: str = "mem_profile_plugin.py",
) -> Path:
    """Write a pytest memory-profile plugin into a temp memprof directory."""

    temp_dir = create_memprof_dir(base_dir=base_dir, prefix=prefix)
    plugin_path = temp_dir / filename
    plugin_path.write_text(plugin_source, encoding="utf-8")
    return plugin_path


@contextmanager
def temporary_memprof_plugin(
    plugin_source: str,
    *,
    base_dir: str | Path | None = None,
    prefix: str = "memprof_",
    filename: str = "mem_profile_plugin.py",
    cleanup: bool = True,
) -> Iterator[Path]:
    """Yield a temporary pytest memory-profile plugin path and clean it up."""

    plugin_path = write_memprof_plugin(
        plugin_source,
        base_dir=base_dir,
        prefix=prefix,
        filename=filename,
    )
    try:
        yield plugin_path
    finally:
        if cleanup:
            shutil.rmtree(plugin_path.parent, ignore_errors=True)
