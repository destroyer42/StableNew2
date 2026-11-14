"""Closed argument vocabulary and image preparation for the pinned mtmd CLI."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from PIL import Image

from src.ai_assist.argv import FORBIDDEN_FLAGS
from tools.qualification.vl220 import contract
from tools.qualification.vl220.candidates import has_link

MAX_IMAGE_BYTES = 8 * 1024**2
MAX_IMAGE_EDGE = 4096
_MEDIA_MARKER = "<__media__>"
_IMAGE_TYPES = {"image/png": ("PNG", ".png"), "image/jpeg": ("JPEG", ".jpg")}
_VISUAL_SWITCHES = frozenset({"--offline", "--no-mmproj-offload", "--jinja"})
_VISUAL_VALUES = frozenset(
    {
        "-ngl",
        "-mmdev",
        "-m",
        "--mmproj",
        "--image",
        "-f",
        "--json-schema-file",
        "-c",
        "-n",
        "-t",
        "--temp",
        "--seed",
        "--prio",
    }
)
VISUAL_ALLOWED_FLAGS = _VISUAL_SWITCHES | _VISUAL_VALUES
VISUAL_FORBIDDEN_FLAGS = (FORBIDDEN_FLAGS - {"--mmproj"}) | {
    "--audio",
    "--video",
    "--log-disable",
    "--control-vector",
    "-p",
}


class InvocationRefused(ValueError):
    """The reason code is safe to include in evidence."""


def copy_image(asset: contract.Asset, source_root: Path, scratch: Path, index: int) -> Path:
    """Check frozen bytes and inspect PNG/JPEG dimensions without decoding pixels."""
    image_type, suffix = _IMAGE_TYPES[asset.media_type]
    source = source_root / f"{asset.asset_id}{suffix}"
    if not source.is_relative_to(source_root) or has_link(source) or not source.is_file():
        raise InvocationRefused("image_path_invalid")
    if not 0 < asset.bytes <= MAX_IMAGE_BYTES or source.stat().st_size != asset.bytes:
        raise InvocationRefused("image_size_mismatch")
    with source.open("rb") as handle:
        data = handle.read(MAX_IMAGE_BYTES + 1)
    if len(data) != asset.bytes or hashlib.sha256(data).hexdigest() != asset.sha256:
        raise InvocationRefused("image_pin_mismatch")
    try:
        with Image.open(io.BytesIO(data), formats=[image_type]) as image:
            accepted = all(0 < edge <= MAX_IMAGE_EDGE for edge in image.size)
    except (ValueError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise InvocationRefused("image_header_invalid") from exc
    if not accepted:
        raise InvocationRefused("image_dimensions_exceeded")
    target = scratch / f"image-{index}{suffix}"
    target.write_bytes(data)
    return target


def write_inputs(case: contract.Case, scratch: Path) -> tuple[Path, Path]:
    """Render a fixed frame from the validated case, with reference data kept out of it."""
    if (
        not case.prompt.strip()
        or _MEDIA_MARKER in case.prompt
        or any(_MEDIA_MARKER in text for _, text in case.elements)
    ):
        raise InvocationRefused("prompt_invalid")
    prompt = case.prompt
    if case.elements:
        prompt += "\nUse these exact element IDs:\n" + "\n".join(
            f"{key}: {text}" for key, text in case.elements
        )
    if case.kind == contract.KIND_BEFORE_AFTER:
        prompt += "\nThe first image is a. The second image is b."
    prompt += f"\nRespond with one JSON object using the {contract.RESPONSE_SCHEMA} schema for {case.kind}."
    prompt_file = scratch / "prompt.txt"
    schema_file = scratch / "schema.json"
    prompt_file.write_text(prompt, encoding="utf-8", newline="\n")
    schema_file.write_text(
        contract.canonical_json(contract.build_response_schema(case.kind)),
        encoding="utf-8",
        newline="\n",
    )
    return prompt_file, schema_file


def build_visual_argv(
    root: Path,
    scratch: Path,
    model: Path,
    projector: Path,
    images: tuple[Path, ...],
    prompt: Path,
    schema: Path,
    *,
    jinja: bool,
    context_tokens: int,
) -> list[str]:
    """Build a single-turn command with explicit local paths and a closed flag set."""
    if len(images) not in (1, 2) or not 512 <= context_tokens <= 4096:
        raise InvocationRefused("invocation_limits_invalid")
    if not root.is_absolute() or not scratch.resolve().is_relative_to(root):
        raise InvocationRefused("invocation_path_invalid")
    for base, paths in ((root, (model, projector)), (scratch, (*images, prompt, schema))):
        for path in paths:
            if has_link(path) or not path.resolve().is_relative_to(base) or not path.is_file():
                raise InvocationRefused("invocation_path_invalid")
    if any("," in str(path) for path in images):
        raise InvocationRefused("image_path_has_csv_separator")
    if not prompt.read_text(encoding="utf-8").strip():
        raise InvocationRefused("prompt_invalid")

    flags = [
        ("--offline", None),
        ("-ngl", "0"),
        ("--no-mmproj-offload", None),
        ("-mmdev", "none"),
        ("-m", str(model)),
        ("--mmproj", str(projector)),
        ("-f", str(prompt)),
        ("--json-schema-file", str(schema)),
        ("-c", str(context_tokens)),
        ("-n", "768"),
        ("-t", "8"),
        ("--temp", "0"),
        ("--seed", "220"),
        ("--prio", "-1"),
    ]
    if jinja:
        flags.append(("--jinja", None))
    # b11960 appends each occurrence to params.image in order.
    flags.extend(("--image", str(image)) for image in images)
    argv: list[str] = []
    for flag, value in flags:
        if flag in VISUAL_FORBIDDEN_FLAGS or flag not in VISUAL_ALLOWED_FLAGS:
            raise InvocationRefused("runtime_flag_refused")
        if (flag in _VISUAL_SWITCHES) != (value is None):
            raise InvocationRefused("runtime_flag_arity")
        argv.append(flag)
        if value is not None:
            argv.append(value)
    if argv.count("--mmproj") != 1:
        raise InvocationRefused("projector_flag_count")
    return argv


def strict_json(text: str) -> object:
    """Apply the no-duplicate-key and no-nonfinite-number rules missing from json.loads defaults."""

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        fields: dict[str, object] = {}
        for key, value in pairs:
            if key in fields:
                raise ValueError("duplicate key")
            fields[key] = value
        return fields

    def invalid_constant(_: str) -> object:
        raise ValueError("non-finite number")

    return json.loads(text, object_pairs_hook=unique, parse_constant=invalid_constant)
