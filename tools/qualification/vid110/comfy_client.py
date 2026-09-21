"""Minimal HTTP client for an *external* ComfyUI (never starts, adopts or restarts it)."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests


class ComfyRunError(RuntimeError):
    """The queued prompt failed, was rejected, or timed out."""


class ComfyClient:
    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.client_id = f"vid110-{uuid.uuid4().hex[:12]}"

    def upload_image(self, path: Path) -> str:
        """Upload an owned input file through the public API; returns the stored name."""

        with path.open("rb") as handle:
            response = requests.post(
                f"{self.base}/upload/image",
                files={"image": (path.name, handle)},
                data={"overwrite": "true"},
                timeout=self.timeout,
            )
        response.raise_for_status()
        return str(response.json()["name"])

    def queue(self, workflow: dict[str, Any]) -> str:
        response = requests.post(
            f"{self.base}/prompt",
            json={"prompt": workflow, "client_id": self.client_id},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise ComfyRunError(f"prompt rejected ({response.status_code}): {response.text[:800]}")
        return str(response.json()["prompt_id"])

    def history(self, prompt_id: str) -> dict[str, Any] | None:
        response = requests.get(f"{self.base}/history/{prompt_id}", timeout=self.timeout)
        response.raise_for_status()
        return response.json().get(prompt_id)

    def running_prompt_ids(self) -> list[str]:
        queue = requests.get(f"{self.base}/queue", timeout=self.timeout).json()
        return [str(item[1]) for item in queue.get("queue_running", [])]

    def interrupt_own(self, prompt_id: str) -> bool:
        """Interrupt only if *our* prompt is the one running (never foreign work)."""

        if prompt_id not in self.running_prompt_ids():
            return False
        requests.post(f"{self.base}/interrupt", timeout=self.timeout)
        return True

    def wait(
        self,
        prompt_id: str,
        *,
        timeout: float,
        poll: float = 2.0,
        abort_reason: Callable[[], str] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            reason = abort_reason() if abort_reason else ""
            if reason:
                self.interrupt_own(prompt_id)
                raise ComfyRunError(f"aborted by safety guard: {reason}")
            entry = self.history(prompt_id)
            if entry is not None:
                status = entry.get("status", {})
                if status.get("status_str") == "error" or not status.get("completed", True):
                    raise ComfyRunError(json.dumps(status.get("messages", []))[:1500])
                return entry
            time.sleep(poll)
        self.interrupt_own(prompt_id)
        raise ComfyRunError(f"timed out after {timeout:.0f}s")

    def output_files(self, entry: dict[str, Any]) -> list[dict[str, str]]:
        files: list[dict[str, str]] = []
        for node_output in entry.get("outputs", {}).values():
            for key in ("images", "videos", "gifs"):
                files.extend(node_output.get(key, []))
        return files

    def download(self, descriptor: dict[str, str], target: Path) -> Path:
        response = requests.get(
            f"{self.base}/view",
            params={
                "filename": descriptor["filename"],
                "subfolder": descriptor.get("subfolder", ""),
                "type": descriptor.get("type", "output"),
            },
            timeout=120,
        )
        response.raise_for_status()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return target
