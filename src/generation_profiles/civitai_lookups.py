"""Civitai lookups by verified SHA-256, one stored result per checkpoint (MEC-903, owner decision D4).

The batch sends only hashes the operator was shown and confirmed, one request at a time under the existing
``EvidenceRefresh`` rate limit, and stops on Cancel. Results are *unreviewed identification facts* (base model, model
and version names, type) or a "not found" note: they are displayed and used as a recipe-order hint for probes, never as
settings, recommendations, family evidence or profiles.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.generation_profiles.evidence_refresh import EvidenceRefresh, Lookup
from src.utils.atomic_io import atomic_write_text

_SHA = re.compile(r"[0-9a-f]{64}")
#: Statuses worth keeping: a definite answer from the service. Offline/rate-limited results are retried later.
_DEFINITE = ("candidate", "service_error")


def default_root() -> Path:
    from src.generation_profiles.evidence_catalog import operator_catalog_root

    return operator_catalog_root() / "lookups" / "civitai"


@dataclass(frozen=True)
class LookupSummary:
    identified: int = 0
    not_found: int = 0
    unavailable: int = 0
    cancelled: bool = False

    def describe(self) -> str:
        text = (
            f"Civitai lookup: {self.identified} identified, {self.not_found} not on Civitai, "
            f"{self.unavailable} unavailable (offline or rate limited; retry later)."
        )
        return text + (" Cancelled; finished lookups are saved." if self.cancelled else "")


def describe_result(result: Mapping[str, Any] | None) -> str:
    """One line for the catalog details pane."""
    if not result:
        return ""
    if result.get("status") == "service_error":
        if result.get("http_status") == 404:
            return (
                "Not found on Civitai by hash (often a merge, a private upload, a converted/pruned copy or a "
                "renamed re-upload)."
            )
        return f"Civitai answered with an error (HTTP {result.get('http_status')})."
    facts = result.get("identification") or {}
    if not result.get("hash_matched") or not facts:
        return "Civitai returned a version, but its file hash did not match; not used."
    name = " / ".join(item for item in (facts.get("model_name"), facts.get("version_name")) if item)
    kind = " ".join(item for item in (facts.get("base_model"), facts.get("model_type")) if item)
    extra = f" ({facts['base_model_type']})" if facts.get("base_model_type") else ""
    return f"Civitai says: {kind}{extra}" + (f" — {name}" if name else "") + " (unreviewed)."


def base_model_hint(result: Mapping[str, Any] | None) -> str:
    if not result or not result.get("hash_matched"):
        return ""
    return str((result.get("identification") or {}).get("base_model") or "")


class LookupStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_root()

    def path_for(self, sha256: str) -> Path:
        if not _SHA.fullmatch(sha256 or ""):
            raise ValueError("Invalid checkpoint SHA-256")
        return self.root / f"{sha256}.json"

    def save(self, sha256: str, result: Mapping[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        document = {**dict(result), "looked_up_at": datetime.now(UTC).isoformat(timespec="seconds")}
        atomic_write_text(self.path_for(sha256), json.dumps(document, indent=2, sort_keys=True))

    def load(self, sha256: str) -> dict[str, Any] | None:
        try:
            path = self.path_for(sha256)
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and data.get("status") in _DEFINITE else None

    def load_all(self) -> dict[str, dict[str, Any]]:
        if not self.root.is_dir():
            return {}
        found = {path.stem: self.load(path.stem) for path in self.root.glob("*.json")}
        return {sha: result for sha, result in found.items() if result is not None}


def disclosure(hashes: Sequence[str], names: Mapping[str, str]) -> str:
    shown = "\n".join(f"  {sha[:16]}…  {names.get(sha, '')}" for sha in hashes[:12])
    more = f"\n  …and {len(hashes) - 12} more" if len(hashes) > 12 else ""
    return (
        f"Send {len(hashes)} SHA-256 hash{'es' if len(hashes) != 1 else ''} to civitai.com, one request about "
        f"every 2 seconds (about {max(1, len(hashes) * 2 // 60)} min). No model bytes, prompts, images, ratings or "
        f"local paths are sent; file names are not sent.\n\n{shown}{more}\n\nResults are saved as unreviewed "
        "identification facts. Cancel stops after the current request."
    )


def batch_lookup(
    hashes: Sequence[str],
    *,
    store: LookupStore,
    refresh: EvidenceRefresh,
    confirmed: bool,
    cancelled: Callable[[], bool] = lambda: False,
    progress: Callable[[str], None] = lambda _message: None,
    sleep: Callable[[float], None] = time.sleep,
    max_wait: float = 120.0,
) -> LookupSummary:
    if confirmed is not True:
        raise ValueError("Confirm the displayed disclosure before lookup")
    identified = not_found = unavailable = 0
    for index, sha in enumerate(hashes, start=1):
        waited = 0.0
        while True:
            if cancelled():
                return LookupSummary(identified, not_found, unavailable, True)
            result = refresh.refresh(Lookup("civitai", sha), confirmed=True, cancelled=cancelled)
            if result.get("status") != "rate_limited":
                break
            delay = float(result.get("retry_after_seconds") or 2)
            if waited + delay > max_wait:
                break
            progress(f"Civitai: waiting {delay:.0f} s (rate limit)…")
            step = 0.0
            while step < delay and not cancelled():
                sleep(min(0.25, delay - step))
                step += 0.25
            waited += delay
        status = result.get("status")
        if status == "cancelled":
            return LookupSummary(identified, not_found, unavailable, True)
        if status in _DEFINITE:
            store.save(sha, result)
            if status == "candidate" and result.get("hash_matched"):
                identified += 1
            else:
                not_found += 1
        else:
            unavailable += 1
        progress(f"Civitai: {index} of {len(hashes)} looked up ({identified} identified)")
    return LookupSummary(identified, not_found, unavailable)
