from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import List

try:
    import psutil  # type: ignore[import]
except ImportError:  # pragma: no cover
    psutil = None

REPO_ROOT = Path(__file__).resolve().parents[2]
KEYWORDS = {"stablenew", "stable-diffusion-webui", "webui-user", "sd-webui"}


def _matches_keywords(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(keyword in lowered for keyword in KEYWORDS)


def _collect_candidates() -> List[str]:
    matches: List[str] = []
    if psutil:
        for proc in psutil.process_iter(attrs=["pid", "name", "cmdline", "cwd"]):
            pid = proc.info.get("pid")
            if pid == os.getpid():
                continue
            name = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or [])
            cwd = proc.info.get("cwd") or ""
            if "python" not in name and "python" not in cmdline.lower():
                continue
            if _matches_keywords(cmdline) or _matches_keywords(cwd) or _matches_keywords(str(REPO_ROOT)):
                matches.append(f"{pid}:{name}:{cmdline}")
        return matches

    if platform.system() == "Windows":
        result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe"], capture_output=True, text=True)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
    else:
        result = subprocess.run(["ps", "-A"], capture_output=True, text=True)
        lines = result.stdout.splitlines()

    for line in lines:
        if "python" not in line.lower():
            continue
        if _matches_keywords(line):
            matches.append(line.strip())
    return matches


def list_stablenew_processes() -> List[str]:
    return _collect_candidates()


def assert_no_stable_new_processes() -> None:
    matches = list_stablenew_processes()
    if matches:
        raise AssertionError(f"StableNew/WebUI processes still running: {matches}")


def request_clean_shutdown(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        proc.send_signal(subprocess.CTRL_BREAK_EVENT)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def assert_no_webui_processes() -> None:
    matches = list_stablenew_processes()
    if matches:
        raise AssertionError(f"StableNew/WebUI processes still running: {matches}")
