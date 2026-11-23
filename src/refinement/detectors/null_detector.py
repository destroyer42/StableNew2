"""Provide a subject detector that always reports no face detections."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base_detector import SubjectDetector


class NullDetector(SubjectDetector):
    detector_id = "null"

    def detect_faces(self, image_path: Path | None) -> tuple[dict[str, Any], ...]:
        return ()
