"""Lane A session: Wan2.2 TI2V-5B on a qualification-owned stock-nodes Comfy.

1. text-to-video of a neutral full-body still (first frame becomes the shared source);
2. image-to-video runs from that source with directed-action prompts.
Local/GPU-bound; run only with the GPU free and never in CI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2

from tools.qualification.vid110.comfy_client import ComfyClient
from tools.qualification.vid110.metrics import read_frames
from tools.qualification.vid110.owned_comfy import OwnedComfy
from tools.qualification.vid110.run import LANE_A_FILES, REPORTS, run_generation
from tools.qualification.vid110.workflows import GenerationSpec, build_lane_a

SOURCE_PROMPT = (
    "A full-body view of an adult person standing centered in a plain light-gray photo studio, "
    "wearing a fitted dark athletic top, dark leggings and white sneakers, arms relaxed at the "
    "sides, head to toe fully visible, static camera, even natural lighting, realistic."
)
DIRECTED_PROMPTS = {
    "walk_wave": (
        "The person walks steadily toward the camera with natural steps and swinging arms, then "
        "stops and waves the right hand. Static camera, the full body stays in frame, the same "
        "person and clothing throughout."
    ),
    "turn_raise_arms": (
        "The person turns to face left, then raises both arms above the head and lowers them "
        "slowly. Static camera, the full body stays in frame, the same person and clothing "
        "throughout."
    ),
}
WIDTH, HEIGHT = 480, 832


def main() -> int:
    scratch = REPORTS / "comfy_owned"
    runs = REPORTS / "runs"
    inputs = REPORTS / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    source = inputs / "source_fullbody.png"
    with OwnedComfy(scratch) as comfy:
        client = ComfyClient(comfy.base_url)
        summary: dict[str, dict] = {}
        if not source.exists():
            spec = GenerationSpec(
                prompt=SOURCE_PROMPT, width=WIDTH, height=HEIGHT, length=5, seed=110110
            )
            record = run_generation(
                candidate="wan2.2-ti2v-5b",
                lane="source_t2v",
                graph=build_lane_a(spec, None, prefix="vid110/source"),
                files=LANE_A_FILES,
                inputs={"source_image": "t2v", "prompt": SOURCE_PROMPT},
                settings=dict(spec.__dict__),
                source_image=None,
                timeout=1500,
                out_dir=runs,
                comfy_url=comfy.base_url,
            )
            record.write(runs)
            summary["source_t2v"] = {"completed": record.completed, "failure": record.failure[:300]}
            if not record.completed:
                print(json.dumps(summary, indent=2))
                return 1
            video = next(Path(o) for o in record.outputs if o.endswith((".mp4", ".webm")))
            frames, _ = read_frames(video)
            cv2.imwrite(str(source), frames[0])
        uploaded = client.upload_image(source)
        for tag, prompt in DIRECTED_PROMPTS.items():
            spec = GenerationSpec(
                prompt=prompt, width=WIDTH, height=HEIGHT, length=49, seed=12345, steps=20
            )
            record = run_generation(
                candidate="wan2.2-ti2v-5b",
                lane=f"i2v_{tag}",
                graph=build_lane_a(spec, uploaded, prefix=f"vid110/{tag}"),
                files=LANE_A_FILES,
                inputs={"source_image": str(source), "prompt": prompt},
                settings=dict(spec.__dict__),
                source_image=source,
                timeout=1800,
                out_dir=runs,
                comfy_url=comfy.base_url,
            )
            record.write(runs)
            summary[tag] = {
                "completed": record.completed,
                "failure": record.failure[:300],
                "wall_s": record.wall_seconds,
                "peaks": record.peaks,
                "metrics": record.metrics,
            }
            if not record.completed:
                break
    print(json.dumps(summary, indent=2))
    return 0 if all(v["completed"] for v in summary.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
