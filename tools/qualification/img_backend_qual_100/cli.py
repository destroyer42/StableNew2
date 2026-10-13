"""Offline qualification packet; no server calls, process actions or generation route."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .capability import capability_matrix, matrix_summary, validate_evidence
from .comfy_graphs import build_graph, graph_digest, scan_source_node_ids, validate_graph_classes
from .inventory import (
    comfy_identity,
    comfy_search_roots,
    forge_identity,
    model_visibility,
    parse_extra_model_paths,
)
from .protocol import build_protocol, validate_protocol
from .spec import REPO_ROOT, build_workloads, spec_digest


def build_packet(
    *,
    repo_root: Path = REPO_ROOT,
    comfy_install: Path | None = None,
    forge_install: Path | None = None,
    extra_paths: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Produce proposed graphs, citations and inventory; missing live evidence remains unverified."""
    workloads = build_workloads(
        sdxl_intent_path=repo_root / "tests/data/contracts/img_forge_100_frozen_intent.json"
    )
    matrix = capability_matrix()
    comfy_source = comfy_install / "source" if comfy_install else None
    forge_source = forge_install / "source" if forge_install else None
    extra: dict[str, list[Path]] = {}
    for file in extra_paths:
        for folder, paths in parse_extra_model_paths(file).items():
            extra.setdefault(folder, []).extend(paths)
    roots = comfy_search_roots(comfy_source, extra) if comfy_source else {}
    node_ids = scan_source_node_ids(comfy_source) if comfy_source else None
    cases: dict[str, dict[str, Any]] = {}
    filenames = {}
    # Inventory selects no model: only one unambiguous file may bind an API relative name.
    for key, workload in workloads.items():
        graph = build_graph(workload)
        inventory = model_visibility(graph, roots)
        for model in inventory:
            if len(model["matches"]) == 1:
                path = Path(model["matches"][0])
                for base in roots.get(model["folder"], ()):
                    if path.is_relative_to(base):
                        filenames[model["name"]] = path.relative_to(base).as_posix()
                        break
        cases[key] = {"workload": workload.identity(), "model_inventory": inventory}
    for key, workload in workloads.items():
        graph = build_graph(workload, filenames=filenames)
        cases[key].update(
            {
                "graph": graph,
                "graph_sha256": graph_digest(graph),
                "class_problems": validate_graph_classes(graph, node_ids)
                if node_ids is not None
                else None,
                "live_schema_validation": "UNVERIFIED",
            }
        )
    manifest = json.loads(
        (repo_root / "config/managed_comfy_runtime.json").read_text(encoding="utf-8")
    )
    protocol = build_protocol(
        workloads, filenames=filenames, comfy_revision=manifest["upstream"]["revision"]
    )
    validate_protocol(protocol)
    return {
        "package": "PR-IMG-BACKEND-QUAL-100",
        "phase": "offline",
        "physical_generation_performed": False,
        "architecture_outcome": "CONDITIONAL",
        "quality_performance_outcome": "INCONCLUSIVE",
        "physical_readiness": "UNVERIFIED; separate authorization and recent-fault clearance required",
        "spec_digest": spec_digest(workloads),
        "workloads": cases,
        "proposed_protocol": protocol,
        "capabilities": [asdict(row) for row in matrix],
        "matrix_summary": matrix_summary(matrix),
        "citations": validate_evidence(
            matrix, repo_root=repo_root, comfy_source=comfy_source, forge_source=forge_source
        ),
        "comfy_identity": comfy_identity(
            repo_root / "config/managed_comfy_runtime.json", comfy_install
        )
        if comfy_install
        else None,
        "forge_identity": forge_identity(
            repo_root / "config/managed_forge_runtime.json", forge_install
        )
        if forge_install
        else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--comfy-install", type=Path)
    parser.add_argument("--forge-install", type=Path)
    parser.add_argument("--extra-paths", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    packet = build_packet(
        repo_root=args.repo_root,
        comfy_install=args.comfy_install,
        forge_install=args.forge_install,
        extra_paths=tuple(args.extra_paths),
    )
    print(json.dumps(packet, indent=2, sort_keys=True))
    return 1 if packet["citations"]["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
