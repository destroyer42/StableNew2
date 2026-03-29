from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.pipeline.config_contract_v26 import validate_train_lora_execution_config

_WEIGHT_FILE_EXTENSIONS = {".safetensors", ".ckpt", ".pt"}
_ENV_TRAIN_COMMAND = "STABLENEW_TRAIN_LORA_COMMAND"


@dataclass
class CharacterTrainingSession:
    payload: dict[str, Any]
    command: list[str]
    process: Any
    output_dir: Path
    started_at: float
    log_tail: deque[str] = field(default_factory=deque)
    cancelled: bool = False
    reader_thread: threading.Thread | None = None


class CharacterEmbedder:
    """Thin subprocess wrapper for external train_lora integrations."""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        popen_factory: Callable[..., Any] | None = None,
        clock: Callable[[], float] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        log_tail_limit: int = 200,
    ) -> None:
        self._env = dict(env) if env is not None else dict(os.environ)
        self._popen_factory = popen_factory or subprocess.Popen
        self._clock = clock or time.time
        self._sleep_fn = sleep_fn or time.sleep
        self._log_tail_limit = max(10, int(log_tail_limit))
        self._active_session: CharacterTrainingSession | None = None

    def start(self, payload: Mapping[str, Any]) -> CharacterTrainingSession:
        normalized = self._normalized_payload(payload)
        if self._active_session and self._active_session.process.poll() is None:
            raise RuntimeError("A character training process is already running.")

        output_dir = Path(str(normalized["output_dir"])).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        working_dir = Path(
            str(
                normalized.get("trainer_working_dir")
                or normalized.get("working_dir")
                or output_dir
            )
        ).expanduser()
        working_dir.mkdir(parents=True, exist_ok=True)

        command = self._build_command(normalized)
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        process = self._popen_factory(
            command,
            cwd=str(working_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=dict(self._env),
            creationflags=creationflags,
        )
        session = CharacterTrainingSession(
            payload=normalized,
            command=command,
            process=process,
            output_dir=output_dir,
            started_at=self._clock(),
            log_tail=deque(maxlen=self._log_tail_limit),
        )
        stdout = getattr(process, "stdout", None)
        if stdout is not None:
            reader = threading.Thread(
                target=self._read_output,
                args=(session,),
                daemon=True,
                name="character-training-log-reader",
            )
            session.reader_thread = reader
            reader.start()
        self._active_session = session
        return session

    def poll(self, session: CharacterTrainingSession | None = None) -> dict[str, Any]:
        current = session or self._active_session
        if current is None:
            return self._status_payload(
                running=False,
                success=False,
                error="No active character training session.",
            )

        returncode = current.process.poll()
        running = returncode is None
        if not running and current.reader_thread and current.reader_thread.is_alive():
            current.reader_thread.join(timeout=0.2)

        weight_path: str | None = None
        error: str | None = None
        success = False
        if running:
            pass
        elif current.cancelled:
            error = "Character training cancelled."
        elif returncode == 0:
            weight_path = self._resolve_weight_path(current)
            if weight_path:
                success = True
            else:
                error = "Character training completed without a produced weight file."
        else:
            error = self._build_failure_message(current, returncode)

        return self._status_payload(
            session=current,
            running=running,
            success=success,
            error=error,
            returncode=returncode,
            weight_path=weight_path,
        )

    def cancel(
        self,
        session: CharacterTrainingSession | None = None,
        *,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        current = session or self._active_session
        if current is None:
            return self._status_payload(
                running=False,
                success=False,
                error="No active character training session.",
            )

        process = current.process
        if process.poll() is None:
            current.cancelled = True
            current.log_tail.append("[stablenew] termination requested")
            process.terminate()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                current.log_tail.append("[stablenew] process did not exit in time; killing")
                process.kill()
                process.wait(timeout=timeout)
        return self.poll(current)

    def run_to_completion(
        self,
        payload: Mapping[str, Any],
        *,
        cancel_token: Any | None = None,
        poll_interval: float = 0.1,
    ) -> dict[str, Any]:
        try:
            session = self.start(payload)
        except Exception as exc:
            return self._status_payload(
                running=False,
                success=False,
                error=str(exc),
            )

        while True:
            if (
                cancel_token is not None
                and callable(getattr(cancel_token, "is_cancelled", None))
                and cancel_token.is_cancelled()
            ):
                status = self.cancel(session)
                status["cancelled"] = True
                status["success"] = False
                status["error"] = status.get("error") or "Character training cancelled."
                return status

            status = self.poll(session)
            if not status.get("running"):
                return status
            self._sleep_fn(max(0.01, float(poll_interval)))

    @staticmethod
    def _normalized_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
        validated = validate_train_lora_execution_config(payload)
        nested = validated.get("train_lora") if isinstance(validated, dict) else None
        if isinstance(nested, Mapping):
            return dict(nested)
        return dict(validated)

    def _build_command(self, payload: Mapping[str, Any]) -> list[str]:
        command = self._resolve_command_value(payload.get("trainer_command"))
        if not command:
            command = self._resolve_command_value(self._env.get(_ENV_TRAIN_COMMAND))
        if not command:
            raise RuntimeError(
                "No train_lora trainer command configured. Provide train_lora.trainer_command "
                f"or set {_ENV_TRAIN_COMMAND}."
            )

        command.extend([
            "--character_name",
            str(payload["character_name"]),
            "--image_dir",
            str(payload["image_dir"]),
            "--output_dir",
            str(payload["output_dir"]),
            "--epochs",
            str(payload["epochs"]),
            "--learning_rate",
            str(payload["learning_rate"]),
        ])

        for field_name in (
            "base_model",
            "trigger_phrase",
            "rank",
            "network_alpha",
        ):
            value = payload.get(field_name)
            if value in (None, ""):
                continue
            command.extend([f"--{field_name}", str(value)])

        extra_args = payload.get("trainer_args") or payload.get("trainer_extra_args")
        if isinstance(extra_args, str) and extra_args.strip():
            command.extend(self._split_command(extra_args))
        elif isinstance(extra_args, (list, tuple)):
            command.extend(str(item).strip() for item in extra_args if str(item).strip())

        return command

    def _resolve_command_value(self, value: Any) -> list[str]:
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value or "").strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return self._split_command(text)

    @staticmethod
    def _split_command(text: str) -> list[str]:
        return shlex.split(text, posix=os.name != "nt")

    def _read_output(self, session: CharacterTrainingSession) -> None:
        stdout = getattr(session.process, "stdout", None)
        if stdout is None:
            return
        try:
            for raw_line in stdout:
                line = str(raw_line).rstrip()
                if line:
                    session.log_tail.append(line)
        finally:
            try:
                stdout.close()
            except Exception:
                pass

    def _resolve_weight_path(self, session: CharacterTrainingSession) -> str | None:
        explicit_path = session.payload.get("produced_weight_path") or session.payload.get("weight_path")
        if explicit_path:
            return str(Path(str(explicit_path)).expanduser().resolve())
        output_name = str(session.payload.get("output_name") or "").strip()
        if output_name:
            candidate = session.output_dir / output_name
            if candidate.exists():
                return str(candidate.resolve())

        candidates = [
            path
            for path in session.output_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in _WEIGHT_FILE_EXTENSIONS
        ]
        if not candidates:
            return None

        recent_candidates = [
            path for path in candidates if path.stat().st_mtime >= session.started_at - 1.0
        ]
        selected = recent_candidates or candidates
        selected.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return str(selected[0].resolve())

    @staticmethod
    def _build_failure_message(session: CharacterTrainingSession, returncode: int | None) -> str:
        tail = list(session.log_tail)
        tail_message = tail[-1] if tail else "Character training process failed."
        if returncode is None:
            return tail_message
        return f"{tail_message} (exit code {returncode})"

    def _status_payload(
        self,
        *,
        session: CharacterTrainingSession | None = None,
        running: bool,
        success: bool,
        error: str | None,
        returncode: int | None = None,
        weight_path: str | None = None,
    ) -> dict[str, Any]:
        log_tail = list(getattr(session, "log_tail", []) or [])
        command = list(getattr(session, "command", []) or [])
        output_dir = str(getattr(session, "output_dir", "") or "")
        duration_seconds = 0.0
        if session is not None:
            duration_seconds = max(0.0, self._clock() - session.started_at)
        return {
            "running": running,
            "success": success,
            "cancelled": bool(getattr(session, "cancelled", False)),
            "error": error,
            "returncode": returncode,
            "weight_path": weight_path,
            "log_tail": log_tail,
            "command": command,
            "output_dir": output_dir,
            "duration_seconds": duration_seconds,
            "character_name": str(getattr(session, "payload", {}).get("character_name", "") or ""),
        }