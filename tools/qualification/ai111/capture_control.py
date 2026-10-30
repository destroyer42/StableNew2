"""PR-AI-QUAL-114E: the operator-run, elevated half of the ETW qualification capture. This whole file is the elevated surface.

Starting a ``Microsoft-Windows-Kernel-Network`` or ``-Kernel-File`` trace session is refused to a standard-user token (even
one in ``Performance Log Users``; measured 2026-10-25). The owner therefore chose operator-initiated, session-level
capture over a resident privileged broker. Three commands may be run from an Administrator terminal, nothing else:

* ``start``: create a *fresh* evidence directory under ``<repo>/reports`` and start exactly three named, file-mode,
  non-circular ``logman -ets`` sessions (Kernel-Network, Kernel-File, DNS-Client) that write into it.
* ``stop`` / ``cleanup``: stop the sessions whose names are derived from one validated capture id, then prove none is left.

``status`` is read-only and runs from any terminal. What the elevated code deliberately does not do: run or import a model or
a downloaded binary, read prompts, execute a path or command it was handed, touch the registry, firewall, a provider ACL or a
group, register a persistent collector (``-ets`` writes no configuration), stay resident, or write anywhere except tiny
create-new JSON state files inside the directory it just created. The harness, every downloaded binary, trace conversion and
all analysis run in a standard-user token (``capture_session.py``, ``capture_analysis.py``).

This file imports **only the standard library**, so the file an operator reviews and pins by SHA-256 is everything that runs
with the administrator token. Run it as ``python -I -B <protected copy>/capture_control.py --repo-root <checkout> ...``:
isolated mode keeps the working directory, ``PYTHONPATH`` and user site-packages out of the elevated interpreter, and ``-B``
keeps it from reading or writing ``.pyc`` files.

An administrator token that executes code a standard-user process can edit is not a privilege boundary, so before any elevated
command does anything it proves its own runtime is protected (``runtime_trust_problems``): the script, the interpreter, the
standard library and every other location Python imports from are owned by an administrator-class principal and grant no
write/replace right to anyone else, and this is not a virtual environment. A user-writable Python install or checkout therefore
refuses; the runbook describes the protected copy and the system-wide interpreter that satisfy it.

Two OS facts shape the design. ``logman -ets`` cannot take a run-for time, so a session has no OS-enforced lifetime: it is
bounded by a *size cap* (sequential file mode stops writing at ``-max``; circular overwrite is never used), by a recorded
deadline that admission and the analyzer enforce, and by the operator's ``stop``. And a start that is denied can still leave
the named session running, so every failure path stops and then looks for what it may have created, and an unproven cleanup is
a ``CLEANUP_REQUIRED`` state that blocks qualification rather than a pass.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA = 1
CAPTURE_PREFIX = "StableNewCap-"
CAPTURE_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")
SESSION_NAME = re.compile(
    r"^" + re.escape(CAPTURE_PREFIX) + r"(\d{8}T\d{6}Z-[0-9a-f]{8})-(network|file|dns)$"
)
#: ``logman query -ets`` list rows: the name, ``Trace``, and the state.
_LIST_ROW = re.compile(
    r"^\s*("
    + re.escape(CAPTURE_PREFIX)
    + r"\d{8}T\d{6}Z-[0-9a-f]{8}-(?:network|file|dns))\s+Trace\s+(\w+)"
)
_HERE = Path(__file__).resolve()
#: A protected copy lives outside any checkout, where there is no ``parents[3]``; it must be told ``--repo-root``.
REPORTS_ROOT = _HERE.parents[3] / "reports" if len(_HERE.parents) > 3 else _HERE.parent / "reports"
_TOOL_RELATIVE = Path("tools") / "qualification" / "ai111" / "capture_control.py"
DEFAULT_MAX_MB = 256
MAX_MB_LIMIT = 1024
DEFAULT_MINUTES = 30
MAX_MINUTES = 120
RESERVE_BYTES = 2 * 1024**3
#: tracerpt's XML is far larger than the ETL it converts; the free-space gate budgets for that, at start and at analysis.
CONVERSION_FACTOR = 16
_TOOL_TIMEOUT_SECONDS = 60.0
_TOOL_OUTPUT_BYTES = 256 * 1024
_REPARSE_POINT = 0x400
_CREATE_NO_WINDOW = 0x08000000
#: Well-known SIDs whose grant on the evidence directory would expose a system-wide trace: Everyone, Authenticated Users,
#: BUILTIN\Users, INTERACTIVE, BUILTIN\Guests. Resolved to this machine's (possibly localized) names at check time.
_BROAD_SIDS = ("S-1-1-0", "S-1-5-11", "S-1-5-32-545", "S-1-5-4", "S-1-5-32-546")
#: Principals whose presence in the evidence directory's ACL would expose raw system-wide traces to other accounts.
BROAD_PRINCIPALS = frozenset(
    {
        "everyone",
        "builtin\\users",
        "nt authority\\authenticated users",
        "nt authority\\interactive",
        "builtin\\guests",
    }
)

STATES = (
    "NOT_STARTED",
    "STARTING",
    "ACTIVE",
    "STOPPING",
    "STOPPED",
    "VERIFIED",
    "FAILED",
    "EXPIRED",
    "CLEANUP_REQUIRED",
)


class CaptureRefused(RuntimeError):
    """A precondition failed; nothing was started."""


@dataclass(frozen=True, slots=True)
class SessionSpec:
    kind: str  # "network" | "file" | "dns": also the session-name suffix
    provider: str
    keywords: int
    level: int = 0x05


# Keyword values read from ``logman query providers`` on the target host (2026-10-24).
NETWORK = SessionSpec("network", "Microsoft-Windows-Kernel-Network", 0x10 | 0x20, 0x04)
FILE = SessionSpec(
    "file",
    "Microsoft-Windows-Kernel-File",
    0x10
    | 0x80
    | 0x200
    | 0x400
    | 0x800
    | 0x1000,  # FILENAME CREATE WRITE DELETE_PATH RENAME_SETLINK CREATE_NEW_FILE
    0x04,
)
DNS = SessionSpec("dns", "Microsoft-Windows-DNS-Client", 0xFFFFFFFFFFFFFFFF, 0x05)
SESSIONS = (NETWORK, FILE, DNS)
BUFFER_KB = 1024
BUFFERS_MIN = 32
BUFFERS_MAX = 128


def provider_config() -> dict[str, Any]:
    """The exact trace configuration; its digest is recorded at start, re-verified from the live sessions and compared at
    admission and in the canary proof."""

    return {
        "sessions": [
            {"kind": s.kind, "provider": s.provider, "keywords": hex(s.keywords), "level": s.level}
            for s in SESSIONS
        ],
        "clock": "perf",
        "buffer_kb": BUFFER_KB,
        "buffers": [BUFFERS_MIN, BUFFERS_MAX],
        "file_mode": "sequential",
        "circular": False,
    }


def provider_config_sha256() -> str:
    return hashlib.sha256(json.dumps(provider_config(), sort_keys=True).encode()).hexdigest()


def tool_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# -- identities ---------------------------------------------------------------------------------------------------------


def new_capture_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(4)}"


def session_names(capture_id: str) -> dict[str, str]:
    """Kind -> session name, derived only from a validated id: the elevated code never takes a session name from input."""

    if not CAPTURE_ID.fullmatch(capture_id):
        raise CaptureRefused(f"not a capture id: {capture_id!r}")
    return {spec.kind: f"{CAPTURE_PREFIX}{capture_id}-{spec.kind}" for spec in SESSIONS}


def system_directory() -> Path:
    """The Windows system directory as the OS reports it (``GetSystemDirectoryW``), never from an environment variable."""

    if os.name != "nt":
        return Path(os.environ.get("SystemRoot") or "C:\\Windows") / "System32"
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetSystemDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
        kernel32.GetSystemDirectoryW.restype = wintypes.UINT
        buffer = ctypes.create_unicode_buffer(260)
        length = kernel32.GetSystemDirectoryW(buffer, 260)
    except Exception as exc:  # noqa: BLE001 - an unresolved system directory is a refusal, never a guess
        raise CaptureRefused("the Windows system directory could not be resolved") from exc
    if length == 0 or length >= 260:
        raise CaptureRefused("the Windows system directory could not be resolved")
    return Path(buffer.value)


def system_tool(name: str) -> str:
    """Absolute path of an OS tool, so an elevated process never resolves ``logman`` through PATH or the working directory."""

    return str(system_directory() / f"{name}.exe")


Run = Callable[[Sequence[str]], tuple[int, str]]


def run_tool(command: Sequence[str]) -> tuple[int, str]:
    """Run one short, fixed OS tool (``logman``/``icacls`` by absolute path) with a timeout and capped output.

    The elevated process cannot import the standard-user bounded runner (see the module docstring); it only ever runs the two
    absolute-path system tools named by ``system_tool``, with arguments built from validated values."""

    if (
        Path(command[0]).name.lower() not in ("logman.exe", "icacls.exe")
        or not Path(command[0]).is_absolute()
    ):
        raise CaptureRefused("only the absolute-path logman/icacls system tools may be run")
    try:
        done = subprocess.run(  # noqa: S603 - fixed system tool, argv list, no shell
            list(command),
            capture_output=True,
            timeout=_TOOL_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
            cwd=str(system_directory()),
            creationflags=_CREATE_NO_WINDOW if os.name == "nt" else 0,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CaptureRefused(f"{Path(command[0]).name} timed out") from exc
    except OSError as exc:
        raise CaptureRefused(f"{Path(command[0]).name}: {exc}") from exc
    text = (done.stdout + done.stderr)[:_TOOL_OUTPUT_BYTES].decode("utf-8", "replace")
    return int(done.returncode), text


def process_elevated() -> bool | None:
    """Whether this process holds an elevated token (``TokenElevation``). ``None`` when it cannot be read: never a pass."""

    if os.name != "nt":
        return None
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            return None
        try:
            elevated = wintypes.DWORD(0)
            returned = wintypes.DWORD(0)
            ok = advapi32.GetTokenInformation(
                token, 20, ctypes.byref(elevated), ctypes.sizeof(elevated), ctypes.byref(returned)
            )
            return (
                bool(elevated.value) if ok and returned.value == ctypes.sizeof(elevated) else None
            )
        finally:
            kernel32.CloseHandle(token)
    except Exception:  # noqa: BLE001 - unreadable is "unknown", which every caller treats as a refusal
        return None


def broad_principal_names() -> frozenset[str]:
    """The English names plus this machine's own names for the broad well-known SIDs (so a localized Windows matches too)."""

    return frozenset(BROAD_PRINCIPALS | _account_names(_BROAD_SIDS))


def _account_names(sids: Sequence[str]) -> set[str]:
    """This machine's own ``DOMAIN\\name`` and bare ``name`` (lower case) for each well-known SID; empty off Windows."""

    names: set[str] = set()
    if os.name != "nt":
        return names
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32.ConvertStringSidToSidW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi32.LookupAccountSidW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.c_void_p,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        for text in sids:
            sid = ctypes.c_void_p()
            if not advapi32.ConvertStringSidToSidW(text, ctypes.byref(sid)):
                continue
            try:
                name = ctypes.create_unicode_buffer(256)
                domain = ctypes.create_unicode_buffer(256)
                name_len, domain_len, use = (
                    wintypes.DWORD(256),
                    wintypes.DWORD(256),
                    wintypes.DWORD(0),
                )
                if advapi32.LookupAccountSidW(
                    None,
                    sid,
                    name,
                    ctypes.byref(name_len),
                    domain,
                    ctypes.byref(domain_len),
                    ctypes.byref(use),
                ):
                    full = f"{domain.value}\\{name.value}" if domain.value else name.value
                    names.add(full.lower())
                    names.add(name.value.lower())
            finally:
                kernel32.LocalFree(sid)
    except Exception:  # noqa: BLE001 - the caller's English names remain
        pass
    return names


class TraceTools:
    """The three ``logman`` operations the capture uses, each on a name the caller derived from a validated id."""

    def __init__(self, run: Run = run_tool) -> None:
        self._run = run
        self._logman = system_tool("logman")

    def start(self, name: str, spec: SessionSpec, etl: Path, max_mb: int) -> tuple[int, str]:
        if not SESSION_NAME.fullmatch(name):
            raise CaptureRefused("refusing to start a session that is not a capture session name")
        return self._run(
            [
                self._logman,
                "start",
                name,
                "-p",
                spec.provider,
                hex(spec.keywords),
                hex(spec.level),
                "-ct",
                "perf",
                "-bs",
                str(BUFFER_KB),
                "-nb",
                str(BUFFERS_MIN),
                str(BUFFERS_MAX),
                "-max",
                str(max_mb),
                "-o",
                str(etl),
                "-ets",
            ]
        )

    def stop(self, name: str) -> tuple[int, str]:
        if not SESSION_NAME.fullmatch(name):
            raise CaptureRefused("refusing to stop a session that is not a capture session name")
        return self._run([self._logman, "stop", name, "-ets"])

    def live(self) -> dict[str, str]:
        """Every live capture session of this tool (name -> state); foreign sessions are never listed or touched."""

        code, text = self._run([self._logman, "query", "-ets"])
        if code != 0:
            raise CaptureRefused(f"logman query failed ({code}): {text.strip()[:200]}")
        return {
            m.group(1): m.group(2) for line in text.splitlines() if (m := _LIST_ROW.match(line))
        }

    def query(self, name: str) -> str:
        if not SESSION_NAME.fullmatch(name):
            raise CaptureRefused("refusing to query a session that is not a capture session name")
        code, text = self._run([self._logman, "query", name, "-ets"])
        if code != 0:
            raise CaptureRefused(f"logman query {name} failed ({code}): {text.strip()[:200]}")
        return text

    def live_for(self, capture_id: str) -> dict[str, str]:
        wanted = set(session_names(capture_id).values())
        return {n: s for n, s in self.live().items() if n in wanted}


# -- verifying what logman says is running --------------------------------------------------------------------------------


def parse_query(text: str) -> dict[str, Any]:
    """Fields of ``logman query <name> -ets``: the session header and each provider block."""

    info: dict[str, Any] = {"providers": []}
    provider: dict[str, Any] | None = None
    for raw in text.splitlines():
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        key, value = key.strip().lower(), value.strip()
        if raw.strip() == "Provider:":
            provider = {}
            info["providers"].append(provider)
            continue
        if provider is not None:
            if key == "name":
                provider["name"] = value
            elif key == "provider guid":
                provider["guid"] = value.lower()
            elif key == "level":
                provider["level"] = _first_int(value)
            elif key == "keywordsany":
                provider["keywords_any"] = _first_int(value)
            elif key == "keywordsall":
                provider["keywords_all"] = _first_int(value)
            continue
        if key == "name" and "name" not in info:
            info["name"] = value
        elif key == "status":
            info["status"] = value.lower()
        elif key == "output location":
            info["output"] = value
        elif key == "circular":
            info["circular"] = value.lower()
        elif key == "clock type":
            info["clock"] = value.lower()
        elif key == "file mode":
            info["file_mode"] = value.lower()
        elif key == "segment":
            info["segment"] = value.lower()
        elif key == "segment max size":
            info["segment_max_mb"] = _first_int(value)
        elif key == "buffers lost":
            info["buffers_lost"] = _first_int(value)
        elif key == "append":
            info["append"] = value.lower()
    return info


def _first_int(text: str) -> int | None:
    token = text.split()[0] if text.split() else ""
    for base in (0, 10):
        try:
            return int(token, base)
        except ValueError:
            continue
    return None


def verify_session(info: dict[str, Any], spec: SessionSpec, etl: Path, max_mb: int) -> list[str]:
    """Why a running session is not the one that was asked for. Anything unreadable is a problem, never a pass."""

    problems: list[str] = []
    if info.get("status") != "running":
        problems.append(f"{spec.kind}: session status is {info.get('status')!r}, not running")
    providers = info.get("providers", [])
    if len(providers) != 1:
        problems.append(f"{spec.kind}: {len(providers)} providers enabled, expected exactly 1")
    else:
        p = providers[0]
        if p.get("name") != spec.provider:
            problems.append(f"{spec.kind}: provider is {p.get('name')!r}, expected {spec.provider}")
        if p.get("level") != spec.level:
            problems.append(f"{spec.kind}: level {p.get('level')} differs from {spec.level}")
        if p.get("keywords_any") != spec.keywords:
            problems.append(
                f"{spec.kind}: keywords {p.get('keywords_any')} differ from {hex(spec.keywords)}"
            )
    if info.get("circular") != "off":
        problems.append(f"{spec.kind}: circular logging is {info.get('circular')!r}, must be off")
    if "performance" not in str(info.get("clock", "")):
        problems.append(
            f"{spec.kind}: clock type is {info.get('clock')!r}, expected the performance counter"
        )
    if info.get("file_mode") not in (None, "file"):
        problems.append(f"{spec.kind}: file mode is {info.get('file_mode')!r}")
    output = info.get("output")
    if not output or os.path.normcase(os.path.normpath(output)) != os.path.normcase(
        os.path.normpath(str(etl))
    ):
        problems.append(f"{spec.kind}: output location {output!r} is not {etl}")
    if info.get("segment_max_mb") not in (None, max_mb):
        problems.append(
            f"{spec.kind}: size cap {info.get('segment_max_mb')} MB differs from {max_mb} MB"
        )
    return problems


# -- the evidence directory ---------------------------------------------------------------------------------------------


def _is_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        return bool(getattr(os.lstat(path), "st_file_attributes", 0) & _REPARSE_POINT)
    except OSError:
        return False


def validate_new_directory(path: Path, reports_root: Path = REPORTS_ROOT) -> Path:
    """An absolute, not-yet-existing directory inside ``reports_root`` whose existing ancestors are plain directories."""

    root = reports_root.resolve()
    target = (Path.cwd() / path if not path.is_absolute() else path).resolve(strict=False)
    if root not in target.parents:
        raise CaptureRefused(f"the evidence directory must be inside {root}")
    if target.exists():
        raise CaptureRefused(f"{target} already exists; a capture needs a fresh directory")
    _require_plain_chain(target.parent, root)
    return target


def validate_existing_directory(path: Path, reports_root: Path = REPORTS_ROOT) -> Path:
    root = reports_root.resolve()
    target = (Path.cwd() / path if not path.is_absolute() else path).resolve(strict=False)
    if root not in target.parents:
        raise CaptureRefused(f"the evidence directory must be inside {root}")
    if not target.is_dir():
        raise CaptureRefused(f"{target} is not a directory")
    _require_plain_chain(target, root)
    return target


def _require_plain_chain(directory: Path, root: Path) -> None:
    """Every existing component from ``root`` down to ``directory`` is a plain directory (no link, junction or mount)."""

    current = directory
    while current != root and root in current.parents:
        if current.exists():
            if _is_reparse(current) or not current.is_dir():
                raise CaptureRefused(f"{current} is a link or reparse point")
        current = current.parent
    if root.exists() and _is_reparse(root):
        raise CaptureRefused(f"{root} is a link or reparse point")


def acl_problems(
    icacls_text: str,
    directory: Path | None = None,
    broad: frozenset[str] | None = None,
) -> list[str]:
    """Broad principals granted access in an ``icacls`` listing (deny entries are ignored).

    A listing with no recognisable entry at all is itself a problem: output the parser cannot read is never a pass."""

    broad = broad_principal_names() if broad is None else broad
    problems: list[str] = []
    entries = 0
    for line in icacls_text.splitlines():
        entry = line.strip()
        if ":(" not in entry:
            continue
        before, _, rest = entry.partition(":(")
        if directory is not None and before.lower().startswith(str(directory).lower()):
            before = before[len(str(directory)) :]
        principal = before.strip().lower()
        entries += 1
        if "(deny)" in f"({rest}".lower():  # ``partition`` consumed the first "("
            continue
        if principal in broad:
            problems.append(f"the directory grants access to {principal}")
    if not entries:
        problems.append("the directory's ACL could not be read")
    return sorted(set(problems))


# -- the elevated runtime must itself be protected ----------------------------------------------------------------------------

#: Administrators, SYSTEM, TrustedInstaller: the only principals that may own what the elevated interpreter loads.
_OWNER_SIDS = frozenset(
    {
        "S-1-5-18",
        "S-1-5-32-544",
        "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",
    }
)
#: Owners plus CREATOR OWNER (an inherit-only placeholder in protected trees): principals whose grants are not a finding.
_TRUSTED_SIDS = (*sorted(_OWNER_SIDS), "S-1-3-0")
_TRUSTED_FALLBACK = frozenset(
    {
        "nt authority\\system",
        "system",
        "builtin\\administrators",
        "administrators",
        "nt service\\trustedinstaller",
        "trustedinstaller",
        "creator owner",
    }
)
#: ``icacls`` right tokens that let a principal replace, add to or re-permission what the elevated interpreter loads.
_REPLACE_RIGHTS = frozenset(
    {"F", "M", "W", "D", "DE", "WD", "AD", "DC", "WDAC", "WO", "GA", "GW", "MA"}
)
#: On a directory above the loaded code, creating a child is harmless; deleting or renaming one, or re-permissioning, is not.
_ANCESTOR_RIGHTS = frozenset({"F", "M", "D", "DE", "DC", "WDAC", "WO", "GA", "MA"})


def trusted_principal_names() -> frozenset[str]:
    return frozenset(
        _TRUSTED_FALLBACK | _account_names(_TRUSTED_SIDS) | {s.lower() for s in _TRUSTED_SIDS}
    )


def write_grant_problems(
    icacls_text: str, path: Path, trusted: frozenset[str], rights: frozenset[str]
) -> list[str]:
    """Principals outside ``trusted`` that an ``icacls`` listing of ``path`` lets modify it (deny and inherit-only entries are
    skipped, so a denied principal is still reported: the safe direction). A listing with no entry at all is a problem."""

    problems: list[str] = []
    entries = 0
    prefix = str(path).lower()
    for line in icacls_text.splitlines():
        entry = line.strip()
        if ":(" not in entry:
            continue
        before, _, rest = entry.partition(":(")
        if before.lower().startswith(prefix):
            before = before[len(prefix) :]
        principal = before.strip().lower()
        flags = {
            token.strip()
            for group in re.findall(r"\(([^)]*)\)", f"({rest}")
            for token in group.upper().split(",")
        }
        entries += 1
        if "DENY" in flags or "IO" in flags or principal in trusted:
            continue
        hit = sorted(flags & rights)
        if hit:
            problems.append(f"{principal or '?'} can modify {path} ({','.join(hit)})")
    if not entries:
        problems.append(f"the ACL of {path} could not be read")
    return problems


def file_owner_sid(path: Path) -> str | None:
    """The owner SID of a file or directory as a string, or ``None`` when it cannot be read (never a pass)."""

    if os.name != "nt":
        return None
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        void_p = ctypes.c_void_p
        advapi32.GetNamedSecurityInfoW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.c_int,
            wintypes.DWORD,
            ctypes.POINTER(void_p),
            ctypes.POINTER(void_p),
            ctypes.POINTER(void_p),
            ctypes.POINTER(void_p),
            ctypes.POINTER(void_p),
        ]
        advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
        advapi32.ConvertSidToStringSidW.argtypes = [void_p, ctypes.POINTER(wintypes.LPWSTR)]
        kernel32.LocalFree.argtypes = [void_p]
        owner, descriptor = void_p(), void_p()
        if advapi32.GetNamedSecurityInfoW(
            str(path), 1, 1, ctypes.byref(owner), None, None, None, ctypes.byref(descriptor)
        ):
            return None
        try:
            text = wintypes.LPWSTR()
            if not advapi32.ConvertSidToStringSidW(owner, ctypes.byref(text)):
                return None
            try:
                return str(text.value)
            finally:
                kernel32.LocalFree(ctypes.cast(text, void_p))
        finally:
            kernel32.LocalFree(descriptor)
    except Exception:  # noqa: BLE001 - unreadable is "unknown", which every caller treats as a refusal
        return None


@dataclass(frozen=True, slots=True)
class RuntimeFacts:
    """What this interpreter is running from; injectable so the trust rules are tested without touching the host."""

    script: Path
    executable: Path
    stdlib_file: Path
    base_prefix: Path
    sys_path_dirs: tuple[Path, ...]
    sys_path_files: tuple[Path, ...]
    module_files: tuple[Path, ...]
    isolated: bool
    bytecode_disabled: bool
    in_venv: bool

    @classmethod
    def current(cls) -> RuntimeFacts:
        dirs: list[Path] = []
        files: list[Path] = []
        for entry in sys.path:
            if not entry:
                continue
            path = Path(entry).resolve(strict=False)
            if path.is_dir():
                dirs.append(path)
            elif path.is_file():
                files.append(path)
        modules = [
            Path(name).resolve(strict=False)
            for module in list(sys.modules.values())
            if isinstance(name := getattr(module, "__file__", None), str) and name
        ]
        return cls(
            script=Path(__file__).resolve(),
            executable=Path(sys.executable).resolve(),
            stdlib_file=Path(os.__file__).resolve(),
            base_prefix=Path(sys.base_prefix).resolve(),
            sys_path_dirs=tuple(dirs),
            sys_path_files=tuple(files),
            module_files=tuple(modules),
            isolated=bool(sys.flags.isolated),
            bytecode_disabled=bool(sys.flags.dont_write_bytecode),
            in_venv=Path(sys.prefix).resolve() != Path(sys.base_prefix).resolve(),
        )


def runtime_trust_problems(
    facts: RuntimeFacts | None = None,
    *,
    acl_reader: Callable[[Path], str] | None = None,
    owner_reader: Callable[[Path], str | None] = file_owner_sid,
    trusted: frozenset[str] | None = None,
) -> list[str]:
    """Why this interpreter-and-script pair is not safe to run with an administrator token (empty list: it is).

    Every file or directory the interpreter takes code from must be owned by an administrator-class principal and grant
    no write/replace right to anyone else; each ancestor must not let a non-administrator delete or re-permission it. The
    scan covers the script, the interpreter, the standard library file and directory, the base prefix, every ``sys.path``
    entry and the directory of every module already loaded, and refuses a module loaded from anywhere else. It does not walk
    every file in the install; a protected install (a system-wide ``Program Files`` Python) is what makes that sound."""

    facts = facts or RuntimeFacts.current()
    reader = acl_reader or (lambda p: run_tool([system_tool("icacls"), str(p)])[1])
    names = trusted if trusted is not None else trusted_principal_names()
    problems: list[str] = []
    if not facts.isolated:
        problems.append("the interpreter was not started with -I (isolated mode)")
    if not facts.bytecode_disabled:
        problems.append("the interpreter was not started with -B (no bytecode files)")
    if facts.in_venv:
        problems.append(
            "this is a virtual environment; use a system-wide Python outside every user-writable location"
        )
    roots = (facts.script.parent, facts.base_prefix)
    for module in facts.module_files:
        if not any(root == module or root in module.parents for root in roots):
            problems.append(f"a module was loaded from outside the protected locations: {module}")
    strong_files = {facts.script, facts.executable, facts.stdlib_file, *facts.sys_path_files}
    strong_dirs = {
        facts.script.parent,
        facts.executable.parent,
        facts.stdlib_file.parent,
        facts.base_prefix,
        *facts.sys_path_dirs,
        *(m.parent for m in facts.module_files),
    }
    strong = strong_files | strong_dirs
    ancestors = {a for p in strong for a in p.parents} - strong
    for path in sorted(strong, key=str):
        problems += _path_problems(path, reader, owner_reader, names, _REPLACE_RIGHTS)
    for path in sorted(ancestors, key=str):
        problems += _path_problems(path, reader, owner_reader, names, _ANCESTOR_RIGHTS)
    return sorted(set(problems))


def _path_problems(
    path: Path,
    reader: Callable[[Path], str],
    owner_reader: Callable[[Path], str | None],
    trusted: frozenset[str],
    rights: frozenset[str],
) -> list[str]:
    try:
        found = write_grant_problems(reader(path), path, trusted, rights)
    except (CaptureRefused, OSError) as exc:
        found = [f"the ACL of {path} could not be read: {exc}"]
    owner = owner_reader(path)
    if owner is None:
        found.append(f"the owner of {path} could not be read")
    elif owner not in _OWNER_SIDS:
        found.append(f"{path} is owned by {owner}, not an administrator-class principal")
    return found


def resolve_reports_root(repo_root: Path | None) -> Path:
    """The ``reports`` directory this command may write under. A protected copy outside any checkout must be told which
    checkout, and the checkout's ``capture_control.py`` must be byte-identical to the running one, so the SHA-256 the analysis
    and admission compare is the SHA-256 of what actually ran."""

    if repo_root is None:
        if len(_HERE.parents) > 3 and (_HERE.parents[3] / _TOOL_RELATIVE).is_file():
            return _HERE.parents[3] / "reports"
        raise CaptureRefused(
            "this capture_control.py is not inside a StableNew checkout; pass --repo-root <checkout>"
        )
    if not repo_root.is_absolute():
        raise CaptureRefused("--repo-root must be an absolute path")
    root = repo_root.resolve()
    pinned = root / _TOOL_RELATIVE
    if not pinned.is_file():
        raise CaptureRefused(
            f"{root} has no {_TOOL_RELATIVE.as_posix()}; it is not a StableNew checkout"
        )
    if hashlib.sha256(pinned.read_bytes()).hexdigest() != tool_sha256():
        raise CaptureRefused(
            "the checkout's capture_control.py differs from the copy being run; copy it again and compare SHA-256"
        )
    _require_plain_chain(root / "reports", root)
    return root / "reports"


def write_new_json(path: Path, value: Any) -> None:
    with path.open(
        "x", encoding="utf-8"
    ) as handle:  # create-new: never follows or replaces an existing entry
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def required_free_bytes(max_mb: int) -> int:
    kernel_sessions = 2
    return kernel_sessions * max_mb * 1024 * 1024 * (1 + CONVERSION_FACTOR) + RESERVE_BYTES


# -- start --------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Environment:
    """Everything the commands read from the host, injectable so the whole state machine is tested without ETW."""

    tools: TraceTools
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    elevated: Callable[[], bool | None] = process_elevated
    free_bytes: Callable[[Path], int] = lambda p: shutil.disk_usage(p).free
    acl_reader: Callable[[Path], str] = lambda p: run_tool([system_tool("icacls"), str(p)])[1]
    reports_root: Path = REPORTS_ROOT
    runtime_check: Callable[[], list[str]] = runtime_trust_problems


def _require_elevated(env: Environment) -> None:
    if env.elevated() is not True:
        raise CaptureRefused(
            "trace-control commands need an Administrator terminal; nothing was started. The qualification harness "
            "itself must never run elevated."
        )
    untrusted = env.runtime_check()
    if untrusted:
        shown = "; ".join(untrusted[:6]) + (
            f"; and {len(untrusted) - 6} more" if len(untrusted) > 6 else ""
        )
        raise CaptureRefused(
            "the elevated Python runtime is not protected, so nothing was started or stopped: "
            f"{shown}. Run the protected copy on a system-wide interpreter (see the runbook)."
        )


def start_capture(
    evidence_dir: Path,
    *,
    run_id: str,
    max_mb: int = DEFAULT_MAX_MB,
    minutes: int = DEFAULT_MINUTES,
    env: Environment | None = None,
    capture_id: str | None = None,
) -> dict[str, Any]:
    env = env or Environment(TraceTools())
    _require_elevated(env)
    if capture_id is not None:
        session_names(capture_id)  # Same closed name grammar as stop/cleanup.
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", run_id or ""):
        raise CaptureRefused(
            "--run-id must be 1-64 characters of letters, digits, dot, dash or underscore"
        )
    if not 16 <= max_mb <= MAX_MB_LIMIT:
        raise CaptureRefused(f"--max-mb must be between 16 and {MAX_MB_LIMIT}")
    if not 1 <= minutes <= MAX_MINUTES:
        raise CaptureRefused(f"--minutes must be between 1 and {MAX_MINUTES}")
    target = validate_new_directory(evidence_dir, env.reports_root)
    existing = env.tools.live()
    if existing:
        raise CaptureRefused(
            f"capture sessions are already running ({sorted(existing)}); stop them with the cleanup command first"
        )
    target.mkdir(parents=True)
    _require_plain_chain(target, env.reports_root.resolve())
    free = env.free_bytes(target)
    need = required_free_bytes(max_mb)
    if free < need:
        _discard_empty(target)
        raise CaptureRefused(
            f"free space {free} bytes is below the {need} bytes this capture budgets for"
        )
    exposed = acl_problems(env.acl_reader(target), target)
    if exposed:
        _discard_empty(target)
        raise CaptureRefused("; ".join(exposed))
    capture_id = capture_id or new_capture_id(env.now())
    names = session_names(capture_id)
    started = env.now()
    deadline = started + timedelta(minutes=minutes)
    manifest = {
        "schema": SCHEMA,
        "capture_id": capture_id,
        "run_id": run_id,
        "created_utc": started.isoformat(),
        "deadline_utc": deadline.isoformat(),
        "max_mb_per_session": max_mb,
        "minutes": minutes,
        "sessions": {
            s.kind: {"name": names[s.kind], "etl": f"{s.kind}.etl", "provider": s.provider}
            for s in SESSIONS
        },
        "provider_config_sha256": provider_config_sha256(),
        "provider_config": provider_config(),
        "tool_sha256": tool_sha256(),
        "elevated_start": True,
        "runtime": {
            "script": str(Path(__file__).resolve()),
            "executable": str(Path(sys.executable).resolve()),
            "python": sys.version.split()[0],
            "protection_verified": True,
        },
        "free_bytes_at_start": free,
        "free_bytes_required": need,
    }
    write_new_json(target / "capture.json", manifest)
    write_new_json(
        target / "state-01-starting.json", {"state": "STARTING", "utc": started.isoformat()}
    )
    problems: list[str] = []
    for spec in SESSIONS:
        etl = target / f"{spec.kind}.etl"
        if os.path.lexists(
            etl
        ):  # the trace file must be created by logman now, never pre-seeded (link, hardlink, stale)
            problems.append(f"{spec.kind}: {etl.name} already exists in the new directory")
            break
        try:
            code, text = env.tools.start(
                names[spec.kind], spec, target / f"{spec.kind}.etl", max_mb
            )
        except (CaptureRefused, OSError) as exc:
            problems.append(f"{spec.kind}: start raised: {exc}")
            break
        if code != 0:
            problems.append(
                f"{spec.kind}: logman start failed ({code}): {' '.join(text.split())[:240]}"
            )
            break
    if not problems:
        for spec in SESSIONS:
            try:
                info = parse_query(env.tools.query(names[spec.kind]))
            except (CaptureRefused, OSError) as exc:
                problems.append(f"{spec.kind}: {exc}")
                continue
            problems += verify_session(info, spec, target / f"{spec.kind}.etl", max_mb)
    if problems:
        remaining = _stop_all(env, capture_id)
        write_new_json(
            target / "state-02-failed.json",
            {
                "state": "FAILED",
                "utc": env.now().isoformat(),
                "problems": problems,
                "sessions_left": remaining,
            },
        )
        return {
            "state": "CLEANUP_REQUIRED" if remaining else "FAILED",
            "capture_id": capture_id,
            "problems": problems,
            "sessions_left": remaining,
            "cleanup": cleanup_instructions(capture_id) if remaining else None,
        }
    write_new_json(
        target / "state-02-active.json",
        {"state": "ACTIVE", "utc": env.now().isoformat(), "sessions": names},
    )
    return {
        "state": "ACTIVE",
        "capture_id": capture_id,
        "evidence_dir": str(target),
        "deadline_utc": deadline.isoformat(),
        "max_mb_per_session": max_mb,
        "tool_sha256": manifest["tool_sha256"],
        "provider_config_sha256": manifest["provider_config_sha256"],
        "next": "run the qualification step from an ordinary terminal, then stop this capture before the deadline",
    }


def _discard_empty(directory: Path) -> None:
    """Remove the directory this command just created if nothing was put in it (so a refused start can be retried)."""

    try:
        for leftover in directory.iterdir():
            if leftover.is_file() and not _is_reparse(leftover):
                return
        directory.rmdir()
    except OSError:
        pass


def _write_state(directory: Path, name: str, value: Any) -> None:
    try:
        write_new_json(directory / name, value)
    except FileExistsError:
        pass  # a repeated stop must not fail on the record an earlier attempt already wrote


def _stop_all(env: Environment, capture_id: str) -> list[str]:
    """Stop every session of this capture (even ones whose start reported failure), then name what is still live."""

    for name in session_names(capture_id).values():
        try:
            env.tools.stop(name)
        except CaptureRefused:
            pass
    try:
        return sorted(env.tools.live_for(capture_id))
    except CaptureRefused:
        return ["<session list unreadable>"]


def cleanup_instructions(capture_id: str) -> list[str]:
    names = session_names(capture_id)
    return [f'logman stop "{name}" -ets' for name in names.values()] + [
        "logman query -ets   (no StableNewCap- line may remain)"
    ]


# -- stop ---------------------------------------------------------------------------------------------------------------


def stop_capture(
    capture_id: str,
    *,
    evidence_dir: Path | None = None,
    env: Environment | None = None,
) -> dict[str, Any]:
    env = env or Environment(TraceTools())
    _require_elevated(env)
    names = session_names(capture_id)  # validates the id: only these names can ever be stopped
    directory: Path | None = None
    if evidence_dir is not None:
        directory = validate_existing_directory(evidence_dir, env.reports_root)
        manifest = _read_json(directory / "capture.json")
        if not manifest or manifest.get("capture_id") != capture_id:
            raise CaptureRefused("the directory's manifest does not name this capture id")
        _write_state(
            directory, "state-03-stopping.json", {"state": "STOPPING", "utc": env.now().isoformat()}
        )
    before = env.tools.live_for(capture_id)
    results: dict[str, Any] = {}
    for kind, name in names.items():
        if name not in before:
            results[kind] = {"was_running": False}
            continue
        code, text = env.tools.stop(name)
        results[kind] = {"was_running": True, "exit": code, "message": " ".join(text.split())[:200]}
    left = sorted(env.tools.live_for(capture_id))
    report: dict[str, Any] = {
        "capture_id": capture_id,
        "stopped_utc": env.now().isoformat(),
        "sessions": results,
        "sessions_left": left,
    }
    if left:
        report["state"] = "CLEANUP_REQUIRED"
        report["cleanup"] = cleanup_instructions(capture_id)
        return report
    report["state"] = "STOPPED"
    if directory is not None:
        sizes = {
            kind: (directory / f"{kind}.etl").stat().st_size
            for kind in names
            if (directory / f"{kind}.etl").is_file()
        }
        report["etl_bytes"] = sizes
        _write_state(directory, "state-04-stopped.json", {**report, "state": "STOPPED"})
    return report


# -- status (read-only, any terminal) -----------------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def derive_state(
    directory: Path,
    live: dict[str, str],
    now: datetime,
) -> dict[str, Any]:
    """The capture's state from what is on disk and what the OS says is running. Pure: no side effects."""

    manifest = _read_json(directory / "capture.json")
    if manifest is None:
        return {"state": "NOT_STARTED", "problems": ["no capture.json"]}
    capture_id = str(manifest.get("capture_id", ""))
    try:
        names = set(session_names(capture_id).values())
    except CaptureRefused:
        return {"state": "FAILED", "problems": ["capture.json carries an invalid capture id"]}
    running = sorted(n for n in live if n in names)
    out: dict[str, Any] = {"capture_id": capture_id, "sessions_running": running}
    has = {p.name for p in directory.glob("state-*.json")}
    if (directory / "verification.json").is_file():
        out["state"] = "VERIFIED"
    elif running and len(running) < len(names):
        out["state"] = "CLEANUP_REQUIRED"
        out["problems"] = ["only some of the capture's sessions are running"]
    elif running and "state-02-active.json" in has and "state-03-stopping.json" not in has:
        deadline = _parse_utc(manifest.get("deadline_utc"))
        if deadline is None or now > deadline:
            out["state"] = "EXPIRED"
            out["problems"] = ["the capture is past its deadline; stop it"]
        else:
            out["state"] = "ACTIVE"
            out["deadline_utc"] = deadline.isoformat()
    elif running:
        out["state"] = "CLEANUP_REQUIRED"
        out["problems"] = ["sessions are running but the capture is not in a clean ACTIVE state"]
    elif "state-04-stopped.json" in has:
        out["state"] = "STOPPED"
    elif "state-03-stopping.json" in has:
        out["state"] = "STOPPING"
        out["problems"] = ["a stop began but was not recorded as finished"]
    elif "state-02-active.json" in has:
        out["state"] = "STOPPED"
        out["problems"] = ["the sessions ended without a recorded operator stop"]
    elif "state-02-failed.json" in has:
        out["state"] = "FAILED"
    else:
        out["state"] = "STARTING"
        out["problems"] = ["a start began but never finished"]
    out["manifest"] = {
        k: manifest.get(k)
        for k in (
            "run_id",
            "created_utc",
            "deadline_utc",
            "max_mb_per_session",
            "provider_config_sha256",
        )
    }
    return out


def _parse_utc(text: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(text))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def capture_status(evidence_dir: Path, *, env: Environment | None = None) -> dict[str, Any]:
    env = env or Environment(TraceTools())
    directory = validate_existing_directory(evidence_dir, env.reports_root)
    return derive_state(directory, env.tools.live(), env.now())


# -- command line -------------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        help="the StableNew checkout whose reports/ directory holds the evidence (required for a protected copy)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="start the capture (Administrator terminal)")
    start.add_argument("--evidence-dir", type=Path, required=True)
    start.add_argument("--run-id", required=True)
    start.add_argument("--capture-id", help="optional exact identity from an approved capture plan")
    start.add_argument("--max-mb", type=int, default=DEFAULT_MAX_MB)
    start.add_argument("--minutes", type=int, default=DEFAULT_MINUTES)
    for name in ("stop", "cleanup"):
        sp = sub.add_parser(name, help="stop the capture's sessions (Administrator terminal)")
        sp.add_argument("--capture-id", required=True)
        if name == "stop":
            sp.add_argument("--evidence-dir", type=Path)
    st = sub.add_parser("status", help="read-only state of a capture (any terminal)")
    st.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        env = Environment(TraceTools(), reports_root=resolve_reports_root(args.repo_root))
        if args.command == "start":
            report = start_capture(
                args.evidence_dir,
                run_id=args.run_id,
                max_mb=args.max_mb,
                minutes=args.minutes,
                env=env,
                capture_id=args.capture_id,
            )
        elif args.command == "stop":
            report = stop_capture(args.capture_id, evidence_dir=args.evidence_dir, env=env)
        elif args.command == "cleanup":
            report = stop_capture(args.capture_id, env=env)
        else:
            report = capture_status(args.evidence_dir, env=env)
    except CaptureRefused as exc:
        print(json.dumps({"state": "REFUSED", "refused": str(exc)}, indent=2))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    if report.get("state") == "CLEANUP_REQUIRED":
        return 3
    return 0 if report.get("state") in ("ACTIVE", "STOPPED", "VERIFIED", "EXPIRED") else 1


if __name__ == "__main__":
    sys.exit(main())
