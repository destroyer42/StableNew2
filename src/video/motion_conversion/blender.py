"""Optional, operator-selected Blender executable (PR-VID-MOTION-354).

StableNew never downloads or installs Blender and never imports ``bpy``.  A candidate is an explicit path (or one found in
the environment variable ``STABLENEW_BLENDER`` / the usual install folders / ``PATH``), accepted only after
``blender --version`` run as a bounded, contained child reports a supported version.  Every later call is a separate
background child with ``--factory-startup`` (no user add-ons or preferences) and ``--disable-autoexec`` (no embedded
scripts or drivers).
"""

from __future__ import annotations

import os
import re
import shutil
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from src.utils.managed_process import ProcessOutcome, run_bounded

ENV_VARIABLE = "STABLENEW_BLENDER"
#: Oldest Blender whose FBX/BVH importers and Cycles CPU settings the render script was written against.
MINIMUM_VERSION = (4, 2, 0)
VERSION_TIMEOUT_SECONDS = 60.0
MAX_VERSION_BYTES = 16 * 1024
_VERSION = re.compile(r"Blender\s+(\d+)\.(\d+)(?:\.(\d+))?", re.IGNORECASE)
#: Environment names a child must not inherit: they can redirect Python or Blender's user scripts, config and add-ons.
_SCRUBBED_ENV = (
    "PYTHONPATH",
    "PYTHONHOME",
    "PYTHONSTARTUP",
    "PYTHONUSERBASE",
    "BLENDER_USER_RESOURCES",
)

ProcessRunner = Callable[..., ProcessOutcome]


class BlenderProblem(RuntimeError):
    """Blender is unavailable or unsupported; the message says why."""


@dataclass(frozen=True, slots=True)
class BlenderInstall:
    executable: Path
    version: tuple[int, int, int]
    version_text: str
    #: The command words that start Blender; tests substitute a fake with the same command-line contract.
    argv_prefix: tuple[str, ...] = ()

    def command(self, *args: str) -> list[str]:
        prefix = self.argv_prefix or (str(self.executable),)
        return [*prefix, *args]

    def to_record(self) -> dict[str, object]:
        return {
            "executable": str(self.executable),
            "version": ".".join(str(part) for part in self.version),
            "version_text": self.version_text,
        }


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.search(text or "")
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def candidate_executables(
    explicit: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    program_dirs: Iterable[str] | None = None,
) -> list[Path]:
    """Where Blender might be, most deliberate first.  Nothing is executed or created here."""

    env = os.environ if environ is None else environ
    found: list[Path] = []

    def add(value: str | Path | None) -> None:
        if value:
            path = Path(str(value)).expanduser()
            if path not in found:
                found.append(path)

    add(explicit)
    add(env.get(ENV_VARIABLE))
    add(which("blender"))
    roots = program_dirs
    if roots is None:
        roots = [
            os.path.join(base, "Blender Foundation")
            for base in (env.get("ProgramFiles", ""), env.get("ProgramW6432", ""))
            if base
        ]
    for root in roots:
        folder = Path(root)
        try:
            for child in sorted(folder.glob("Blender*"), reverse=True):
                add(child / "blender.exe")
        except OSError:
            continue
    return found


def child_environment(base: Mapping[str, str] | None, private_dir: Path) -> dict[str, str]:
    """The environment for a Blender child: the host's, minus Python redirection, with user dirs pointed at empty folders."""

    env = {
        k: v
        for k, v in (os.environ if base is None else base).items()
        if k.upper() not in _SCRUBBED_ENV
    }
    for name in (
        "BLENDER_USER_SCRIPTS",
        "BLENDER_USER_CONFIG",
        "BLENDER_USER_EXTENSIONS",
        "BLENDER_USER_DATAFILES",
    ):
        folder = private_dir / name.lower()
        folder.mkdir(parents=True, exist_ok=True)
        env[name] = str(folder)
    return env


def verify_blender(
    candidate: str | Path,
    *,
    runner: ProcessRunner = run_bounded,
    argv_prefix: Sequence[str] | None = None,
    cancel: threading.Event | None = None,
) -> BlenderInstall:
    """Run ``--version`` as a bounded child and accept only a supported Blender.  Raises ``BlenderProblem``."""

    path = Path(str(candidate)).expanduser()
    if argv_prefix is None and not path.is_file():
        raise BlenderProblem(f"Blender was not found at {path}.")
    prefix = tuple(argv_prefix) if argv_prefix is not None else (str(path),)
    outcome = runner(
        [*prefix, "--background", "--factory-startup", "--version"],
        timeout_seconds=VERSION_TIMEOUT_SECONDS,
        max_stdout_bytes=MAX_VERSION_BYTES,
        cancel=cancel,
    )
    if outcome.launch_error:
        raise BlenderProblem(f"Blender could not be started: {outcome.launch_error}")
    if (
        outcome.timed_out
        or outcome.cancelled
        or outcome.output_truncated
        or outcome.returncode != 0
    ):
        raise BlenderProblem("Blender did not report its version cleanly.")
    text = outcome.stdout.decode("utf-8", "replace")
    version = parse_version(text)
    if version is None:
        raise BlenderProblem("The executable did not identify itself as Blender.")
    if version < MINIMUM_VERSION:
        raise BlenderProblem(
            "Blender {} is older than the supported minimum {}.".format(
                ".".join(map(str, version)), ".".join(map(str, MINIMUM_VERSION))
            )
        )
    first_line = text.strip().splitlines()[0].strip() if text.strip() else ""
    return BlenderInstall(
        path, version, first_line[:80], tuple(argv_prefix) if argv_prefix is not None else ()
    )


def discover_blender(
    explicit: str | Path | None = None,
    *,
    runner: ProcessRunner = run_bounded,
    cancel: threading.Event | None = None,
    **options: object,
) -> BlenderInstall | None:
    """The first candidate that verifies, or ``None``.  A named ``explicit`` path that fails raises instead of being skipped."""

    if explicit:
        return verify_blender(explicit, runner=runner, cancel=cancel)
    for path in candidate_executables(None, **options):  # type: ignore[arg-type]
        if not path.is_file():
            continue
        try:
            return verify_blender(path, runner=runner, cancel=cancel)
        except BlenderProblem:
            continue
    return None
