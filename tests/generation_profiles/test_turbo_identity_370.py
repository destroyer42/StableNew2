from dataclasses import replace
from shutil import copyfile

from src.api.webui_resources import WebUIResource, WebUIResourceType
from src.assets import AssetKind, AssetRegistry
from src.generation_profiles.contract import KIND_RESEARCH
from src.generation_profiles.identity import ModelIdentityResolver, RegistryShaLookup
from src.generation_profiles.research import KLEIN_RESEARCH_ID, SDXL_RESEARCH_ID
from src.generation_profiles.service import GenerationProfileService
from src.generation_profiles.store import GenerationProfileStore
from src.image_backends.forge_klein_profile import KLEIN_PROFILE_V1
from src.image_backends.model_policy import RegistryFamilyLookup
from src.learning.compatibility_probe import RECIPES
from tests.assets.checkpoint_fixtures import tensor_checkpoint


def test_turbo_research_is_bound_to_verified_bytes_and_respects_precedence(tmp_path):
    models = tmp_path / "models" / "Stable-diffusion"
    original = tensor_checkpoint(models / "original.safetensors", metadata={"modelspec.architecture": "sdxl-turbo"})
    renamed = models / "renamed.safetensors"
    copyfile(original, renamed)
    ordinary = tensor_checkpoint(models / "looks-like-turbo.safetensors")
    conflict = tensor_checkpoint(models / "conflict.safetensors", metadata={
        "modelspec.architecture": "sdxl-turbo", "ss_base_model_version": "sd_v1.5",
    })
    served = []
    registry = AssetRegistry(tmp_path, cache_path=tmp_path / "assets.json")
    resolver = ModelIdentityResolver(
        family_lookup=RegistryFamilyLookup(registry),
        sha_lookup=RegistryShaLookup(registry, served_models=lambda: served),
    )
    service = GenerationProfileService(GenerationProfileStore(tmp_path / "profiles"), resolver)
    # Header metadata does not make a recommendation before byte verification.
    assert not service.state_for(original.name).options
    registry.refresh(kinds=(AssetKind.CHECKPOINT,))
    research = service.state_for(original.name + " [displayhash]").options
    turbo = research[0]
    assert turbo.ref.kind == KIND_RESEARCH
    assert turbo.profile.settings == RECIPES["sdxl_turbo"].settings
    assert service.state_for(renamed.name).options[0].ref == turbo.ref
    assert service.state_for(ordinary.name).options[0].ref.profile_id == SDXL_RESEARCH_ID
    assert not service.state_for(conflict.name).options
    assert service.state_for(KLEIN_PROFILE_V1.transformer.filename).options[0].ref.profile_id == KLEIN_RESEARCH_ID

    # The favorite or an explicit choice may select the general SDXL Research profile.
    service.set_favorite(original.name, research[1].ref)
    assert service.on_model_changed(original.name, {})[0].profile == research[1].ref
    plan, _ = service.select(original.name, turbo.ref, {})
    assert plan.changes == RECIPES["sdxl_turbo"].settings
    service.save_startup_defaults(original.name, plan.changes, {}, {})
    assert service.plan_startup(available_models={original.name})[1].profile == turbo.ref
    pending = service.plan_startup(available_models=None, resources={})[1]
    assert pending.awaiting_model_catalog and not pending.restores_anything
    verified = registry.inspect_picker_candidate(original, original.name, vae=False)
    catalog = {"models": [
        WebUIResource(WebUIResourceType.MODEL, original.name, original.name, picker=replace(verified, path=original)),
    ]}
    assert service.plan_startup(available_models={original.name}, resources=catalog)[1].profile == turbo.ref

    elsewhere = tensor_checkpoint(tmp_path / "remote" / original.name)
    evidence = registry.inspect_picker_candidate(elsewhere, original.name, vae=False)
    served.append(WebUIResource(WebUIResourceType.MODEL, original.name, original.name, picker=replace(evidence, path=elsewhere)))
    assert service.state_for(original.name).options[0].ref.profile_id == SDXL_RESEARCH_ID
    assert service.plan_startup(available_models={original.name})[1].model_name is None
    served.clear()

    # A same-name replacement invalidates a saved recommendation before and after reindexing.
    tensor_checkpoint(original, metadata={"modelspec.architecture": "sdxl-turbo", "different": "same name"})
    assert not resolver.resolve(original.name).identity.sha256
    assert service.select(original.name, turbo.ref, {})[0].changes == {}
    assert service.plan_startup(available_models={original.name})[1].model_name is None
    registry.refresh(kinds=(AssetKind.CHECKPOINT,))
    assert service.state_for(original.name).options[0].ref != turbo.ref
    assert service.select(original.name, turbo.ref, {})[0].changes == {}
    assert service.state_for(renamed.name).options[0].ref == turbo.ref
