from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.video.motion.secondary_motion_worker import run_secondary_motion_worker


def test_secondary_motion_worker_round_trip(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    for index in range(3):
        Image.new("RGBA", (10, 10), (255, index * 20, 0, 255)).save(input_dir / f"frame_{index:04d}.png")

    result = run_secondary_motion_worker(
        {
            "input_dir": str(input_dir),
            "output_dir": str(output_dir),
            "seed": 1234,
            "intent": {
                "enabled": True,
                "mode": "apply",
                "intent": "micro_sway",
                "regions": ["fabric"],
            },
            "policy": {
                "policy_id": "worker_apply_v1",
                "enabled": True,
                "backend_mode": "apply_shared_postprocess_candidate",
                "intensity": 0.4,
                "damping": 0.9,
                "frequency_hz": 0.3,
                "cap_pixels": 4,
            },
        }
    )

    assert result["status"] == "applied"
    assert result["application_path"] == "frame_directory_worker"
    assert result["frames_in"] == 3
    assert result["frames_out"] == 3
    assert len(result["output_paths"]) == 3
    assert all(Path(path).exists() for path in result["output_paths"])
