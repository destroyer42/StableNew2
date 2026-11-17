from __future__ import annotations

import os
import time
from unittest.mock import Mock

import pytest

from src.app.site_pairing_protocol import SCHEME, TICKET_SECONDS, PairingTickets, handle_protocol
from src.app.site_queue_bridge import SiteSession
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
    dialog = site_connection_dialog.SiteConnectionDialog(Mock(), app)
    listener = Mock()
    registry = Mock()
    monkeypatch.setattr(site_connection_dialog, "SiteListener", listener)
    monkeypatch.setattr(site_connection_dialog, "register_protocol", registry)
    monkeypatch.setattr(dialog, "_tick", Mock())
    dialog.start_default()
    assert dialog.dialog is None
    session = listener.call_args.args[0]
    assert session.output_catalog is not None
    assert session.pack_catalog is not None
    dialog.close()
    listener.return_value.close.assert_called_once()
