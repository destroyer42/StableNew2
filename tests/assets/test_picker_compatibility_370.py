from src.api.webui_resource_service import WebUIResourceService
from src.assets import AssetRegistry
from src.assets.compatibility import ModelFamily
from src.assets.picker_compatibility import VaeCatalog, vae_catalog
from src.image_backends.forge_flux1_profile import flux_variant_refusal
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1
from src.image_backends.model_policy import resolve_model_policy
from tests.assets import topology_fixtures_152 as fx
from tests.assets.checkpoint_fixtures import tensor_checkpoint
from tests.assets.flux_fixtures_130 import flux1_table, write_gguf


def _tensor(shape):
    return ("F16", shape)


def test_resource_refresh_classifies_exact_served_paths(tmp_path):
    ordinary = tensor_checkpoint(tmp_path / "ordinary.safetensors")
    encoder = fx.safetensors(
        tmp_path / "misplaced.safetensors",
        {
            "text_model.embeddings.token_embedding.weight": _tensor([2, 2]),
            "text_model.encoder.layers.0.self_attn.k_proj.weight": _tensor([2, 2]),
        },
    )
    vae = fx.safetensors(
        tmp_path / "decoder.safetensors",
        {
            "decoder.conv_in.weight": _tensor([2, 4, 1, 1]),
            "decoder.conv_out.weight": _tensor([3, 2, 1, 1]),
        },
    )
    vae.with_suffix(".civitai.info").write_text('{"baseModel": "SDXL"}')
    ambiguous = fx.safetensors(
        tmp_path / "ambiguous.safetensors",
        {
            "decoder.conv_in.weight": _tensor([2, 4, 1, 1]),
            "decoder.conv_out.weight": _tensor([3, 2, 1, 1]),
        },
    )
    preview = fx.safetensors(
        tmp_path / "misnamed.safetensors", {"taesd_decoder.0.weight": _tensor([2, 4, 1, 1])}
    )
    klein = fx.safetensors(tmp_path / "renamed-klein.safetensors", fx.flux2_native(4096))
    unknown = tmp_path / "unknown.safetensors"
    unknown.write_bytes(b"truncated")

    class Client:
        def get_models(self):
            return [
                {
                    "model_name": path.stem,
                    "title": f"{path.name} [serverhash]",
                    "filename": str(path),
                }
                for path in (ordinary, encoder, vae, preview, klein, unknown)
            ]

        def get_vae_models(self):
            return [
                {"model_name": path.name, "filename": str(path)}
                for path in (
                    vae,
                    ambiguous,
                    ordinary,
                    encoder,
                    preview,
                    unknown,
                    vae.with_suffix(".civitai.info"),
                )
            ]

    resources = WebUIResourceService(client=Client(), webui_root=str(tmp_path)).refresh_all()
    models = {entry.name: entry.picker for entry in resources["models"]}
    assert models[ordinary.stem].family == "sdxl"
    assert all(models[path.stem].excluded for path in (encoder, vae, preview))
    # N1: no longer refused; a warning that keeps the recorded NO-GO verdict and says what makes it work.
    klein_warning = models[klein.stem]
    assert klein_warning.warning and klein_warning.refusal.startswith(
        f"{klein.stem} is not qualified."
    )
    assert (
        flux_variant_refusal("flux2_klein_9b").split(" StableNew refuses")[0]
        in klein_warning.refusal
    )
    assert (
        "refuses it" not in klein_warning.refusal
        and "Queue runs it anyway" in klein_warning.refusal
    )
    assert not models[unknown.stem].recognized and not models[unknown.stem].excluded

    sdxl = vae_catalog(resources["vaes"], "sdxl")
    assert sdxl.offered == (vae.name, ambiguous.name, unknown.name)
    assert sdxl.verified == (vae.name,)
    assert sdxl.resolve(ambiguous.name, recommendation=True) is None
    assert sdxl.resolve(vae.stem) == vae.name
    sd1 = vae_catalog(resources["vaes"], "sd1")
    assert sd1.offered == (ambiguous.name, unknown.name)
    assert not sd1.verified
    assert vae_catalog([], "sdxl") is None


def test_a_catalog_alias_cannot_substitute_another_file_for_a_rejected_vae():
    catalog = VaeCatalog(
        offered=("same.safetensors", "other.safetensors", "other.pt"),
        verified=("same.safetensors", "other.safetensors"),
        listed=("same.pt", "same.safetensors", "other.safetensors", "other.pt"),
    )
    assert catalog.resolve("same.pt") is None
    assert catalog.resolve("same") is None
    assert catalog.resolve("other.pt", recommendation=True) is None
    assert catalog.resolve("other", recommendation=True) is None


def test_picker_explains_ambiguous_z_image_and_missing_flux_modules(tmp_path):
    z_image = fx.safetensors(
        tmp_path / "renamed-z.safetensors",
        {
            "layers.0.attention.qkv.weight": _tensor([2, 2]),
            "layers.0.adaLN_modulation.weight": _tensor([2, 2]),
            "cap_embedder.0.weight": _tensor([2]),
        },
    )
    flux = write_gguf(tmp_path / "renamed-dev.gguf", flux1_table())

    class Client:
        def get_models(self):
            return [{"model_name": path.name, "filename": str(path)} for path in (z_image, flux)]

    registry = AssetRegistry(tmp_path, cache_path=tmp_path / "registry.json")
    compatibility = registry.inspect_checkpoint(z_image).compatibility
    assert compatibility.family is ModelFamily.Z_IMAGE
    policy = resolve_model_policy(z_image.name, family_lookup=lambda _: compatibility)
    assert policy.profile_ref is None
    assert "cannot establish Turbo compatibility" in policy.refusal
    assert (
        resolve_model_policy(ZIMAGE_PROFILE_V1.transformer.filename).profile_ref
        == ZIMAGE_PROFILE_V1.reference()
    )

    resources = WebUIResourceService(client=Client(), webui_root=str(tmp_path)).refresh_all()
    models = {entry.name: entry.picker for entry in resources["models"]}
    assert (
        models[z_image.name].warning and policy.refusal in models[z_image.name].refusal
    )  # N1: a warning
    assert "clip_l.safetensors" in models[flux.name].refusal
    assert "t5xxl_fp8_e4m3fn.safetensors" in models[flux.name].refusal
