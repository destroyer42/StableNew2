"""Physical-path rehearsal: run a journey's *physical* code path against loopback servers this module owns.

The physical journeys must work from a plan and a URL alone, with no fake-backend object handed to the journey.  The
rehearsal proves that deterministically: the loopback servers (and, for video, the runtime-readiness boundary patches)
are owned and entered here, outside the journey; the journey is run with ``simulated=False``, the frozen-plan gate
installed, and no fake object in ``GoldenRun``.  Nothing real is touched: the servers are loopback fakes, the driver is
the semantic Tk driver and the evidence is labelled ``rehearsal`` (never ``physical``).

``python -m tools.operator_journey.golden.rehearsal --journey image|video|learning --evidence-dir DIR [--tamper KEY]``
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from tools.operator_journey.evidence import JourneyEvidence

REHEARSAL = "rehearsal"
TAMPER_KEYS = ("steps", "seed", "width", "height", "frames", "model", "prompt")


def synthetic_target(
    key: str, base_url: str, model_name: str, source: Path | None
) -> dict[str, Any]:
    from tools.operator_journey.golden.frozen import journey_inputs

    runtime = {
        "kind": "comfy" if key == "video" else "forge",
        "ownership": "external",
        "base_url": base_url,
        "identity": "loopback-rehearsal",
    }
    if key == "video":
        return {
            "runtime": runtime,
            "workflow": {"id": "wan22_ti2v_5b_i2v_v1", "version": "1.3.0"},
            "source_assets": [{"path": str(source), "sha256": None}],
            "settings": {"frames": 17, "width": 480, "height": 832, "seed": 7001},
            "inputs": journey_inputs("video"),
            "job_count": 1,
            "expected_artifacts": 1,
        }
    return {
        "runtime": runtime,
        "model": {"name": model_name, "path": "n/a", "sha256": "n/a"},
        "settings": {"width": 1024, "height": 1024, "steps": 6, "seed": 424242}
        if key == "image"
        else {"width": 512, "height": 512, "steps": 8, "seed": 12345},
        "inputs": journey_inputs(key),
        "job_count": 1 if key == "image" else 3,
        "expected_artifacts": 1 if key == "image" else 3,
    }


def _tamper(key: str, target: dict[str, Any], what: str) -> None:
    settings = target["settings"]
    if what in {"steps", "seed", "width", "height", "frames"}:
        settings[what] = int(settings.get(what, 1)) + 1
    elif what == "model":
        target["model"]["name"] = "some-other-model.safetensors"
    elif what == "prompt":
        target["inputs"]["prompt" if key == "image" else "motion_prompt"] = "a different prompt"


def rehearse(key: str, evidence_dir: Path, *, tamper: str | None = None) -> JourneyEvidence:
    from tools.operator_journey.golden.definitions import JOURNEYS
    from tools.operator_journey.golden.fixtures import make_fake_a1111
    from tools.operator_journey.golden.modes import validate_combination
    from tools.operator_journey.golden.session import RunConfig, run_journey_body
    from tools.operator_journey.journeys.learning_lora_strength import DEFAULT_LORA

    validate_combination(
        mode="simulated", driver="tk", plan=None
    )  # refuses CI-hostile combinations early
    journey = JOURNEYS[key]
    fake_a = make_fake_a1111(loras=(DEFAULT_LORA,) if key == "learning" else ())
    fake_a.start()
    fake_c = None
    spec = None
    source = None
    try:
        if key == "video":
            from src.video.workflow_registry import build_default_workflow_registry
            from tools.operator_journey.fake_comfy import FakeComfy
            from tools.operator_journey.golden.vid01 import (
                WORKFLOW_ID,
                WORKFLOW_VERSION,
                make_reference_image,
            )

            spec = build_default_workflow_registry().get(WORKFLOW_ID, WORKFLOW_VERSION)
            fake_c = FakeComfy(spec)
            fake_c.start()
            source = make_reference_image(
                Path(evidence_dir) / "rehearsal_source" / "lighthouse.png"
            )
        from tools.operator_journey.golden.media import sha256_file

        base = fake_c.base_url if fake_c is not None else fake_a.base_url
        target = synthetic_target(key, base, list(fake_a.model_names)[0], source)
        if source is not None:
            target["source_assets"][0]["sha256"] = sha256_file(source)
        # The journey is given the true plan; ``--tamper`` corrupts only the copy the pre-dispatch gate compares with,
        # standing in for a GUI that does not apply the plan faithfully.
        gate_target = copy.deepcopy(target)
        if tamper:
            _tamper(key, gate_target, tamper)
        config = RunConfig(
            driver="tk", evidence_dir=Path(evidence_dir) / "journeys", hide_window=True
        )
        config.extras.update(target=gate_target, journey_key=key)
        if key == "image":
            from tools.operator_journey.golden.img01 import run_img01

            body = lambda run: run_img01(run, simulated=False, physical=target)  # noqa: E731
        elif key == "video":
            from tools.operator_journey.golden.vid01 import run_vid01

            body = lambda run: run_vid01(run, simulated=False, physical=target)  # noqa: E731
        else:
            from tools.operator_journey.golden.lrn01 import run_lrn01

            body = lambda run: run_lrn01(run, simulated=False, physical=target)  # noqa: E731
        boundary = nullcontext({})
        if key == "video":
            from tools.operator_journey.golden.video_fixture import fixture_video_runtime

            boundary = fixture_video_runtime(fake_c, spec)  # entered here, outside the journey
        from tools.operator_journey.golden.fixtures import seed_declared_sdxl

        with boundary:
            return run_journey_body(
                journey.id,
                body,
                config,
                mode_label=REHEARSAL,
                base_url=fake_a.base_url,
                workspace_hook=lambda ws, _a, _c: seed_declared_sdxl(ws, fake_a, None),
                execution_mode=REHEARSAL,
            )
    finally:
        fake_a.stop()
        if fake_c is not None:
            fake_c.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.operator_journey.golden.rehearsal")
    parser.add_argument("--journey", choices=["image", "video", "learning"], required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--tamper", choices=TAMPER_KEYS, default=None)
    args = parser.parse_args(argv)
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence = rehearse(args.journey, args.evidence_dir, tamper=args.tamper)
    (args.evidence_dir / "rehearsal_evidence.json").write_text(
        json.dumps(evidence.as_dict(), indent=2, default=str), "utf-8"
    )
    print(f"rehearsal[{args.journey}]: {evidence.verdict}")
    return {"PASS": 0, "FAIL": 1, "HOLD": 2, "NO-GO": 3}[evidence.verdict]


if __name__ == "__main__":
    sys.exit(main())
