"""Read-only, visibility-aware reporting of frozen explicit selection evidence."""

from collections.abc import Mapping
from typing import Any


def selection_detail_lines(record: Any, *, visible: bool) -> list[str]:
    metadata = getattr(getattr(record, "provenance", None), "metadata", {})
    manifest = metadata.get("klein_lora_selection")
    if not isinstance(manifest, Mapping):
        return []
    lines = [
        f"  Klein adapter selection: {manifest.get('choice', 'unknown')} (frozen before admission)"
    ]
    selected = manifest.get("selected")
    if selected:
        name = selected["name"] if visible else "Verified adapter"
        lines.append(f"  Selected: {name} at authored weight {selected['weight']}")
    else:
        lines.append("  Selected: none")
    for item in manifest.get("excluded", ()):
        name = item["name"] if visible else f"Adapter {item['index'] + 1}"
        reason = item["reason"] if visible else "Exact policy assessment"
        lines.append(
            f"  Excluded: {name} — {item['status']} / {item['exclusion_reason']}: {reason}"
        )
    return lines
