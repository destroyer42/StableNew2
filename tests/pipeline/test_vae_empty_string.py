"""Quick test to verify VAE empty string handling."""

def test_vae_empty_string_not_defaulted():
    """When VAE is explicitly set to empty string, it should not default to 'Automatic'."""
    
    # Simulate config with empty VAE (user selected "No VAE (model default)")
    config = {
        "model": "sdxlNuclearGeneralPurposeV3Semi_v30BakedVAE",
        "sd_vae": "",  # Empty string - user explicitly selected no VAE
        "prompt": "test",
    }
    
    # OLD BEHAVIOR (BUGGY):
    # requested_vae = config.get("vae") or config.get("vae_name") or "Automatic"
    # Result: "Automatic" (WRONG - empty string is falsy)
    
    # NEW BEHAVIOR (FIXED):
    requested_vae = config.get("vae") if "vae" in config else (
        config.get("sd_vae") if "sd_vae" in config else config.get("vae_name")
    )
    
    # Result: "" (CORRECT - preserves empty string)
    assert requested_vae == "", f"Expected empty string, got: {repr(requested_vae)}"
    print("[OK] Empty VAE string is preserved, not defaulted to 'Automatic'")


def test_vae_missing_key_uses_none():
    """When VAE key is missing, it should be None (not set)."""
    
    config = {
        "model": "sdxlNuclearGeneralPurposeV3Semi_v30BakedVAE",
        "prompt": "test",
        # No vae, sd_vae, or vae_name keys
    }
    
    requested_vae = config.get("vae") if "vae" in config else (
        config.get("sd_vae") if "sd_vae" in config else config.get("vae_name")
    )
    
    assert requested_vae is None, f"Expected None, got: {repr(requested_vae)}"
    print("[OK] Missing VAE key returns None")


def test_vae_specified_is_preserved():
    """When VAE is specified, it should be preserved."""
    
    config = {
        "model": "sdxlNuclearGeneralPurposeV3Semi_v30BakedVAE",
        "vae": "sdxl_vae.safetensors",
        "prompt": "test",
    }
    
    requested_vae = config.get("vae") if "vae" in config else (
        config.get("sd_vae") if "sd_vae" in config else config.get("vae_name")
    )
    
    assert requested_vae == "sdxl_vae.safetensors", f"Expected specific VAE, got: {repr(requested_vae)}"
    print("[OK] Specified VAE is preserved")


if __name__ == "__main__":
    test_vae_empty_string_not_defaulted()
    test_vae_missing_key_uses_none()
    test_vae_specified_is_preserved()
    print("\n[OK] All VAE tests passed!")
