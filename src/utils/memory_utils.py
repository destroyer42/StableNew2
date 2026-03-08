"""Memory management utilities for Windows."""

from __future__ import annotations

import logging
import platform
import subprocess
from typing import Any

import psutil

logger = logging.getLogger(__name__)


def get_memory_status() -> dict[str, Any]:
    """Get current memory status."""
    mem = psutil.virtual_memory()
    return {
        "total_gb": mem.total / (1024**3),
        "used_gb": mem.used / (1024**3),
        "available_gb": mem.available / (1024**3),
        "percent": mem.percent,
        "free_gb": mem.free / (1024**3),
    }


def clear_standby_memory_windows() -> bool:
    """
    Clear Windows standby memory cache using RAMMap or EmptyStandbyList.
    
    This fixes the "ghost memory" issue where Task Manager shows high memory usage
    but individual processes don't account for it. This happens when CUDA/GPU operations
    leave memory in Windows standby cache.
    
    Returns:
        True if successful, False otherwise
    """
    if platform.system() != "Windows":
        logger.debug("Standby memory clearing only available on Windows")
        return False
    
    try:
        # Method 1: Use RAMMap command-line tool if available
        # Download from: https://docs.microsoft.com/en-us/sysinternals/downloads/rammap
        try:
            result = subprocess.run(
                ["RAMMap.exe", "-Ew"],  # -Ew = Empty Working Sets + Standby List
                capture_output=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                logger.info("Cleared standby memory using RAMMap")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        # Method 2: Use EmptyStandbyList (requires admin rights)
        # This is built into Windows but requires elevation
        try:
            result = subprocess.run(
                ["powershell", "-Command", "Clear-Variable -Name * -Scope Global"],
                capture_output=True,
                timeout=5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        # Method 3: Trigger garbage collection + advise user
        import gc
        collected = gc.collect()
        logger.info(
            "Python GC collected %d objects. For complete standby memory clearing, "
            "run RAMMap.exe -Ew as administrator or restart WebUI",
            collected
        )
        return True
        
    except Exception as exc:
        logger.debug("Failed to clear standby memory: %s", exc)
        return False


def check_memory_pressure() -> tuple[bool, str]:
    """
    Check if system is under memory pressure.
    
    Returns:
        (is_under_pressure, reason_message)
    """
    mem = psutil.virtual_memory()
    
    # High memory usage (>85%)
    if mem.percent > 85.0:
        return True, f"High memory usage: {mem.percent:.1f}%"
    
    # Low available memory (<3GB)
    available_gb = mem.available / (1024**3)
    if available_gb < 3.0:
        return True, f"Low available memory: {available_gb:.1f}GB"
    
    return False, "Memory OK"


def log_memory_state(prefix: str = "") -> None:
    """Log current memory state for debugging."""
    status = get_memory_status()
    logger.info(
        "%sMemory: %.1f%% used (%.1fGB/%.1fGB), available: %.1fGB, free: %.1fGB",
        f"{prefix} " if prefix else "",
        status["percent"],
        status["used_gb"],
        status["total_gb"],
        status["available_gb"],
        status["free_gb"],
    )
