"""Read-only diagnosis of AssetRegistry checkpoint-evidence reuse (PR-LEARN-COMPARE-145).

Answers, for an installation, "why would StableNew read a multi-GB checkpoint again?" without hashing, writing,
locking or modifying the cache or any model file. It reports where the effective cache lives, whether it parses, its
schema version and entry counts, and for each ``--checkpoint`` the exact reason its cached evidence is or is not
reusable, distinguishing the misses that need a full SHA-256 read from the ones that need only a header/sidecar
re-read. Paths are replaced by short stable labels unless ``--show-paths`` is given.

Usage (from the repository root, on the machine that owns the cache)::

    python tools/diagnose_asset_registry_cache.py --checkpoint "D:/models/Stable-diffusion/model.safetensors"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _label(path: Path | str, show_paths: bool) -> str:
    text = str(path)
    return text if show_paths else "path:" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def diagnose(
    *,
    cache: Path | None,
    webui_root: Path | None,
    checkpoints: list[Path],
    show_paths: bool = False,
) -> dict[str, Any]:
    from src.assets import AssetRegistry

    registry = AssetRegistry(webui_root, cache_path=cache)
    description = registry.describe_cache()
    report: dict[str, Any] = {
        "cache": {"location": _label(registry.cache_path, show_paths), **description.as_dict()},
        "webui_root_configured": registry.webui_root is not None,
        "checkpoints": [],
    }
    cached_keys: set[str] = set()
    try:
        document = json.loads(registry.cache_path.read_text(encoding="utf-8"))
        cached_keys = set(document.get("entries", {})) if isinstance(document, dict) else set()
    except (OSError, ValueError, TypeError):
        pass
    for path in checkpoints:
        status = registry.checkpoint_status(path)
        resolved = str(path.resolve())
        item: dict[str, Any] = {
            "checkpoint": _label(path, show_paths),
            "reason": status.reason.value,
            "current": status.current,
            "needs_full_hash": status.needs_hash,
            "digest_reusable": status.digest_reusable,
            "cache_state": status.cache_state.value,
            "exact_resolved_path_is_cached": resolved in cached_keys,
        }
        if not item["exact_resolved_path_is_cached"] and cached_keys:
            # A cache that holds the same file under a different spelling is the typical "moved workspace" signature.
            item["same_file_name_cached_under_another_path"] = any(
                Path(key).name.casefold() == path.name.casefold() for key in cached_keys
            )
        report["checkpoints"].append(item)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--cache", type=Path, help="cache file (default: the workspace's asset_registry_v1.json)")
    parser.add_argument("--webui-root", type=Path, help="optional WebUI root (not needed to diagnose checkpoints)")
    parser.add_argument("--checkpoint", type=Path, action="append", default=[], help="exact checkpoint file; repeatable")
    parser.add_argument("--show-paths", action="store_true", help="print real paths instead of short labels")
    args = parser.parse_args(argv)
    print(
        json.dumps(
            diagnose(
                cache=args.cache, webui_root=args.webui_root, checkpoints=args.checkpoint,
                show_paths=args.show_paths,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
