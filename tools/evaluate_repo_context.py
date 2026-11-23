"""Compare bounded context routing with lexical navigation over the two existing maps."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from statistics import median
from time import perf_counter

from tools import context_index, context_router, repo_context
from tools.generate_code_map import ROOT


def map_baseline(index: dict) -> dict:
    """Use the same lexical ranking and cap with only information available in the maps."""
    summaries = {}
    directory = ""
    for line in index["code_map"].splitlines():
        if line.startswith("## "):
            directory = line[3:]
        match = re.fullmatch(r"- \x60([^\x60]+)\x60: (.*)", line)
        if match and directory:
            summaries[directory + match[1]] = match[2]
    return {
        **index,
        "modules": {
            path: {
                "summary": summary,
                "symbols": {},
                "docs": {},
                "tests": {},
                "dependencies": [],
                "dependents": [],
                "imports": [],
                "parsed": True,
            }
            for path, summary in sorted(summaries.items())
        },
        "tools": sorted(
            {
                path
                for row in index["navigation"]
                for path in row["paths"]
                if path.startswith(("tools/", ".github/")) and path.endswith((".py", ".yml"))
            }
        ),
        "tests": {},
        "tool_terms": {},
    }


def evaluate(index: dict, cases: list[dict], limit: int) -> dict:
    baseline = map_baseline(index)
    results = []
    for case in cases:
        row = {"task": case["task"], "primary": case["primary"]}
        targets = set(case["primary"])
        for name, corpus in (("router", index), ("baseline", baseline)):
            elapsed = []
            outputs = []
            for _ in range(3):
                start = perf_counter()
                result = context_router.route(corpus, case["task"], limit=limit)
                elapsed.append((perf_counter() - start) * 1000)
                outputs.append(result)
            surfaces = [item["path"] for item in result["sources"]]
            found = targets.intersection(surfaces)
            capsule = repo_context.capsule(
                corpus, result, repo_context.DEFAULT_BUDGET, repo_context.markdown
            )
            row[name] = {
                "surfaces": surfaces,
                "hits": sorted(found),
                "misses": sorted(targets - found),
                "unlabeled": len(surfaces) - len(found),
                "median_route_ms": round(median(elapsed), 2),
                "estimated_capsule_tokens": repo_context.size_units(capsule),
                "repeatable": outputs[0] == outputs[1] == outputs[2],
            }
        results.append(row)
    total = sum(len(row["primary"]) for row in results)
    metrics = {}
    for name in ("router", "baseline"):
        hits = sum(len(row[name]["hits"]) for row in results)
        offered = sum(len(row[name]["surfaces"]) for row in results)
        metrics[name] = {
            "primary_hits": hits,
            "labeled_primary": total,
            "offered": offered,
            "recall": hits / total,
            "labeled_precision": hits / offered if offered else 0,
            "median_route_ms": median(row[name]["median_route_ms"] for row in results),
            "median_estimated_capsule_tokens": median(
                row[name]["estimated_capsule_tokens"] for row in results
            ),
            "repeatable": all(row[name]["repeatable"] for row in results),
        }
    return {"limit": limit, "metrics": metrics, "cases": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--limit", type=int, default=context_router.DEFAULT_RESULTS)
    args = parser.parse_args()
    start = perf_counter()
    index = context_index.build(args.root)
    build_ms = round((perf_counter() - start) * 1000, 2)
    report = evaluate(
        index, json.loads((ROOT / "tests/tools/context_cases.json").read_bytes()), args.limit
    )
    print(
        json.dumps({**report, "identity": index["identity"], "index_build_ms": build_ms}, indent=2)
    )


if __name__ == "__main__":
    main()
