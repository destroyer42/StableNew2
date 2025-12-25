#!/usr/bin/env python3
"""
Pre-commit hook: Verify threading.Thread() uses ThreadRegistry

PR-THREAD-001 Guardrail: Ensures all threading.Thread() instantiations
use ThreadRegistry.spawn() for centralized lifecycle management.
"""

import ast
import sys
from pathlib import Path
from typing import List, Tuple

# Files exempt from ThreadRegistry requirement
EXEMPT_FILES = {
    "src/utils/thread_registry.py",  # ThreadRegistry implementation itself
    "scripts/check_thread_registry_usage.py",  # This file
    "tests/",  # Tests may create threads directly for testing
}

# Modules that are allowed to create threads directly
ALLOWED_MODULES = {
    "threading.Timer",  # Timer is OK (short-lived)
}


class ThreadCreationVisitor(ast.NodeVisitor):
    """AST visitor to find threading.Thread instantiations."""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.violations: List[Tuple[int, str]] = []
    
    def visit_Call(self, node: ast.Call):
        """Check for threading.Thread() calls."""
        # Check for threading.Thread()
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == "Thread":
                # Check if it's threading.Thread (not ThreadRegistry.spawn)
                if isinstance(node.func.value, ast.Name):
                    if node.func.value.id == "threading":
                        # Found threading.Thread() - this is a violation
                        line_num = node.lineno
                        self.violations.append((line_num, "threading.Thread()"))
        
        # Check for direct Thread() without module prefix
        elif isinstance(node.func, ast.Name):
            if node.func.id == "Thread":
                # Found Thread() - likely from "from threading import Thread"
                line_num = node.lineno
                self.violations.append((line_num, "Thread()"))
        
        self.generic_visit(node)


def is_exempt(filepath: str) -> bool:
    """Check if file is exempt from ThreadRegistry requirement."""
    for exempt in EXEMPT_FILES:
        if filepath.startswith(exempt):
            return True
    return False


def check_file(filepath: str) -> List[Tuple[int, str]]:
    """Check a single Python file for threading.Thread usage.
    
    Returns:
        List of (line_number, call_type) tuples for violations
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            source = f.read()
        
        tree = ast.parse(source, filename=filepath)
        visitor = ThreadCreationVisitor(filepath)
        visitor.visit(tree)
        
        return visitor.violations
    
    except SyntaxError:
        # File has syntax errors, let other linters handle it
        return []
    except Exception as e:
        print(f"Error parsing {filepath}: {e}", file=sys.stderr)
        return []


def main(files: List[str]) -> int:
    """Check provided files for threading.Thread usage."""
    root_dir = Path(__file__).parent.parent
    violations_found = False
    
    for filepath in files:
        # Convert to relative path
        try:
            rel_path = Path(filepath).relative_to(root_dir).as_posix()
        except ValueError:
            # File not in repo
            continue
        
        if is_exempt(rel_path):
            continue
        
        violations = check_file(filepath)
        
        if violations:
            violations_found = True
            print(f"\n❌ VIOLATION: Direct threading.Thread usage in {rel_path}", file=sys.stderr)
            for line_num, call_type in violations:
                print(f"   Line {line_num}: {call_type}", file=sys.stderr)
    
    if violations_found:
        print("\n" + "="*80, file=sys.stderr)
        print("⚠️  THREAD REGISTRY GUARDRAIL VIOLATION", file=sys.stderr)
        print("="*80, file=sys.stderr)
        print("\nDirect threading.Thread() usage is prohibited by PR-THREAD-001.", file=sys.stderr)
        print("\nReason: Centralized thread lifecycle management is required.", file=sys.stderr)
        print("\nSolution: Use ThreadRegistry.spawn() instead:", file=sys.stderr)
        print("\n  # DON'T:", file=sys.stderr)
        print("  thread = threading.Thread(target=my_func, name='Worker')", file=sys.stderr)
        print("  thread.start()", file=sys.stderr)
        print("\n  # DO:", file=sys.stderr)
        print("  from src.utils.thread_registry import get_thread_registry", file=sys.stderr)
        print("  registry = get_thread_registry()", file=sys.stderr)
        print("  thread = registry.spawn(", file=sys.stderr)
        print("      target=my_func,", file=sys.stderr)
        print("      name='Worker',", file=sys.stderr)
        print("      purpose='Description of thread purpose'", file=sys.stderr)
        print("  )", file=sys.stderr)
        print("\nIf this file should be exempt, add to EXEMPT_FILES.", file=sys.stderr)
        print("="*80 + "\n", file=sys.stderr)
        return 1
    
    return 0


if __name__ == "__main__":
    # Get files from command line arguments (passed by pre-commit)
    files = sys.argv[1:] if len(sys.argv) > 1 else []
    
    if not files:
        print("✅ No files to check")
        sys.exit(0)
    
    result = main(files)
    if result == 0:
        print("✅ All threading.Thread() calls use ThreadRegistry")
    sys.exit(result)
