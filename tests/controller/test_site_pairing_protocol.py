from __future__ import annotations

import os
import time
from unittest.mock import Mock

import pytest

from src.app.site_pairing_protocol import SCHEME, TICKET_SECONDS, PairingTickets, handle_protocol
from src.app.site_queue_bridge import DESKTOP_SECONDS, PAIR_SECONDS, SiteSession
from src.gui import site_connection_dialog
from tests.controller.test_site_queue_bridge import request


def test_protocol_does_not_pass_uri_to_the_launcher_or_open_a_second_instance(tmp_path):
    (tmp_path / ".venv").mkdir()
    tickets = PairingTickets(tmp_path)
    launch = Mock()
    first, second, third = "a" * 32, "b" * 32, "c" * 32
    handle_protocol(f"{SCHEME}://connect/{first}", tickets, lambda: True, launch)
    launch.assert_not_called()
    assert tickets.consume(first)
    handle_protocol(f"{SCHEME}://connect/{second}", tickets, lambda: False, launch)
    handle_protocol(f"{SCHEME}://connect/{third}", tickets, lambda: False, launch)
    launch.assert_called_once_with()
    assert tickets.consume(second) and tickets.consume(third)
    with pytest.raises(ValueError):
        handle_protocol(f"{SCHEME}://connect/{first}?run=anything", tickets, lambda: False, launch)
    launch.assert_called_once()


def test_site_claim_requires_origin_and_one_matching_fresh_ticket(tmp_path):
    (tmp_path / ".venv").mkdir()
    tickets = PairingTickets(tmp_path)
    session = SiteSession(claim_ticket=tickets.consume)
    nonce = "d" * 32
    route = f"/v1/operator-pair/{nonce}"

    tickets.offer(nonce)
    assert request(session, "POST", route, origin="https://other.invalid")[0] == 403
    assert request(session, "POST", route, host="localhost:49381")[0] == 403
    assert request(session, "POST", route, body=b"{}")[0] == 400
    assert request(session, "POST", route)[2] == {"code": session.code}
    assert request(session, "POST", route)[2] == {"error": "pairing_pending"}

    tickets.offer(nonce)
    expired = time.time() - TICKET_SECONDS - 1
    os.utime(tickets.directory / f"{nonce}.ticket", (expired, expired))
    assert request(session, "POST", route)[0] == 409
    tickets.offer(nonce)
    session.revoke()
    assert request(session, "POST", route)[0] == 409


def test_desktop_activity_extends_only_authenticated_live_pairing(monkeypatch):
    from src.app import site_queue_bridge

    now = 30.0
    monkeypatch.setattr(site_queue_bridge, "time", Mock(monotonic=lambda: now))
    session = SiteSession()
    original_expiry = session.expires_at
    route = "/v1/operator-keepalive"
    now += PAIR_SECONDS - 1
    assert request(session, "POST", route, body=b"{}")[0] == 401
    assert (
        request(
            session, "POST", route, body=b"{}", token=session.code, origin="https://other.invalid"
        )[0]
        == 403
    )
    assert (
        request(session, "POST", route, body=b'{"unexpected":true}', token=session.code)[0] == 400
    )
    assert session.expires_at == original_expiry
    assert request(session, "POST", route, body=b"{}", token=session.code)[0] == 200
    assert session.expires_at == now + DESKTOP_SECONDS
    now += 2
    preview = request(session, "GET", "/v1/preview", token=session.code)
    assert preview[0] == 200
    assert preview[2]["desktop_keepalive"] is True
    now = session.expires_at
    assert request(session, "POST", route, body=b"{}", token=session.code)[0] == 401
    assert session.expired


def test_pairing_claim_starts_a_full_desktop_window(monkeypatch):
    from src.app import site_queue_bridge

    now = 30.0
    monkeypatch.setattr(site_queue_bridge, "time", Mock(monotonic=lambda: now))
    session = SiteSession(claim_ticket=lambda _nonce: True)
    now += PAIR_SECONDS - 1
    assert request(session, "POST", "/v1/operator-pair/" + "a" * 32)[0] == 200
    assert session.expires_at == now + DESKTOP_SECONDS
    session.revoke()
    assert not session.renew_desktop_lease()


def test_eight_hour_inactivity_is_exact_and_status_does_not_slide(monkeypatch):
    from src.app import site_queue_bridge

    now = 100.0
    monkeypatch.setattr(site_queue_bridge, "time", Mock(monotonic=lambda: now))
    session = SiteSession()
    assert request(session, "GET", "/v1/preview", token=session.code)[0] == 200
    deadline = session.expires_at
    assert deadline == now + 8 * 3600
    for elapsed in (16 * 60, 3600, 8 * 3600 - 1):
        now = 100.0 + elapsed
        status, _, payload = request(session, "GET", "/v1/connection", token=session.code)
        assert status == 200 and payload["version"] == 2
        assert payload["remaining_ms"] == int((deadline - now) * 1000)
        assert request(session, "GET", "/v1/preview", token=session.code)[0] == 200
        assert session.expires_at == deadline
    now = deadline
    expired, _, expired_payload = request(session, "GET", "/v1/connection", token=session.code)
    assert expired == 401 and expired_payload == {"error": "authorization_expired"}
    assert (
        request(session, "POST", "/v1/operator-keepalive", token=session.code, body=b"{}")[0] == 401
    )
    assert not session.renew_desktop_lease()
    assert session.connection_status()["state"] == "expired"


def test_live_activity_slides_but_disconnect_and_shutdown_are_terminal(monkeypatch):
    from src.app import site_queue_bridge

    now = 100.0
    monkeypatch.setattr(site_queue_bridge, "time", Mock(monotonic=lambda: now))
    session = SiteSession()
    assert session.renew_desktop_lease()
    now += 7 * 3600
    response = request(session, "POST", "/v1/operator-keepalive", token=session.code, body=b"{}")
    assert response[0] == 200
    assert session.expires_at == now + 8 * 3600
    assert (
        request(session, "POST", "/v1/operator-disconnect", token=session.code, body=b"{}")[0]
        == 204
    )
    assert session.connection_status()["state"] == "revoked"
    revoked, _, revoked_payload = request(session, "GET", "/v1/connection", token=session.code)
    assert revoked == 401 and revoked_payload == {"error": "pairing_revoked"}
    invalid, _, invalid_payload = request(session, "GET", "/v1/connection", token="x" * 43)
    assert invalid == 401 and invalid_payload == {"error": "pairing_required"}
    assert not session.renew_desktop_lease()
    assert request(session, "GET", "/v1/receipt", token=session.code)[0] == 401
    listener = site_queue_bridge.SiteListener.__new__(site_queue_bridge.SiteListener)
    listener._session = SiteSession()
    listener._stop = Mock()
    listener.begin_shutdown()
    assert listener._session.expired


def test_unclaimed_pairing_stays_short_and_cannot_enter_an_eight_hour_lease(monkeypatch):
    from src.app import site_queue_bridge

    now = 100.0
    monkeypatch.setattr(site_queue_bridge, "time", Mock(monotonic=lambda: now))
    session = SiteSession(claim_ticket=lambda _nonce: True)
    now += PAIR_SECONDS
    assert session.expired
    assert request(session, "GET", "/v1/preview", token=session.code)[0] == 401
    assert request(session, "POST", "/v1/operator-pair/" + "a" * 32)[0] == 409
    assert not session.renew_desktop_lease()


def test_startup_shares_configured_output_and_visible_packs_without_opening_a_dialog(
    tmp_path, monkeypatch
):
    output = tmp_path / "output"
    output.mkdir()
    packs = tmp_path / "packs"
    packs.mkdir()
    app = Mock(_is_shutting_down=False, _packs_dir=packs, packs=[])
    app.app_state.resources = {}
    app._config_manager.load_settings.return_value = {"output_dir": str(output)}
    phone = Mock()
    monkeypatch.setattr(site_connection_dialog, "SitePhoneConnector", Mock(return_value=phone))
    dialog = site_connection_dialog.SiteConnectionDialog(Mock(), app)
    listener = Mock()
    registry = Mock()
    monkeypatch.setattr(site_connection_dialog, "SiteListener", listener)
    monkeypatch.setattr(site_connection_dialog, "register_protocol", registry)
    monkeypatch.setattr(dialog, "_tick", Mock())
    dialog.start_default()
    phone.start.assert_called_once_with()
    assert dialog.dialog is None
    session = listener.call_args.args[0]
    assert session.output_catalog is not None
    assert session.pack_catalog is not None
    dialog._timer = "pending"
    dialog.shutdown()
    phone.close.assert_called_once_with(timeout=0)
    dialog.root.after_cancel.assert_not_called()
    listener.return_value.begin_shutdown.assert_called_once_with()
    assert dialog.listener is None and dialog._timer is None
