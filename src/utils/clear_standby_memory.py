"""Utility to clear Windows standby memory - fixes 'ghost memory' issue.

Run this when Task Manager shows high memory usage but processes don't add up.
This happens after GPU-intensive operations like hires fix upscaling.

Usage:
    python -m src.utils.clear_standby_memory
"""

from __future__ import annotations

import logging
import sys

from src.utils.memory_utils import (
    check_memory_pressure,
    clear_standby_memory_windows,
    log_memory_state,
)

# Set up simple console logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)


def main() -> int:
    """Clear standby memory and report results."""
    logger.info("=" * 60)
    logger.info("Windows Standby Memory Clearer")
    logger.info("=" * 60)
    
    # Show current memory state
    log_memory_state("Before cleanup:")
    
    under_pressure, reason = check_memory_pressure()
    if under_pressure:
        logger.warning("Memory pressure detected: %s", reason)
    else:
        logger.info("Memory status: %s", reason)
    
    # Clear standby memory
    logger.info("\nClearing standby memory...")
    success = clear_standby_memory_windows()
    
    if success:
        logger.info("✓ Standby memory cleared")
    else:
        logger.warning("⚠ Standby memory clearing incomplete")
        logger.info("\nFor complete cleanup, run as administrator:")
        logger.info("  powershell -Command \"Clear-Variable -Name * -Scope Global; [gc]::Collect()\"")
        logger.info("\nOr download RAMMap from Microsoft Sysinternals:")
        logger.info("  https://docs.microsoft.com/en-us/sysinternals/downloads/rammap")
        logger.info("  Then run: RAMMap.exe -Ew")
    
    # Show final memory state
    log_memory_state("\nAfter cleanup:")
    
    under_pressure, reason = check_memory_pressure()
    if under_pressure:
        logger.warning("Still under memory pressure: %s", reason)
        logger.info("Consider restarting WebUI or the entire application")
        return 1
    else:
        logger.info("✓ Memory status: %s", reason)
        return 0


if __name__ == "__main__":
    sys.exit(main())
