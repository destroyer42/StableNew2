from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import traceback
import zipfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from src.api.webui_process_manager import get_global_webui_process_manager
from src.config.app_config import get_jsonl_log_config
from src.services.queue_store_v2 import get_queue_state_path
from src.utils.logger import InMemoryLogHandler
from src.utils.process_inspector_v2 import (
    collect_gpu_snapshot,
    format_process_brief,
    iter_stablenew_like_processes,
)
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
_PRESSURE_REASON_HINTS = {"ui_heartbeat_stall", "queue_runner_stall", "webui_pressure", "webui_unavailable"}


def _is_pressure_reason(reason: str) -> bool:
    candidate = str(reason or "").strip().lower()
    return candidate in _PRESSURE_REASON_HINTS or "pressure" in candidate or "stall" in candidate


def _reason_guard_name(reason: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in str(reason or "diagnostic").lower())
    return safe.strip("_") or "diagnostic"


def _cooldown_marker_path(directory: Path, reason: str) -> Path:
    return directory / f".diag_cooldown_{_reason_guard_name(reason)}.json"


def _lock_marker_path(directory: Path, reason: str) -> Path:
    return directory / f".diag_lock_{_reason_guard_name(reason)}.lock"


def _cross_process_cooldown_active(directory: Path, reason: str, cooldown_s: float) -> bool:
    marker = _cooldown_marker_path(directory, reason)
    if not marker.exists():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        last_ts = float(payload.get("last_ts", 0.0) or 0.0)
    except Exception:
        try:
            last_ts = marker.stat().st_mtime
        except Exception:
            return False
    return (time.time() - last_ts) < float(cooldown_s)


def _write_cooldown_marker(directory: Path, reason: str) -> None:
    marker = _cooldown_marker_path(directory, reason)
    payload = {"pid": os.getpid(), "last_ts": time.time()}
    try:
        marker.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        logger.debug("Failed to write diagnostics cooldown marker", exc_info=True)


def _acquire_cross_process_lock(directory: Path, reason: str) -> Path | None:
    lock_path = _lock_marker_path(directory, reason)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    try:
        os.write(fd, json.dumps({"pid": os.getpid(), "ts": time.time()}).encode("utf-8"))
    finally:
        os.close(fd)
    return lock_path


def _release_cross_process_lock(lock_path: Path | None) -> None:
    if lock_path is None:
        return
    try:
        lock_path.unlink(missing_ok=True)
    except Exception:
        logger.debug("Failed to release diagnostics lock %s", lock_path, exc_info=True)


def _resolve_default_webui_tail(
    reason: str,
    provided_tail: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if provided_tail:
        return provided_tail
    if not _is_pressure_reason(reason):
        return None
    manager = get_global_webui_process_manager()
    if manager is None:
        return None
    try:
        return manager.get_recent_output_tail(max_lines=200)
    except Exception:
        return None


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
) -> threading.Thread | None:
    """Create a diagnostics bundle asynchronously (single-flight per reason)."""
    effective_include_process_state = bool(include_process_state or _is_pressure_reason(reason))
    effective_webui_tail = _resolve_default_webui_tail(reason, webui_tail)
    directory = _resolve_output_dir(output_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    now = time.monotonic()
    with _BUNDLE_LOCK:
        last = _LAST_BUNDLE_TS.get(reason, 0.0)
        if reason in _IN_FLIGHT:
            return
        if (now - last) < float(cooldown_s):
            return None
        if _cross_process_cooldown_active(directory, reason, cooldown_s):
            return None
        _IN_FLIGHT.add(reason)
        _LAST_BUNDLE_TS[reason] = now
    lock_path = _acquire_cross_process_lock(directory, reason)
    if lock_path is None:
        with _BUNDLE_LOCK:
            _IN_FLIGHT.discard(reason)
        return None

    def _worker():
        try:
            build_crash_bundle(
                reason=reason,
                log_handler=log_handler,
                job_service=job_service,
                extra_context=extra_context,
                webui_tail=effective_webui_tail,
                output_dir=output_dir,
                image_roots=image_roots,
                include_process_state=effective_include_process_state,
                include_queue_state=include_queue_state,
            )
            _write_cooldown_marker(directory, reason)
        finally:
            with _BUNDLE_LOCK:
                _IN_FLIGHT.discard(reason)
            _release_cross_process_lock(lock_path)
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass

    thread = threading.Thread(target=_worker, daemon=False, name=f"DiagBundle-{reason}")
    thread.start()
    return thread


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
    include_process_state: bool = False,
    include_queue_state: bool = False,
) -> Path | None:
    """Create a diagnostics zip bundle for the given reason."""
    effective_include_process_state = bool(include_process_state or _is_pressure_reason(reason))
    effective_webui_tail = _resolve_default_webui_tail(reason, webui_tail)

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
                "bundle_features": {
                    "include_process_state": bool(effective_include_process_state),
                    "include_queue_state": bool(include_queue_state),
                    "include_webui_tail": bool(effective_webui_tail),
                },
            }
            # Accept context from new argument (overrides extra_context if both given)
            if context is not None:
                metadata["context"] = _anonymize(context)
            elif extra_context:
                metadata["context"] = _anonymize(extra_context)
            if job_snapshot:
                metadata["job_snapshot"] = _anonymize(job_snapshot)
            sanitized_tail = _anonymize(effective_webui_tail) if effective_webui_tail else None
            if sanitized_tail:
                metadata["webui_tail"] = sanitized_tail
            gpu_snapshot = collect_gpu_snapshot()
            if gpu_snapshot:
                metadata["gpu_snapshot"] = gpu_snapshot

            # PR-HB-003: Capture thread dump for heartbeat stall diagnostics
            # Never let thread dump failure prevent bundle creation
            try:
                thread_dump_text, thread_dump_json = _capture_thread_dump()
                metadata["thread_dump_captured"] = True
            except Exception as e:
                thread_dump_text = f"ERROR: Thread dump capture failed: {e!r}"
                thread_dump_json = {"error": str(e)}
                metadata["thread_dump_captured"] = False
                metadata["thread_dump_error"] = str(e)

            inspector_lines = _collect_process_inspector_lines()
            with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("metadata/info.json", json.dumps(_anonymize(metadata), indent=2))
                
                # PR-HB-003: Always write thread dumps, even if capture failed
                zf.writestr("metadata/thread_dump.txt", thread_dump_text)
                zf.writestr("metadata/thread_dump.json", json.dumps(_anonymize(thread_dump_json), indent=2))
                
                if entries:
                    zf.writestr("logs/gui_logs.json", json.dumps(_anonymize(entries), indent=2))
                if job_snapshot:
                    zf.writestr(
                        "runtime/job_snapshot.json",
                        json.dumps(_anonymize(job_snapshot), indent=2),
                    )
                    selected_job = _select_bundle_job_summary(job_snapshot)
                    result_summary = selected_job.get("result_summary")
                    if isinstance(result_summary, Mapping) and result_summary:
                        zf.writestr(
                            "runtime/result_summary.json",
                            json.dumps(_anonymize(dict(result_summary)), indent=2),
                        )
                        replay_descriptor = result_summary.get("replay_descriptor")
                        if isinstance(replay_descriptor, Mapping) and replay_descriptor:
                            zf.writestr(
                                "runtime/replay_descriptor.json",
                                json.dumps(_anonymize(dict(replay_descriptor)), indent=2),
                            )
                            curation_descriptor = replay_descriptor.get("curation")
                            if isinstance(curation_descriptor, Mapping) and curation_descriptor:
                                zf.writestr(
                                    "runtime/curation_descriptor.json",
                                    json.dumps(_anonymize(dict(curation_descriptor)), indent=2),
                                )
                if inspector_lines and effective_include_process_state:
                    zf.writestr("metadata/process_inspector.txt", "\n".join(inspector_lines))
                if gpu_snapshot:
                    zf.writestr("metadata/gpu_snapshot.json", json.dumps(_anonymize(gpu_snapshot), indent=2))
                _include_jsonl_logs(zf)
                _include_image_metadata(zf, image_roots)
                if include_queue_state:
                    _include_queue_state(zf)
                if sanitized_tail:
                    zf.writestr(
                        "runtime/webui_tail.json",
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
    if image_roots is None and os.environ.get("PYTEST_CURRENT_TEST"):
        return
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


def _include_queue_state(zf: zipfile.ZipFile) -> None:
    queue_state_path = get_queue_state_path()
    if not queue_state_path.exists():
        return
    try:
        payload = json.loads(queue_state_path.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("Failed to include queue state in diagnostics bundle", exc_info=True)
        return
    zf.writestr("runtime/queue_state.json", json.dumps(_anonymize(payload), indent=2))


def _select_bundle_job_summary(job_snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(job_snapshot, Mapping):
        return {}
    jobs = job_snapshot.get("jobs")
    if not isinstance(jobs, list):
        return {}
    queue = job_snapshot.get("queue")
    current_job_id = queue.get("current_job_id") if isinstance(queue, Mapping) else None

    for job in jobs:
        if isinstance(job, Mapping) and current_job_id and job.get("job_id") == current_job_id:
            return dict(job)
    for job in jobs:
        if isinstance(job, Mapping) and job.get("status") == "running":
            return dict(job)
    for job in jobs:
        if isinstance(job, Mapping):
            return dict(job)
    return {}


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


def _capture_thread_dump() -> tuple[str, dict]:
    """
    PR-HB-003: Capture current thread stacks for heartbeat stall diagnostics.
    
    Returns:
        tuple of (text_dump, json_dump) for both human-readable and structured formats.
    
    PR-HB-003: Fixed to use sys._current_frames() for real frame objects and
    traceback.extract_stack() for FrameSummary objects (not frame.f_code access).
    """
    text_lines = []
    json_threads = {}
    
    try:
        frames = sys._current_frames()
        thread_map = {t.ident: t for t in threading.enumerate() if t.ident is not None}
        
        for thread_id, frame in frames.items():
            # Get thread object for name/metadata
            thread_obj = thread_map.get(thread_id)
            thread_name = thread_obj.name if thread_obj else f"Thread-{thread_id}"
            is_daemon = thread_obj.daemon if thread_obj else False
            is_alive = thread_obj.is_alive() if thread_obj else False
            
            # PR-HB-003: Use format_stack for text, extract_stack for structured data
            stack_lines = traceback.format_stack(frame)
            stack_text = "".join(stack_lines)
            
            # Add to text dump
            text_lines.append(f"\n{'='*80}")
            text_lines.append(f"Thread: {thread_name} (ID: {thread_id})")
            text_lines.append(f"  Daemon: {is_daemon}, Alive: {is_alive}")
            text_lines.append(f"{'-'*80}")
            text_lines.append(stack_text)
            
            # PR-HB-003: extract_stack returns FrameSummary objects, not frames
            extracted_frames = traceback.extract_stack(frame)
            json_threads[str(thread_id)] = {
                "thread_id": thread_id,
                "name": thread_name,
                "daemon": is_daemon,
                "alive": is_alive,
                "stack_frames": [
                    {
                        "filename": fs.filename,
                        "lineno": fs.lineno,
                        "function": fs.name,
                        "line": fs.line or "",
                    }
                    for fs in extracted_frames
                ],
            }
        
        text_dump = "\n".join(text_lines) if text_lines else "(No threads found)"
        
    except Exception as e:
        text_dump = f"ERROR capturing thread dump: {e!r}\n{traceback.format_exc()}"
        json_threads = {"error": str(e)}
    
    return text_dump, json_threads
    
    return text_dump, json_threads


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
