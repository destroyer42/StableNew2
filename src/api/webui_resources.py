from __future__ import annotations
import os
from enum import Enum, auto
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.api.client import SDWebUIClient

class WebUIResourceType(Enum):
    MODEL = auto()
    VAE = auto()
    HYPERNET = auto()
    EMBEDDING = auto()
    UPSCALER = auto()
    STYLE = auto()
    # Add more types as needed

@dataclass
class WebUIResource:
    type: WebUIResourceType
    name: str
    display_name: str
    raw: dict[str, Any] | None = None

class WebUIResourceService:
    def __init__(self, client: SDWebUIClient | None = None, webui_root: str | None = None):
        self.client = client or SDWebUIClient()
        self.webui_root = webui_root or os.environ.get("STABLENEW_WEBUI_ROOT", "stable-diffusion-webui")
        self.root_path = Path(self.webui_root or "stable-diffusion-webui")

    def list_models(self) -> list[WebUIResource]:
        # If no client, always use filesystem fallback
        def is_in_temp_dir(file: Path) -> bool:
            # Only include files strictly under the provided webui_root
            try:
                return str(file.resolve()).startswith(str(self.root_path.resolve()))
            except Exception:
                return False

        if self.client is None:
            model_dir = self.root_path / "models" / "Stable-diffusion"
            resources = []
            if model_dir.exists():
                for ext in ("*.ckpt", "*.safetensors"):
                    for file in model_dir.glob(ext):
                        if is_in_temp_dir(file):
                            name = file.stem
                            resources.append(WebUIResource(
                                type=WebUIResourceType.MODEL,
                                name=name,
                                display_name=name,
                                raw={"path": str(file)},
                            ))
            return resources
        # Try API first
        try:
            api_models = self.client.get_models()
            if api_models:
                return [WebUIResource(
                    type=WebUIResourceType.MODEL,
                    name=m.get("model_name", m.get("title", "")),
                    display_name=m.get("title", m.get("model_name", "")),
                    raw=m,
                ) for m in api_models]
        except Exception:
            pass
        # Fallback to filesystem
        model_dir = self.root_path / "models" / "Stable-diffusion"
        resources = []
        if model_dir.exists():
            for ext in ("*.ckpt", "*.safetensors"):
                for file in model_dir.glob(ext):
                    if is_in_temp_dir(file):
                        name = file.stem
                        resources.append(WebUIResource(
                            type=WebUIResourceType.MODEL,
                            name=name,
                            display_name=name,
                            raw={"path": str(file)},
                        ))
        return resources

    def list_vaes(self) -> list[WebUIResource]:
        try:
            api_vaes = self.client.get_vae_models()
            if api_vaes:
                return [WebUIResource(
                    type=WebUIResourceType.VAE,
                    name=v.get("model_name", v.get("title", "")),
                    display_name=v.get("title", v.get("model_name", "")),
                    raw=v,
                ) for v in api_vaes]
        except Exception:
            pass
        vae_dir = self.root_path / "models" / "VAE"
        resources = []
        for file in vae_dir.glob("*"):
            if file.is_file():
                name = file.stem
                resources.append(WebUIResource(
                    type=WebUIResourceType.VAE,
                    name=name,
                    display_name=name,
                    raw={"path": str(file)},
                ))
        return resources

    def list_hypernetworks(self) -> list[WebUIResource]:
        try:
            api_hypernets = self.client.get_hypernetworks()
            if api_hypernets:
                return [WebUIResource(
                    type=WebUIResourceType.HYPERNET,
                    name=h.get("name", ""),
                    display_name=h.get("name", ""),
                    raw=h,
                ) for h in api_hypernets]
        except Exception:
            pass
        hyper_dir = self.root_path / "models" / "hypernetworks"
        resources = []
        for file in hyper_dir.glob("*"):
            if file.is_file():
                name = file.stem
                resources.append(WebUIResource(
                    type=WebUIResourceType.HYPERNET,
                    name=name,
                    display_name=name,
                    raw={"path": str(file)},
                ))
        return resources

    def list_embeddings(self) -> list[WebUIResource]:
        # No API endpoint in SDWebUIClient, fallback to filesystem only
        emb_dir = self.root_path / "embeddings"
        resources = []
        for file in emb_dir.glob("*"):
            if file.is_file():
                name = file.stem
                resources.append(WebUIResource(
                    type=WebUIResourceType.EMBEDDING,
                    name=name,
                    display_name=name,
                    raw={"path": str(file)},
                ))
        return resources

    def list_upscalers(self) -> list[WebUIResource]:
        try:
            api_upscalers = self.client.get_upscalers()
            if api_upscalers:
                return [WebUIResource(
                    type=WebUIResourceType.UPSCALER,
                    name=u.get("name", ""),
                    display_name=u.get("name", ""),
                    raw=u,
                ) for u in api_upscalers]
        except Exception:
            pass
        up_dir = self.root_path / "models" / "ESRGAN"
        resources = []
        for file in up_dir.glob("*"):
            if file.is_file():
                name = file.stem
                resources.append(WebUIResource(
                    type=WebUIResourceType.UPSCALER,
                    name=name,
                    display_name=name,
                    raw={"path": str(file)},
                ))
        return resources

__all__ = ["WebUIResourceType", "WebUIResource", "WebUIResourceService"]
