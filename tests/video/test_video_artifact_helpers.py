"""Unit tests for src.video.video_artifact_helpers (PR-VIDEO-215)."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.video.video_artifact_helpers import (
    build_video_artifact_bundle,
    bundle_from_execution_result,
    extract_primary_video_path,
    extract_source_image_for_handoff,
    extract_video_frame_paths,
)


class TestBuildVideoArtifactBundle:
    def test_all_canonical_keys_present(self) -> None:
        bundle = build_video_artifact_bundle(
            stage="video_workflow",
            backend_id="comfy",
            primary_path="/out/clip.mp4",
            output_paths=["/out/clip.mp4"],
            video_paths=["/out/clip.mp4"],
            gif_paths=[],
            frame_paths=["/out/frame_001.png"],
            manifest_path="/out/manifests/clip.json",
            thumbnail_path="/out/frame_001.png",
            source_image_path="/in/start.png",
        )
        assert bundle["stage"] == "video_workflow"
        assert bundle["backend_id"] == "comfy"
        assert bundle["artifact_type"] == "video"
        assert bundle["primary_path"] == "/out/clip.mp4"
        assert "/out/clip.mp4" in bundle["output_paths"]
        assert "/out/clip.mp4" in bundle["video_paths"]
        assert bundle["gif_paths"] == []
        assert "/out/frame_001.png" in bundle["frame_paths"]
        assert bundle["manifest_path"] == "/out/manifests/clip.json"
        assert "/out/manifests/clip.json" in bundle["manifest_paths"]
        assert bundle["thumbnail_path"] == "/out/frame_001.png"
        assert bundle["source_image_path"] == "/in/start.png"
        assert bundle["count"] == 1

    def test_manifest_path_deduped_when_also_in_manifest_paths(self) -> None:
        bundle = build_video_artifact_bundle(
            stage="video_workflow",
            backend_id="comfy",
            primary_path="/out/clip.mp4",
            output_paths=[],
            manifest_path="/out/manifests/clip.json",
            manifest_paths=["/out/manifests/clip.json"],
        )
        assert bundle["manifest_paths"].count("/out/manifests/clip.json") == 1

    def test_manifest_path_prepended_if_not_in_manifest_paths(self) -> None:
        bundle = build_video_artifact_bundle(
            stage="video_workflow",
            backend_id="comfy",
            primary_path=None,
            output_paths=[],
            manifest_path="/out/manifests/clip.json",
            manifest_paths=["/out/manifests/other.json"],
        )
        assert bundle["manifest_paths"][0] == "/out/manifests/clip.json"

    def test_count_falls_back_to_video_paths(self) -> None:
        bundle = build_video_artifact_bundle(
            stage="video_workflow",
            backend_id="comfy",
            primary_path=None,
            output_paths=[],
            video_paths=["/out/a.mp4", "/out/b.mp4"],
        )
        assert bundle["count"] == 2

    def test_none_primary_path_stored_as_none(self) -> None:
        bundle = build_video_artifact_bundle(
            stage="video_workflow",
            backend_id="comfy",
            primary_path=None,
            output_paths=[],
        )
        assert bundle["primary_path"] is None

    def test_empty_bundle_has_correct_defaults(self) -> None:
        bundle = build_video_artifact_bundle(
            stage="video_workflow",
            backend_id="comfy",
            primary_path=None,
            output_paths=[],
        )
        assert bundle["video_paths"] == []
        assert bundle["gif_paths"] == []
        assert bundle["frame_paths"] == []
        assert bundle["manifest_paths"] == []
        assert bundle["thumbnail_path"] is None
        assert bundle["source_image_path"] is None
        assert bundle["count"] == 0
        assert bundle["artifacts"] == []

    def test_artifact_records_stored(self) -> None:
        artifact = {"schema": "stablenew.artifact.v2.6", "primary_path": "/out/clip.mp4"}
        bundle = build_video_artifact_bundle(
            stage="video_workflow",
            backend_id="comfy",
            primary_path="/out/clip.mp4",
            output_paths=["/out/clip.mp4"],
            artifact_records=[artifact],
        )
        assert len(bundle["artifacts"]) == 1
        assert bundle["artifacts"][0]["primary_path"] == "/out/clip.mp4"

    def test_filters_falsy_paths(self) -> None:
        bundle = build_video_artifact_bundle(
            stage="video_workflow",
            backend_id="comfy",
            primary_path=None,
            output_paths=["", "/out/clip.mp4", None],  # type: ignore[list-item]
            video_paths=["", "/out/clip.mp4"],
        )
        assert "" not in bundle["output_paths"]
        assert "" not in bundle["video_paths"]
        assert len(bundle["output_paths"]) == 1
        assert len(bundle["video_paths"]) == 1


class TestBundleFromExecutionResult:
    def _make_result(
        self,
        *,
        primary_path: str = "/out/clip.mp4",
        output_paths: list[str] | None = None,
        frame_paths: list[str] | None = None,
        manifest_path: str | None = "/out/manifests/clip.json",
        thumbnail_path: str | None = "/out/frame_001.png",
        artifact: dict | None = None,
        stage_name: str = "video_workflow",
        backend_id: str = "comfy",
        video_paths: list[str] | None = None,
        gif_paths: list[str] | None = None,
        source_image_path: str | None = "/in/start.png",
    ):
        mock = MagicMock()
        mock.primary_path = primary_path
        mock.output_paths = output_paths or [primary_path]
        mock.frame_paths = frame_paths or []
        mock.manifest_path = manifest_path
        mock.thumbnail_path = thumbnail_path
        mock.artifact = artifact or {}
        mock.stage_name = stage_name
        mock.backend_id = backend_id
        mock.to_variant_payload.return_value = {
            "video_paths": video_paths or [primary_path],
            "gif_paths": gif_paths or [],
            "source_image_path": source_image_path,
        }
        return mock

    def test_produces_valid_bundle(self) -> None:
        result = self._make_result()
        bundle = bundle_from_execution_result(result)
        assert bundle["stage"] == "video_workflow"
        assert bundle["backend_id"] == "comfy"
        assert bundle["primary_path"] == "/out/clip.mp4"
        assert bundle["thumbnail_path"] == "/out/frame_001.png"
        assert bundle["source_image_path"] == "/in/start.png"

    def test_artifact_records_extracted(self) -> None:
        artifact = {"schema": "stablenew.artifact.v2.6", "primary_path": "/out/clip.mp4"}
        result = self._make_result(artifact=artifact)
        bundle = bundle_from_execution_result(result)
        assert len(bundle["artifacts"]) == 1

    def test_no_artifact_gives_empty_records(self) -> None:
        result = self._make_result(artifact=None)
        result.artifact = None
        bundle = bundle_from_execution_result(result)
        assert bundle["artifacts"] == []


class TestExtractPrimaryVideoPath:
    def test_returns_primary_path(self) -> None:
        bundle = {"primary_path": "/out/clip.mp4"}
        assert extract_primary_video_path(bundle) == "/out/clip.mp4"

    def test_falls_back_to_video_paths(self) -> None:
        bundle = {"primary_path": None, "video_paths": ["/out/a.mp4"]}
        assert extract_primary_video_path(bundle) == "/out/a.mp4"

    def test_falls_back_through_chain(self) -> None:
        bundle = {"primary_path": None, "video_paths": [], "gif_paths": ["/out/a.gif"]}
        assert extract_primary_video_path(bundle) == "/out/a.gif"

    def test_returns_none_for_empty_bundle(self) -> None:
        assert extract_primary_video_path({}) is None


class TestExtractVideoFramePaths:
    def test_returns_frame_paths(self) -> None:
        bundle = {"frame_paths": ["/out/f001.png", "/out/f002.png"]}
        assert extract_video_frame_paths(bundle) == ["/out/f001.png", "/out/f002.png"]

    def test_returns_empty_when_no_frames(self) -> None:
        assert extract_video_frame_paths({}) == []

    def test_filters_falsy_entries(self) -> None:
        bundle = {"frame_paths": ["", "/out/f001.png", None]}
        result = extract_video_frame_paths(bundle)
        assert "" not in result
        assert "/out/f001.png" in result


class TestExtractSourceImageForHandoff:
    def test_prefers_thumbnail(self) -> None:
        bundle = {
            "thumbnail_path": "/out/frame_001.png",
            "source_image_path": "/in/start.png",
        }
        assert extract_source_image_for_handoff(bundle) == "/out/frame_001.png"

    def test_falls_back_to_source_image(self) -> None:
        bundle = {"thumbnail_path": None, "source_image_path": "/in/start.png"}
        assert extract_source_image_for_handoff(bundle) == "/in/start.png"

    def test_falls_back_to_first_frame(self) -> None:
        bundle = {
            "thumbnail_path": None,
            "source_image_path": None,
            "frame_paths": ["/out/f001.png"],
        }
        assert extract_source_image_for_handoff(bundle) == "/out/f001.png"

    def test_returns_none_for_empty(self) -> None:
        assert extract_source_image_for_handoff({}) is None
