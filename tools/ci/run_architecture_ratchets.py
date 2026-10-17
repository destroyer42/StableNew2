"""Architecture-rule ratchets as AST checks (audit P1-5b).

Rules that previously lived only as prose or as pre-commit scripts that were broken on ``main`` become checked ratchets
over ``tools/ci/architecture_baseline.json``: per-file counts may not exceed the baseline, a file absent from the baseline
must have none, and an improvement must be locked in with ``--update``.

* **daemon_threads** - ``daemon=True`` passed to a thread constructor or ``ThreadRegistry.spawn`` in ``src`` (PR-THREAD-001:
  shutdown must be able to account for every thread).
* **raw_threads** - ``threading.Thread(...)`` created in ``src`` outside ``src/utils/thread_registry.py`` instead of through
  the registry.
* **utils_upward_imports** - ``src/utils`` importing a higher layer (controller, gui, pipeline, queue, api, ...); utils must
  stay at the bottom of the dependency order.
* **controller_gui_imports** - ``src/controller`` importing ``src.gui``: controllers coordinate services and must not depend
  on Tk presentation.

Pure ``ast`` (no imports of application code), so it is instant and identical on every platform.

    python tools/ci/run_architecture_ratchets.py            # check
    python tools/ci/run_architecture_ratchets.py --update   # rewrite the baseline after a deliberate improvement
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
BASELINE_PATH = ROOT / "tools" / "ci" / "architecture_baseline.json"
SCHEMA_VERSION = 1

THREAD_REGISTRY_FILE = "src/utils/thread_registry.py"
UTILS_UPWARD_PACKAGES = frozenset(
    {
        "controller",
        "gui",
        "gui_v2",
        "pipeline",
        "queue",
        "api",
        "learning",
        "video",
        "image_backends",
        "services",
        "promptpacks",
    }
)
RULES = ("daemon_threads", "raw_threads", "utils_upward_imports", "controller_gui_imports")


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _is_thread_constructor(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr == "Thread":
        return isinstance(func.value, ast.Name) and func.value.id == "threading"
    return isinstance(func, ast.Name) and func.id == "Thread"


def _has_daemon_true(call: ast.Call) -> bool:
    return any(
        kw.arg == "daemon" and isinstance(kw.value, ast.Constant) and kw.value.value is True
        for kw in call.keywords
    )


def _imported_src_packages(node: ast.AST) -> list[str]:
    """First package below ``src`` for each absolute ``src.<pkg>`` import in this statement."""

    names: list[str] = []
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
    packages = []
    for name in names:
        parts = name.split(".")
        if len(parts) >= 2 and parts[0] == "src":
            packages.append(parts[1])
    return sorted(set(packages)) if isinstance(node, ast.ImportFrom) else packages


def scan_source(relative: str, source: str) -> dict[str, int]:
    """Rule counts for one file (relative POSIX path, source text)."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    counts = dict.fromkeys(RULES, 0)
    in_utils = relative.startswith("src/utils/")
    in_controller = relative.startswith("src/controller/")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if _has_daemon_true(node):
                counts["daemon_threads"] += 1
            if _is_thread_constructor(node) and relative != THREAD_REGISTRY_FILE:
                counts["raw_threads"] += 1
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            packages = _imported_src_packages(node)
            if in_utils and any(p in UTILS_UPWARD_PACKAGES for p in packages):
                counts["utils_upward_imports"] += 1
            if in_controller and "gui" in packages:
                counts["controller_gui_imports"] += 1
    return {rule: n for rule, n in counts.items() if n}


def collect(src: Path = SRC) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for path in sorted(src.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        counts = scan_source(_relative(path), path.read_text(encoding="utf-8"))
        if counts:
            result[_relative(path)] = counts
    return result


def compare(current: dict[str, dict[str, int]], baseline: dict[str, dict[str, int]]) -> list[str]:
    problems = []
    for path in sorted(set(current) | set(baseline)):
        for rule in RULES:
            have, allowed = current.get(path, {}).get(rule, 0), baseline.get(path, {}).get(rule, 0)
            if have > allowed:
                problems.append(
                    f"{rule} REGRESSION: {path}: {have} (baseline {allowed}); see the rule in tools/ci/run_architecture_ratchets.py"
                )
            elif have < allowed:
                problems.append(
                    f"{rule} IMPROVED: {path}: {have} (baseline {allowed}); run `python tools/ci/run_architecture_ratchets.py --update`"
                )
    return problems


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, dict[str, int]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{path.name}: unsupported schema_version {data.get('schema_version')!r}")
    return {p: {r: int(n) for r, n in per.items()} for p, per in data["counts"].items()}


def totals(counts: dict[str, dict[str, int]]) -> dict[str, int]:
    return {rule: sum(per.get(rule, 0) for per in counts.values()) for rule in RULES}


def write_baseline(counts: dict[str, dict[str, int]], path: Path = BASELINE_PATH) -> None:
    payload = {"schema_version": SCHEMA_VERSION, "totals": totals(counts), "counts": counts}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--update", action="store_true", help="rewrite the baseline from the current state"
    )
    args = parser.parse_args(argv)

    counts = collect()
    if args.update:
        write_baseline(counts)
        print(f"architecture ratchet baseline written: {totals(counts)}")
        return 0
    if not BASELINE_PATH.is_file():
        print(
            f"architecture ratchets FAILED: {BASELINE_PATH.name} is missing; create it with --update",
            file=sys.stderr,
        )
        return 1
    problems = compare(counts, load_baseline())
    if problems:
        print(f"architecture ratchets FAILED ({len(problems)} issue(s))", file=sys.stderr)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print(f"architecture ratchets OK: {totals(counts)} - none beyond the baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
