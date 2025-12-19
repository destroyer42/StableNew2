"""Configuration management utilities"""

import json
import logging
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_GLOBAL_NEGATIVE_PROMPT = (
    "blurry, bad quality, distorted, ugly, malformed, nsfw, nude, naked, explicit, "
    "sexual content, adult content, immodest"
)

DEFAULT_GLOBAL_POSITIVE_PROMPT = (
    ""
)

logger = logging.getLogger(__name__)
LAST_RUN_PATH = Path("state/last_run_v2.json")


def _normalize_scheduler_name(scheduler: str | None) -> str | None:
    """
    Normalize scheduler names into values WebUI understands.

    Treats None, empty strings, "None", and "Automatic" (case-insensitive) as no scheduler.
    """

    if scheduler is None:
        return None

    value = str(scheduler).strip()
    if not value:
        return None

    lowered = value.lower()
    if lowered in {"none", "automatic"}:
        return None

    return value


def build_sampler_scheduler_payload(
    sampler_name: str | None,
    scheduler_name: str | None,
) -> dict[str, str]:
    """
    Build sampler / scheduler payload segment following WebUI expectations.

    When a scheduler is selected, we send both the combined sampler name
    (e.g., "DPM++ 2M Karras") and the explicit scheduler field. Otherwise
    we omit the scheduler key entirely and send only the sampler name.
    """

    payload: dict[str, str] = {}

    sampler = (sampler_name or "").strip()
    if not sampler:
        return payload

    normalized_scheduler = _normalize_scheduler_name(scheduler_name)

    if normalized_scheduler:
        payload["sampler_name"] = f"{sampler} {normalized_scheduler}"
        payload["scheduler"] = normalized_scheduler
    else:
        payload["sampler_name"] = sampler

    return payload


@dataclass(frozen=True)
class LoraRuntimeConfig:
    """Lightweight runtime configuration for a LoRA block."""

    name: str
    strength: float = 1.0
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LoraRuntimeConfig":
        return cls(
            name=str(data.get("name", "") or "").strip(),
            strength=float(data.get("strength", 1.0) or 1.0),
            enabled=bool(data.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "strength": self.strength, "enabled": self.enabled}


def normalize_lora_strengths(raw: Iterable[dict[str, Any]] | None) -> list[LoraRuntimeConfig]:
    if not raw:
        return []
    configs: list[LoraRuntimeConfig] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        config = LoraRuntimeConfig.from_dict(entry)
        if config.name:
            configs.append(config)
    return configs


class ConfigManager:
    """Manages configuration, presets, and simple engine settings."""

    def __init__(self, presets_dir: str | Path = "presets"):
        """
        Initialize configuration manager.

        Args:
            presets_dir: Directory containing preset files
        """
        self.presets_dir = Path(presets_dir)
        self.presets_dir.mkdir(exist_ok=True)
        self._global_negative_path = self.presets_dir / "global_negative.txt"
        self._global_negative_cache: str | None = None
        self._global_positive_path = self.presets_dir / "global_positive.txt"
        self._global_positive_cache: str | None = None
        self._default_preset_path = self.presets_dir / ".default_preset"
        self._settings_path = self.presets_dir / "settings.json"
        self._settings_cache: dict[str, Any] | None = None

    def load_preset(self, name: str) -> dict[str, Any] | None:
        """
        Load a preset configuration.

        Args:
            name: Name of the preset

        Returns:
            Preset configuration dictionary
        """
        preset_path = self.presets_dir / f"{name}.json"
        if not preset_path.exists():
            logger.warning(f"Preset '{name}' not found at {preset_path}")
            return None

        try:
            with open(preset_path, encoding="utf-8") as f:
                preset = self._merge_config_with_defaults(json.load(f))
            logger.info(f"Loaded preset: {name}")
            return preset
        except Exception as e:
            logger.error(f"Failed to load preset '{name}': {e}")
            return None

    def save_preset(self, name: str, config: dict[str, Any]) -> bool:
        """
        Save a preset configuration.

        Args:
            name: Name of the preset
            config: Configuration dictionary

        Returns:
            True if saved successfully
        """
        preset_path = self.presets_dir / f"{name}.json"
        try:
            merged = self._merge_config_with_defaults(config)
            with open(preset_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved preset: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to save preset '{name}': {e}")
            return False

    def list_presets(self) -> list[str]:
        """
        List all available presets.

        Returns:
            List of preset names
        """
        presets = [p.stem for p in self.presets_dir.glob("*.json")]
        logger.info(f"Found {len(presets)} presets")
        return sorted(presets)

    def delete_preset(self, name: str) -> bool:
        """
        Delete a preset configuration.

        Args:
            name: Name of the preset to delete

        Returns:
            True if deleted successfully
        """
        if name == "default":
            logger.warning("Cannot delete the default preset")
            return False

        preset_path = self.presets_dir / f"{name}.json"
        if not preset_path.exists():
            logger.warning(f"Preset '{name}' not found at {preset_path}")
            return False

        try:
            preset_path.unlink()
            logger.info(f"Deleted preset: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete preset '{name}': {e}")
            return False

    def get_default_config(self) -> dict[str, Any]:
        """
        Get the default configuration for all pipeline stages.

        IMPORTANT: When adding new parameters to this configuration,
        run the validation test to ensure proper parameter pass-through:

        python tests/test_config_passthrough.py

        See CONFIGURATION_TESTING_GUIDE.md for detailed maintenance instructions.

        Returns:
            Dictionary containing default configuration for all stages
        """
        """
        Get default configuration.

        Returns:
            Default configuration dictionary
        """
        return {
            "txt2img": {
                "steps": 20,
                "sampler_name": "Euler a",
                "scheduler": "Normal",
                "cfg_scale": 7.0,
                "width": 512,
                "height": 512,
                "negative_prompt": "blurry, bad quality, distorted",
                "seed": -1,  # -1 for random
                "seed_resize_from_h": -1,
                "seed_resize_from_w": -1,
                "enable_hr": False,  # High-res fix / hires.fix
                "hr_scale": 2.0,  # Hires.fix upscale factor
                "hr_upscaler": "Latent",  # Hires.fix upscaler
                "hr_sampler_name": "",  # Optional separate sampler for hires second pass
                "hr_second_pass_steps": 0,  # 0 = use same as steps
                "hr_resize_x": 0,  # 0 = automatic based on hr_scale
                "hr_resize_y": 0,  # 0 = automatic based on hr_scale
                "denoising_strength": 0.7,  # For hires.fix second pass
                "clip_skip": 2,  # CLIP layers to skip
                "model": "juggernautXL_ragnarokBy.safetensors",  # SD model checkpoint (empty = use current)
                "vae": "",  # VAE model (empty = use model default)
                "hypernetwork": "None",
                "hypernetwork_strength": 1.0,
                "styles": [],  # Style names to apply
                # SDXL refiner controls
                "refiner_checkpoint": "",
                "refiner_switch_at": 0.8,  # ratio 0-1 used by WebUI
                "refiner_switch_steps": 0,  # optional: absolute step number within base pass; 0=unused
                "refiner_enabled": False,
                "refiner_model_name": "",
            },
            "img2img": {
                "steps": 15,
                "sampler_name": "Euler a",
                "scheduler": "Normal",
                "cfg_scale": 7.0,
                "denoising_strength": 0.3,
                "seed": -1,  # -1 for random
                "clip_skip": 2,
                "model": "juggernautXL_ragnarokBy.safetensors",  # SD model checkpoint (empty = use current)
                "vae": "",  # VAE model (empty = use model default)
                "hypernetwork": "None",
                "hypernetwork_strength": 1.0,
                "prompt_adjust": "",
                "negative_adjust": "",
            },
            "upscale": {
                "upscaler": "R-ESRGAN 4x+",
                "upscaling_resize": 2.0,
                "upscale_mode": "single",  # "single" (direct) or "img2img" (more control)
                "denoising_strength": 0.35,  # For img2img-based upscaling
                "steps": 20,
                "sampler_name": "Euler a",
                "scheduler": "Normal",
                "gfpgan_visibility": 0.0,  # Face restoration strength
                "codeformer_visibility": 0.0,  # Face restoration alternative
                "codeformer_weight": 0.5,  # CodeFormer fidelity
            },
            "adetailer": {
                "enabled": False,
                "adetailer_enabled": False,
                "adetailer_model": "face_yolov8n.pt",
                "adetailer_confidence": 0.3,
                "adetailer_mask_feather": 4,
                "adetailer_sampler": "DPM++ 2M",
                "adetailer_scheduler": "inherit",
                "adetailer_steps": 28,
                "adetailer_denoise": 0.4,
                "adetailer_cfg": 7.0,
                "adetailer_prompt": "",
                "adetailer_negative_prompt": "",
            },
            "video": {"fps": 24, "codec": "libx264", "quality": "medium"},
            "api": {"base_url": "http://127.0.0.1:7860", "timeout": 300},
            "webui_options_write_enabled": False,
            "randomization": {
                "enabled": False,
                # Optional seed for deterministic randomization.
                # When None, a fresh RNG seed is used each run.
                "seed": None,
                "prompt_sr": {
                    "enabled": False,
                    "mode": "random",
                    "rules": [],
                    "raw_text": "",
                },
                "wildcards": {
                    "enabled": False,
                    "mode": "random",
                    "tokens": [],
                    "raw_text": "",
                },
                "matrix": {
                    "enabled": False,
                    "mode": "fanout",
                    "limit": 8,
                    "slots": [],
                    "raw_text": "",
                },
            },
            "aesthetic": {
                "enabled": False,
                "mode": "script",
                "weight": 0.9,
                "steps": 5,
                "learning_rate": 0.0001,
                "slerp": False,
                "slerp_angle": 0.1,
                "embedding": "None",
                "text": "",
                "text_is_negative": False,
                "fallback_prompt": "",
            },
            "pipeline": {
                "img2img_enabled": True,
                "upscale_enabled": True,
                "adetailer_enabled": False,
                "allow_hr_with_stages": False,
                "refiner_compare_mode": False,  # When True and refiner+hires enabled, branch original & refined
                # Global negative application toggles per-stage (default True for backward compatibility)
                "apply_global_negative_txt2img": True,
                "apply_global_negative_img2img": True,
                "apply_global_negative_upscale": True,
                "apply_global_negative_adetailer": True,
            },
            "hires_fix": {
                "enabled": False,
                "upscaler_name": "Latent",
                "upscale_factor": 2.0,
                "steps": 0,
                "denoise": 0.3,
                "use_base_model": True,
            },
            "randomization_enabled": False,
            "max_variants": 1,
            "lora_strengths": [],
        }

    def resolve_config(
        self,
        preset_name: str | None = None,
        pack_overrides: dict[str, Any] | None = None,
        runtime_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Resolve configuration with hierarchy: Default → Preset → Pack overrides → Runtime params.

        Args:
            preset_name: Name of preset to load
            pack_overrides: Pack-specific configuration overrides
            runtime_params: Runtime parameter overrides

        Returns:
            Resolved configuration dictionary
        """
        # Start with default config
        config = self.get_default_config()

        # Apply preset overrides
        if preset_name:
            preset_config = self.load_preset(preset_name)
            if preset_config:
                config = self._merge_configs(config, preset_config)

        # Apply pack-specific overrides
        if pack_overrides:
            config = self._merge_configs(config, pack_overrides)

        # Apply runtime parameters
        if runtime_params:
            config = self._merge_configs(config, runtime_params)

        return config

    def _merge_configs(
        self, base_config: dict[str, Any], override_config: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Deep merge two configuration dictionaries.

        Args:
            base_config: Base configuration
            override_config: Override configuration

        Returns:
            Merged configuration
        """
        import copy

        merged = copy.deepcopy(base_config)

        for key, value in override_config.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = self._merge_configs(merged[key], value)
            else:
                merged[key] = value

        return merged

    def _ensure_refiner_hires_fields(self, config: dict[str, Any]) -> None:
        txt2img = config.setdefault("txt2img", {})
        hires = config.setdefault("hires_fix", {})
        defaults = {
            "refiner_enabled": False,
            "refiner_model_name": "",
            "refiner_switch_at": 0.8,
            "hires_enabled": False,
            "hires_upscaler_name": "Latent",
            "hires_upscale_factor": 2.0,
            "hires_steps": 0,
            "hires_denoise": 0.3,
            "hires_use_base_model": True,
        }
        for key in ("refiner_enabled", "refiner_model_name", "refiner_switch_at"):
            txt2img.setdefault(key, defaults[key])
        for key in (
            "hires_enabled",
            "hires_upscaler_name",
            "hires_upscale_factor",
            "hires_steps",
            "hires_denoise",
            "hires_use_base_model",
        ):
            hires.setdefault(key, defaults[key])

    def get_pack_overrides(self, pack_name: str) -> dict[str, Any]:
        """
        Get pack-specific configuration overrides.

        Args:
            pack_name: Name of the prompt pack

        Returns:
            Pack override configuration
        """
        overrides_file = self.presets_dir / "pack_overrides.json"
        if not overrides_file.exists():
            return {}

        try:
            with open(overrides_file, encoding="utf-8") as f:
                all_overrides = json.load(f)

            return all_overrides.get(pack_name, {})
        except Exception as e:
            logger.error(f"Failed to load pack overrides: {e}")
            return {}

    def save_pack_overrides(self, pack_name: str, overrides: dict[str, Any]) -> bool:
        """
        Save pack-specific configuration overrides.

        Args:
            pack_name: Name of the prompt pack
            overrides: Override configuration

        Returns:
            True if saved successfully
        """
        overrides_file = self.presets_dir / "pack_overrides.json"

        try:
            # Load existing overrides
            all_overrides = {}
            if overrides_file.exists():
                with open(overrides_file, encoding="utf-8") as f:
                    all_overrides = json.load(f)

            # Update with new overrides
            all_overrides[pack_name] = overrides

            # Save back
            with open(overrides_file, "w", encoding="utf-8") as f:
                json.dump(all_overrides, f, indent=2, ensure_ascii=False)

            logger.info(f"Saved pack overrides for: {pack_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to save pack overrides: {e}")
            return False

    def _pack_config_path(self, pack_name: str) -> Path:
        """
        Return the expected config file path for a prompt pack.
        """
        pack_stem = Path(pack_name).stem
        return Path("packs") / f"{pack_stem}.json"

    def get_pack_config(self, pack_name: str) -> dict[str, Any]:
        """
        Get individual pack configuration from its .json file.

        Args:
            pack_name: Name of the prompt pack (e.g., "heroes.txt")

        Returns:
            Pack configuration or empty dict if not found
        """

        config_path = self._pack_config_path(pack_name)

        if not config_path.exists():
            return {}

        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
            logger.debug(f"Loaded pack config: {pack_name}")
            return config
        except Exception as e:
            logger.error(f"Failed to load pack config '{pack_name}': {e}")
            return {}

    def load_pack_config(self, pack_name: str) -> dict[str, Any] | None:
        """
        Load and normalize a pack configuration, filling defaults where fields are missing.
        """
        config_path = self._pack_config_path(pack_name)
        if not config_path.exists():
            return None
        raw = self.get_pack_config(pack_name)
        return self._merge_config_with_defaults(raw)

    def save_pack_config(self, pack_name: str, config: dict[str, Any]) -> bool:
        """
        Save individual pack configuration to its .json file.

        Args:
            pack_name: Name of the prompt pack (e.g., "heroes.txt")
            config: Configuration to save

        Returns:
            True if successful
        """

        try:
            # Convert pack_name to config filename (heroes.txt -> heroes.json)
            config_path = self._pack_config_path(pack_name)

            # Debug: Log what we're about to save
            pipeline_section = config.get("pipeline", {})
            logger.info(
                "Saving pack config '%s': pipeline flags: txt2img=%s, img2img=%s, adetailer=%s, upscale=%s",
                pack_name,
                pipeline_section.get("txt2img_enabled"),
                pipeline_section.get("img2img_enabled"),
                pipeline_section.get("adetailer_enabled"),
                pipeline_section.get("upscale_enabled"),
            )

            # Ensure packs directory exists
            config_path.parent.mkdir(exist_ok=True)

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

            logger.info(f"Saved pack config to: {config_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save pack config '{pack_name}': {e}")
            return False

    def ensure_pack_config(self, pack_name: str, preset_name: str = "default") -> dict[str, Any]:
        """
        Ensure pack has a configuration file, creating one with preset defaults if needed.

        Args:
            pack_name: Name of the prompt pack
            preset_name: Preset to use as base for new pack config

        Returns:
            Pack configuration
        """
        config = self._merge_config_with_defaults(self.get_pack_config(pack_name))

        if not config:
            # Create pack config from preset defaults
            preset_config = self.load_preset(preset_name)
            if preset_config:
                self.save_pack_config(pack_name, preset_config)
                logger.info(
                    f"Created pack config for '{pack_name}' based on preset '{preset_name}'"
                )
                return self._merge_config_with_defaults(preset_config)
            else:
                logger.warning(f"Failed to create pack config - preset '{preset_name}' not found")

        return self._merge_config_with_defaults(config)

    def _load_settings(self) -> dict[str, Any]:
        if self._settings_cache is not None:
            return self._settings_cache
        self._settings_cache = {}
        if self._settings_path.exists():
            try:
                text = self._settings_path.read_text(encoding="utf-8")
                data = json.loads(text)
                if isinstance(data, dict):
                    self._settings_cache = data
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to load engine settings: %s", exc)
        return self._settings_cache

    def load_settings(self) -> dict[str, Any]:
        defaults = self._default_settings()
        stored = self._load_settings()
        merged = dict(defaults)
        merged.update(stored)
        return merged

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self.load_settings().get(key, default)

    def update_settings(self, updates: dict[str, Any]) -> None:
        current = dict(self._load_settings())
        current.update({k: v for k, v in updates.items() if v is not None})
        self.save_settings(current)

    def save_settings(self, settings: dict[str, Any] | None = None) -> bool:
        data = settings if settings is not None else dict(self._load_settings())
        try:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._settings_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            self._settings_cache = dict(data)
            return True
        except Exception as exc:
            logger.error("Failed to persist engine settings: %s", exc)
            return False

    def _default_settings(self) -> dict[str, Any]:
        from src.config import app_config

        return {
            "webui_base_url": "http://127.0.0.1:7860",
            "webui_workdir": str(app_config.get_webui_workdir() or ""),
            "webui_autostart_enabled": app_config.is_webui_autostart_enabled(),
            "webui_health_initial_timeout_seconds": app_config.get_webui_health_initial_timeout_seconds(),
            "webui_health_retry_count": app_config.get_webui_health_retry_count(),
            "webui_health_retry_interval_seconds": app_config.get_webui_health_retry_interval_seconds(),
            "webui_health_total_timeout_seconds": app_config.get_webui_health_total_timeout_seconds(),
            "output_dir": str(Path("output")),
            "model_dir": str(Path("models")),
        }

    def get_default_engine_settings(self) -> dict[str, Any]:
        """Expose default engine setting values."""
        return dict(self._default_settings())

    def get_global_negative_prompt(self) -> str:
        """Return the persisted global negative prompt, creating a default if missing."""

        if self._global_negative_cache is not None:
            return self._global_negative_cache

        prompt = DEFAULT_GLOBAL_NEGATIVE_PROMPT
        try:
            if self._global_negative_path.exists():
                text = self._global_negative_path.read_text(encoding="utf-8").strip()
                # Use the saved value even if it's blank (user explicitly saved empty)
                prompt = text
            else:
                self._global_negative_path.parent.mkdir(parents=True, exist_ok=True)
                self._global_negative_path.write_text(prompt, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - log and fall back to default
            logger.warning("Failed reading global negative prompt: %s", exc)
        self._global_negative_cache = prompt
        return prompt

    def save_global_negative_prompt(self, prompt: str) -> bool:
        """Persist a custom global negative prompt to disk."""

        text = (prompt or "").strip()
        try:
            self._global_negative_path.parent.mkdir(parents=True, exist_ok=True)
            self._global_negative_path.write_text(text, encoding="utf-8")
            self._global_negative_cache = text
            logger.info("Saved global negative prompt (%s chars)", len(text))
            return True
        except Exception as exc:  # noqa: BLE001 - surface failure but keep running
            logger.error("Failed to save global negative prompt: %s", exc)
            return False

    def get_global_positive_prompt(self) -> str:
        """Return the persisted global positive prompt, creating a default if missing."""

        if self._global_positive_cache is not None:
            return self._global_positive_cache

        prompt = DEFAULT_GLOBAL_POSITIVE_PROMPT
        try:
            if self._global_positive_path.exists():
                text = self._global_positive_path.read_text(encoding="utf-8").strip()
                if text:
                    prompt = text
            else:
                self._global_positive_path.parent.mkdir(parents=True, exist_ok=True)
                self._global_positive_path.write_text(prompt, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - log and fall back to default
            logger.warning("Failed reading global positive prompt: %s", exc)
        self._global_positive_cache = prompt
        return prompt

    def save_global_positive_prompt(self, prompt: str) -> bool:
        """Persist a custom global positive prompt to disk."""

        text = (prompt or "").strip()
        try:
            self._global_positive_path.parent.mkdir(parents=True, exist_ok=True)
            self._global_positive_path.write_text(text, encoding="utf-8")
            self._global_positive_cache = text
            logger.info("Saved global positive prompt (%s chars)", len(text))
            return True
        except Exception as exc:  # noqa: BLE001 - surface failure but keep running
            logger.error("Failed to save global positive prompt: %s", exc)
            return False

    def add_global_negative(self, negative_prompt: str) -> str:
        """
        Add global safety terms to the provided negative prompt.

        Args:
            negative_prompt: Existing negative prompt

        Returns:
            Combined negative prompt string
        """

        global_neg = self.get_global_negative_prompt().strip()
        base = (negative_prompt or "").strip()
        if not global_neg:
            return base
        if base:
            return f"{base}, {global_neg}"
        return global_neg

    def _merge_config_with_defaults(self, config: dict[str, Any] | None) -> dict[str, Any]:
        base = self.get_default_config()
        merged = self._deep_merge_dicts(base, config or {})
        self._ensure_refiner_hires_fields(merged)
        return merged

    def _deep_merge_dicts(self, base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base)
        for key, value in (overrides or {}).items():
            if isinstance(merged.get(key), dict) and isinstance(value, dict):
                merged[key] = self._deep_merge_dicts(merged.get(key, {}), value)
            else:
                merged[key] = value
        return merged

    def set_default_preset(self, preset_name: str) -> bool:
        """
        Set a preset as the default to load on startup.

        Args:
            preset_name: Name of the preset to set as default

        Returns:
            True if set successfully
        """
        if not preset_name:
            logger.warning("Cannot set empty preset name as default")
            return False

        # Verify preset exists
        preset_path = self.presets_dir / f"{preset_name}.json"
        if not preset_path.exists():
            logger.warning(f"Preset '{preset_name}' does not exist, cannot set as default")
            return False

        try:
            self._default_preset_path.write_text(preset_name, encoding="utf-8")
            logger.info(f"Set default preset to: {preset_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to set default preset: {e}")
            return False

    def get_default_preset(self) -> str | None:
        """
        Get the name of the default preset.

        Returns:
            Name of default preset, or None if not set
        """
        if not self._default_preset_path.exists():
            return None

        try:
            preset_name = self._default_preset_path.read_text(encoding="utf-8").strip()
            if preset_name:
                # Verify preset still exists
                preset_path = self.presets_dir / f"{preset_name}.json"
                if preset_path.exists():
                    return preset_name
                else:
                    logger.warning(f"Default preset '{preset_name}' no longer exists")
                    # Clean up stale reference
                    self._default_preset_path.unlink(missing_ok=True)
                    return None
            return None
        except Exception as e:
            logger.error(f"Failed to read default preset: {e}")
            return None

    def clear_default_preset(self) -> bool:
        """
        Clear the default preset setting.

        Returns:
            True if cleared successfully
        """
        try:
            self._default_preset_path.unlink(missing_ok=True)
            logger.info("Cleared default preset")
            return True
        except Exception as e:
            logger.error(f"Failed to clear default preset: {e}")
            return False

    def write_last_run(self, payload: dict[str, Any]) -> None:
        """Persist the last-run payload so the GUI can restore it later."""

        if not payload:
            return
        try:
            LAST_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LAST_RUN_PATH.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
            logger.info("Last run configuration written to %s", LAST_RUN_PATH)
        except Exception as exc:
            logger.warning("Failed to write last run configuration: %s", exc)

    def load_last_run(self) -> dict[str, Any] | None:
        """Read the previously saved last-run payload."""

        if not LAST_RUN_PATH.exists():
            return None
        try:
            with LAST_RUN_PATH.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:
            logger.warning("Failed to load last run configuration: %s", exc)
            return None


# PR-203: Queue state persistence
QUEUE_STATE_PATH = Path("state/queue_state_v2.json")


def save_queue_state(queue_data: dict[str, Any]) -> bool:
    """
    Save the queue state to disk for persistence across sessions.

    Args:
        queue_data: Serialized queue state from JobQueueV2.serialize()

    Returns:
        True if saved successfully
    """
    if not queue_data:
        return False
    try:
        QUEUE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with QUEUE_STATE_PATH.open("w", encoding="utf-8") as fh:
            json.dump(queue_data, fh, indent=2, ensure_ascii=False)
        logger.info("Queue state saved to %s", QUEUE_STATE_PATH)
        return True
    except Exception as exc:
        logger.warning("Failed to save queue state: %s", exc)
        return False


def load_queue_state() -> dict[str, Any] | None:
    """
    Load the queue state from disk.

    Returns:
        Serialized queue state to pass to JobQueueV2.restore(), or None if no state exists
    """
    if not QUEUE_STATE_PATH.exists():
        return None
    try:
        with QUEUE_STATE_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        logger.info("Queue state loaded from %s", QUEUE_STATE_PATH)
        return data
    except Exception as exc:
        logger.warning("Failed to load queue state: %s", exc)
        return None


def clear_queue_state() -> bool:
    """
    Delete the saved queue state file.

    Returns:
        True if cleared successfully
    """
    try:
        QUEUE_STATE_PATH.unlink(missing_ok=True)
        logger.info("Queue state cleared")
        return True
    except Exception as exc:
        logger.warning("Failed to clear queue state: %s", exc)
        return False
