#!/usr/bin/env python3
"""
Summarize file access logs and join with repo_inventory.json for StableNew V2.5 clean-house effort.
Outputs CSV and Markdown reports for later archiving and migration.
"""

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path("logs/file_access")
INVENTORY_PATH = Path("repo_inventory.json")
REPORT_DIR = Path("reports/file_access")
CSV_PATH = REPORT_DIR / "file_access_summary.csv"
MD_PATH = REPORT_DIR / "CLEANHOUSE_REPORT_V2_5_2025_11_26.md"

CATEGORY_A = "A_RUNTIME_CORE"
CATEGORY_B = "B_RUNTIME_ADJACENT"
CATEGORY_C = "C_TEST"
CATEGORY_D = "D_ARCHIVE_OR_LEGACY"
CATEGORY_E = "E_OTHER"

CSV_HEADER = [
    "path",
    "touched_at_runtime",
    "reasons",
    "reachable_from_main",
    "is_src",
    "is_test",
    "is_archive",
    "is_gui",
    "category",
    "package",
]


def normalize_to_repo_relative(
    abs_path: Path, repo_root: Path, anchors=("src", "tests", "docs", "archive", "tools")
):
    try:
        # Strict: relative to repo root
        return abs_path.resolve().relative_to(repo_root.resolve()).as_posix()
    except Exception:
        parts = abs_path.parts
        for anchor in anchors:
            if anchor in parts:
                i = parts.index(anchor)
                rel = Path(*parts[i:])
                return rel.as_posix()
    return None


def load_file_access_logs(log_dir: Path, repo_root: Path):
    """Aggregate all file access logs into a dict keyed by repo-relative path."""
    if not log_dir.exists():
        print("No file access logs found; nothing to summarize.")
        return {}
    paths = {}
    unmatched_paths = set()
    total_lines = 0
    for log_file in log_dir.glob("*.jsonl"):
        try:
            with log_file.open("r", encoding="utf-8") as f:
                for line in f:
                    total_lines += 1
                    try:
                        entry = json.loads(line)
                        abs_path = Path(entry.get("path", "")).resolve()
                        rel_path = normalize_to_repo_relative(abs_path, repo_root)
                        reason = entry.get("reason", "")
                        if rel_path:
                            if rel_path not in paths:
                                paths[rel_path] = {"touched_at_runtime": True, "reasons": set()}
                            paths[rel_path]["reasons"].add(reason)
                        else:
                            unmatched_paths.add(str(abs_path))
                    except Exception:
                        continue
        except Exception:
            continue
    # Convert reasons sets to comma-separated strings
    for v in paths.values():
        v["reasons"] = ",".join(sorted(v["reasons"]))
    print(
        f"[summarize] Loaded {total_lines} JSONL entries from {len(list(log_dir.glob('*.jsonl')))} files."
    )
    print(f"[summarize] Resolved {len(paths)} unique repo-relative paths.")
    print(
        f"[summarize] {len(unmatched_paths)} runtime paths could not be normalized (see unmatched list)."
    )
    return paths


def load_repo_inventory(inv_path: Path):
    """Load repo_inventory.json as a list of dicts."""
    if not inv_path.exists():
        print(f"repo_inventory.json not found at {inv_path}")
        sys.exit(1)
    try:
        with inv_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                # If top-level is a dict, assume records under 'files' or similar
                data = data.get("files", [])
            if not isinstance(data, list):
                print("repo_inventory.json is malformed (expected list of records)")
                sys.exit(1)
            return data
    except Exception as e:
        print(f"Error loading repo_inventory.json: {e}")
        sys.exit(1)


def categorize(path, inv):
    """Determine category for a file based on path and inventory flags."""
    p = path.lower()
    is_src = p.startswith("src/")
    is_test = p.startswith("tests/") or inv.get("is_test", False)
    is_archive = p.startswith("archive/") or "(old" in p or "legacy" in p or "gui_v1_legacy" in p
    touched = inv.get("touched_at_runtime", False)
    reachable = inv.get("reachable_from_main", False)
    # Category rules
    if is_src and (touched or reachable):
        return CATEGORY_A
    if is_src and not touched and not reachable and not is_test and not is_archive:
        return CATEGORY_B
    if is_test:
        return CATEGORY_C
    if is_archive:
        return CATEGORY_D
    return CATEGORY_E


def join_inventory_and_logs(inv_list, log_dict):
    """Join inventory and log info into a list of dicts for reporting."""
    all_paths = set(log_dict.keys()) | {rec.get("path", "") for rec in inv_list}
    rows = []
    for path in sorted(all_paths):
        inv = next((rec for rec in inv_list if rec.get("path", "") == path), {})
        log = log_dict.get(path, {})
        row = {
            "path": path,
            "touched_at_runtime": str(log.get("touched_at_runtime", False)).lower(),
            "reasons": log.get("reasons", ""),
            "reachable_from_main": str(inv.get("reachable_from_main", "")).lower()
            if "reachable_from_main" in inv
            else "",
            "is_src": str(path.startswith("src/")).lower(),
            "is_test": str(path.startswith("tests/") or inv.get("is_test", False)).lower(),
            "is_archive": str(
                path.startswith("archive/")
                or "(OLD" in path
                or "legacy" in path
                or "gui_v1_legacy" in path
            ).lower(),
            "is_gui": str(inv.get("is_gui", False) or path.startswith("src/gui/")).lower(),
            "category": categorize(path, {**inv, **log}),
            "package": inv.get("package", ""),
        }
        rows.append(row)
    return rows


def write_csv(rows, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_markdown(rows, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cats = [CATEGORY_A, CATEGORY_B, CATEGORY_C, CATEGORY_D, CATEGORY_E]
    cat_counts = dict.fromkeys(cats, 0)
    for r in rows:
        cat_counts[r["category"]] += 1
    total = len(rows)
    with out_path.open("w", encoding="utf-8") as f:
        f.write("# CLEANHOUSE File Access Report (V2.5)\n\n")
        f.write(f"_Generated: {now}_\n\n")
        f.write(f"**Total files:** {total}\n\n")
        for c in cats:
            f.write(f"- {c}: {cat_counts[c]}\n")
        f.write("\n")
        for c in cats:
            f.write(f"## Category {c}\n\n")
            for r in rows:
                if r["category"] == c:
                    note = []
                    if r["is_gui"] == "true":
                        note.append("GUI")
                    if r["package"]:
                        note.append(r["package"])
                    if r["is_archive"] == "true":
                        note.append("ARCHIVE/LEGACY")
                    if r["is_test"] == "true":
                        note.append("TEST")
                    bullet = f"- `{r['path']}` | touched: {r['touched_at_runtime']}"
                    if r["reachable_from_main"]:
                        bullet += f" | reachable_from_main: {r['reachable_from_main']}"
                    if note:
                        bullet += f" | {'; '.join(note)}"
                    f.write(bullet + "\n")
            f.write("\n")


def main():
    repo_root = Path.cwd()
    log_dict = load_file_access_logs(LOG_DIR, repo_root)
    inv_list = load_repo_inventory(INVENTORY_PATH)
    rows = join_inventory_and_logs(inv_list, log_dict)
    write_csv(rows, CSV_PATH)
    write_markdown(rows, MD_PATH)
    print(f"Summary written to {CSV_PATH} and {MD_PATH}")


if __name__ == "__main__":
    main()
