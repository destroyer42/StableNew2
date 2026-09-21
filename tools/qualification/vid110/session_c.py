"""Lane B/A session on operator-supplied media: a source photo and a driving clip.

Both files are only *read*; working copies are written to ``reports/vid110/inputs``
(git-ignored).  Runs Wan2.1 VACE-1.3B with the driving clip as a Canny control video
(stock nodes) and Wan2.2 TI2V-5B prompt-only on the same source.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageOps

from tools.qualification.vid110.comfy_client import ComfyClient
from tools.qualification.vid110.metrics import curve_correlation, motion_curve
from tools.qualification.vid110.owned_comfy import OwnedComfy
from tools.qualification.vid110.run import REPORTS, run_generation
from tools.qualification.vid110.workflows import (
    LANE_A_FILES,
    LANE_B_FILES,
    GenerationSpec,
    build_lane_a,
    build_lane_b,
)

WIDTH, HEIGHT, LENGTH, FPS = 480, 832, 49, 24
PROMPT = (
    "The child bends at the hips and knees, grips a barbell on the ground with both hands, and "
    "lifts it while standing up straight. Static camera, the same child and clothing throughout."
)


def prepare_source(photo: Path, target: Path) -> Path:
    """EXIF-upright, centre-crop to 9:16 (sides only for a 3:4 portrait), resize."""

    image = ImageOps.exif_transpose(Image.open(photo)).convert("RGB")
    width, height = image.size
    want = WIDTH / HEIGHT
    if width / height > want:
        new_width = int(height * want)
        left = (width - new_width) // 2
        image = image.crop((left, 0, left + new_width, height))
    else:
        new_height = int(width / want)
        top = (height - new_height) // 2
        image = image.crop((0, top, width, top + new_height))
    target.parent.mkdir(parents=True, exist_ok=True)
    image.resize((WIDTH, HEIGHT), Image.LANCZOS).save(target)
    return target


def prepare_drive(clip: Path, target: Path, *, start_s: float) -> Path:
    """A 49-frame, 24 fps, 480x832 working copy of one lift (original untouched)."""

    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603 - fixed argv, operator-supplied local file
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-ss",
            str(start_s),
            "-i",
            str(clip),
            "-vf",
            f"fps={FPS},scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT}",
            "-frames:v",
            str(LENGTH),
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ],
        check=True,
    )
    return target


def main(argv: list[str]) -> int:
    photo, clip = Path(argv[1]), Path(argv[2])
    start_s = float(argv[3]) if len(argv) > 3 else 5.2
    inputs = REPORTS / "inputs"
    source = prepare_source(photo, inputs / "source_user.png")
    drive = prepare_drive(clip, inputs / "drive_user.mp4", start_s=start_s)
    drive_curve = motion_curve(drive)
    summary: dict[str, dict] = {}
    with OwnedComfy(REPORTS / "comfy_owned") as comfy:
        client = ComfyClient(comfy.base_url)
        image_name = client.upload_image(source)
        video_name = client.upload_image(drive)
        spec_a = GenerationSpec(
            prompt=PROMPT, width=WIDTH, height=HEIGHT, length=LENGTH, seed=12345
        )
        spec_b = GenerationSpec(
            prompt=PROMPT, width=WIDTH, height=HEIGHT, length=LENGTH, steps=25, cfg=6.0, seed=12345
        )
        jobs = (
            (
                "wan2.2-ti2v-5b",
                "user_i2v_prompt",
                build_lane_a(spec_a, image_name, prefix="vid110/user_a"),
                LANE_A_FILES,
                spec_a,
                None,
            ),
            (
                "wan2.1-vace-1.3b",
                "user_control_canny",
                build_lane_b(spec_b, image_name, video_name, prefix="vid110/user_b"),
                LANE_B_FILES,
                spec_b,
                str(drive),
            ),
        )
        for candidate, lane, graph, files, spec, control in jobs:
            record = run_generation(
                candidate=candidate,
                lane=lane,
                graph=graph,
                files=files,
                inputs={"source_image": str(source), "control_video": control, "prompt": PROMPT},
                settings=dict(spec.__dict__),
                source_image=source,
                timeout=2400,
                out_dir=REPORTS / "runs",
                comfy_url=comfy.base_url,
            )
            video = next((Path(o) for o in record.outputs if o.endswith((".mp4", ".webm"))), None)
            if video is not None:
                record.metrics["drive_curve_correlation"] = round(
                    curve_correlation(motion_curve(video), drive_curve), 4
                )
            record.write(REPORTS / "runs")
            summary[lane] = {
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
    sys.exit(main(sys.argv))
