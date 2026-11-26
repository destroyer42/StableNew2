"""Serve the two listeners in one process, with retention and the Immich uploader beside them."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sqlite3
import threading
from collections.abc import Iterator

import uvicorn

from .app import Gateway
from .config import Settings

RETENTION_INTERVAL_S = 3600
_LOG = logging.getLogger("review_gateway")


class _Server(uvicorn.Server):
    """Signals are handled once for both servers, not by whichever installed its handler last."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


def server_configs(
    settings: Settings, gateway: Gateway | None = None
) -> tuple[uvicorn.Config, uvicorn.Config]:
    """``(phone, sync)``: loopback plain HTTP for ``tailscale serve``, and the LAN sync listener."""

    settings.check_listeners()
    gateway = gateway or Gateway(settings)
    common = {
        # Paths carry run folder names; the gateway logs no requests.
        "access_log": False,
        "proxy_headers": False,
        "server_header": False,
        "lifespan": "off",
        "timeout_graceful_shutdown": 10,
    }
    phone = uvicorn.Config(
        gateway.phone_app(), host=settings.phone_host, port=settings.phone_port, **common
    )
    sync = uvicorn.Config(
        gateway.sync_app(),
        host=settings.sync_host,
        port=settings.sync_port,
        ssl_certfile=str(settings.sync_tls_cert) if settings.sync_tls_cert else None,
        ssl_keyfile=str(settings.sync_tls_key) if settings.sync_tls_key else None,
        **common,
    )
    return phone, sync


async def _retention(gateway: Gateway) -> None:
    while True:
        try:
            summary = await asyncio.to_thread(gateway.retention)
        except (OSError, sqlite3.Error):
            _LOG.exception("retention failed; it runs again later")
        else:
            if any(summary.values()):
                _LOG.info("retention removed %s", summary)
        await asyncio.sleep(RETENTION_INTERVAL_S)


async def _run(gateway: Gateway, configs: tuple[uvicorn.Config, ...]) -> int:
    servers = [_Server(config) for config in configs]
    loop = asyncio.get_running_loop()

    def stop() -> None:
        for server in servers:
            server.should_exit = True

    for number in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(number, stop)
        except NotImplementedError:  # Windows, used only for local trials
            signal.signal(number, lambda *_: loop.call_soon_threadsafe(stop))
    retention = asyncio.create_task(_retention(gateway))
    # Its own thread, so a slow Immich never delays a request. Uploads are safe to cut off and repeat.
    finished = threading.Event()
    uploads = threading.Thread(
        target=gateway.uploader().run, args=(finished,), name="immich-uploader", daemon=True
    )
    uploads.start()
    tasks = [asyncio.create_task(server.serve()) for server in servers]
    # One listener ending (or failing to bind) ends the service so systemd restarts both.
    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    stop()
    await asyncio.gather(*tasks)
    retention.cancel()
    finished.set()
    await asyncio.to_thread(uploads.join, 5)
    return 0 if all(server.started for server in servers) else 1


def serve(settings: Settings) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings.check_listeners()
    gateway = Gateway(settings)
    return asyncio.run(_run(gateway, server_configs(settings, gateway)))
