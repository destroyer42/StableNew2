"""PR-IMG-FORGE-100: ForgeWebUIClient transport differences (HTTP faked, no network/GPU)."""

from __future__ import annotations

import pytest

from src.api.client import SDWebUIClient
from src.api.forge_client import ForgeVAEError, ForgeWebUIClient, normalize_sd_modules
from tests.helpers.fake_webui_transport import FakeWebUITransport

MODULES = [
    {"model_name": "sdxl_vae.safetensors", "filename": "/models/VAE/sdxl_vae.safetensors"},
    {"model_name": "clip_l.safetensors", "filename": "/models/text_encoder/clip_l.safetensors"},
]


def _client(transport: FakeWebUITransport) -> ForgeWebUIClient:
    client = ForgeWebUIClient(base_url="http://127.0.0.1:7861", options_write_enabled=True)
    client._session.request = transport  # type: ignore[method-assign]
    # The shared options-POST throttle is unchanged client behavior; disable it so consecutive
    # writes inside one test are not skipped.
    client._options_min_interval_seconds = 0.0
    return client


def test_forge_client_is_an_sdwebui_client_subclass_so_shared_transport_is_unchanged() -> None:
    assert issubclass(ForgeWebUIClient, SDWebUIClient)
    overridden = {
        name
        for name in ("get_vae_models", "set_vae", "get_current_vae")
        if name in vars(ForgeWebUIClient)
    }
    assert overridden == {"get_vae_models", "set_vae", "get_current_vae"}
    # Generation/progress/interrupt/options transport is inherited, never re-implemented.
    for inherited in (
        "txt2img",
        "img2img",
        "upscale_image",
        "interrupt",
        "get_progress",
        "set_model",
    ):
        if hasattr(SDWebUIClient, inherited):
            assert inherited not in vars(ForgeWebUIClient)


def test_vae_listing_uses_sd_modules_not_sd_vae_and_normalizes_to_resource_contract() -> None:
    transport = FakeWebUITransport(modules=MODULES)
    models = _client(transport).get_vae_models()
    assert models == MODULES
    assert transport.paths("GET") == ["/sdapi/v1/sd-modules"]
    assert "/sdapi/v1/sd-vae" not in transport.paths()


def test_normalize_sd_modules_drops_malformed_entries_and_non_lists() -> None:
    assert normalize_sd_modules(None) == []
    assert normalize_sd_modules({"detail": "Not Found"}) == []
    assert normalize_sd_modules(
        [{"model_name": "a.safetensors", "filename": "/p/a.safetensors"}, {"filename": "x"}, "junk"]
    ) == [{"model_name": "a.safetensors", "filename": "/p/a.safetensors"}]


def test_set_vae_writes_forge_additional_modules_and_verifies_by_reading_back() -> None:
    transport = FakeWebUITransport(modules=MODULES)
    client = _client(transport)
    assert client.set_vae("sdxl_vae.safetensors") is True
    writes = [
        body
        for verb, path, body in transport.calls
        if verb == "POST" and path == "/sdapi/v1/options"
    ]
    assert writes == [{"forge_additional_modules": ["sdxl_vae.safetensors"]}]
    assert "sd_vae" not in writes[0]  # Forge's sd_vae option is a non-interactive placeholder
    assert client.get_current_vae() == "sdxl_vae.safetensors"


def test_set_vae_accepts_name_without_extension_and_case_differences() -> None:
    transport = FakeWebUITransport(modules=MODULES)
    client = _client(transport)
    assert client.set_vae("SDXL_VAE") is True
    assert client.get_current_vae() == "sdxl_vae.safetensors"


@pytest.mark.parametrize("automatic", ["Automatic", "None", "", "automatic"])
def test_automatic_clears_the_module_list_and_reports_automatic(automatic: str) -> None:
    transport = FakeWebUITransport(modules=MODULES)
    client = _client(transport)
    client.set_vae("sdxl_vae.safetensors")
    assert client.set_vae(automatic) is True
    assert transport.options["forge_additional_modules"] == []
    assert client.get_current_vae() == "Automatic"


def test_unknown_vae_is_refused_before_any_write_because_forge_would_silently_clear_it() -> None:
    transport = FakeWebUITransport(modules=MODULES)
    client = _client(transport)
    client.set_vae("sdxl_vae.safetensors")
    writes_before = len([c for c in transport.calls if c[0] == "POST"])
    with pytest.raises(ForgeVAEError, match="not listed by the Forge endpoint"):
        client.set_vae("missing_vae.safetensors")
    assert len([c for c in transport.calls if c[0] == "POST"]) == writes_before
    assert client.get_current_vae() == "sdxl_vae.safetensors"  # previous VAE untouched


def test_unverified_write_raises_instead_of_proceeding_with_the_wrong_vae() -> None:
    transport = FakeWebUITransport(modules=MODULES)
    client = _client(transport)

    def ignore_writes(body: dict) -> None:  # Forge accepted the POST but applied nothing
        return None

    transport._apply_options = ignore_writes  # type: ignore[method-assign]
    with pytest.raises(ForgeVAEError, match="did not apply VAE"):
        client.set_vae("sdxl_vae.safetensors")


def test_current_vae_maps_forge_paths_to_basenames_and_multiple_modules_are_visible() -> None:
    transport = FakeWebUITransport(modules=MODULES)
    client = _client(transport)
    assert client.get_current_vae() == "Automatic"
    transport.options["forge_additional_modules"] = [
        "/models/VAE/sdxl_vae.safetensors",
        "C:\\models\\text_encoder\\clip_l.safetensors",
    ]
    assert client.get_current_vae() == "sdxl_vae.safetensors, clip_l.safetensors"


def test_options_writes_remain_gated_by_safe_mode() -> None:
    transport = FakeWebUITransport(modules=MODULES)
    client = ForgeWebUIClient(base_url="http://127.0.0.1:7861", options_write_enabled=False)
    client._session.request = transport  # type: ignore[method-assign]
    assert client.set_vae("sdxl_vae.safetensors") is False
    assert [c for c in transport.calls if c[0] == "POST"] == []


def test_interrupt_posts_to_sdapi_interrupt() -> None:
    transport = FakeWebUITransport(modules=MODULES)
    assert _client(transport).interrupt() is True
    assert ("POST", "/sdapi/v1/interrupt") in [(v, p) for v, p, _ in transport.calls]


def test_construction_performs_no_network_or_process_work() -> None:
    # Import/registry/client creation never touches HTTP: only the injected transport could.
    transport = FakeWebUITransport()
    _client(transport)
    assert transport.calls == []


KLEIN_MODULES = [
    {"model_name": "qwen_3_4b", "filename": "/data/models/text_encoder/qwen_3_4b.safetensors"},
    {"model_name": "flux2-vae", "filename": "/data/models/VAE/flux2-vae.safetensors"},
    *MODULES,
]


def _writes(transport: FakeWebUITransport) -> list[dict]:
    return [b for verb, path, b in transport.calls if verb == "POST" and path == "/sdapi/v1/options"]


def test_set_additional_modules_sends_the_complete_list_once_and_verifies_the_exact_set() -> None:
    transport = FakeWebUITransport(modules=KLEIN_MODULES)
    client = _client(transport)
    assert client.set_additional_modules(["qwen_3_4b.safetensors", "flux2-vae.safetensors"]) is True
    assert _writes(transport) == [{"forge_additional_modules": ["qwen_3_4b", "flux2-vae"]}]
    # Forge reports the module set as paths; the fake orders them, the contract is the exact set.
    assert sorted(client.get_additional_modules() or []) == [
        "flux2-vae.safetensors",
        "qwen_3_4b.safetensors",
    ]


def test_set_additional_modules_refuses_an_unavailable_module_before_any_write() -> None:
    transport = FakeWebUITransport(modules=MODULES)
    client = _client(transport)
    with pytest.raises(ForgeVAEError, match="not listed by the Forge endpoint"):
        client.set_additional_modules(["qwen_3_4b.safetensors", "sdxl_vae.safetensors"])
    assert _writes(transport) == []


def test_set_additional_modules_fails_closed_when_forge_applies_only_part_of_the_set() -> None:
    transport = FakeWebUITransport(modules=KLEIN_MODULES)
    client = _client(transport)
    original = transport._apply_options

    def drop_second(body: dict) -> None:
        original({"forge_additional_modules": body["forge_additional_modules"][:1]})

    transport._apply_options = drop_second  # type: ignore[method-assign]
    with pytest.raises(ForgeVAEError, match="did not apply module"):
        client.set_additional_modules(["qwen_3_4b.safetensors", "flux2-vae.safetensors"])


def test_set_additional_modules_rejects_duplicates_and_empty_clears() -> None:
    transport = FakeWebUITransport(modules=KLEIN_MODULES)
    client = _client(transport)
    with pytest.raises(ForgeVAEError, match="Duplicate"):
        client.set_additional_modules(["flux2-vae", "flux2-vae.safetensors"])
    client.set_additional_modules(["flux2-vae"])
    assert client.set_additional_modules([]) is True
    assert client.get_current_vae() == "Automatic"


def test_set_vae_delegates_to_the_single_module_write_authority() -> None:
    transport = FakeWebUITransport(modules=KLEIN_MODULES)
    client = _client(transport)
    client.set_additional_modules(["qwen_3_4b", "flux2-vae"])
    assert client.set_vae("sdxl_vae.safetensors") is True
    assert _writes(transport)[-1] == {"forge_additional_modules": ["sdxl_vae.safetensors"]}


def _throttled_client(transport: FakeWebUITransport, interval: float = 0.3) -> ForgeWebUIClient:
    client = _client(transport)
    client._options_min_interval_seconds = interval  # the production client throttles consecutive /options writes
    return client


def test_set_additional_modules_waits_out_the_options_throttle_instead_of_skipping() -> None:
    transport = FakeWebUITransport(modules=KLEIN_MODULES)
    client = _throttled_client(transport)
    client.set_additional_modules(["flux2-vae.safetensors"])  # e.g. directly after a model switch
    assert client.set_additional_modules(["qwen_3_4b.safetensors", "flux2-vae.safetensors"]) is True
    assert _writes(transport)[-1] == {"forge_additional_modules": ["qwen_3_4b", "flux2-vae"]}
    assert sorted(client.get_additional_modules() or []) == ["flux2-vae.safetensors", "qwen_3_4b.safetensors"]


def test_set_vae_keeps_its_existing_skip_semantics_under_the_throttle() -> None:
    transport = FakeWebUITransport(modules=KLEIN_MODULES)
    client = _throttled_client(transport, interval=30.0)
    assert client.set_vae("flux2-vae.safetensors") is True
    assert client.set_vae("sdxl_vae.safetensors") is False  # unchanged SDXL behavior: skipped, not waited
    assert len(_writes(transport)) == 1


def test_set_additional_modules_raises_when_options_writes_are_disabled() -> None:
    transport = FakeWebUITransport(modules=KLEIN_MODULES)
    client = ForgeWebUIClient(base_url="http://127.0.0.1:7861", options_write_enabled=False)
    client._session.request = transport  # type: ignore[method-assign]
    with pytest.raises(ForgeVAEError, match="was not applied"):
        client.set_additional_modules(["qwen_3_4b.safetensors", "flux2-vae.safetensors"])
    assert _writes(transport) == []


def test_module_set_key_is_order_case_and_extension_insensitive() -> None:
    from src.api.forge_client import module_set_key

    assert module_set_key(["/d/Qwen_3_4B.safetensors", "flux2-vae"]) == ["flux2-vae", "qwen_3_4b"]
    assert module_set_key(None) == [] and module_set_key(["", "  "]) == []


def test_get_loras_reads_the_forge_listing_without_writing_anything() -> None:
    """PR-IMG-117: read-only evidence of what the serving Forge will load (never an identity authority)."""

    loras = [{"name": "style", "alias": "style", "path": "/x/Lora/style.safetensors", "metadata": {"a": 1}}]
    transport = FakeWebUITransport(flavor="forge", loras=loras)
    client = _client(transport)

    assert client.get_loras() == [{"name": "style", "alias": "style", "path": "/x/Lora/style.safetensors"}]
    assert [verb for verb, _path, _body in transport.calls if verb != "GET"] == []
