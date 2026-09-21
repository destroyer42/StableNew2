"""Session D: one bounded VACE run with a pose-skeleton-only control video.

Same source still, prompt, seed, steps and cfg as the stock-Canny run in ``session_c``; only
the control representation changes (a rendered skeleton on black, see ``pose.py``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tools.qualification.vid110.comfy_client import ComfyClient
from tools.qualification.vid110.metrics import curve_correlation, motion_curve
from tools.qualification.vid110.owned_comfy import OwnedComfy
from tools.qualification.vid110.run import REPORTS, run_generation
from tools.qualification.vid110.session_c import HEIGHT, LENGTH, PROMPT, WIDTH
from tools.qualification.vid110.workflows import LANE_B_FILES, GenerationSpec, build_lane_b

LANE = "user_control_pose"


def main(argv: list[str]) -> int:
    strength = float(argv[1]) if len(argv) > 1 else 0.7
    tag = argv[2] if len(argv) > 2 else ""
    inputs = REPORTS / "inputs"
    source, pose, drive = (
        inputs / "source_user.png",
        inputs / "pose_user.mp4",
        inputs / "drive_user.mp4",
    )
    spec = GenerationSpec(
        prompt=PROMPT, width=WIDTH, height=HEIGHT, length=LENGTH, steps=25, cfg=6.0, seed=12345
    )
    lane = LANE + tag
    with OwnedComfy(REPORTS / "comfy_owned") as comfy:
        client = ComfyClient(comfy.base_url)
        graph = build_lane_b(
            spec,
            client.upload_image(source),
            client.upload_image(pose),
            strength=strength,
            control="raw",
            prefix="vid110/user_pose",
        )
        record = run_generation(
            candidate="wan2.1-vace-1.3b",
            lane=lane,
            graph=graph,
            files=LANE_B_FILES,
            inputs={"source_image": str(source), "control_video": str(pose), "prompt": PROMPT},
            settings={**spec.__dict__, "control_strength": strength, "control": "pose-skeleton"},
            source_image=source,
            timeout=2400,
            out_dir=REPORTS / "runs",
            comfy_url=comfy.base_url,
        )
        video = next((Path(o) for o in record.outputs if o.endswith((".mp4", ".webm"))), None)
        if video is not None:
            record.metrics["drive_curve_correlation"] = round(
                curve_correlation(motion_curve(video), motion_curve(drive)), 4
            )
        record.write(REPORTS / "runs")
    print(
        json.dumps(
            {
                "lane": lane,
                "completed": record.completed,
                "failure": record.failure[:400],
                "wall_s": record.wall_seconds,
                "peaks": record.peaks,
                "metrics": record.metrics,
            },
            indent=2,
        )
    )
    return 0 if record.completed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
