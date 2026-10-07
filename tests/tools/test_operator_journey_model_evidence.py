from unittest.mock import Mock

import pytest

from tools.operator_journey.fixtures import seed_sdxl_checkpoint_evidence
from tools.operator_journey.workspace import OperatorWorkspace


@pytest.mark.parametrize("model", ["arbitrary-checkpoint", "arbitrary-checkpoint.safetensors"])
def test_fixture_evidence_uses_only_activated_workspace_cache(tmp_path, monkeypatch, model):
    import os

    from src.assets import AssetRegistry
    from src.config import app_config
    from src.image_backends.model_policy import RegistryFamilyLookup, Support, resolve_model_policy

    forbidden = Mock(side_effect=AssertionError("fixture attempted a scan"))
    monkeypatch.setattr(AssetRegistry, "refresh", forbidden)
    monkeypatch.setattr(AssetRegistry, "snapshot", forbidden)
    monkeypatch.delenv("STABLENEW_WEBUI_ROOT", raising=False)
    monkeypatch.setattr(app_config, "STABLENEW_WEBUI_ROOT", "")
    workspace = OperatorWorkspace(tmp_path / "workspace", "http://127.0.0.1:1")
    with workspace.activate():
        unknown = resolve_model_policy(model, family_lookup=RegistryFamilyLookup())
        assert unknown.feature("lora").support is Support.UNVERIFIED
        seed_sdxl_checkpoint_evidence(workspace, model)
        policy = resolve_model_policy(model, family_lookup=RegistryFamilyLookup())
        assert policy.family == "sdxl"
        assert policy.evidence == "registry_evidence"
        assert policy.feature("lora").support is Support.SUPPORTED
        assert (workspace.state_dir / "asset_registry_v1.json").is_file()
        assert not (workspace.root / "fixture-models").exists()
    forbidden.assert_not_called()
    assert "STABLENEW_WEBUI_ROOT" not in os.environ


def test_fixture_evidence_cannot_write_without_workspace_activation(tmp_path):
    workspace = OperatorWorkspace(tmp_path / "inactive", "http://127.0.0.1:1")
    with pytest.raises(RuntimeError, match="activated isolated workspace"):
        seed_sdxl_checkpoint_evidence(workspace, "arbitrary-checkpoint")
    assert not workspace.root.exists()
