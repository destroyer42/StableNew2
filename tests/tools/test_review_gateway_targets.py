"""PHONE-CORE PS-1: the closed ``--target`` set (T12) and the separate staging settings (T11)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.app import review_gateway_store
from src.app.review_gateway_store import GatewaySettings, GatewaySettingsStore
from tools import review_gateway_deploy as deploy
from tools import review_gateway_targets as targets

ROOT = Path(__file__).resolve().parents[2]
NEW = "ab" * 20
PRODUCTION = GatewaySettings.build(
    "192.0.2.10:9443", "1" * 64, "production-secret-0123456789-abcdefgh"
)
STAGING_VALUES = ("192.0.2.20:9443", "2" * 64, "staging-secret-0123456789-abcdefghijk")
PHONE_URL = "https://review-staging.example.ts.net"


def plain(data: bytes) -> bytes:
    """Stands in for DPAPI so the tests run everywhere."""

    return data[::-1]


@pytest.fixture
def local(monkeypatch, tmp_path) -> Path:
    """A throwaway local application data folder and no DPAPI."""

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for owner in (GatewaySettingsStore, targets.StagingPhoneStore):
        monkeypatch.setitem(owner.__init__.__kwdefaults__, "protect", plain)
        monkeypatch.setitem(owner.__init__.__kwdefaults__, "unprotect", plain)
    return tmp_path / "StableNew" / "review-gateway"


def configure(*, values=STAGING_VALUES, phone_url=PHONE_URL, target="staging") -> int:
    address, fingerprint, secret = values
    answers = iter([address, fingerprint, phone_url])
    return deploy.main(
        ["--target", target, "configure"],
        prompt=lambda _question: next(answers),
        secret_prompt=lambda _question: secret,
    )


@pytest.mark.parametrize(
    "target",
    [
        "prod",
        "Staging",
        "staging ",
        "staging;reboot",
        "$(reboot)",
        "../staging",
        "https://other.example",
        "root@192.0.2.1",
        "main",
        NEW,
        "",
    ],
)
def test_a_target_outside_the_set_is_refused_before_any_settings_are_read(
    monkeypatch, capsys, target
) -> None:
    def never(*_args, **_kwargs):
        raise AssertionError("settings were read for an unknown target")

    monkeypatch.setattr(deploy, "default_client", never)

    assert deploy.main(["--target", target, "request", NEW]) == deploy.EXIT_USAGE
    assert "invalid choice" in capsys.readouterr().err


def test_the_target_set_is_closed_and_defaults_to_production(monkeypatch) -> None:
    asked = []

    def client(target):
        asked.append(target)
        raise targets.NoSettings

    monkeypatch.setattr(deploy, "default_client", client)
    deploy.main(["status"])
    deploy.main(["--target", "production", "status"])
    deploy.main(["--target", "staging", "status"])

    assert targets.TARGETS == ("production", "staging")
    assert asked == ["production", "production", "staging"]


def test_the_deploy_tool_runs_no_command_and_builds_no_shell_string() -> None:
    for name in ("review_gateway_deploy.py", "review_gateway_targets.py"):
        source = (ROOT / "tools" / name).read_text(encoding="utf-8")
        assert not re.search(r"subprocess|os\.system|os\.popen|shell\s*=", source), name


def test_each_target_reads_its_own_settings_file(local, monkeypatch) -> None:
    pinned = []
    monkeypatch.setattr(deploy, "PinnedHttpsTransport", lambda settings: pinned.append(settings))
    monkeypatch.setattr(targets, "PinnedHttpsTransport", lambda settings: pinned.append(settings))
    GatewaySettingsStore().save(PRODUCTION)
    assert configure() == deploy.EXIT_OK

    deploy.default_client()
    deploy.default_client("staging")

    assert [settings.host for settings in pinned] == ["192.0.2.10", "192.0.2.20"]
    assert GatewaySettingsStore().path == local / "settings.dpapi"
    assert GatewaySettingsStore(name="staging").path == local / "settings-staging.dpapi"
    assert targets.StagingPhoneStore().path == local / "staging-phone.dpapi"


def test_configure_stores_staging_apart_and_never_prints_the_secret(local, capsys) -> None:
    GatewaySettingsStore().save(PRODUCTION)
    before = (local / "settings.dpapi").read_bytes()

    assert configure() == deploy.EXIT_OK

    assert (local / "settings.dpapi").read_bytes() == before
    assert GatewaySettingsStore(name="staging").load().secret == STAGING_VALUES[2]
    assert targets.StagingPhoneStore().load() == PHONE_URL
    shown = "".join(capsys.readouterr())
    assert STAGING_VALUES[2] not in shown and PRODUCTION.secret not in shown


def test_staging_alone_never_creates_or_changes_the_apps_settings(local) -> None:
    assert configure() == deploy.EXIT_OK

    assert not (local / "settings.dpapi").exists()
    assert GatewaySettingsStore().load() is None  # what StableNew reads


def test_configure_is_refused_for_production(local, capsys) -> None:
    assert configure(target="production") == deploy.EXIT_USAGE
    assert not local.exists()
    assert "Phone review gateway" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("values", "shared"),
    [
        (("192.0.2.10:9443", "2" * 64, STAGING_VALUES[2]), "address"),
        (("192.0.2.10:9555", "2" * 64, STAGING_VALUES[2]), "address"),
        (("192.0.2.20:9443", "1" * 64, STAGING_VALUES[2]), "certificate fingerprint"),
        (("192.0.2.20:9443", "2" * 64, PRODUCTION.secret), "sync secret"),
    ],
)
def test_production_values_are_refused_as_staging(local, capsys, values, shared) -> None:
    GatewaySettingsStore().save(PRODUCTION)

    assert configure(values=values) == deploy.EXIT_USAGE

    assert not (local / "settings-staging.dpapi").exists()
    err = capsys.readouterr().err
    assert shared in err and values[2] not in err


def test_staging_that_became_production_is_refused_when_used(local, capsys) -> None:
    assert configure() == deploy.EXIT_OK
    # Later, the app is pointed at that gateway: the staging commands must stop.
    GatewaySettingsStore().save(GatewaySettings.build(*STAGING_VALUES))

    assert deploy.main(["--target", "staging", "request", NEW]) == deploy.EXIT_USAGE
    assert "Refused" in capsys.readouterr().err


def test_unreadable_production_settings_stop_staging(local) -> None:
    assert configure() == deploy.EXIT_OK
    (local / "settings.dpapi").write_bytes(b"not settings")

    with pytest.raises(targets.TargetMixup):
        targets.staging_settings()


def test_without_staging_settings_the_tool_says_how_to_make_them(local, capsys) -> None:
    assert deploy.main(["--target", "staging", "status"]) == deploy.EXIT_USAGE
    assert targets.CONFIGURE_HINT in capsys.readouterr().err


@pytest.mark.parametrize(
    "url",
    [
        "http://review-staging.example.ts.net",  # the cookie never travels in clear text
        "https://review-staging.example.ts.net/path",
        "https://user@review-staging.example.ts.net",
        "https://review-staging.example.ts.net?x=1",
        "https://review-staging.example.ts.net:0",
        "https://review-staging.example.ts.net:port",
        "review-staging.example.ts.net",
        "file:///etc/passwd",
        "https://",
    ],
)
def test_a_phone_address_is_https_and_a_host_only(url) -> None:
    with pytest.raises(ValueError):
        targets.parse_phone_url(url)


def test_plain_http_is_only_for_a_gateway_on_this_pc() -> None:
    assert targets.parse_phone_url("http://localhost:8443/") == "http://localhost:8443"


def test_a_settings_name_comes_from_a_closed_set() -> None:
    for name in ("production", "../x", "other"):
        with pytest.raises(ValueError):
            GatewaySettingsStore(name=name)


def test_the_application_never_reads_the_staging_store() -> None:
    """T11: StableNew syncs only with the unnamed store, so it can never publish to staging."""

    defines = Path(review_gateway_store.__file__).resolve()
    built = []
    for path in (ROOT / "src").rglob("*.py"):
        source = path.read_text(encoding="utf-8", errors="replace")
        if path.resolve() != defines:
            assert "staging.dpapi" not in source and "review_gateway_targets" not in source, path
            assert not re.search(r"settings-staging|staging-phone", source), path
        built += re.findall(r"GatewaySettingsStore\(([^)]*)\)", source)
    assert built, "the application no longer builds the store: update this check"
    assert not any("name" in arguments for arguments in built)
