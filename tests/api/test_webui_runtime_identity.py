"""PR-IMG-FORGE-100: read-only WebUI-family runtime identity classification + guard (mocks only)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from src.api.client import SDWebUIClient
from src.api.webui_runtime_identity import (
    A1111_WEBUI_IDENTITY,
    FORGE_WEBUI_IDENTITY,
    UNKNOWN_RUNTIME_IDENTITY,
    UNKNOWN_WEBUI_IDENTITY,
    WebUIRuntimeIdentity,
    WebUIRuntimeIdentityMismatch,
    assert_runtime_matches_backend,
    classify_client_runtime,
    classify_runtime_identity,
    normalize_webui_runtime_identity,
    probe_endpoint_runtime_identity,
    probe_runtime_identity,
    resolve_configured_webui_runtime_identity,
)

FORGE_FLAGS = {"api": True, "forge_ref_a1111_home": None, "port": 7861}
FORGE_OPTIONS = {"forge_additional_modules": [], "forge_preset": "sdxl",
                 "forge_unet_storage_dtype": "Automatic"}
A1111_FLAGS = {"api": True, "port": 7860, "xformers": False}
MODULE_LIST = [{"model_name": "sdxl_vae.safetensors", "filename": "/m/VAE/sdxl_vae.safetensors"}]


def _fetcher(routes: dict[str, Any], calls: list[str] | None = None):
    def fetch(path: str) -> Any:
        if calls is not None:
            calls.append(path)
        return routes.get(path)

    return fetch


@pytest.mark.parametrize("flags", [FORGE_FLAGS, None, "upstream HTTP 500"])
def test_forge_positively_identified_from_options_and_sd_modules(flags) -> None:
    observed = classify_runtime_identity(flags, MODULE_LIST, None, options=FORGE_OPTIONS)
    assert observed.identity == FORGE_WEBUI_IDENTITY and observed.is_forge


def test_a1111_positively_identified_from_vae_route_without_forge_signature() -> None:
    observed = classify_runtime_identity(A1111_FLAGS, None, [], options={})
    assert observed.identity == A1111_WEBUI_IDENTITY and observed.is_a1111


@pytest.mark.parametrize(
    ("flags", "modules", "vae"),
    [
        (None, None, None),  # unreachable
        ({}, None, None),  # reachable but neither signature
        (FORGE_FLAGS, None, None),  # forge flags but no module listing: not a compatible Forge
        (A1111_FLAGS, MODULE_LIST, []),  # both routes answer: contradictory, never guessed
        ({"forge_unit": 1}, None, []),  # forge-looking key but not the reference flag
        ("<html>", [], []),  # non-mapping flags
    ],
)
def test_ambiguous_evidence_is_unknown(flags: Any, modules: Any, vae: Any) -> None:
    assert classify_runtime_identity(flags, modules, vae).identity == UNKNOWN_WEBUI_IDENTITY


@pytest.mark.parametrize("options,modules,vae,flags", [
    ({}, [], None, FORGE_FLAGS),  # flags and modules alone are insufficient
    (FORGE_OPTIONS, None, None, None),
    (FORGE_OPTIONS, {}, None, None),
    ([], [], None, None),
    ("<html>", [], None, None),
    ({"forge_unrecognized": True}, [], None, None),
    (FORGE_OPTIONS, [], [], FORGE_FLAGS),  # contradictory route signatures
    (FORGE_OPTIONS, [], {}, FORGE_FLAGS),  # malformed opposing route
    ({}, None, [], FORGE_FLAGS),  # contradictory flags/options
    ({}, {}, [], A1111_FLAGS),  # malformed module route cannot establish A1111
])
def test_weak_malformed_or_conflicting_options_evidence_is_unknown(options, modules, vae, flags):
    assert classify_runtime_identity(flags, modules, vae, options=options).identity == "unknown"


def test_optional_cmd_flags_failure_does_not_suppress_independent_forge_evidence():
    def fetch(path):
        if path.endswith("cmd-flags"):
            raise RuntimeError("HTTP 500 response validation error")
        return {"/sdapi/v1/options": FORGE_OPTIONS, "/sdapi/v1/sd-modules": []}.get(path)
    observed = probe_runtime_identity(fetch)
    assert observed.is_forge and not observed.evidence["cmd_flags_readable"]


def test_probe_uses_only_read_only_gets_and_stays_deterministic() -> None:
    forge_calls: list[str] = []
    forge = probe_runtime_identity(
        _fetcher(
            {"/sdapi/v1/cmd-flags": FORGE_FLAGS, "/sdapi/v1/sd-modules": MODULE_LIST,
             "/sdapi/v1/options": FORGE_OPTIONS}, forge_calls
        )
    )
    assert forge.is_forge
    assert forge_calls == ["/sdapi/v1/cmd-flags", "/sdapi/v1/options",
                           "/sdapi/v1/sd-modules", "/sdapi/v1/sd-vae"]

    a1111_calls: list[str] = []
    a1111 = probe_runtime_identity(
        _fetcher({"/sdapi/v1/cmd-flags": A1111_FLAGS, "/sdapi/v1/sd-vae": [],
                  "/sdapi/v1/options": {}}, a1111_calls)
    )
    assert a1111.is_a1111
    assert set(a1111_calls) <= {
        "/sdapi/v1/cmd-flags",
        "/sdapi/v1/options",
        "/sdapi/v1/sd-modules",
        "/sdapi/v1/sd-vae",
    }


def test_probe_never_raises_on_transport_failure() -> None:
    def boom(_path: str) -> Any:
        raise OSError("connection reset")

    assert probe_runtime_identity(boom) is UNKNOWN_RUNTIME_IDENTITY


def test_endpoint_probe_is_read_only_get_only_and_unreachable_is_unknown() -> None:
    seen: list[tuple[str, float]] = []

    def http_get(url: str, *, timeout: float) -> Any:
        seen.append((url, timeout))
        payloads = {
            "http://127.0.0.1:7861/sdapi/v1/cmd-flags": FORGE_FLAGS,
            "http://127.0.0.1:7861/sdapi/v1/options": FORGE_OPTIONS,
            "http://127.0.0.1:7861/sdapi/v1/sd-modules": MODULE_LIST,
        }
        return SimpleNamespace(status_code=200, json=lambda: payloads[url])

    assert probe_endpoint_runtime_identity("http://127.0.0.1:7861/", http_get=http_get).is_forge
    assert all(url.startswith("http://127.0.0.1:7861/sdapi/v1/") for url, _ in seen)

    def refused(*_a: Any, **_k: Any) -> Any:
        raise ConnectionError("refused")

    assert probe_endpoint_runtime_identity("http://127.0.0.1:1", http_get=refused).identity == (
        UNKNOWN_WEBUI_IDENTITY
    )

    not_found = Mock(status_code=404)
    assert probe_endpoint_runtime_identity(
        "http://127.0.0.1:1", http_get=lambda *_a, **_k: not_found
    ).identity == (UNKNOWN_WEBUI_IDENTITY)


# --------------------------------------------------------------------------------------------
# Guard matrix: backend identity x observed endpoint identity
# --------------------------------------------------------------------------------------------

FORGE = WebUIRuntimeIdentity(FORGE_WEBUI_IDENTITY)
A1111 = WebUIRuntimeIdentity(A1111_WEBUI_IDENTITY)


def test_guard_a1111_backend_allows_a1111_and_unclassified_but_rejects_forge() -> None:
    assert_runtime_matches_backend(A1111_WEBUI_IDENTITY, A1111)
    assert_runtime_matches_backend(A1111_WEBUI_IDENTITY, UNKNOWN_RUNTIME_IDENTITY)
    with pytest.raises(WebUIRuntimeIdentityMismatch, match="Generation was not dispatched"):
        assert_runtime_matches_backend(A1111_WEBUI_IDENTITY, FORGE)


def test_guard_forge_backend_requires_a_positively_identified_forge() -> None:
    assert_runtime_matches_backend(FORGE_WEBUI_IDENTITY, FORGE)
    for observed in (A1111, UNKNOWN_RUNTIME_IDENTITY):
        with pytest.raises(WebUIRuntimeIdentityMismatch, match="positively identified Forge"):
            assert_runtime_matches_backend(FORGE_WEBUI_IDENTITY, observed)


def test_guard_rejects_non_webui_family_backend_ids() -> None:
    with pytest.raises(ValueError):
        assert_runtime_matches_backend("comfy", FORGE)


# --------------------------------------------------------------------------------------------
# Client seam
# --------------------------------------------------------------------------------------------


def test_client_probe_is_read_only_and_classifies_through_the_session() -> None:
    client = SDWebUIClient(base_url="http://127.0.0.1:7861", options_write_enabled=False)
    payloads = {
        "/sdapi/v1/cmd-flags": FORGE_FLAGS,
        "/sdapi/v1/options": FORGE_OPTIONS,
        "/sdapi/v1/sd-modules": MODULE_LIST,
    }
    methods: list[str] = []

    def get(url: str, **_kwargs: Any) -> Any:
        methods.append("GET")
        path = url.replace("http://127.0.0.1:7861", "")
        response = Mock(status_code=200 if path in payloads else 404)
        response.json.return_value = payloads.get(path)
        return response

    client._session.get = get  # type: ignore[method-assign]
    client._session.request = Mock(side_effect=AssertionError("probe must not use request()"))
    assert client.probe_runtime_identity().is_forge
    assert set(methods) == {"GET"}


def test_classify_client_runtime_degrades_to_unknown_for_clients_without_a_probe() -> None:
    assert classify_client_runtime(None) is UNKNOWN_RUNTIME_IDENTITY
    assert classify_client_runtime(object()) is UNKNOWN_RUNTIME_IDENTITY
    # A bare Mock answers any attribute with a Mock; that is not an identity.
    assert classify_client_runtime(Mock()) is UNKNOWN_RUNTIME_IDENTITY
    broken = SimpleNamespace(probe_runtime_identity=Mock(side_effect=RuntimeError("down")))
    assert classify_client_runtime(broken) is UNKNOWN_RUNTIME_IDENTITY
    forge_client = SimpleNamespace(probe_runtime_identity=lambda: FORGE)
    assert classify_client_runtime(forge_client).is_forge


# --------------------------------------------------------------------------------------------
# Configured identity
# --------------------------------------------------------------------------------------------


def test_configured_identity_defaults_to_a1111_and_never_infers_from_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", raising=False)
    assert resolve_configured_webui_runtime_identity({}) == A1111_WEBUI_IDENTITY
    assert resolve_configured_webui_runtime_identity(None) == A1111_WEBUI_IDENTITY
    # A workdir or model name that merely contains "forge" is never evidence.
    settings = {"webui_workdir": "D:/forge", "webui_base_url": "http://forge:7860"}
    assert resolve_configured_webui_runtime_identity(settings) == A1111_WEBUI_IDENTITY
    assert (
        resolve_configured_webui_runtime_identity({"webui_runtime_identity": "forge_webui"})
        == FORGE_WEBUI_IDENTITY
    )


def test_unrecognized_configured_identity_is_rejected_not_coerced() -> None:
    with pytest.raises(ValueError):
        normalize_webui_runtime_identity("forge")
    assert normalize_webui_runtime_identity("") == A1111_WEBUI_IDENTITY
    # The resolver logs and degrades to A1111; the dispatch-time guard still fails closed.
    assert (
        resolve_configured_webui_runtime_identity({"webui_runtime_identity": "forge"})
        == A1111_WEBUI_IDENTITY
    )


def test_environment_fallback_is_used_only_when_setting_is_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", "forge_webui")
    assert resolve_configured_webui_runtime_identity({}) == FORGE_WEBUI_IDENTITY
    assert (
        resolve_configured_webui_runtime_identity({"webui_runtime_identity": "a1111_webui"})
        == A1111_WEBUI_IDENTITY
    )
