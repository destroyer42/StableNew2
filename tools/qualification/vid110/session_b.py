"""Lane B session: Wan2.1 VACE-1.3B reference-image + prompt (no control video available).

The motion-transfer comparison needs an owned human driving clip and stays on HOLD
until one exists; this session only measures VACE's prompt-directed reference-to-video
behaviour and footprint on the shared source still.
"""

from __future__ import annotations

import json
import sys

from tools.qualification.vid110.comfy_client import ComfyClient
from tools.qualification.vid110.owned_comfy import OwnedComfy
from tools.qualification.vid110.run import REPORTS, run_generation
from tools.qualification.vid110.session_a import DIRECTED_PROMPTS, HEIGHT, WIDTH
from tools.qualification.vid110.workflows import LANE_B_FILES, GenerationSpec, build_lane_b


def main() -> int:
    source = REPORTS / "inputs" / "source_fullbody.png"
    if not source.exists():
        print("source still missing; run session_a first")
        return 2
    summary: dict[str, dict] = {}
    with OwnedComfy(REPORTS / "comfy_owned") as comfy:
        uploaded = ComfyClient(comfy.base_url).upload_image(source)
        for tag, prompt in DIRECTED_PROMPTS.items():
            spec = GenerationSpec(
                prompt=prompt, width=WIDTH, height=HEIGHT, length=49, steps=25, cfg=6.0, seed=12345
            )
            record = run_generation(
                candidate="wan2.1-vace-1.3b",
                lane=f"ref2v_{tag}",
                graph=build_lane_b(spec, uploaded, None, prefix=f"vid110/vace_{tag}"),
                files=LANE_B_FILES,
                inputs={"reference_image": str(source), "control_video": None, "prompt": prompt},
                settings=dict(spec.__dict__),
                source_image=source,
                timeout=1800,
                out_dir=REPORTS / "runs",
                comfy_url=comfy.base_url,
            )
            record.write(REPORTS / "runs")
            summary[tag] = {
                "completed": record.completed,
                "failure": record.failure[:400],
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
