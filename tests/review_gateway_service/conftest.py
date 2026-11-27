"""Hermetic fixtures for the review gateway (RG-110): temp dirs, a fake clock and ASGI test clients.

The gateway is a separate deployable (``services/review_gateway``) that never imports ``src``; it is put on
``sys.path`` here so its tests run under the repository's one pytest configuration.
"""

from __future__ import annotations

import hashlib
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATEWAY_ROOT = ROOT / "services" / "review_gateway"
SCHEMA_PATH = ROOT / "docs" / "schemas" / "stablenew.review-gateway-sync.v1.json"
SCHEMA_VERSION = "stablenew.review-gateway-sync.v1"
SECRET = "test-sync-secret-0123456789-abcdefghij"

if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 25, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)

    def stamp(self, **delta: float) -> str:
        return (self.now + timedelta(**delta)).isoformat().replace("+00:00", "Z")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Rig:
    """One gateway instance with both listeners' test clients and the PC/phone steps tests repeat."""

    def __init__(self, tmp_path: Path, clock: FakeClock, **overrides) -> None:
        from review_gateway.app import Gateway
        from review_gateway.config import Settings

        self.clock = clock
        tmp_path.mkdir(parents=True, exist_ok=True)
        secret_file = tmp_path / "sync_secret"
        secret_file.write_text(SECRET + "\n", encoding="utf-8")
        secret_file.chmod(0o600)
        self.settings = Settings(
            data_dir=tmp_path / "data",
            media_dir=tmp_path / "media",
            secret_file=secret_file,
            schema_file=SCHEMA_PATH,
            sync_host="127.0.0.1",
            **overrides,
        )
        self.gateway = Gateway(self.settings, clock=clock)
        self._clients: list = []
        self.sync = self.client(self.gateway.sync_app(), headers=self.auth())
        self.phone = self.new_phone()

    def client(self, app, headers=None):
        from starlette.testclient import TestClient

        client = TestClient(app, base_url="https://gateway.test", headers=headers or {})
        self._clients.append(client)
        return client

    def new_phone(self):
        return self.client(self.gateway.phone_app(), headers={"X-Review-Gateway": "1"})

    def close(self) -> None:
        for client in self._clients:
            client.close()

    @staticmethod
    def auth() -> dict[str, str]:
        return {"Authorization": f"Bearer {SECRET}"}

    # --- PC steps -------------------------------------------------------------------------------------------------

    def manifest(
        self,
        name: str = "one",
        *,
        run_id: str = "20261125_101500_pack",
        kind: str = "image",
        extra: dict[str, bytes] | None = None,
        batch: dict | None = None,
        source: str | None = None,
    ) -> tuple[dict, dict[str, bytes]]:
        """Return ``(item_manifest, {digest: bytes})`` for a small synthetic item."""

        original = f"original-{name}".encode() * 4
        blobs = {"thumb_320": f"thumb-{name}".encode(), "original": original}
        if kind == "video":
            blobs["mobile_video"] = bytes(range(256)) + name.encode()
        else:
            blobs["preview_1080"] = f"preview-{name}".encode() * 2
        blobs.update(extra or {})
        types = {
            "thumb_320": "image/jpeg",
            "preview_1080": "image/jpeg",
            "mobile_video": "video/mp4",
            "original": "video/mp4" if kind == "video" else "image/png",
        }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "type": "item_manifest",
            "item": {"library_id": f"lib-{name:_<8}", "sha256": sha(original)},
            "kind": kind,
            "run_id": run_id,
            "created_at": self.clock.stamp(),
            "media": {
                variant: {"sha256": sha(data), "bytes": len(data), "content_type": types[variant]}
                for variant, data in blobs.items()
            },
            "display": {"model": "juggernaut", "prompt_excerpt": "a <b>lighthouse</b>", "seed": 42},
        }
        if kind == "video":
            manifest["duration_s"] = 5.0
        if batch is not None:
            manifest["batch"] = batch
        if source is not None:
            manifest["source"] = source
        return manifest, {sha(data): data for data in blobs.values()}

    def publish(self, name: str = "one", **options) -> dict[str, str]:
        """Publish one item completely and return its ``item_ref``."""

        manifest, blobs = self.manifest(name, **options)
        response = self.sync.post("/sync/v1/items", json=manifest)
        assert response.status_code == 200, response.text
        for digest in response.json()["missing"]:
            uploaded = self.sync.put(f"/sync/v1/media/{digest}", content=blobs[digest])
            assert uploaded.status_code in (200, 201), uploaded.text
        return manifest["item"]

    def offer(
        self,
        code: str = "K7QF2M9D",
        *,
        scopes: tuple[str, ...] = ("review",),
        expires_in: float = 300,
        max_attempts: int | None = None,
        label: str = "Pixel",
    ) -> dict:
        salt = uuid.uuid4().hex
        offer = {
            "schema_version": SCHEMA_VERSION,
            "type": "pairing_offer",
            "offer_id": str(uuid.uuid4()),
            "code_salt": salt,
            "code_sha256": sha((salt + code).encode()),
            "scopes": list(scopes),
            "device_label": label,
            "expires_at": self.clock.stamp(seconds=expires_in),
        }
        if max_attempts is not None:
            offer["max_attempts"] = max_attempts
        return offer

    def pair(self, phone=None, code: str = "K7QF2M9D", **options) -> str:
        """Offer a code from the PC, enter it on ``phone`` and return the new device id."""

        phone = phone or self.phone
        assert self.sync.post(
            "/sync/v1/pairing-offers", json=self.offer(code, **options)
        ).is_success
        response = phone.post("/api/pair", json={"code": code})
        assert response.status_code == 200, response.text
        return response.json()["device_id"]

    def outbox(self, query: str = "") -> dict:
        response = self.sync.get(f"/sync/v1/outbox{query}")
        assert response.status_code == 200, response.text
        return response.json()

    def acknowledge(self, record_id: str, outcome: str = "applied", **fields):
        payload = {
            "schema_version": SCHEMA_VERSION,
            "type": "acknowledgement",
            "record_id": record_id,
            "outcome": outcome,
            "acknowledged_at": self.clock.stamp(),
            **fields,
        }
        return self.sync.post("/sync/v1/acknowledgements", json=payload)

    def confirm_uploads(self) -> None:
        """Stand in for Immich where a test is only about what happens after it has the keepers."""

        with self.gateway.store.write() as database:
            database.execute("UPDATE immich_upload SET state = 'done' WHERE state <> 'cancelled'")

    # --- phone steps ----------------------------------------------------------------------------------------------

    def decide(
        self,
        item: dict[str, str],
        verdict: str = "keep",
        *,
        favorite: bool = False,
        tags: tuple[str, ...] = (),
        key: str | None = None,
        phone=None,
    ):
        return (phone or self.phone).post(
            "/api/decisions",
            json={
                **item,
                "verdict": verdict,
                "favorite": favorite,
                "tags": list(tags),
                "idempotency_key": key or str(uuid.uuid4()),
            },
        )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def rig(tmp_path: Path, clock: FakeClock):
    instance = Rig(tmp_path, clock)
    yield instance
    instance.close()
