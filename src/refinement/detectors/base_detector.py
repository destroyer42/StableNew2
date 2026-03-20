from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class SubjectDetector(ABC):
    detector_id: str = "unknown"

    @abstractmethod
    def detect_faces(self, image_path: Path | None) -> tuple[dict[str, Any], ...]:
        raise NotImplementedError
