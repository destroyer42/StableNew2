#!/usr/bin/env python3
"""
Pre-commit hook: Check for daemon=True thread usage

PR-THREAD-001 Guardrail: Prevents introduction of new daemon threads.
Daemon threads should be avoided in favor of ThreadRegistry with proper shutdown.
"""

import os
import re
import sys
from pathlib import Path

# Files exempt from daemon thread check
EXEMPT_FILES = {
    "scripts/check_daemon_threads.py",  # This file
    "tests/",  # Tests may use daemon threads for timeouts
}

# Allowed daemon thread patterns (legacy code that's approved)
ALLOWED_DAEMON_PATTERNS = [
    # Add specific approved cases here, e.g.:
    # "src/legacy/old_module.py:123",
]


def is_exempt(filepath: str) -> bool:
    """Check if file is exempt from daemon thread check."""
    for exempt in EXEMPT_FILES:
        if filepath.startswith(exempt):
            return True
    return False


def find_daemon_threads(filepath: str) -> list[tuple[int, str]]:
    """Find all daemon=True usages in a Python file.
    
    Returns:
        List of (line_number, line_content) tuples
    """
    violations = []
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, start=1):
                # Skip comments and docstrings
                stripped = line.strip()
                if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                
                # Look for daemon=True
                if re.search(r'\bdaemon\s*=\s*True\b', line):
                    # Check if this is an allowed pattern
                    location = f"{filepath}:{line_num}"
                    if location not in ALLOWED_DAEMON_PATTERNS:
                        violations.append((line_num, line.rstrip()))
    
    except Exception as e:
        print(f"Error reading {filepath}: {e}", file=sys.stderr)
    
    return violations


def main():
    """Scan all Python files for daemon=True threads."""
    root_dir = Path(__file__).parent.parent
    src_dir = root_dir / "src"
    
    violations_found = False
    
    # Scan all Python files in src/
    for python_file in src_dir.rglob("*.py"):
        rel_path = python_file.relative_to(root_dir).as_posix()
        
        if is_exempt(rel_path):
            continue
        
        violations = find_daemon_threads(str(python_file))
        
        if violations:
            violations_found = True
            print(f"\n❌ VIOLATION: daemon=True found in {rel_path}", file=sys.stderr)
            for line_num, line in violations:
                print(f"   Line {line_num}: {line}", file=sys.stderr)
    
    if violations_found:
        print("\n" + "="*80, file=sys.stderr)
        print("⚠️  DAEMON THREAD GUARDRAIL VIOLATION", file=sys.stderr)
        print("="*80, file=sys.stderr)
        print("\nDaemon threads are prohibited by PR-THREAD-001.", file=sys.stderr)
        print("\nReason: Daemon threads become zombies after GUI shutdown.", file=sys.stderr)
        print("\nSolution: Use ThreadRegistry.spawn() with daemon=False instead:", file=sys.stderr)
        print("\n  from src.utils.thread_registry import get_thread_registry", file=sys.stderr)
        print("  registry = get_thread_registry()", file=sys.stderr)
        print("  thread = registry.spawn(", file=sys.stderr)
        print("      target=my_function,", file=sys.stderr)
        print("      name='MyWorkerThread',", file=sys.stderr)
        print("      daemon=False  # Explicit", file=sys.stderr)
        print("  )", file=sys.stderr)
        print("\nIf this is intentional, add to ALLOWED_DAEMON_PATTERNS.", file=sys.stderr)
        print("="*80 + "\n", file=sys.stderr)
        return 1
    
    print("✅ No daemon=True violations found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
