"""Listener rules (D9, S2), the secret file, the admin CLI (S11) and how the two listeners are served."""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import os
import stat

import pytest
from review_gateway.__main__ import main
from review_gateway.config import (
    ConfigError,
    Settings,
    create_secret,
    default_schema_file,
    load_settings,
    read_secret,
)
from review_gateway.server import server_configs

from tests.review_gateway_service.conftest import SCHEMA_PATH


def settings(tmp_path, **changes) -> Settings:
    base = Settings(
        data_dir=tmp_path / "data",
        media_dir=tmp_path / "media",
        secret_file=tmp_path / "sync_secret",
        schema_file=SCHEMA_PATH,
        sync_host="192.168.1.50",
        sync_tls_cert=tmp_path / "sync.crt",
        sync_tls_key=tmp_path / "sync.key",
    )
    return dataclasses.replace(base, **changes)


def config_file(tmp_path, extra: str = "", sync_host: str = "192.168.1.50"):
    path = tmp_path / "config.toml"
    extra += (
        f'sync_tls_cert = "{(tmp_path / "sync.crt").as_posix()}"\n'
        f'sync_tls_key = "{(tmp_path / "sync.key").as_posix()}"\n'
    )
    path.write_text(
        f'data_dir = "{(tmp_path / "data").as_posix()}"\n'
        f'media_dir = "{(tmp_path / "media").as_posix()}"\n'
        f'secret_file = "{(tmp_path / "sync_secret").as_posix()}"\n'
        f'sync_host = "{sync_host}"\n{extra}',
        encoding="utf-8",
    )
    return path


def test_the_defaults_are_the_two_documented_listeners(tmp_path) -> None:
    loaded = load_settings(config_file(tmp_path))

    loaded.check_listeners()
    assert (loaded.phone_host, loaded.phone_port) == ("127.0.0.1", 8443)
    assert loaded.sync_port == 9443
    assert loaded.schema_file == default_schema_file()
    assert loaded.schema_file.is_file()


@pytest.mark.parametrize(
    "changes",
    [
        {"phone_host": "0.0.0.0"},
        {"phone_host": "192.168.1.50"},
        {"sync_host": "0.0.0.0"},
        {"sync_host": "::"},
        {"sync_host": "100.101.102.103"},  # a tailnet address
        {"sync_host": "fd7a:115c:a1e0::1"},
        {"sync_host": "gateway.lan"},
        {"sync_port": 8443},
        {"sync_tls_key": None},
        {"sync_tls_cert": None},
        {"sync_tls_cert": None, "sync_tls_key": None},  # no plain HTTP on the LAN
    ],
)
def test_a_listener_that_would_widen_exposure_is_refused(tmp_path, changes) -> None:
    with pytest.raises(ConfigError):
        settings(tmp_path, **changes).check_listeners()


def test_a_misspelt_or_missing_setting_is_refused(tmp_path) -> None:
    with pytest.raises(ConfigError, match="phone_hots"):
        load_settings(config_file(tmp_path, 'phone_hots = "127.0.0.1"\n'))
    empty = tmp_path / "empty.toml"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(empty)


def test_the_secret_is_generated_once(tmp_path) -> None:
    path = tmp_path / "etc" / "sync_secret"

    assert create_secret(path) is True
    first = read_secret(path)
    assert create_secret(path) is False
    assert read_secret(path) == first
    assert len(first) >= 43
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_short_or_absent_secret_is_refused(tmp_path) -> None:
    path = tmp_path / "sync_secret"
    with pytest.raises(ConfigError):
        read_secret(path)
    path.write_text("guessable\n", encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(ConfigError):
        read_secret(path)


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_a_secret_other_users_can_read_is_refused(tmp_path) -> None:
    path = tmp_path / "sync_secret"
    create_secret(path)
    path.chmod(0o640)

    with pytest.raises(ConfigError, match="600"):
        read_secret(path)


def test_the_two_listeners_are_configured_separately(tmp_path) -> None:
    gateway_settings = settings(tmp_path)
    create_secret(gateway_settings.secret_file)

    phone, sync = server_configs(gateway_settings)

    assert (phone.host, phone.port) == ("127.0.0.1", 8443)
    assert (sync.host, sync.port) == ("192.168.1.50", 9443)
    assert sync.proxy_headers is False
    assert phone.access_log is False and sync.access_log is False
    assert phone.app is not sync.app
    assert {route.path for route in phone.app.routes}.isdisjoint(r.path for r in sync.app.routes)
    assert (sync.ssl_certfile, sync.ssl_keyfile) == (
        str(tmp_path / "sync.crt"),
        str(tmp_path / "sync.key"),
    )
    assert phone.ssl_certfile is None  # tailscale serve terminates TLS for the phone


def test_only_a_loopback_trial_may_serve_sync_without_a_certificate(tmp_path) -> None:
    trial = settings(tmp_path, sync_host="127.0.0.1", sync_tls_cert=None, sync_tls_key=None)
    create_secret(trial.secret_file)

    _phone, sync = server_configs(trial)

    assert sync.ssl_certfile is None


def test_the_fingerprint_the_desktop_pins_is_sha256_over_the_certificate_der(
    tmp_path, capsys
) -> None:
    der = bytes(range(200))
    encoded = base64.encodebytes(der).decode()
    (tmp_path / "sync.crt").write_text(
        f"-----BEGIN CERTIFICATE-----\n{encoded}-----END CERTIFICATE-----\n", encoding="ascii"
    )

    assert main(["--config", str(config_file(tmp_path)), "fingerprint"]) == 0

    assert capsys.readouterr().out == hashlib.sha256(der).hexdigest() + "\n"


def test_a_missing_certificate_has_no_fingerprint(tmp_path, capsys) -> None:
    assert main(["--config", str(config_file(tmp_path)), "fingerprint"]) == 2
    assert "sync.crt" in capsys.readouterr().err


def test_serving_refuses_an_unsafe_configuration(tmp_path, capsys) -> None:
    path = config_file(tmp_path, sync_host="0.0.0.0")
    create_secret(tmp_path / "sync_secret")

    assert main(["--config", str(path), "serve"]) == 2
    assert "sync_host" in capsys.readouterr().err


def test_init_secret_reports_the_file_and_never_the_value(tmp_path, capsys) -> None:
    path = config_file(tmp_path)

    assert main(["--config", str(path), "init-secret"]) == 0

    output = capsys.readouterr().out
    assert str(tmp_path / "sync_secret") in output.replace("/", os.sep)
    assert read_secret(tmp_path / "sync_secret").decode() not in output


def test_the_owner_can_list_and_revoke_devices_on_the_gateway(rig, tmp_path, capsys) -> None:
    device_id = rig.pair()
    path = config_file(tmp_path, f'schema_file = "{SCHEMA_PATH.as_posix()}"\n')

    assert main(["--config", str(path), "devices"]) == 0
    assert device_id in capsys.readouterr().out
    assert main(["--config", str(path), "revoke", device_id]) == 0
    assert rig.phone.get("/api/session").status_code == 401
    assert main(["--config", str(path), "revoke", "nobody-here"]) == 1


def test_device_ids_never_start_with_a_dash() -> None:
    # A leading "-" made `revoke <id>` parse the id as an option (seen as a CI flake about 1 run in 64).
    from review_gateway.store import new_device_id

    assert not any(new_device_id().startswith("-") for _ in range(2000))


def test_revoke_accepts_an_id_starting_with_a_dash_after_the_separator(tmp_path, capsys) -> None:
    path = config_file(tmp_path, f'schema_file = "{SCHEMA_PATH.as_posix()}"\n')

    assert main(["--config", str(path), "revoke", "--", "-not-enrolled"]) == 1
    assert "no such device: -not-enrolled" in capsys.readouterr().err


def test_status_and_purge_report_without_serving(rig, tmp_path, capsys) -> None:
    rig.publish()
    path = config_file(tmp_path)

    assert main(["--config", str(path), "status"]) == 0
    assert "items: 1" in capsys.readouterr().out
    assert main(["--config", str(path), "purge"]) == 0
    assert "items_purged: 0" in capsys.readouterr().out
