"""
Lightweight repository inventory helper.

Walks the tree, captures per-file metadata, builds a best-effort static import
graph from src/main.py, and emits:
- repo_inventory.json (machine-readable)
- docs/ACTIVE_MODULES.md
- docs/LEGACY_CANDIDATES.md

Run from repo root:
    python -m tools.inventory_repo
"""

from __future__ import annotations

import ast
import json
from collections import deque
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
OUTPUT_JSON = ROOT / "repo_inventory.json"
OUTPUT_ACTIVE_MD = DOCS_DIR / "ACTIVE_MODULES.md"
OUTPUT_LEGACY_MD = DOCS_DIR / "LEGACY_CANDIDATES.md"

SCAN_DIRS = ["src", "tests", "docs"]


@dataclass
class FileRecord:
    path: str
    module: str | None
    line_count: int
    has_tk: bool
    is_gui: bool
    has_v1_marker: bool
    imports: list[str]
    reachable_from_main: bool = False


def iter_py_files() -> Iterable[Path]:
    for dirname in SCAN_DIRS:
        base = ROOT / dirname
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if path.is_file():
                yield path


def module_name_for(path: Path) -> str | None:
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return None
    parts = rel.with_suffix("").parts
    if parts[0] not in {"src", "tests"}:
        return None
    # Drop __init__ for package module naming
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def resolve_relative_import(current_module: str, target: str | None, level: int) -> str | None:
    if not current_module:
        return target
    base_parts = current_module.split(".")
    if level > len(base_parts):
        return target
    prefix = base_parts[:-level]
    if target:
        prefix.append(target)
    return ".".join(prefix)


def parse_file(path: Path, module_name: str | None) -> tuple[list[str], bool]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(text)
    except Exception:
        return [], False

    imports: list[str] = []
    has_tk = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                imports.append(name)
                if name.startswith(("tkinter", "ttk")):
                    has_tk = True
        elif isinstance(node, ast.ImportFrom):
            mod = node.module
            if node.level and module_name:
                mod = resolve_relative_import(module_name, mod, node.level)
            if mod:
                imports.append(mod)
                if mod.startswith(("tkinter", "ttk")):
                    has_tk = True
    return imports, has_tk


def build_records() -> dict[Path, FileRecord]:
    records: dict[Path, FileRecord] = {}
    for path in iter_py_files():
        module_name = module_name_for(path)
        imports, has_tk = parse_file(path, module_name)
        rel = path.relative_to(ROOT)
        line_count = sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
        has_v1_marker = "v1" in path.name.lower()
        try:
            header = "".join(
                path.read_text(encoding="utf-8", errors="ignore").splitlines()[:3]
            ).lower()
            has_v1_marker = has_v1_marker or "v1" in header
        except Exception:
            pass
        is_gui = has_tk or "gui" in rel.parts
        records[path] = FileRecord(
            path=str(rel.as_posix()),
            module=module_name,
            line_count=line_count,
            has_tk=has_tk,
            is_gui=is_gui,
            has_v1_marker=has_v1_marker,
            imports=imports,
        )
    return records


def build_module_map(records: dict[Path, FileRecord]) -> dict[str, Path]:
    mod_map: dict[str, Path] = {}
    for path, rec in records.items():
        if rec.module:
            mod_map[rec.module] = path
    return mod_map


def resolve_import_to_path(import_name: str, module_map: dict[str, Path]) -> Path | None:
    candidates = [import_name]
    if not import_name.startswith("src."):
        candidates.append(f"src.{import_name}")
    for cand in candidates:
        if cand in module_map:
            return module_map[cand]
    return None


def mark_reachable(records: dict[Path, FileRecord]) -> None:
    module_map = build_module_map(records)
    start = ROOT / "src" / "main.py"
    if start not in records:
        return
    queue: deque[Path] = deque([start])
    visited: set[Path] = set()
    while queue:
        path = queue.popleft()
        if path in visited:
            continue
        visited.add(path)
        record = records[path]
        record.reachable_from_main = True
        for imp in record.imports:
            target = resolve_import_to_path(imp, module_map)
            if target and target not in visited:
                queue.append(target)


def write_json(records: dict[Path, FileRecord]) -> None:
    OUTPUT_JSON.write_text(
        json.dumps(
            {
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "root": str(ROOT),
                "files": [asdict(rec) for rec in sorted(records.values(), key=lambda r: r.path)],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def write_active_md(records: dict[Path, FileRecord]) -> None:
    reachable = [rec for rec in records.values() if rec.reachable_from_main]
    lines = [
        "# Active Modules",
        "",
        f"Generated: {datetime.utcnow().isoformat()}Z",
        "",
        f"Total tracked files: {len(records)}",
        f"Reachable from src/main.py: {len(reachable)}",
        "",
        "## List",
    ]
    for rec in sorted(reachable, key=lambda r: r.path):
        markers = []
        if rec.is_gui:
            markers.append("gui")
        if rec.has_v1_marker:
            markers.append("v1?")
        marker_text = f" ({', '.join(markers)})" if markers else ""
        lines.append(f"- `{rec.path}`{marker_text}")
    OUTPUT_ACTIVE_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_ACTIVE_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def categorize(path: str) -> str:
    lower = path.lower()
    if "gui" in lower:
        return "GUI"
    if "pipeline" in lower:
        return "Pipeline"
    if "tests" in lower:
        return "Tests"
    if "tools" in lower or "scripts" in lower:
        return "Tooling"
    return "Other"


def write_legacy_md(records: dict[Path, FileRecord]) -> None:
    legacy = [rec for rec in records.values() if rec.has_v1_marker or not rec.reachable_from_main]
    buckets: dict[str, list[FileRecord]] = {}
    for rec in legacy:
        buckets.setdefault(categorize(rec.path), []).append(rec)

    lines = [
        "# Legacy Candidates",
        "",
        "Files flagged as likely V1 or not reachable from src/main.py.",
        f"Generated: {datetime.utcnow().isoformat()}Z",
        "",
    ]

    for bucket in sorted(buckets):
        lines.append(f"## {bucket}")
        for rec in sorted(buckets[bucket], key=lambda r: r.path):
            markers = []
            if rec.has_v1_marker:
                markers.append("v1-marker")
            if not rec.reachable_from_main:
                markers.append("unreachable")
            marker_text = f" ({', '.join(markers)})" if markers else ""
            lines.append(f"- `{rec.path}`{marker_text}")
        lines.append("")

    OUTPUT_LEGACY_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_LEGACY_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    records = build_records()
    mark_reachable(records)
    write_json(records)
    write_active_md(records)
    write_legacy_md(records)
    print(f"Inventory written to {OUTPUT_JSON}")
    print(f"Active modules summary: {OUTPUT_ACTIVE_MD}")
    print(f"Legacy candidates summary: {OUTPUT_LEGACY_MD}")


if __name__ == "__main__":
    main()
