from __future__ import annotations

from pathlib import Path
from typing import Any


class FakePipeline:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.stage_events: list[dict[str, Any]] = []
        self._output_writer = _kwargs.get("output_writer")

    def run_txt2img_stage(
        self,
        prompt: str,
        negative_prompt: str,
        config: dict[str, Any],
        output_dir: Path,
        *,
        image_name: str | None = None,
        batch_size: int = 1,
        cancel_token: Any | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(("txt2img", image_name or "txt2img"))
        self.stage_events.append({"stage": "txt2img"})
        generated = [output_dir / f"{image_name or 'txt2img'}_{i}.png" for i in range(batch_size)]
        if self._output_writer:
            for path in generated:
                self._output_writer(path)
        return {"path": str(generated[0]), "images": [str(path) for path in generated]}

    def run_img2img_stage(
        self,
        input_image: Any,
        prompt: str,
        negative_prompt: str,
        config: dict[str, Any],
        output_dir: Path,
        *,
        image_name: str | None = None,
        cancel_token: Any | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(("img2img", image_name or "img2img"))
        self.stage_events.append({"stage": "img2img"})
        output_path = output_dir / f"{image_name or 'img2img'}.png"
        if self._output_writer:
            self._output_writer(output_path)
        return {"path": str(output_path), "images": [str(output_path)]}

    def run_upscale_stage(
        self,
        input_image: Any,
        config: dict[str, Any],
        output_dir: Path,
        *,
        image_name: str | None = None,
        cancel_token: Any | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(("upscale", image_name or "upscale"))
        self.stage_events.append({"stage": "upscale"})
        output_path = output_dir / f"{image_name or 'upscale'}.png"
        if self._output_writer:
            self._output_writer(output_path)
        return {"path": str(output_path), "images": [str(output_path)]}

    def run_adetailer_stage(
        self,
        input_image: Any,
        config: dict[str, Any],
        output_dir: Path,
        *,
        image_name: str | None = None,
        prompt: str | None = None,
        cancel_token: Any | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(("adetailer", image_name or "adetailer"))
        self.stage_events.append({"stage": "adetailer"})
        output_path = output_dir / f"{image_name or 'adetailer'}.png"
        if self._output_writer:
            self._output_writer(output_path)
        return {"path": str(output_path), "images": [str(output_path)]}

    def reset_stage_events(self) -> None:
        self.stage_events = []

    def get_stage_events(self) -> list[dict[str, Any]]:
        return list(self.stage_events)
