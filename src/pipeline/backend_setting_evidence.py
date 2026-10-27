"""Allow-listed values explicitly reported in a generation response or dispatched request.

The caller records the provenance. An outbound request is never backend readback.
"""

from collections.abc import Mapping
from typing import Any

from src.generation_profiles.contract import SETTING_KEYS, validate_settings


def setting_values(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {}
    result = {}
    for key in SETTING_KEYS:
        if key in raw:
            try:
                result.update(validate_settings({key: raw[key]}))
            except ValueError:
                continue
    return result
