from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from src.api.http_transport import (
    HttpTransport,
    HttpTransportError,
    RequestPolicy,
)


class ComfyApiClient:
    """Typed client for a local ComfyUI.

    Every failure is an ``HttpTransportError`` subclass (``src.api.http_transport``).  In particular ``queue_prompt`` is
    never retried and raises ``DispatchOutcomeUnknown`` when the server may already have accepted the prompt: callers must
    treat that as "possibly running", not as "not started"."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8188",
        session: requests.Session | None = None,
    ) -> None:
        self._transport = HttpTransport(base_url, session)
        self.base_url = self._transport.base_url

    @property
    def session(self) -> requests.Session:
        return self._transport.session

    def close(self) -> None:
        self._transport.close()

    def get_system_stats(self, *, timeout: float = 5.0) -> dict[str, Any]:
        return self._get_json("/system_stats", timeout=timeout)

    def get_object_info(self, *, timeout: float = 10.0) -> dict[str, Any]:
        return self._get_json("/object_info", timeout=timeout)

    def get_queue(self, *, timeout: float = 5.0) -> dict[str, Any]:
        return self._get_json("/queue", timeout=timeout)

    def get_history(
        self,
        prompt_id: str | None = None,
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        normalized_prompt_id = str(prompt_id or "").strip()
        path = f"/history/{normalized_prompt_id}" if normalized_prompt_id else "/history"
        return self._get_json(path, timeout=timeout)

    def queue_prompt(self, payload: dict[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
        """Start a generation.  Not idempotent: never retried (see the class docstring)."""

        return self._transport.request_json(
            "POST",
            "/prompt",
            policy=RequestPolicy(timeout=timeout, idempotent=False),
            json=dict(payload or {}),
        )

    def interrupt(self, prompt_id: str | None = None, *, timeout: float = 5.0) -> None:
        """Ask Comfy to stop the prompt it is executing.

        With ``prompt_id`` the request names the prompt (current Comfy interrupts only that prompt if it is the one
        running).  Idempotent: stopping twice is the same as once."""

        body = {"prompt_id": str(prompt_id)} if prompt_id else {}
        self._transport.send(
            "POST",
            "/interrupt",
            policy=RequestPolicy(timeout=timeout, idempotent=True),
            json=body,
        )

    def delete_from_queue(self, prompt_ids: list[str], *, timeout: float = 5.0) -> None:
        """Remove still-pending prompts from Comfy's queue (a running prompt is not affected)."""

        self._transport.send(
            "POST",
            "/queue",
            policy=RequestPolicy(timeout=timeout, idempotent=True),
            json={"delete": [str(item) for item in prompt_ids]},
        )

    def upload_image(
        self,
        image_path: str | Path,
        *,
        image_type: str = "input",
        overwrite: bool = True,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        path = Path(image_path).expanduser()
        with path.open("rb") as handle:
            return self._transport.request_json(
                "POST",
                "/upload/image",
                policy=RequestPolicy(timeout=timeout, idempotent=True),
                files={"image": (path.name, handle, "application/octet-stream")},
                data={
                    "type": str(image_type or "input"),
                    "overwrite": "true" if overwrite else "false",
                },
            )

    def download_view(
        self,
        filename: str,
        destination: str | Path,
        *,
        subfolder: str = "",
        file_type: str = "output",
        timeout: float = 300.0,
    ) -> Path:
        """Fetch one produced file through Comfy's ``/view`` endpoint into ``destination``."""

        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        response = self._transport.send(
            "GET",
            "/view",
            policy=RequestPolicy(timeout=timeout, idempotent=True),
            params={"filename": filename, "subfolder": subfolder, "type": file_type},
            stream=True,
        )
        try:
            with target.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    if chunk:
                        handle.write(chunk)
        except requests.exceptions.RequestException as exc:
            raise HttpTransportError(
                f"GET /view: the download of {filename!r} was interrupted ({exc})",
                method="GET",
                path="/view",
            ) from exc
        finally:
            response.close()
        return target

    def _get_json(self, path: str, *, timeout: float) -> dict[str, Any]:
        return self._transport.request_json(
            "GET", path, policy=RequestPolicy(timeout=timeout, idempotent=True)
        )


__all__ = ["ComfyApiClient"]
