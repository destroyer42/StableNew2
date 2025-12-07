"""Utilities for building diagnostics crash bundles."""

from __future__ import annotations

import json
import logging
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from src.config.app_config import get_jsonl_log_config
from src.utils.logger import InMemoryLogHandler
from src.utils.process_inspector_v2 import format_process_brief, iter_stablenew_like_processes
from src.utils.system_info_v2 import collect_system_snapshot

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
HOME = Path.home()
DEFAULT_BUNDLE_DIR = Path("reports") / "diagnostics"
_BUNDLE_LOCK = threading.Lock()


def build_crash_bundle(
    *,
    reason: str,
    log_handler: InMemoryLogHandler | None,
    job_service: Any | None = None,
    extra_context: Mapping[str, Any] | None = None,
    output_dir: Path | None = None,
) -> Path | None:
    """Create a diagnostics zip bundle for the given reason."""

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_reason = _sanitize_filename(reason) or "diagnostic"
    directory = Path(output_dir or DEFAULT_BUNDLE_DIR)

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
            if extra_context:
                metadata["context"] = _anonymize(extra_context)
            if job_snapshot:
                metadata["job_snapshot"] = _anonymize(job_snapshot)

            inspector_lines = _collect_process_inspector_lines()
            with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("metadata/info.json", json.dumps(_anonymize(metadata), indent=2))
                if entries:
                    zf.writestr("logs/gui_logs.json", json.dumps(_anonymize(entries), indent=2))
                if inspector_lines:
                    zf.writestr("metadata/process_inspector.txt", "\n".join(inspector_lines))
                _include_jsonl_logs(zf)
            logger.info("Crash bundle saved to %s", bundle_path)
            return bundle_path
        except Exception as exc:  # pragma: no cover - best effort
            logger.exception("Failed to build diagnostics bundle: %s", exc)
            return None


def _collect_process_inspector_lines() -> list[str]:
    return [format_process_brief(proc) for proc in iter_stablenew_like_processes()]


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
