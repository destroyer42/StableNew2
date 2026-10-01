"""PR-VID-192 qualification tooling: motion-source corpus contract and the one-variable experiment.

No GPU, Comfy, model or media download.  The corpus tests exercise the contract on tracked
annotations/inventory (never on media), and build real entries only from a tiny synthetic clip made
by ffmpeg when it is installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.acceptance import vid190_queue_recycling_acceptance as harness
from tools.qualification.vid192 import motion_corpus as corpus

VID192 = Path(__file__).resolve().parents[2] / "tools" / "qualification" / "vid192"
ANNOTATIONS = json.loads((VID192 / "corpus_annotations.json").read_text(encoding="utf-8"))["entries"]
INVENTORY = json.loads((VID192 / "corpus_inventory.json").read_text(encoding="utf-8"))
# The frozen PR-VID-184/191 driving clip (docs: sha256 d761eb58...).
FROZEN_DRIVING_SHA_PREFIX = "d761eb58"

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _annotation(**overrides):
    entry = {
        "asset_id": "mot192_test",
        "local_path": "clip.mp4",
        "source": "unit test",
        "license_status": "stablenew_generated",
        "subjects": "single",
        "body_visibility": "full_body",
        "camera_movement": "static",
        "occlusion": "none",
        "motion_tags": ["arm_wave"],
        "motion_intensity": "low",
        "start_pose_notes": "standing",
        "end_pose_notes": "waving",
    }
    entry.update(overrides)
    return entry


# ------------------------------------------------------------------ corpus contract


def test_tracked_annotations_are_complete_valid_and_free_of_absolute_paths() -> None:
    ids = [entry["asset_id"] for entry in ANNOTATIONS]
    assert len(ids) == len(set(ids)) and 6 <= len(ids) <= 10
    for entry in ANNOTATIONS:
        assert corpus.validate_annotation(entry) == [], entry["asset_id"]
        assert not corpus.is_absolute_local(entry["local_path"])
        assert entry["local_path"].startswith(("reports/", corpus.QUAL_PREFIX))
    blob = json.dumps(ANNOTATIONS) + json.dumps(INVENTORY)
    assert "C:\\\\" not in blob and "/Users/" not in blob


def test_third_party_media_is_flagged_and_carries_its_use_scope() -> None:
    flagged = {e["asset_id"] for e in ANNOTATIONS if e["license_status"] in corpus.FLAGGED_LICENSES}
    assert flagged and set(INVENTORY["flagged_licenses"]) == flagged
    for entry in ANNOTATIONS:
        if entry["asset_id"] in flagged:
            note = entry["license_note"].lower()
            assert "internal qualification" in note and "only" in note and "never" in note
            assert entry["local_path"].startswith(corpus.QUAL_PREFIX)  # never inside the repo


def test_inventory_records_every_required_property_for_every_annotation() -> None:
    assert [e["asset_id"] for e in INVENTORY["entries"]] == sorted(e["asset_id"] for e in ANNOTATIONS)
    for entry in INVENTORY["entries"]:
        for field in (*corpus.PROBED_FIELDS, "locator", "subjects", "motion_tags", "start_pose_notes"):
            assert entry.get(field) not in (None, "", []), (entry["asset_id"], field)
        assert len(entry["sha256"]) == 64 and entry["frame_count"] > 0 and entry["fps"] > 0
        assert entry["duration_s"] == pytest.approx(entry["frame_count"] / entry["fps"], abs=0.01)
    frozen = next(e for e in INVENTORY["entries"] if e["asset_id"].endswith("high_knee_39f"))
    assert frozen["sha256"].startswith(FROZEN_DRIVING_SHA_PREFIX)


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        ({"license_status": "mystery"}, "license_status"),
        ({"subjects": "crowd"}, "subjects"),
        ({"motion_tags": []}, "motion_tags"),
        ({"motion_tags": "wave"}, "must be a list"),
        ({"start_pose_notes": ""}, "start_pose_notes"),
        ({"local_path": "C:\\clips\\a.mp4"}, "absolute local path"),
        ({"license_status": "third_party_internal_only"}, "license_note"),
    ],
)
def test_incomplete_or_unsafe_annotations_are_rejected(overrides, fragment) -> None:
    problems = corpus.validate_annotation(_annotation(**overrides))
    assert any(fragment in problem for problem in problems), problems


def test_ffprobe_output_is_parsed_into_the_recorded_properties() -> None:
    payload = json.dumps(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 480,
                    "height": 832,
                    "r_frame_rate": "24/1",
                    "nb_read_frames": "49",
                }
            ]
        }
    )
    assert corpus.parse_ffprobe(payload) == {
        "width": 480,
        "height": 832,
        "fps": 24.0,
        "frame_count": 49,
        "duration_s": 2.042,
    }
    with pytest.raises(corpus.CorpusError, match="frame count unavailable"):
        corpus.parse_ffprobe(json.dumps({"streams": [{"width": 1, "height": 1, "nb_frames": "N/A"}]}))


def test_locators_resolve_only_under_the_repo_or_the_declared_qualification_root(tmp_path) -> None:
    assert corpus.resolve_local_path("reports/a.mp4", qual_root=None, repo_root=tmp_path) == (
        tmp_path / "reports/a.mp4"
    )
    assert corpus.resolve_local_path("$QUAL/x/a.mp4", qual_root=tmp_path / "q") == (
        tmp_path / "q" / "x/a.mp4"
    )
    with pytest.raises(corpus.CorpusError, match="needs --qual-root"):
        corpus.resolve_local_path("$QUAL/x/a.mp4", qual_root=None)
    with pytest.raises(corpus.CorpusError, match="absolute"):
        corpus.resolve_local_path("C:\\a.mp4", qual_root=None)


@pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg/ffprobe not installed")
def test_a_real_clip_is_probed_hashed_and_third_party_media_inside_the_repo_is_refused(tmp_path) -> None:
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "testsrc=size=64x96:rate=8", "-frames:v", "8", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )  # fmt: skip
    entry = corpus.build_entry(_annotation(), qual_root=None, repo_root=tmp_path)
    assert (entry["width"], entry["height"], entry["frame_count"]) == (64, 96, 8)
    assert entry["fps"] == 8.0 and len(entry["sha256"]) == 64 and "local_path" not in entry

    with pytest.raises(corpus.CorpusError, match="must live outside the repository"):
        corpus.build_entry(
            _annotation(license_status="third_party_internal_only", license_note="internal only"),
            qual_root=None,
            repo_root=tmp_path,
        )
    with pytest.raises(corpus.CorpusError, match="duplicate asset ids"):
        corpus.build_inventory([_annotation(), _annotation()], qual_root=None, repo_root=tmp_path)


# ------------------------------------------------------------------ experiment suite


def _arms():
    return {job[0]: job for job in harness.SUITES["animate2_controls"]}


def test_experiment_is_one_variable_per_arm_over_a_frozen_reference_setup() -> None:
    arms = _arms()
    assert list(arms) == ["A0", "A1", "A2", "A3"]
    # (workflow_id, frames, seed, appearance prompt, driving video) are identical in every arm
    assert len({job[1:2] + job[3:7] for job in arms.values()}) == 1
    a0, a1, a2, a3 = (arms[label] for label in ("A0", "A1", "A2", "A3"))
    assert a0[2] == "1.0.0" and a0[7] is None  # the PR-VID-191 baseline: no controls, old graph
    assert {a1[2], a2[2], a3[2]} == {"1.1.0"}
    motion = harness._MOTION_PROMPT_QUALIFIED
    assert a1[7] == {"pose_prompt": motion}  # only the Motion Prompt differs from the baseline
    assert a2[7] == {**a1[7], "pose_strength": "1.5"}  # A1 + exactly one bounded change
    assert a3[7] == {**a1[7], "reference_image_strength": "1.3"}  # A1 + exactly one change
    assert a1[7] != a2[7] != a3[7]


def test_experiment_uses_the_qualified_motion_prompt_and_no_committed_machine_paths() -> None:
    assert "high-knee running drill" in harness._MOTION_PROMPT_QUALIFIED
    source = Path(harness.__file__).read_text(encoding="utf-8")
    assert "C:\\Users" not in source


def test_every_experiment_arm_is_admissible_and_freezes_its_controls(tmp_path) -> None:
    from PIL import Image

    clip = tmp_path / "driving.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42 fake")
    reference = tmp_path / "reference.png"
    Image.new("RGB", (48, 80), "navy").save(reference)
    submitted: list = []
    stack = SimpleNamespace(
        service=SimpleNamespace(submit_njrs=lambda records, _policy: submitted.extend(records) or "j")
    )
    for job in harness.SUITES["animate2_controls"]:
        job = job[:6] + (str(clip),) + job[7:]
        harness._submit(stack, reference, tmp_path, job)
    extras = {
        job[0]: record.stage_chain[0].to_dict()["extra"]
        for job, record in zip(harness.SUITES["animate2_controls"], submitted, strict=True)
    }
    assert "operator_controls" not in extras["A0"] and extras["A0"]["workflow_version"] == "1.0.0"
    frozen = {label: extras[label]["operator_controls"] for label in ("A1", "A2", "A3")}
    assert frozen["A1"]["pose_strength"] == frozen["A3"]["pose_strength"] == 1.0
    assert frozen["A2"]["pose_strength"] == 1.5 and frozen["A2"]["reference_image_strength"] == 1.0
    assert frozen["A3"]["reference_image_strength"] == 1.3
    assert {e["seed"] for e in extras.values()} == {19103}
