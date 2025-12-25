from __future__ import annotations

import json
import logging
import threading
import time
import zipfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config.app_config import get_jsonl_log_config
from src.utils.logger import InMemoryLogHandler
from src.utils.process_inspector_v2 import format_process_brief, iter_stablenew_like_processes
from src.utils.system_info_v2 import collect_system_snapshot
from src.utils.image_metadata import decode_payload, read_image_metadata

"""Utilities for building diagnostics crash bundles."""

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
HOME = Path.home()
DEFAULT_BUNDLE_DIR = Path("reports") / "diagnostics"
_BUNDLE_LOCK = threading.Lock()


def _resolve_output_dir(output_dir: Path | None) -> Path:
    if output_dir:
        candidate = Path(output_dir).expanduser()
        try:
            return candidate.resolve(strict=False)
        except Exception:
            return candidate
    return DEFAULT_BUNDLE_DIR


# Single-flight / cooldown guards for async bundle creation
_LAST_BUNDLE_TS: dict[str, float] = {}
_IN_FLIGHT: set[str] = set()


def build_async(
    *,
    reason: str,
    log_handler: InMemoryLogHandler | None = None,
    job_service: Any | None = None,
    extra_context: Mapping[str, Any] | None = None,
    output_dir: Path | None = None,
    image_roots: list[Path] | None = None,
    include_process_state: bool = False,
    include_queue_state: bool = False,
    cooldown_s: float = 30.0,
    on_done: callable | None = None,
    webui_tail: Mapping[str, Any] | None = None,
) -> None:
    """Create a diagnostics bundle asynchronously (single-flight per reason)."""
    now = time.monotonic()
    with _BUNDLE_LOCK:
        last = _LAST_BUNDLE_TS.get(reason, 0.0)
        if reason in _IN_FLIGHT:
            return
        if (now - last) < float(cooldown_s):
            return
        _IN_FLIGHT.add(reason)
        _LAST_BUNDLE_TS[reason] = now

    def _worker():
        try:
            build_crash_bundle(
                reason=reason,
                log_handler=log_handler,
                job_service=job_service,
                extra_context=extra_context,
                webui_tail=webui_tail,
                output_dir=output_dir,
                image_roots=image_roots,
            )
        finally:
            with _BUNDLE_LOCK:
                _IN_FLIGHT.discard(reason)
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass

    threading.Thread(target=_worker, daemon=False, name=f"DiagBundle-{reason}").start()


def build_crash_bundle(
    *,
    reason: str,
    log_handler: InMemoryLogHandler | None = None,
    job_service: Any | None = None,
    extra_context: Mapping[str, Any] | None = None,
    output_dir: Path | None = None,
    webui_tail: Mapping[str, Any] | None = None,
    image_roots: list[Path] | None = None,
    context: dict | None = None,
) -> Path | None:
    """Create a diagnostics zip bundle for the given reason."""

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_reason = _sanitize_filename(reason) or "diagnostic"
    directory = _resolve_output_dir(output_dir)

    with _BUNDLE_LOCK:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            bundle_path = directory / f"stablenew_diagnostics_{timestamp}_{safe_reason}.zip"
            entries = list(log_handler.get_entries()) if log_handler else []
            job_snapshot = (
                job_service.get_diagnostics_snapshot()
                if job_service and hasattr(job_service, "get_diagnostics_snapshot")
                else {}
            )
            metadata = {
                "reason": reason,
                "timestamp": timestamp,
                "system": collect_system_snapshot(),
            }
            # Accept context from new argument (overrides extra_context if both given)
            if context is not None:
                metadata["context"] = _anonymize(context)
            elif extra_context:
                metadata["context"] = _anonymize(extra_context)
            if job_snapshot:
                metadata["job_snapshot"] = _anonymize(job_snapshot)
            sanitized_tail = _anonymize(webui_tail) if webui_tail else None
            if sanitized_tail:
                metadata["webui_tail"] = sanitized_tail

            inspector_lines = _collect_process_inspector_lines()
            with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("metadata/info.json", json.dumps(_anonymize(metadata), indent=2))
                if entries:
                    zf.writestr("logs/gui_logs.json", json.dumps(_anonymize(entries), indent=2))
                if inspector_lines:
                    zf.writestr("metadata/process_inspector.txt", "\n".join(inspector_lines))
                _include_jsonl_logs(zf)
                _include_image_metadata(zf, image_roots)
                if sanitized_tail:
                    zf.writestr(
                        "artifacts/webui_tail.json",
                        json.dumps(sanitized_tail, indent=2),
                    )
            logger.info("Crash bundle saved to %s", bundle_path)
            return bundle_path
        except Exception as exc:  # pragma: no cover - best effort
            logger.exception("Failed to build diagnostics bundle: %s", exc)
            return None


def _collect_process_inspector_lines() -> list[str]:
    try:
        return [format_process_brief(proc) for proc in iter_stablenew_like_processes()]
    except Exception:
        return []


def _include_jsonl_logs(zf: zipfile.ZipFile) -> None:
    config = get_jsonl_log_config()
    path = config.path
    if not config.enabled or path is None:
        return
    log_files: list[Path] = []
    if path.exists():
        log_files.append(path)
    parent = path.parent
    if parent.exists():
        pattern = f"{path.name}*"
        for candidate in sorted(parent.glob(pattern)):
            if candidate.exists() and candidate not in log_files:
                log_files.append(candidate)
    for log_path in log_files:
        try:
            arcname = Path("logs") / log_path.name
            zf.write(log_path, arcname)
        except Exception:
            logger.debug("Failed to include JSONL log %s in bundle", log_path)


def _include_image_metadata(zf: zipfile.ZipFile, image_roots: list[Path] | None) -> None:
    roots = image_roots or [ROOT / "output", ROOT / "outputs"]
    image_paths = _collect_image_paths(roots, limit=25)
    if not image_paths:
        return
    for image_path in image_paths:
        try:
            kv = read_image_metadata(image_path)
            payload_result = decode_payload(kv)
            meta_name = image_path.name
            if payload_result.payload is not None:
                payload = {
                    "status": payload_result.status,
                    "payload": payload_result.payload,
                    "kv": kv,
                    "path": str(image_path),
                }
                zf.writestr(
                    f"artifacts/image_metadata/{meta_name}.meta.json",
                    json.dumps(_anonymize(payload), indent=2),
                )
            else:
                note = f"metadata missing or invalid: {payload_result.status}"
                zf.writestr(
                    f"artifacts/image_metadata/{meta_name}.meta.missing.txt",
                    note,
                )
        except Exception:
            logger.debug("Failed to include image metadata for %s", image_path)


def _collect_image_paths(roots: list[Path], *, limit: int = 25) -> list[Path]:
    seen: set[Path] = set()
    images: list[Path] = []
    for root in roots:
        if not root or not root.exists():
            continue
        for ext in (".png", ".jpg", ".jpeg"):
            for path in root.rglob(f"*{ext}"):
                if path in seen or not path.is_file():
                    continue
                seen.add(path)
                images.append(path)
    images.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return images[:limit]


def _sanitize_filename(token: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in token.strip())
    return safe[:128]


def _anonymize(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace(str(HOME), "<USER_HOME>").replace(str(ROOT), "<REPO_ROOT>")
    if isinstance(value, Mapping):
        return {str(k): _anonymize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_anonymize(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_anonymize(v) for v in value)
    return value
