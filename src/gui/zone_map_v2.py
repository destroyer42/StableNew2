from __future__ import annotations

from collections.abc import Iterable
from typing import Any

ZONE_MAP: dict[str, Any] = {
    "root": {
        "grid": {
            "rows": [
                {"index": 0, "weight": 0, "minsize": 48},
                {"index": 1, "weight": 1, "minsize": 400},
                {"index": 2, "weight": 0, "minsize": 60},
            ],
            "columns": [
                {"index": 0, "weight": 0, "minsize": 260},
                {"index": 1, "weight": 1, "minsize": 560},
                {"index": 2, "weight": 0, "minsize": 360},
            ],
        },
        "zones": {
            "header": {"row": 0, "column": 0, "columnspan": 3, "sticky": "nsew"},
            "main": {"row": 1, "column": 0, "columnspan": 3, "sticky": "nsew"},
            "status": {"row": 2, "column": 0, "columnspan": 3, "sticky": "nsew"},
        },
    },
    "pipeline_tab": {
        "left": {"panel": "sidebar_panel_v2"},
        "center": {
            "panel": "stage_cards_panel_v2",
            "stages_order": ["txt2img", "img2img", "adetailer", "upscale"],
        },
        "right": {"panel": "preview_panel_v2"},
    },
    "prompt_tab": {
        "main": {"panel": "prompt_tab_frame_v2"},
    },
    "learning_tab": {
        "main": {"panel": "learning_tab_frame_v2"},
    },
}


def get_root_rows() -> Iterable[dict[str, Any]]:
    return ZONE_MAP["root"]["grid"]["rows"]


def get_root_columns() -> Iterable[dict[str, Any]]:
    return ZONE_MAP["root"]["grid"]["columns"]


def get_root_zone_config(zone_name: str) -> dict[str, Any]:
    return ZONE_MAP["root"]["zones"].get(zone_name, {})


def get_pipeline_stage_order() -> list[str]:
    center = ZONE_MAP.get("pipeline_tab", {}).get("center", {})
    order = center.get("stages_order")
    if isinstance(order, list):
        return list(order)
    return []


__all__ = [
    "get_pipeline_stage_order",
    "get_root_columns",
    "get_root_rows",
    "get_root_zone_config",
    "ZONE_MAP",
]
