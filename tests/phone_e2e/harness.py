"""The PHONE-CORE PC-0 browser harness: a real gateway on loopback, the PC played through the real sync API, and touch.

Nothing here reaches a network, a container, the PC app or the deployed gateway. The gateway is the code under
``services/review_gateway`` with temporary directories; the phone is headless Chromium driven by Playwright.
"""

from __future__ import annotations

import hashlib
import json
import struct
import threading
import time
import uuid
import zlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tests.review_gateway_service.conftest import SCHEMA_PATH, SCHEMA_VERSION, SECRET

RUN = "20261125_101500_pack"
CODE = "K7QF2M9D"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RealClock:
    """The gateway's clock: real time, so the page's own clock and the gateway's agree."""

    def __call__(self) -> datetime:
        return datetime.now(UTC)

    def stamp(self, **delta: float) -> str:
        return (self() + timedelta(**delta)).isoformat().replace("+00:00", "Z")


def png(width: int, height: int, colour: tuple[int, int, int]) -> bytes:
    """A real, decodable PNG of one colour with a darker band, so items differ visibly."""

    red, green, blue = colour
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter: none
        shade = 0.6 if height // 3 <= y < 2 * height // 3 else 1.0
        rows += bytes((int(red * shade), int(green * shade), int(blue * shade))) * width

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return (
            struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows)))
        + chunk(b"IEND", b"")
    )


_COLOURS = [
    (200, 60, 60),
    (60, 160, 70),
    (60, 90, 200),
    (200, 170, 40),
    (150, 60, 170),
    (40, 170, 170),
]


def _corrupting(app: Any, ending: str) -> Any:
    async def wrapped(scope: Any, receive: Any, send: Any) -> None:
        async def damaged(message: Any) -> None:
            if message["type"] == "http.response.body" and message.get("body"):
                body = message["body"]
                message = {**message, "body": body[:-1] + (b"." if body[-1:] != b"." else b",")}
            await send(message)

        hit = scope["type"] == "http" and scope["path"].endswith(ending)
        await app(scope, receive, damaged if hit else send)

    return wrapped


class TestGateway:
    """One gateway: the phone app served on loopback for the browser, the sync app called in process as the PC."""

    __test__ = False  # not a pytest test class

    def __init__(self, root: Path) -> None:
        from review_gateway.app import Gateway
        from review_gateway.config import Settings
        from starlette.testclient import TestClient

        root.mkdir(parents=True, exist_ok=True)
        secret_file = root / "sync_secret"
        secret_file.write_text(SECRET + "\n", encoding="utf-8")
        secret_file.chmod(0o600)
        self.clock = RealClock()
        settings = Settings(
            data_dir=root / "data",
            media_dir=root / "media",
            secret_file=secret_file,
            schema_file=SCHEMA_PATH,
            sync_host="127.0.0.1",
        )
        self.gateway = Gateway(settings, clock=self.clock)
        self.store = self.gateway.store
        self.sync = TestClient(
            self.gateway.sync_app(),
            base_url="https://gateway.test",
            headers={"Authorization": f"Bearer {SECRET}"},
        )
        self.root = root
        self._app = self.gateway.phone_app()
        self._port = 0
        self.start()
        # "localhost", not 127.0.0.1: a secure context in which Chromium keeps the Secure session cookie.
        self.url = f"http://localhost:{self._port}"

    def start(self) -> None:
        """Serve the phone app; after ``stop``, on the same port, so the phone finds it at the same origin."""

        import uvicorn

        config = uvicorn.Config(
            self._app, host="127.0.0.1", port=self._port, log_level="warning", lifespan="off"
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, name="phone-e2e-gateway", daemon=True
        )
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started:
            if time.monotonic() > deadline or not self._thread.is_alive():
                raise RuntimeError("the test gateway did not start")
            time.sleep(0.02)
        self._port = self._server.servers[0].sockets[0].getsockname()[1]

    def stop(self) -> None:
        """Nothing listens any more, as when the phone cannot reach the gateway."""

        self._server.should_exit = True
        self._thread.join(timeout=10)

    def deploy(self, static_root: Path, commit: str, *, corrupt: str | None = None) -> None:
        """Restart on the same address with another static tree and commit, as an installed update does.

        ``corrupt`` names a path whose last byte is changed on the way out, as a damaged download would be.
        """

        from review_gateway.phone_app import build_phone_app

        release = self.root / f"release-{commit[:8]}"
        release.mkdir(exist_ok=True)
        (release / "source.json").write_text(json.dumps({"commit": commit}), encoding="utf-8")
        app = build_phone_app(
            self.store, self.clock, self.gateway.ratings, release, static_root=static_root
        )
        self.stop()
        self._app = app if corrupt is None else _corrupting(app, corrupt)
        self.start()

    def close(self) -> None:
        self.stop()
        self.sync.close()

    # --- the PC, through the real sync API ---------------------------------------------------------------------

    def publish(
        self,
        name: str,
        *,
        run_id: str = RUN,
        source: str = "pipeline",
        parent: dict[str, str] | None = None,
        colour: int = 0,
        info: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Publish one image item with real thumb, preview and original PNGs; return its ``item_ref``."""

        tint = _COLOURS[colour % len(_COLOURS)]
        blobs = {
            "thumb_320": png(32, 48, tint),
            "preview_1080": png(120, 180, tint),
            # Bytes after IEND keep it decodable and give each item its own digest.
            "original": png(240, 360, tint) + name.encode(),
        }
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "type": "item_manifest",
            "item": {"library_id": f"lib-{name:_<8}", "sha256": sha(blobs["original"])},
            "kind": "image",
            "run_id": run_id,
            "created_at": self.clock.stamp(),
            "media": {
                variant: {"sha256": sha(data), "bytes": len(data), "content_type": "image/png"}
                for variant, data in blobs.items()
            },
            "display": {"model": "juggernaut", "prompt_excerpt": "a <b>lighthouse</b>", "seed": 42},
            "source": source,
        }
        if parent is not None:
            manifest["parent"] = parent
        if info is not None:
            manifest["info"] = info
        response = self.sync.post("/sync/v1/items", json=manifest)
        assert response.status_code == 200, response.text
        by_digest = {sha(data): data for data in blobs.values()}
        for digest in response.json()["missing"]:
            uploaded = self.sync.put(f"/sync/v1/media/{digest}", content=by_digest[digest])
            assert uploaded.status_code in (200, 201), uploaded.text
        return manifest["item"]

    def offer(self, code: str = CODE, scopes: tuple[str, ...] = ("review",)) -> None:
        salt = uuid.uuid4().hex
        offer = {
            "schema_version": SCHEMA_VERSION,
            "type": "pairing_offer",
            "offer_id": str(uuid.uuid4()),
            "code_salt": salt,
            "code_sha256": sha((salt + code).encode()),
            "scopes": list(scopes),
            "device_label": "Pixel",
            "expires_at": self.clock.stamp(seconds=300),
        }
        response = self.sync.post("/sync/v1/pairing-offers", json=offer)
        assert response.is_success, response.text

    def outbox_page(self, cursor: str = "") -> dict[str, Any]:
        query = f"?limit=500&cursor={cursor}" if cursor else "?limit=500"
        response = self.sync.get(f"/sync/v1/outbox{query}")
        assert response.status_code == 200, response.text
        return response.json()

    def outbox(self) -> list[dict[str, Any]]:
        """Every record the PC would list now, oldest first (all pages)."""

        records: list[dict[str, Any]] = []
        cursor = ""
        while True:
            page = self.outbox_page(cursor)
            records += page["records"]
            cursor = page.get("next_cursor") or ""
            if not cursor:
                return records

    def acknowledge(self, record_id: str, outcome: str = "applied", **fields: Any) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "type": "acknowledgement",
            "record_id": record_id,
            "outcome": outcome,
            "acknowledged_at": self.clock.stamp(),
            **fields,
        }
        response = self.sync.post("/sync/v1/acknowledgements", json=payload)
        assert response.is_success, response.text

    def pc_status(self, head: str, main: str) -> None:
        body = {
            "schema_version": SCHEMA_VERSION,
            "type": "pc_status",
            "published_at": self.clock.stamp(),
            "checkout": {
                "head_sha": head,
                "origin_main_sha": main,
                "commits_behind": 3,
                "fetched_at": self.clock.stamp(minutes=-5),
            },
            "queue": {"state": "idle", "queued": 0},
            "remote_update_enabled": True,
            "update": {"state": "idle"},
        }
        response = self.sync.put("/sync/v1/pc-status", json=body)
        assert response.status_code == 200, response.text

    def rating_task(self, task: dict[str, Any]) -> None:
        response = self.sync.post("/sync/v1/rating-tasks", json=task)
        assert response.status_code == 200, response.text
        assert response.json()["missing"] == [], response.text

    def rating_submissions(self) -> list[dict[str, Any]]:
        response = self.sync.get("/sync/v1/rating-submissions")
        assert response.status_code == 200, response.text
        return response.json()["submissions"]


def decisions(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if record.get("kind", "decision") == "decision"]


def wait_for(
    condition: Callable[[], Any],
    *,
    timeout: float = 10.0,
    what: str = "condition",
    page: Any = None,
) -> Any:
    """Poll a gateway-side condition: the page sends on its own timers.

    Pass ``page`` while a Playwright route handler is installed: the sync API runs handlers only while the test
    thread waits inside Playwright, so the poll then waits with ``page.wait_for_timeout`` instead of sleeping.
    """

    deadline = time.monotonic() + timeout
    while True:
        value = condition()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        if page is not None:
            page.wait_for_timeout(50)
        else:
            time.sleep(0.05)


def swipe(page: Any, dx: float, dy: float, *, selector: str = ".stage", steps: int = 8) -> None:
    """A real touch swipe from the middle of ``selector``; Chromium turns it into touch pointer events."""

    box = page.locator(selector).first.bounding_box()
    assert box, f"{selector} is not on screen"
    x0, y0 = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    cdp = page.context.new_cdp_session(page)
    try:
        cdp.send(
            "Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x0, "y": y0}]}
        )
        for step in range(1, steps + 1):
            point = {"x": x0 + dx * step / steps, "y": y0 + dy * step / steps}
            cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [point]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    finally:
        cdp.detach()


# --- phone steps ------------------------------------------------------------------------------------------------


def pair(phone: Any, gateway: TestGateway, scopes: tuple[str, ...] = ("review",)) -> None:
    """Offer a code from the PC, enter it on the phone and wait for the home screen."""

    from playwright.sync_api import expect

    gateway.offer(scopes=scopes)
    phone.goto("/")
    phone.get_by_label("Pairing code").fill(CODE)
    phone.get_by_role("button", name="Pair this phone").click()
    expect(phone.locator("#title")).to_have_text("Review")


def release_held(phone: Any) -> None:
    """What leaving the page does: the decision still held for Undo is sent now (``pagehide``)."""

    phone.evaluate("window.dispatchEvent(new Event('pagehide'))")


def ready(phone: Any) -> None:
    """Wait until the item on screen can be decided, as a person would.

    The decision buttons stay off until the item has loaded, and for 250 ms after the page moves on a decision is
    ignored so that a double tap never decides the next item unseen. Waiting that out keeps these tests free of the
    page's internals, which become module-private in PC-1a.
    """

    from playwright.sync_api import expect

    expect(phone.get_by_role("button", name="Keep", exact=True)).to_be_enabled()
    phone.wait_for_timeout(300)
