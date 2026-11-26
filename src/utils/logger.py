"""Logging utilities with structured JSON output"""

import atexit
import contextlib
import copy
import csv
import json
import logging
import os
import queue
import shutil
import sys
import time
import weakref
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
from threading import RLock
from typing import Any

from src.utils.atomic_io import atomic_write_json

# Module-level registry for StructuredLogger lifecycle management
_structured_logger_registry: weakref.WeakSet[Any] = weakref.WeakSet()

# PR-HARDEN-002: Global async logging infrastructure
_async_log_queue: queue.Queue[logging.LogRecord] | None = None
_async_queue_listener: QueueListener | None = None

_ASCII_REPLACEMENTS: dict[str, str] = {
    "→": "->",
    "—": "-",
    "–": "-",
    "▼": "v",
    "▲": "^",
    "✅": "[ok]",
    "❌": "[error]",
    "⚠️": "[warn]",
    "⚠": "[warn]",
    "🔍": "[debug]",
    "🔵": "[debug]",
    "📝": "[manifest]",
    "🎯": "[detail]",
    "🎨": "[prompt]",
    "🚫": "[skip]",
    "🚀": "[request]",
    "✨": "[detail]",
    "🔀": "[refiner]",
    "🛡️": "[safety]",
    "🛡": "[safety]",
    "🧹": "[memory]",
    "⏭️": "[skip]",
    "⏭": "[skip]",
}
_LOG_REQUIRED_FIELDS: tuple[str, ...] = (
    "event",
    "subsystem",
    "stage",
    "job_id",
    "run_id",
    "image_index",
    "duration_ms",
    "outcome",
)


def get_structured_logger_registry_count() -> int:
    """Return the current count of active StructuredLogger instances."""
    return len(_structured_logger_registry)


def close_all_structured_loggers() -> None:
    """
    Close all active StructuredLogger instances (best-effort, safe to call multiple times).

    Iterates through registered loggers and calls close() on each.
    Silently continues on any exception.
    """
    # Make a copy to avoid mutation during iteration
    loggers_to_close = list(_structured_logger_registry)
    for logger_instance in loggers_to_close:
        try:
            logger_instance.close()
        except Exception:
            # Best-effort: silently skip any that fail
            pass


def get_logger(name: str) -> logging.Logger:
    """Return a module logger with a single indirection for future tweaks."""
    return logging.getLogger(name)


def normalize_log_message(value: str) -> str:
    """Normalize UI-facing log text to stable ASCII-friendly output."""
    text = str(value or "")
    for source, replacement in _ASCII_REPLACEMENTS.items():
        text = text.replace(source, replacement)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = " ".join(text.split())
    return text


def install_async_logging(
    *handlers: logging.Handler,
    queue_size: int = 10000,
) -> QueueListener | None:
    """
    PR-HARDEN-002: Install async logging to prevent UI thread blocking.

    Wraps the provided handlers with a QueueHandler/QueueListener pattern.
    Log records are placed on a queue and processed by a background thread,
    preventing synchronous file I/O from blocking the calling thread.

    Args:
        *handlers: One or more logging handlers to wrap asynchronously
        queue_size: Maximum queue size (default 10000, drops oldest on overflow)

    Returns:
        QueueListener if installed, None if no handlers provided

    Usage:
        handler = logging.FileHandler("app.log")
        listener = install_async_logging(handler)
        # At shutdown: listener.stop()
    """
    global _async_log_queue, _async_queue_listener

    if not handlers:
        return None

    # Create bounded queue to prevent memory exhaustion
    _async_log_queue = queue.Queue(maxsize=queue_size)

    # Create listener that processes records from queue
    _async_queue_listener = QueueListener(
        _async_log_queue,
        *handlers,
        respect_handler_level=True,
    )

    # Start background processing thread
    _async_queue_listener.start()

    # Register cleanup at exit
    atexit.register(_shutdown_async_logging)

    return _async_queue_listener


def get_async_queue_handler() -> QueueHandler | None:
    """
    PR-HARDEN-002: Get a QueueHandler for the async logging queue.

    Returns a handler that can be added to loggers. Records sent to this
    handler are processed asynchronously by the background listener.

    Returns:
        QueueHandler if async logging is installed, None otherwise
    """
    if _async_log_queue is None:
        return None
    return QueueHandler(_async_log_queue)


def _shutdown_async_logging() -> None:
    """Cleanup async logging on shutdown."""
    global _async_queue_listener
    if _async_queue_listener is not None:
        try:
            _async_queue_listener.stop()
        except Exception:
            pass
        _async_queue_listener = None


@dataclass
class LogContext:
    """Contextual information for logging (run_id, stage, subsystem, etc.)."""

    run_id: str | None = None
    job_id: str | None = None
    stage: str | None = None
    subsystem: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.run_id:
            data["run_id"] = self.run_id
        if self.job_id:
            data["job_id"] = self.job_id
        if self.stage:
            data["stage"] = self.stage
        if self.subsystem:
            data["subsystem"] = self.subsystem
        return data


@dataclass(frozen=True)
class JsonlFileLogConfig:
    """Configuration for JSONL log sinking."""

    enabled: bool = True
    path: Path | None = None
    max_bytes: int = 10_000_000
    backup_count: int = 5


# A refused rotation is retried no sooner than this; before N11 it was retried on every record.
_ROTATION_RETRY_SECONDS = 60.0
# Keys every JSONL record carries (N11). A payload's own value for one of them is kept as ``payload_<key>``.
_JSONL_RECORD_KEYS = ("ts", "level", "logger")


def _record_timestamp(created: float) -> str:
    """ISO 8601 local time with its UTC offset, to the millisecond."""

    return datetime.fromtimestamp(created).astimezone().isoformat(timespec="milliseconds")


class JsonlFileHandler(RotatingFileHandler):
    """Handler that writes one JSON object per line, with rotation that never fails silently.

    Every record carries ``ts``, ``level`` and ``logger``; an exception's traceback stays inside the line as
    ``exc_text``. Rotation renames the live file before touching any backup, so a refused rename (on Windows, any
    other open handle) destroys nothing. It then falls back to copy-and-truncate. If that fails too it writes one
    ``log_rotation_failed`` record and retries after ``_ROTATION_RETRY_SECONDS``.
    """

    def __init__(
        self,
        path: Path,
        *,
        level: int = logging.INFO,
        max_bytes: int = 0,
        backup_count: int = 0,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(
            filename=str(path),
            mode="a",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        self.setLevel(level)
        self._next_rotation_attempt = 0.0
        self._rotation_failure_reported = False

    # -- rotation --------------------------------------------------------------------------------------------------

    def shouldRollover(self, record: logging.LogRecord) -> bool:  # noqa: N802 - logging API
        if self.maxBytes <= 0 or time.monotonic() < self._next_rotation_attempt:
            return False
        return bool(super().shouldRollover(record))

    def doRollover(self) -> None:  # noqa: N802 - logging API
        if self.stream:
            self.stream.close()
            self.stream = None  # type: ignore[assignment]
        failure: OSError | None = None
        try:
            self._rotate_files()
        except OSError as exc:
            failure = exc
        finally:
            if not self.stream:
                self.stream = self._open()
        if failure is None:
            self._next_rotation_attempt = 0.0
            self._rotation_failure_reported = False
            return
        self._next_rotation_attempt = time.monotonic() + _ROTATION_RETRY_SECONDS
        self._report_rotation_failure(failure)

    def _rename(self, source: str, destination: str) -> None:
        os.replace(source, destination)

    def _copy(self, source: str, destination: str) -> None:
        shutil.copyfile(source, destination)

    def _backup_name(self, index: int) -> str:
        return self.rotation_filename(f"{self.baseFilename}.{index}")

    def _rotate_files(self) -> None:
        base = self.baseFilename
        if not os.path.exists(base):
            return
        if self.backupCount <= 0:
            self._truncate(base)
            return
        staging = base + ".rotating"
        try:
            self._rename(base, staging)
        except OSError:
            # Another handle has the live file open (a log viewer, a diagnostics bundle, a second process).
            # The backups are not held, so shift them and keep this file's content as a copy.
            self._shift_backups()
            self._copy(base, self._backup_name(1))
            self._truncate(base)
            return
        try:
            self._shift_backups()
            self._rename(staging, self._backup_name(1))
        except OSError:
            try:
                self._rename(staging, base)  # nothing is lost: the live file goes back where it was
            except OSError:
                pass
            raise

    def _shift_backups(self) -> None:
        # ``os.replace`` overwrites the next name in one step, so a refused move deletes nothing.
        for index in range(self.backupCount - 1, 0, -1):
            source = self._backup_name(index)
            if os.path.exists(source):
                self._rename(source, self._backup_name(index + 1))

    @staticmethod
    def _truncate(path: str) -> None:
        with open(path, "r+b") as handle:
            handle.truncate(0)

    def _report_rotation_failure(self, error: OSError) -> None:
        try:
            size = os.path.getsize(self.baseFilename)
        except OSError:
            size = -1
        text = f"{type(error).__name__}: {error}"
        if self._rotation_failure_reported:
            return
        self._rotation_failure_reported = True
        message = (
            f"Log rotation failed for {self.baseFilename} ({size} bytes, limit {self.maxBytes}); "
            f"retrying in {int(_ROTATION_RETRY_SECONDS)} s: {text}"
        )
        payload = {
            "message": message,
            "event": "log_rotation_failed",
            "error": text,
            "size_bytes": size,
            "max_bytes": self.maxBytes,
            "retry_in_s": _ROTATION_RETRY_SECONDS,
            "ts": _record_timestamp(time.time()),
            "level": "WARNING",
            "logger": __name__,
        }
        # Reporting must never raise out of a log call: a closed stderr or a full disk ends the report quietly.
        with contextlib.suppress(OSError, ValueError):
            print(message, file=sys.stderr)
        with contextlib.suppress(OSError, ValueError):
            if self.stream:
                self.stream.write(
                    json.dumps(payload, sort_keys=True, ensure_ascii=False) + self.terminator
                )
                self.flush()

    # -- records ---------------------------------------------------------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        payload = getattr(record, "json_payload", None)
        payload = (
            dict(payload) if isinstance(payload, Mapping) else {"message": record.getMessage()}
        )
        values = {
            "ts": _record_timestamp(record.created),
            "level": record.levelname,
            "logger": record.name,
        }
        for key in _JSONL_RECORD_KEYS:
            if key in payload and payload[key] != values[key]:
                payload[f"payload_{key}"] = payload[key]
            payload[key] = values[key]
        exc_text = self._exception_text(record)
        if exc_text:
            payload.setdefault("exc_text", exc_text)
        try:
            json_line = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            json_line = json.dumps({"message": record.getMessage(), **values}, ensure_ascii=False)
        record = copy.copy(record)
        record.msg = json_line
        record.args = ()
        # The traceback is inside the JSON; the formatter must not append it as raw lines.
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        super().emit(record)

    @staticmethod
    def _exception_text(record: logging.LogRecord) -> str:
        parts: list[str] = []
        if record.exc_info:
            parts.append(record.exc_text or logging.Formatter().formatException(record.exc_info))
        elif record.exc_text:
            parts.append(record.exc_text)
        if record.stack_info:
            parts.append(record.stack_info)
        return "\n".join(parts)


def attach_jsonl_log_handler(
    config: JsonlFileLogConfig | None = None,
    *,
    level: int = logging.INFO,
) -> JsonlFileHandler | None:
    """Attach a JSONL rotating log handler to the root logger (once per file: a second handler on the same file
    would hold it open and make the first one's rotation fail)."""

    cfg = config or JsonlFileLogConfig(path=Path("logs") / "stablenew.log.jsonl")
    if not cfg.enabled or cfg.path is None:
        return None
    root = logging.getLogger()
    target = os.path.normcase(os.path.abspath(cfg.path))
    for existing in root.handlers:
        if (
            isinstance(existing, JsonlFileHandler)
            and os.path.normcase(existing.baseFilename) == target
        ):
            return existing
    handler = JsonlFileHandler(
        cfg.path,
        level=level,
        max_bytes=cfg.max_bytes,
        backup_count=cfg.backup_count,
    )
    if root.level > level or root.level == logging.NOTSET:
        root.setLevel(level)
    root.addHandler(handler)
    return handler


def log_with_ctx(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    ctx: LogContext | None = None,
    extra_fields: Mapping[str, Any] | None = None,
) -> None:
    """Log a message with optional structured context, appended as JSON."""
    normalized_message = normalize_log_message(message)
    payload: dict[str, Any] = {}
    if ctx is not None:
        payload.update(ctx.to_dict())
    if extra_fields:
        payload.update(extra_fields)
    json_payload: dict[str, Any] = {"message": normalized_message}
    json_payload.update(payload)

    if payload:
        logger.log(
            level,
            "%s | %s",
            normalized_message,
            json.dumps(payload, sort_keys=True, ensure_ascii=False),
            extra={"json_payload": json_payload},
        )
    else:
        logger.log(level, "%s", normalized_message, extra={"json_payload": json_payload})


class InMemoryLogHandler(logging.Handler):
    """Logging handler that stores recent log records in memory."""

    def __init__(self, max_entries: int = 500, level: int = logging.NOTSET) -> None:
        super().__init__(level=level)
        self._max_entries = max_entries
        self._lock = RLock()
        self._entries: deque[dict[str, Any]] = deque(maxlen=max_entries)
        self._version = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = normalize_log_message(self.format(record))
        except Exception:
            msg = normalize_log_message(record.getMessage())

        payload = getattr(record, "json_payload", None)
        if isinstance(payload, dict):
            payload = self._normalize_payload(payload)

        entry = {
            "level": record.levelname,
            "name": record.name,
            "message": msg,
            "created": record.created,
            "first_created": record.created,
            "last_created": record.created,
            "repeat_count": 1,
        }
        if payload is not None:
            entry["payload"] = payload

        with self._lock:
            if self._entries and self._same_entry(self._entries[-1], entry):
                current = self._entries[-1]
                current["repeat_count"] = int(current.get("repeat_count", 1)) + 1
                current["last_created"] = record.created
                self._version += 1
                return
            self._entries.append(entry)
            self._version += 1

    def get_entries(self) -> Iterable[dict[str, Any]]:
        """Return a snapshot of the current entries."""
        with self._lock:
            return list(self._entries)

    def get_version(self) -> int:
        """Return a monotonically increasing version for cheap change detection."""
        with self._lock:
            return self._version

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        message = normalized.get("message")
        if isinstance(message, str):
            normalized["message"] = normalize_log_message(message)
        event = normalized.get("event")
        if isinstance(event, str):
            normalized["event"] = normalize_log_message(event)
        return normalized

    def _same_entry(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        if left.get("level") != right.get("level"):
            return False
        if left.get("name") != right.get("name"):
            return False
        if left.get("message") != right.get("message"):
            return False
        return self._entry_signature(left.get("payload")) == self._entry_signature(
            right.get("payload")
        )

    def _entry_signature(self, payload: Any) -> tuple[Any, ...] | None:
        if not isinstance(payload, dict):
            return None
        signature: list[Any] = []
        for key in _LOG_REQUIRED_FIELDS:
            signature.append(payload.get(key))
        envelope = payload.get("error_envelope") or payload.get("envelope")
        if isinstance(envelope, dict):
            signature.append(envelope.get("error_type"))
            signature.append(envelope.get("severity"))
        return tuple(signature)


def attach_gui_log_handler(max_entries: int = 500) -> InMemoryLogHandler:
    """Attach an in-memory log handler to the root logger for GUI mode.

    Captures DEBUG and above for GUI log panel display with filtering.
    """
    handler = InMemoryLogHandler(max_entries=max_entries, level=logging.DEBUG)
    root = logging.getLogger()
    # Ensure root logger allows DEBUG messages to reach the handler
    if root.level > logging.DEBUG or root.level == logging.NOTSET:
        root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    return handler


class StructuredLogger:
    """Logger that creates JSON manifests and CSV summaries"""

    def __init__(self, output_dir: str = "output"):
        """
        Initialize structured logger.

        Args:
            output_dir: Base output directory
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        # Setup Python logging
        self.logger = logging.getLogger("StableNew")

        # Track handlers added by this instance
        self._handlers_added: list[logging.Handler] = []
        self._closed: bool = False

        # Register this instance in the global registry
        _structured_logger_registry.add(self)

    def close(self) -> None:
        """
        Close this logger instance: flush, close, and remove all attached handlers.

        Idempotent: safe to call multiple times.
        """
        if self._closed:
            return

        self._closed = True

        # Detach and close all handlers we added
        for handler in self._handlers_added:
            try:
                handler.flush()
                handler.close()
                self.logger.removeHandler(handler)
            except Exception:
                # Best-effort: continue even if one handler fails
                pass

        self._handlers_added.clear()

    def create_run_directory(self, run_name: str | None = None) -> Path:
        """
        Create a new run directory with improved architecture:
        single_date_time_folder/pack_name/combined_steps_folder/numbered_images.png

        Args:
            run_name: Optional name for the run

        Returns:
            Path to the run directory
        """
        if run_name is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_name = f"run_{timestamp}"

        run_dir = self.output_dir / run_name
        run_dir.mkdir(exist_ok=True, parents=True)

        # NOTE: Pack-specific subdirectories will be created as needed
        # Structure: run_dir / pack_name / steps_folder / images
        # No longer pre-creating generic subdirectories

        self.logger.info(f"Created run directory: {run_dir}")
        return run_dir

    def create_pack_directory(self, run_dir: Path, pack_name: str) -> Path:
        """
        Create directory structure for a specific pack with traditional pipeline folders.

        Args:
            run_dir: Main run directory
            pack_name: Name of the prompt pack (without .txt extension)

        Returns:
            Path to the pack directory
        """
        # Remove .txt extension if present and add _pack suffix
        clean_pack_name = pack_name.replace(".txt", "")
        if not clean_pack_name.endswith("_pack"):
            clean_pack_name += "_pack"

        pack_dir = run_dir / clean_pack_name
        pack_dir.mkdir(exist_ok=True, parents=True)

        # Create traditional pipeline subdirectories within pack
        (pack_dir / "txt2img").mkdir(exist_ok=True)
        (pack_dir / "img2img").mkdir(exist_ok=True)
        (pack_dir / "adetailer").mkdir(exist_ok=True)
        (pack_dir / "upscaled").mkdir(exist_ok=True)
        (pack_dir / "video").mkdir(exist_ok=True)
        (pack_dir / "manifests").mkdir(exist_ok=True)

        self.logger.info(f"Created pack directory with pipeline folders: {pack_dir}")
        return pack_dir

    def save_manifest(self, run_dir: Path, image_name: str, metadata: dict[str, Any]) -> bool:
        """
        Save JSON manifest for an image.

        Args:
            run_dir: Run directory
            image_name: Name of the image
            metadata: Metadata to save

        Returns:
            True if saved successfully
        """
        manifest_dir = run_dir / "manifests"
        manifest_dir.mkdir(exist_ok=True, parents=True)  # Ensure manifests directory exists

        manifest_path = manifest_dir / f"{image_name}.json"
        try:
            atomic_write_json(manifest_path, metadata, indent=2, ensure_ascii=False)
            self.logger.info(f"Saved manifest: {manifest_path.name}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save manifest: {e}")
            return False

    def save_pack_manifest(self, pack_dir: Path, image_name: str, metadata: dict[str, Any]) -> bool:
        """Save a per-image JSON manifest inside a pack directory.

        Args:
            pack_dir: The pack directory (contains txt2img/img2img/etc.)
            image_name: Base name of the image (without extension)
            metadata: Metadata dictionary to persist

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            manifest_dir = pack_dir / "manifests"
            manifest_dir.mkdir(exist_ok=True, parents=True)
            manifest_path = manifest_dir / f"{image_name}.json"
            atomic_write_json(manifest_path, metadata, indent=2, ensure_ascii=False)
            self.logger.info(f"Saved pack manifest: {manifest_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save pack manifest: {e}")
            return False

    def create_csv_summary(self, run_dir: Path, images_data: list) -> bool:
        """
        Create CSV rollup summary of all images.

        Args:
            run_dir: Run directory
            images_data: List of image metadata dictionaries

        Returns:
            True if created successfully
        """
        if not images_data:
            self.logger.warning("No image data to summarize")
            return False

        try:
            summary_file = run_dir / "summary.csv"

            # Define CSV headers
            headers = [
                "image_name",
                "stage",
                "timestamp",
                "prompt",
                "negative_prompt",
                "steps",
                "sampler",
                "cfg_scale",
                "width",
                "height",
                "seed",
                "model",
                "file_path",
                "file_size",
            ]

            with open(summary_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()

                for img_data in images_data:
                    # Extract config data safely
                    config = img_data.get("config", {})

                    # Get file size if file exists
                    file_size = ""
                    if "path" in img_data:
                        try:
                            file_path = Path(img_data["path"])
                            if file_path.exists():
                                file_size = file_path.stat().st_size
                        except (OSError, ValueError):
                            pass

                    row = {
                        "image_name": img_data.get("name", ""),
                        "stage": img_data.get("stage", ""),
                        "timestamp": img_data.get("timestamp", ""),
                        "prompt": img_data.get("prompt", ""),
                        "negative_prompt": config.get("negative_prompt", ""),
                        "steps": config.get("steps", ""),
                        "sampler": config.get("sampler_name", ""),
                        "cfg_scale": config.get("cfg_scale", ""),
                        "width": config.get("width", ""),
                        "height": config.get("height", ""),
                        "seed": config.get("seed", ""),
                        "model": img_data.get("model", ""),
                        "file_path": img_data.get("path", ""),
                        "file_size": file_size,
                    }
                    writer.writerow(row)

            self.logger.info(f"Created CSV summary: {summary_file}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to create CSV summary: {e}")
            return False

    def create_pack_csv_summary(
        self, summary_path: Path, summary_data: list[dict[str, Any]]
    ) -> bool:
        """
        Create CSV summary for a specific pack.

        Args:
            summary_path: Path where to save the CSV
            summary_data: List of summary entries

        Returns:
            True if created successfully
        """
        try:
            with open(summary_path, "w", newline="", encoding="utf-8") as csvfile:
                if not summary_data:
                    return False

                fieldnames = summary_data[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(summary_data)

            self.logger.info(f"Created pack CSV summary: {summary_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to create pack CSV summary: {e}")
            return False

    def create_rollup_manifest(self, run_dir: Path) -> bool:
        """
        Create rollup manifest from all individual JSON manifests.

        Args:
            run_dir: Run directory

        Returns:
            True if created successfully
        """
        try:
            manifests_dir = run_dir / "manifests"
            if not manifests_dir.exists():
                self.logger.warning("No manifests directory found")
                return True

            # Collect all manifest files
            manifest_files = list(manifests_dir.glob("*.json"))
            if not manifest_files:
                self.logger.warning("No manifest files found")
                return True

            # Read all manifests
            all_images = []
            for manifest_file in manifest_files:
                try:
                    with open(manifest_file, encoding="utf-8") as f:
                        manifest_data = json.load(f)
                        all_images.append(manifest_data)
                except Exception as e:
                    self.logger.error(f"Failed to read manifest {manifest_file.name}: {e}")

            if not all_images:
                self.logger.warning("No valid manifest data found")
                return True

            # Create rollup manifest
            rollup_data = {
                "run_info": {
                    "run_directory": str(run_dir),
                    "timestamp": datetime.now().isoformat(),
                    "total_images": len(all_images),
                },
                "images": all_images,
            }

            rollup_file = run_dir / "rollup_manifest.json"
            atomic_write_json(rollup_file, rollup_data, indent=2, ensure_ascii=False)

            # Create CSV summary
            self.create_csv_summary(run_dir, all_images)

            self.logger.info(f"Created rollup manifest with {len(all_images)} images")
            return True

        except Exception as e:
            self.logger.error(f"Failed to create rollup manifest: {e}")
            return False

    def record_run_status(self, run_dir: Path, status: str, reason: str | None = None) -> bool:
        """
        Persist the final status of a pipeline run (e.g., success, cancelled).

        Args:
            run_dir: Run directory for the pipeline.
            status: Status string such as "success", "cancelled", or "error".
            reason: Optional human-readable reason to record.
        """
        try:
            run_dir = Path(run_dir)
            run_dir.mkdir(exist_ok=True, parents=True)
            payload: dict[str, Any] = {
                "status": status,
                "timestamp": datetime.now().isoformat(),
            }
            if reason:
                payload["reason"] = reason
            status_path = run_dir / "run_status.json"
            atomic_write_json(status_path, payload, indent=2, ensure_ascii=False)
            self.logger.info(f"Recorded run status '{status}' at {status_path}")
            return True
        except Exception as exc:  # noqa: BLE001 - log and continue
            self.logger.error(f"Failed to record run status: {exc}")
            return False


def setup_logging(log_level: str = "INFO", log_file: str | None = None):
    """
    Setup logging configuration for console and file output.

    Note: The root logger level may be set to DEBUG by the GUI log handler
    to capture all messages for GUI display. This function sets the level
    for console/file handlers only.

    Args:
        log_level: Logging level for console output (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional log file path
    """
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Create console handler with specified level
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level.upper()))
    console_handler.setFormatter(logging.Formatter(log_format))

    handlers = [console_handler]

    if log_file:
        # Ensure the log file directory exists
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(getattr(logging, log_level.upper()))
        file_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(file_handler)

    # Configure root logger - but don't force its level if GUI handler needs DEBUG
    root_logger = logging.getLogger()

    # Only set root level if it's higher than the console level or not set
    # This allows GUI handler to capture DEBUG while console shows WARNING
    current_level = root_logger.level
    desired_level = getattr(logging, log_level.upper())
    if current_level == logging.NOTSET or current_level > desired_level:
        root_logger.setLevel(desired_level)

    # Add handlers
    for handler in handlers:
        root_logger.addHandler(handler)
