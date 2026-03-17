from __future__ import annotations

import json
from pathlib import Path

from src.video.svd_config import SVDConfig
from src.video.svd_registry import build_svd_history_record, write_svd_run_manifest


class _FakePreprocess:
    def __init__(self, root: Path) -> None:
        self.source_path = root / "source.png"
        self.prepared_path = root / "_svd_temp" / "prepared.png"
        self.original_width = 768
        self.original_height = 1280
        self.target_width = 1024
        self.target_height = 576
        self.resize_mode = "center_crop"
        self.was_resized = True
        self.was_padded = False
        self.was_cropped = True


class _FakeResult:
    def __init__(self, root: Path, *, output_kind: str = "video") -> None:
        self.source_image_path = root / "source.png"
        self.video_path = root / "clip.mp4" if output_kind == "video" else None
        self.gif_path = root / "clip.gif" if output_kind == "gif" else None
        self.frame_paths = [root / "frames" / "frame_0001.png", root / "frames" / "frame_0002.png"] if output_kind == "frames" else []
        self.thumbnail_path = root / "preview.png"
        self.metadata_path = root / "manifests" / "clip.json"
        self.frame_count = 25
        self.fps = 7
        self.seed = 1234
        self.model_id = "stabilityai/stable-video-diffusion-img2vid-xt"
        self.preprocess = _FakePreprocess(root)
        self.postprocess = {"applied": ["interpolation"], "output_frame_count": 49}


def test_write_svd_run_manifest_includes_canonical_artifact(tmp_path: Path) -> None:
    result = _FakeResult(tmp_path, output_kind="video")
    config = SVDConfig()

    manifest_path = write_svd_run_manifest(run_dir=tmp_path, config=config, result=result)

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["artifact"]["schema"] == "stablenew.artifact.v2.6"
    assert payload["artifact"]["primary_path"] == str(result.video_path)
    assert payload["artifact"]["manifest_path"] == str(manifest_path)
    assert payload["video_paths"] == [str(result.video_path)]
    assert payload["manifest_paths"] == [str(manifest_path)]
    assert payload["count"] == 1


def test_build_svd_history_record_supports_frames_only_outputs(tmp_path: Path) -> None:
    result = _FakeResult(tmp_path, output_kind="frames")
    config = SVDConfig()

    record = build_svd_history_record(config=config, result=result)

    assert record["output_paths"] == [str(path) for path in result.frame_paths]
    assert record["video_paths"] == []
    assert record["gif_paths"] == []
    assert record["manifest_paths"] == [str(result.metadata_path)]
    assert record["count"] == 2
    assert record["artifact"]["primary_path"] == str(result.frame_paths[0])
