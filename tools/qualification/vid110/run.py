"""Qualification CLI: inventory, lane runs and evidence capture (local-only, GPU-bound)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from tools.qualification.vid110 import evidence as ev
from tools.qualification.vid110.comfy_client import ComfyClient, ComfyRunError
from tools.qualification.vid110.inventory import build_inventory, missing_prerequisites
from tools.qualification.vid110.metrics import clip_metrics, contact_sheet
from tools.qualification.vid110.monitor import LOW_RAM_GB, ResourceSampler
from tools.qualification.vid110.workflows import (
    LANE_A_FILES,
    GenerationSpec,
    build_lane_a,
    validate_graph,
)

REPORTS = Path("reports/vid110")
COMFY_URL = "http://127.0.0.1:8000"
MODELS_DIR = Path("E:/Users/rober/ComfyUI/models")
SUSTAINED_LOW_RAM_SAMPLES = 60  # ~30 s at 0.5 s: abort our own prompt before the machine thrashes


def _model_manifest() -> dict[str, dict[str, str]]:
    path = REPORTS / "model_manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def run_generation(
    *,
    candidate: str,
    lane: str,
    graph: dict[str, Any],
    files: dict[str, list[str]],
    inputs: dict[str, Any],
    settings: dict[str, Any],
    source_image: Path | None,
    timeout: float,
    out_dir: Path,
    shared_gpu: bool = False,
    comfy_url: str = COMFY_URL,
) -> ev.RunEvidence:
    """Queue one graph on the external Comfy, sample resources, capture the output."""

    problems = validate_graph(graph)
    if problems:
        raise ValueError("; ".join(problems))
    inventory = build_inventory(comfy_url, MODELS_DIR)
    unmet = missing_prerequisites(inventory, required_files=files)
    manifest = _model_manifest()
    record = ev.RunEvidence(
        candidate=candidate,
        lane=lane,
        evidence_class="stock-comfy",
        shared_gpu=shared_gpu,
        model_files={n: manifest.get(n, {}) for names in files.values() for n in names},
        dependencies=[f"ComfyUI {inventory['comfy'].get('comfyui_version')} (stock nodes only)"],
        inputs=inputs,
        settings=settings,
        gpu_total_mib=int(inventory["gpu"].get("vram_total_mib", 12282)),
    )
    if unmet:
        record.failure = "; ".join(unmet)
        return record
    client = ComfyClient(comfy_url)
    started = time.monotonic()
    with ResourceSampler(log_path=out_dir / f"{candidate}_{lane}_telemetry.csv") as sampler:
        try:
            prompt_id = client.queue(graph)
            entry = client.wait(
                prompt_id,
                timeout=timeout,
                abort_reason=lambda: (
                    f"system RAM stayed below {LOW_RAM_GB} GB for {sampler.peaks.low_ram_samples} samples"
                    if sampler.peaks.low_ram_samples >= SUSTAINED_LOW_RAM_SAMPLES
                    else ""
                ),
            )
            record.completed = True
        except ComfyRunError as exc:
            record.failure = str(exc)[:1500]
            entry = None
    record.wall_seconds = round(time.monotonic() - started, 1)
    record.peaks = sampler.peaks.as_dict()
    if entry is not None:
        for descriptor in client.output_files(entry):
            if descriptor["filename"].lower().endswith((".mp4", ".webm", ".gif")):
                target = client.download(
                    descriptor, out_dir / f"{candidate}_{lane}{Path(descriptor['filename']).suffix}"
                )
                record.outputs.append(str(target))
                record.metrics = clip_metrics(target, source_image=source_image).as_dict()
                sheet = contact_sheet(target, out_dir / f"{candidate}_{lane}_sheet.png")
                record.outputs.append(str(sheet))
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.qualification.vid110.run")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory")
    a = sub.add_parser("lane-a")
    a.add_argument(
        "--source",
        type=Path,
        default=None,
        help="owned source image (omit for a neutral T2V still)",
    )
    a.add_argument("--prompt", required=True)
    a.add_argument("--tag", default="laneA")
    a.add_argument("--width", type=int, default=480)
    a.add_argument("--height", type=int, default=832)
    a.add_argument("--length", type=int, default=49)
    a.add_argument("--steps", type=int, default=20)
    a.add_argument("--seed", type=int, default=12345)
    a.add_argument("--sampler", default="uni_pc")
    a.add_argument("--timeout", type=float, default=1500)
    args = parser.parse_args(argv)
    REPORTS.mkdir(parents=True, exist_ok=True)
    if args.command == "inventory":
        print(json.dumps(build_inventory(COMFY_URL, MODELS_DIR), indent=2, sort_keys=True))
        return 0
    spec = GenerationSpec(
        prompt=args.prompt,
        width=args.width,
        height=args.height,
        length=args.length,
        steps=args.steps,
        seed=args.seed,
    )
    name = None
    if args.source is not None:
        name = ComfyClient(COMFY_URL).upload_image(args.source)
    graph = build_lane_a(spec, name, prefix=f"vid110/{args.tag}")
    record = run_generation(
        candidate="wan2.2-ti2v-5b",
        lane=args.tag,
        graph=graph,
        files=LANE_A_FILES,
        inputs={"source_image": str(args.source) if args.source else "t2v", "prompt": args.prompt},
        settings={**spec.__dict__},
        source_image=args.source,
        timeout=args.timeout,
        out_dir=REPORTS / "runs",
    )
    print(record.write(REPORTS / "runs"))
    print(
        json.dumps(
            {
                "completed": record.completed,
                "failure": record.failure,
                "wall_s": record.wall_seconds,
                "peaks": record.peaks,
                "metrics": record.metrics,
            },
            indent=2,
        )
    )
    return 0 if record.completed else 1


if __name__ == "__main__":
    sys.exit(main())
