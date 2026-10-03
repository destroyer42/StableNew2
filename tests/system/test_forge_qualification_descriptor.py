"""PR-IMG-FORGE-100: the Forge qualification descriptor stays evidence-oriented and pinned."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.image_backends import DEFAULT_IMAGE_BACKEND_ID, FORGE_IMAGE_BACKEND_ID

DESCRIPTOR = Path(__file__).resolve().parents[2] / "config" / "forge_qualification_runtime.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _load() -> dict:
    return json.loads(DESCRIPTOR.read_text(encoding="utf-8"))


def test_descriptor_pins_backend_identity_and_keeps_a1111_the_default() -> None:
    data = _load()
    assert data["backend_id"] == FORGE_IMAGE_BACKEND_ID == "forge_webui"
    assert data["default_image_backend_id"] == DEFAULT_IMAGE_BACKEND_ID == "a1111_webui"
    assert data["backend_policy"]["historical_records_without_image_backend"].startswith(
        "resolve to a1111_webui"
    )


def test_source_and_extension_are_frozen_to_exact_commits() -> None:
    data = _load()
    assert data["source"]["repository"].endswith("/Haoming02/sd-webui-forge-classic")
    assert data["source"]["branch"] == "neo"
    assert SHA40.match(data["source"]["commit"])
    assert SHA40.match(data["adetailer"]["commit"])
    assert data["adetailer"]["repository"].endswith("/Haoming02/ADetailer-Neo")
    assert data["adetailer"]["commit"] == "af228eba7a3f3691a25bcd1fc94aa95e600dd3e6"
    assert data["adetailer"]["rejected_candidate"]["commit"] == "3a599f5d4607d8f9d8b9fc5a15526197418dae1a"
    assert data["adetailer"]["required_detectors"] == ["face_yolov8n.pt", "hand_yolov8n.pt"]
    assert data["adetailer"]["mediapipe_substitution"].startswith("forbidden")


def test_launch_contract_is_the_three_frozen_flags_on_a_non_discoverable_port() -> None:
    launch = _load()["launch"]
    flags = launch["frozen_flags"]
    assert flags[0] == "--api" and "--forge-ref-a1111-home" in flags and "--port" in flags
    assert not set(flags) & set(launch["forbidden_tuning_flags"])
    # StableNew's WebUI discovery scans 7860-7869; the qualification endpoint must sit outside.
    assert not 7860 <= launch["qualification_port"] <= 7869
    # The owner approved the download-free deviation for isolated install/read-only preflight.
    assert launch["extension_safety_flags_pending_owner_approval"] == []
    assert launch["extension_safety_flags_owner_approved"] == ["--ad-no-huggingface"]
    assert "--ad-no-huggingface" not in flags


def test_descriptor_records_no_verdict_before_the_authorized_physical_run() -> None:
    data = _load()
    assert data["classification"] is None
    assert "NOT_AUTHORIZED" in data["qualification_status"]
    assert data["isolation"]["a1111_installation_mutation"] == "forbidden"
    assert data["dependency_install"]["model_downloads"].startswith("NOT authorized")


def test_yolo_only_profile_keeps_mediapipe_outside_qualification() -> None:
    data = _load()
    profile = data["adetailer"]["qualification_profile"]
    assert profile["yolo_face"].startswith("REQUIRED / QUALIFY")
    assert profile["yolo_hands"].startswith("REQUIRED / QUALIFY")
    for mode in ("mediapipe_face", "mediapipe_mesh", "mediapipe_eyes"):
        assert profile[mode] == "NOT QUALIFIED"
    assert "--skip-install" in data["launch"]["qualification_runtime_flags_owner_approved"]
    assert data["launch"]["skip_install_scope"].startswith("Qualification only")
