"""Run a local test command where it cannot disturb the desktop (PR-DEVEX-QUIET-LOCAL-TESTS).

    python tools/ci/quiet_run.py -- python -m pytest tests/gui_v2

On a local Windows machine the command runs on a private desktop (``StableNewTests``) that has no input or display,
inside a job object at below-normal priority. Tk windows there are
real and viewable (layout, focus and ``event_generate`` behave as on the interactive desktop), but nothing reaches the
operator's screen or takes focus from the live application. Children inherit the desktop, the job and its limits;
``KILL_ON_JOB_CLOSE`` ends the whole tree when this process ends, so a cancelled or killed run leaves no hidden
orphans. Standard streams are the caller's own handles, and the exit code is the child's.

``STABLENEW_TESTS_CORES=efficiency`` also limits the job to the efficiency cores of a hybrid CPU. It is off by default:
measured on the owner's i9-13900K, below-normal priority plus efficiency cores roughly doubled the gui_v2/tools wall time and
made two timing-sensitive layout tests fail that pass visibly, with no measurable gain in a normal-priority Tk loop's
latency over priority alone (``docs/superpowers/specs/2026-11-16-unobtrusive-local-tests-design.md``, Outcome).

Pass-through (the command runs exactly as before) when hosted CI is detected (``CI`` set), off Windows, when the
operator opts out with ``STABLENEW_TESTS_VISIBLE=1``, for the opt-in physical-input lane (``STABLENEW_DESKTOP_LANE=1``,
which needs the real desktop) and inside an existing quiet run (``STABLENEW_QUIET_RUN=1``, the recursion marker).

If the private desktop cannot be created, one warning line is printed and the command runs visibly but still in the
low-priority job: visibility fails open, test execution never does. Nothing here touches a process it did not start.

``tests/conftest.py`` relaunches command-line pytest sessions through :func:`relaunch_pytest_session`; the PR gate and
the sharded census wrap their steps and workers with :func:`wrap`.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

DESKTOP_NAME = "StableNewTests"
MARKER_ENV = "STABLENEW_QUIET_RUN"
VISIBLE_ENV = "STABLENEW_TESTS_VISIBLE"
DESKTOP_LANE_ENV = "STABLENEW_DESKTOP_LANE"
CORES_ENV = "STABLENEW_TESTS_CORES"
CORES_EFFICIENCY = "efficiency"
CORES_ALL = "all"
DEFAULT_CORES = CORES_ALL


def cores_setting(environ: Mapping[str, str]) -> str:
    """``efficiency`` (hybrid CPUs: efficiency cores only) or ``all`` (priority only); unknown values use the default."""

    value = environ.get(CORES_ENV, "").strip().lower()
    return value if value in {CORES_EFFICIENCY, CORES_ALL} else DEFAULT_CORES


SCRIPT = Path(__file__).resolve()

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
JOB_OBJECT_LIMIT_AFFINITY = 0x00000010
JOB_OBJECT_LIMIT_PRIORITY_CLASS = 0x00000020
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
STARTF_USESTDHANDLES = 0x00000100
STD_INPUT_HANDLE = 0xFFFFFFF6  # (DWORD)-10
STD_OUTPUT_HANDLE = 0xFFFFFFF5  # (DWORD)-11
STD_ERROR_HANDLE = 0xFFFFFFF4  # (DWORD)-12
INVALID_HANDLE_VALUE = (1 << (8 * ctypes.sizeof(ctypes.c_void_p))) - 1
DUPLICATE_SAME_ACCESS = 0x00000002
MAX_AFFINITY_CPUS = 64
WAIT_SLICE_MS = 250
INTERRUPT_GRACE_MS = 5000
STARTUP_FAILURE_EXIT = 126


@dataclass(frozen=True)
class Core:
    """One physical core from ``GetLogicalProcessorInformationEx(RelationProcessorCore)``."""

    efficiency_class: int
    group: int
    mask: int


@dataclass(frozen=True)
class Plan:
    desktop: str | None
    priority_class: int
    affinity: int | None


class Win32Api(Protocol):
    """The Win32 surface used by :func:`run`; :class:`Win32` is the real one, unit tests pass a fake."""

    def window_station(self) -> str: ...
    def open_desktop(self, name: str) -> int: ...
    def processor_cores(self) -> list[Core]: ...
    def create_job(self, *, priority_class: int, affinity: int | None) -> int: ...
    def create_suspended(
        self,
        application: str,
        command_line: str,
        *,
        desktop: str | None,
        environment: Mapping[str, str],
        cwd: str | None,
        priority_class: int,
    ) -> tuple[int, int]: ...
    def assign(self, job: int, process: int) -> bool: ...
    def set_affinity(self, process: int, mask: int) -> bool: ...
    def resume(self, thread: int) -> None: ...
    def wait(self, process: int, timeout_ms: int) -> bool: ...
    def exit_code(self, process: int) -> int: ...
    def terminate(self, job: int, process: int, code: int) -> None: ...
    def close(self, handle: int) -> None: ...


def efficiency_mask(cores: Sequence[Core], logical_cpus: int) -> int | None:
    """Affinity mask of the lowest-efficiency-class cores, or ``None`` (priority only) when that is not meaningful.

    ``None`` for a non-hybrid CPU (one efficiency class), more than 64 logical CPUs or more than one processor group,
    where a single job affinity mask cannot describe the efficiency cores.
    """

    if not cores or logical_cpus > MAX_AFFINITY_CPUS:
        return None
    if any(core.group != 0 for core in cores):
        return None
    classes = {core.efficiency_class for core in cores}
    if len(classes) < 2:
        return None
    lowest = min(classes)
    mask = 0
    for core in cores:
        if core.efficiency_class == lowest:
            mask |= core.mask
    return mask or None


def quiet_reason_skipped(environ: Mapping[str, str], platform: str = sys.platform) -> str | None:
    """Why the command runs unchanged, or ``None`` when it should run quietly."""

    if platform != "win32":
        return "not Windows"
    if environ.get("CI"):
        return "hosted CI"
    if environ.get(MARKER_ENV) == "1":
        return "already quiet"
    if environ.get(VISIBLE_ENV) == "1":
        return f"{VISIBLE_ENV}=1"
    if environ.get(DESKTOP_LANE_ENV) == "1":
        return f"{DESKTOP_LANE_ENV}=1 needs the real desktop"
    return None


def should_quiet(environ: Mapping[str, str] | None = None, platform: str = sys.platform) -> bool:
    return quiet_reason_skipped(os.environ if environ is None else environ, platform) is None


def wrap(
    command: Sequence[str],
    *,
    environ: Mapping[str, str] | None = None,
    platform: str = sys.platform,
    python: str = sys.executable,
) -> list[str]:
    """``command`` prefixed with this script when it should run quietly, else ``command`` unchanged."""

    if not should_quiet(environ, platform):
        return list(command)
    return [python, str(SCRIPT), "--", *command]


def _resolve(program: str, environ: Mapping[str, str], cwd: str | None) -> str | None:
    candidate = Path(program)
    if candidate.is_absolute() or candidate.parent != Path("."):
        path = candidate if candidate.is_absolute() else Path(cwd or os.getcwd()) / candidate
        for option in (path, path.with_name(path.name + ".exe")):
            if option.is_file():
                return str(option)
        return None
    return shutil.which(program, path=environ.get("PATH"))


def run(
    command: Sequence[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    win32: Win32Api | None = None,
    platform: str = sys.platform,
    warn: Callable[[str], None] | None = None,
) -> int:
    """Run ``command`` quietly when appropriate and return its exit code."""

    environ = dict(os.environ if env is None else env)
    cwd_text = None if cwd is None else os.fspath(cwd)
    if not command:
        raise ValueError("quiet_run needs a command")
    if quiet_reason_skipped(environ, platform) is not None:
        return subprocess.run(list(command), cwd=cwd_text, env=environ, check=False).returncode
    say = warn or (lambda line: print(line, file=sys.stderr, flush=True))
    api = win32 if win32 is not None else Win32()

    program = _resolve(command[0], environ, cwd_text)
    if program is None:
        say(f"quiet_run: cannot find {command[0]!r} on PATH")
        return STARTUP_FAILURE_EXIT
    plan = _plan(api, say, environ)
    environ[MARKER_ENV] = "1"
    command_line = subprocess.list2cmdline([command[0], *command[1:]])

    job = api.create_job(priority_class=plan.priority_class, affinity=plan.affinity)
    process = thread = 0
    try:
        try:
            process, thread = api.create_suspended(
                program,
                command_line,
                desktop=plan.desktop,
                environment=environ,
                cwd=cwd_text,
                priority_class=plan.priority_class,
            )
        except OSError as exc:
            if plan.desktop is None:
                raise
            say(
                f"quiet_run: WARNING cannot start on the hidden desktop ({exc}); running visibly at low priority"
            )
            process, thread = api.create_suspended(
                program,
                command_line,
                desktop=None,
                environment=environ,
                cwd=cwd_text,
                priority_class=plan.priority_class,
            )
        if not (job and api.assign(job, process)) and plan.affinity is not None:
            # No job (for example a parent job forbids nesting): the creation priority class and this affinity are
            # still inherited by every child the command starts; only kill-on-close is lost.
            api.set_affinity(process, plan.affinity)
        api.resume(thread)
        return _wait(api, job, process)
    finally:
        for handle in (thread, process, job):
            if handle:
                api.close(handle)


def _plan(api: Win32Api, say: Callable[[str], None], environ: Mapping[str, str]) -> Plan:
    desktop: str | None = None
    try:
        if api.open_desktop(DESKTOP_NAME):
            desktop = f"{api.window_station()}\\{DESKTOP_NAME}"
    except OSError:
        desktop = None
    if desktop is None:
        say(
            f"quiet_run: WARNING cannot create the hidden desktop {DESKTOP_NAME}; running visibly at low priority"
        )
    affinity: int | None = None
    if cores_setting(environ) == CORES_EFFICIENCY:
        try:
            affinity = efficiency_mask(api.processor_cores(), os.cpu_count() or 0)
        except OSError:
            affinity = None
    return Plan(desktop=desktop, priority_class=BELOW_NORMAL_PRIORITY_CLASS, affinity=affinity)


def _wait(api: Win32Api, job: int, process: int) -> int:
    try:
        while not api.wait(process, WAIT_SLICE_MS):
            pass
    except KeyboardInterrupt:
        # The child shares the console and received the same Ctrl+C; give it a moment, then end the whole tree.
        if not api.wait(process, INTERRUPT_GRACE_MS):
            api.terminate(job, process, 130)
            api.wait(process, INTERRUPT_GRACE_MS)
    return api.exit_code(process)


def relaunch_pytest_session(
    *,
    argv: Sequence[str] | None = None,
    orig_argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str = sys.platform,
    runner: Callable[[Sequence[str]], int] | None = None,
    exit: Callable[[int], Any] | None = None,
) -> bool:
    """Re-run a command-line pytest session quietly and exit with its code; ``False`` when nothing was done.

    Called from ``tests/conftest.py`` in ``pytest_configure`` (after pytest has restored the real standard streams
    and before collection). Only a real command-line run is relaunched (``pytest ...`` or ``python -m pytest ...``):
    an in-process ``pytest.main()`` call has another program's ``sys.argv`` and is left alone.
    """

    argv = list(sys.argv if argv is None else argv)
    orig = list(getattr(sys, "orig_argv", []) if orig_argv is None else orig_argv)
    if not should_quiet(environ, platform) or not _is_pytest_cli(argv, orig):
        return False
    command = [sys.executable, *orig[1:]]
    code = (runner or (lambda cmd: run(cmd, cwd=os.getcwd())))(command)
    sys.stdout.flush()
    sys.stderr.flush()
    (exit or os._exit)(code)
    return True


def _is_pytest_cli(argv: Sequence[str], orig: Sequence[str]) -> bool:
    if not argv or len(orig) < len(argv):
        return False
    entry = Path(argv[0])
    by_module = entry.name == "__main__.py" and entry.parent.name == "pytest"
    by_script = entry.stem.lower() in {"pytest", "py.test"}
    if not (by_module or by_script):
        return False
    return list(orig[len(orig) - len(argv) + 1 :]) == list(argv[1:])


# -- the real Win32 surface -------------------------------------------------------------------------------------------


class Win32:
    """The only place user32/kernel32 are touched by this tool; replaced by a fake in unit tests."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("quiet_run's Win32 surface requires Windows")
        from ctypes import wintypes as w

        self.w = w
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.u = ctypes.WinDLL("user32", use_last_error=True)
        k, u = self.k, self.u
        u.GetProcessWindowStation.restype = w.HANDLE
        u.GetUserObjectInformationW.argtypes = [
            w.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            w.DWORD,
            ctypes.POINTER(w.DWORD),
        ]
        u.CreateDesktopW.restype = w.HANDLE
        u.CreateDesktopW.argtypes = [
            w.LPCWSTR,
            w.LPCWSTR,
            ctypes.c_void_p,
            w.DWORD,
            w.DWORD,
            ctypes.c_void_p,
        ]
        k.GetLogicalProcessorInformationEx.argtypes = [
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.POINTER(w.DWORD),
        ]
        k.CreateJobObjectW.restype = w.HANDLE
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        k.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
        k.SetProcessAffinityMask.argtypes = [w.HANDLE, ctypes.c_size_t]
        k.ResumeThread.argtypes = [w.HANDLE]
        k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        k.WaitForSingleObject.restype = w.DWORD
        k.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        k.CloseHandle.argtypes = [w.HANDLE]
        k.GetStdHandle.restype = w.HANDLE
        k.GetStdHandle.argtypes = [w.DWORD]
        k.GetCurrentProcess.restype = w.HANDLE
        k.DuplicateHandle.argtypes = [
            w.HANDLE,
            w.HANDLE,
            w.HANDLE,
            ctypes.POINTER(w.HANDLE),
            w.DWORD,
            w.BOOL,
            w.DWORD,
        ]
        self._desktops: list[
            int
        ] = []  # kept open for this process's lifetime so the desktop outlives the child

        class STARTUPINFOW(ctypes.Structure):
            _fields_ = [
                ("cb", w.DWORD),
                ("lpReserved", w.LPWSTR),
                ("lpDesktop", w.LPWSTR),
                ("lpTitle", w.LPWSTR),
                ("dwX", w.DWORD),
                ("dwY", w.DWORD),
                ("dwXSize", w.DWORD),
                ("dwYSize", w.DWORD),
                ("dwXCountChars", w.DWORD),
                ("dwYCountChars", w.DWORD),
                ("dwFillAttribute", w.DWORD),
                ("dwFlags", w.DWORD),
                ("wShowWindow", w.WORD),
                ("cbReserved2", w.WORD),
                ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", w.HANDLE),
                ("hStdOutput", w.HANDLE),
                ("hStdError", w.HANDLE),
            ]

        class PROCESS_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("hProcess", w.HANDLE),
                ("hThread", w.HANDLE),
                ("dwProcessId", w.DWORD),
                ("dwThreadId", w.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in ("r", "w", "o", "rb", "wb", "ob")]

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", w.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", w.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", w.DWORD),
                ("SchedulingClass", w.DWORD),
            ]

        class EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMIT),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        k.CreateProcessW.argtypes = [
            w.LPCWSTR,
            w.LPWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
            w.BOOL,
            w.DWORD,
            ctypes.c_void_p,
            w.LPCWSTR,
            ctypes.POINTER(STARTUPINFOW),
            ctypes.POINTER(PROCESS_INFORMATION),
        ]
        self.STARTUPINFOW = STARTUPINFOW
        self.PROCESS_INFORMATION = PROCESS_INFORMATION
        self.EXTENDED_LIMIT = EXTENDED_LIMIT

    def _error(self, what: str) -> OSError:
        code = ctypes.get_last_error()
        return OSError(code, f"{what} failed: {ctypes.FormatError(code).strip()}")

    def window_station(self) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        needed = self.w.DWORD()
        if not self.u.GetUserObjectInformationW(
            self.u.GetProcessWindowStation(), 2, buffer, ctypes.sizeof(buffer), ctypes.byref(needed)
        ):
            raise self._error("GetUserObjectInformationW")
        return buffer.value

    def open_desktop(self, name: str) -> int:
        """Create the named desktop, or open it when it exists (``CreateDesktopW`` does both)."""

        generic_all = 0x10000000
        handle = self.u.CreateDesktopW(name, None, None, 0, generic_all, None)
        if not handle:
            raise self._error("CreateDesktopW")
        self._desktops.append(handle)
        return int(handle)

    def processor_cores(self) -> list[Core]:
        relation_processor_core = 0
        size = self.w.DWORD(0)
        self.k.GetLogicalProcessorInformationEx(relation_processor_core, None, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not self.k.GetLogicalProcessorInformationEx(
            relation_processor_core, buffer, ctypes.byref(size)
        ):
            raise self._error("GetLogicalProcessorInformationEx")
        return parse_processor_cores(buffer.raw[: size.value], ctypes.sizeof(ctypes.c_size_t))

    def create_job(self, *, priority_class: int, affinity: int | None) -> int:
        job = self.k.CreateJobObjectW(None, None)
        if not job:
            return 0
        info = self.EXTENDED_LIMIT()
        flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_PRIORITY_CLASS
        info.BasicLimitInformation.PriorityClass = priority_class
        if affinity is not None:
            flags |= JOB_OBJECT_LIMIT_AFFINITY
            info.BasicLimitInformation.Affinity = affinity
        info.BasicLimitInformation.LimitFlags = flags
        extended_limit_information = 9
        if not self.k.SetInformationJobObject(
            job, extended_limit_information, ctypes.byref(info), ctypes.sizeof(info)
        ):
            self.k.CloseHandle(job)
            return 0
        return int(job)

    def _inheritable_std_handles(self) -> list[tuple[int, bool]]:
        """This process's standard handles as inheritable duplicates; ``(handle, owned)`` pairs to close afterwards."""

        handles: list[tuple[int, bool]] = []
        current = self.k.GetCurrentProcess()
        for std in (STD_INPUT_HANDLE, STD_OUTPUT_HANDLE, STD_ERROR_HANDLE):
            handle = self.k.GetStdHandle(std)
            duplicate = self.w.HANDLE()
            if (
                handle
                and handle != INVALID_HANDLE_VALUE
                and self.k.DuplicateHandle(
                    current,
                    handle,
                    current,
                    ctypes.byref(duplicate),
                    0,
                    True,
                    DUPLICATE_SAME_ACCESS,
                )
            ):
                handles.append((int(duplicate.value or 0), True))
            else:
                handles.append((int(handle or 0), False))
        return handles

    def create_suspended(
        self,
        application: str,
        command_line: str,
        *,
        desktop: str | None,
        environment: Mapping[str, str],
        cwd: str | None,
        priority_class: int,
    ) -> tuple[int, int]:
        startup = self.STARTUPINFOW()
        startup.cb = ctypes.sizeof(startup)
        startup.lpDesktop = desktop  # ctypes keeps the string alive with the structure
        std = self._inheritable_std_handles()
        startup.dwFlags = STARTF_USESTDHANDLES
        startup.hStdInput, startup.hStdOutput, startup.hStdError = (handle for handle, _ in std)
        encoded = environment_block(environment).encode("utf-16-le")
        block = (ctypes.c_char * len(encoded)).from_buffer_copy(encoded)
        info = self.PROCESS_INFORMATION()
        flags = CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | priority_class
        try:
            if not self.k.CreateProcessW(
                application,
                ctypes.create_unicode_buffer(command_line),
                None,
                None,
                True,
                flags,
                block,
                cwd,
                ctypes.byref(startup),
                ctypes.byref(info),
            ):
                raise self._error("CreateProcessW")
        finally:
            for handle, owned in std:
                if owned:
                    self.k.CloseHandle(handle)
        return int(info.hProcess), int(info.hThread)

    def assign(self, job: int, process: int) -> bool:
        return bool(self.k.AssignProcessToJobObject(job, process))

    def set_affinity(self, process: int, mask: int) -> bool:
        return bool(self.k.SetProcessAffinityMask(process, mask))

    def resume(self, thread: int) -> None:
        if self.k.ResumeThread(thread) == 0xFFFFFFFF:
            raise self._error("ResumeThread")

    def wait(self, process: int, timeout_ms: int) -> bool:
        return int(self.k.WaitForSingleObject(process, timeout_ms)) == 0

    def exit_code(self, process: int) -> int:
        code = self.w.DWORD()
        if not self.k.GetExitCodeProcess(process, ctypes.byref(code)):
            raise self._error("GetExitCodeProcess")
        return int(code.value)  # unsigned, as ``subprocess`` reports Windows exit codes

    def terminate(self, job: int, process: int, code: int) -> None:
        if not (job and self.k.TerminateJobObject(job, code)):
            self.k.TerminateProcess(process, code)

    def close(self, handle: int) -> None:
        self.k.CloseHandle(handle)


def parse_processor_cores(raw: bytes, pointer_size: int = 8) -> list[Core]:
    """Decode ``SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX`` records for ``RelationProcessorCore``.

    Each record: ``Relationship`` and ``Size`` (DWORDs), then ``PROCESSOR_RELATIONSHIP``: ``Flags`` and
    ``EfficiencyClass`` (bytes), 20 reserved bytes, ``GroupCount`` (WORD) and ``GroupCount`` ``GROUP_AFFINITY``
    entries (a pointer-sized ``Mask``, ``Group`` WORD and three reserved WORDs). Only the first group of a core is used.
    """

    cores: list[Core] = []
    offset = 0
    while offset + 8 <= len(raw):
        relationship = int.from_bytes(raw[offset : offset + 4], "little")
        size = int.from_bytes(raw[offset + 4 : offset + 8], "little")
        if size <= 0:
            break
        body = offset + 8
        if relationship == 0 and body + 24 + pointer_size + 2 <= len(raw):
            efficiency = raw[body + 1]
            group_count = int.from_bytes(raw[body + 22 : body + 24], "little")
            affinity_at = body + 24
            if group_count:
                mask = int.from_bytes(raw[affinity_at : affinity_at + pointer_size], "little")
                group = int.from_bytes(
                    raw[affinity_at + pointer_size : affinity_at + pointer_size + 2], "little"
                )
                cores.append(Core(efficiency_class=efficiency, group=group, mask=mask))
        offset += size
    return cores


def environment_block(environment: Mapping[str, str]) -> str:
    """A ``CREATE_UNICODE_ENVIRONMENT`` block: ``NAME=value`` entries sorted case-insensitively, double-NUL ended."""

    entries = [
        f"{name}={value}"
        for name, value in sorted(environment.items(), key=lambda item: item[0].upper())
    ]
    return "\0".join(entries) + "\0\0"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--":
        args = args[1:]
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        return 0 if args else 2
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
