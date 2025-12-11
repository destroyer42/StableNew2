#!/usr/bin/env python
"""
Generate pipeline_config_refs.md listing all occurrences of "pipeline_config"
in the repo, excluding archive/, .git/, and *.zip paths.

Requires ripgrep (`rg`) on PATH.
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "pipeline_config_refs.md"

RG_CMD = [
    "rg",
    "--line-number",
    "pipeline_config",
    "--hidden",  # allow scanning hidden files unless excluded
    "--glob",
    "!archive/**",
    "--glob",
    "!.git/**",
    "--glob",
    "!**/*.zip",
]


def main() -> None:
    result = subprocess.run(
        RG_CMD,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode not in (0, 1):  # 1 means no matches
        raise RuntimeError(f"rg failed: {result.stderr}")

    grouped: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for line in result.stdout.splitlines():
        try:
            path, lineno, text = line.split(":", 2)
            grouped[path].append((int(lineno), text.strip()))
        except ValueError:
            continue

    with OUTPUT.open("w", encoding="utf-8") as f:
        f.write("# pipeline_config references (excluding archive/.git/zip)\n\n")
        for path in sorted(grouped.keys()):
            f.write(f"## {path}\n")
            for lineno, text in sorted(grouped[path], key=lambda x: x[0]):
                f.write(f"- {path}:{lineno}: {text}\n")
            f.write("\n")

    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
