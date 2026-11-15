"""The closed visual argument vocabulary and builder for ``llama-mtmd-cli.exe`` (PR-AI-VL-220, image invocation contract).

This is the only place in the repository where ``--mmproj`` or ``--image`` may be emitted. It lives in the evaluation harness,
never in ``src/ai_assist/argv.py``: ``FORBIDDEN_FLAGS``, ``ALLOWED_FLAGS``, ``build_argv`` and ``build_production_argv`` are
untouched, so production still refuses a projector, an image and every network flag.

The vocabulary is exactly the "yes" rows of section 2 of ``docs/Subsystems/AiAssist/PR-AI-VL-220_Image_Invocation_Contract.md``.
Every flag comes from a closed list and every value from a typed parameter or a checked path; a prompt is never on the command
line (``-f`` names a file), ``--log-disable`` is absent (it would empty stdout), and ``-p``, ``-hf``, ``-mu``, ``--mmproj-url``,
and every other forbidden network or loader flag are refused. Pure apart from reading the files it is asked to check: it starts no
process and opens no socket.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from src.ai_assist.argv import FORBIDDEN_FLAGS
from tools.qualification.vl220 import contract

#: The separate pinned build entry (same archive and per-file hashes as ``b11960-cpu``) that carries this tool.
VISION_BUILD_ID = "b11960-cpu-vision"
VISION_TOOL = "llama-mtmd-cli.exe"

#: Switches take no value; every other allowed flag takes exactly one.
VISUAL_SWITCHES: frozenset[str] = frozenset({"--offline", "--no-mmproj-offload"})
VISUAL_VALUE_FLAGS: frozenset[str] = frozenset(
    {
        "-ngl", "-f", "--json-schema-file", "-c", "-n", "-t", "--temp", "--top-p", "--top-k", "--min-p",
        "--presence-penalty", "--repeat-penalty", "--seed", "--prio", "-m", "--mmproj", "--image", "-mmdev",
        "--image-min-tokens", "--image-max-tokens",
    }
)  # fmt: skip
VISUAL_ALLOWED_FLAGS: frozenset[str] = VISUAL_SWITCHES | VISUAL_VALUE_FLAGS

#: Refused by name even though a typo could not widen the allow-list anyway: the production forbidden set (minus the one flag
#: this builder owns) plus the contract's explicit "no" rows (``-p``, ``--log-disable``) and the open ``--jinja`` question.
VISUAL_REFUSED_FLAGS: frozenset[str] = (FORBIDDEN_FLAGS - {"--mmproj"}) | {
    "-p",
    "--prompt",
    "--log-disable",
    "--jinja",
}

_ROLE_OF_FLAG = {
    "-m": "<model>",
    "--mmproj": "<mmproj>",
    "--image": "<image>",
    "-f": "<prompt>",
    "--json-schema-file": "<schema>",
}
_GEMMA_TEMPLATE_FLAG = "--jinja"
_AT_MOST_ONCE = (VISUAL_ALLOWED_FLAGS | {_GEMMA_TEMPLATE_FLAG}) - {"--image"}

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_SIDE = 4096
_HEADER_BYTES = 256 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


class VisualArgvRefused(ValueError):
    """A visual command line (or one of its files) is not acceptable. ``code`` is a stable token; nothing was built."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def _refuse(code: str, detail: str = "") -> VisualArgvRefused:
    return VisualArgvRefused(code, detail)


@dataclass(frozen=True, slots=True)
class VisualLimits:
    """Per-case ceilings and image-token bounds. The image-token values are a conservative starting point: the contract sets
    the real ones from the first supervised measurement, so they are owner-tunable and bounded here."""

    context_tokens: int = contract.ResourceLimits().max_context_tokens
    max_new_tokens: int = 768
    threads: int = 8
    timeout_seconds: float = contract.ResourceLimits().max_wall_seconds
    max_stdout_bytes: int = 64 * 1024
    image_min_tokens: int = 64
    image_max_tokens: int = 256

    def __post_init__(self) -> None:
        if not 512 <= self.context_tokens <= 32768:
            raise ValueError("context_tokens out of range")
        if not 16 <= self.max_new_tokens <= self.context_tokens:
            raise ValueError("max_new_tokens out of range")
        if not 1 <= self.threads <= 64:
            raise ValueError("threads out of range")
        if not (math.isfinite(self.timeout_seconds) and 1.0 <= self.timeout_seconds <= 600.0):
            raise ValueError("timeout_seconds out of range")
        if not contract.MAX_RESPONSE_BYTES <= self.max_stdout_bytes <= 4 * 1024 * 1024:
            raise ValueError("max_stdout_bytes out of range")
        if not 1 <= self.image_min_tokens <= self.image_max_tokens <= 1024:
            raise ValueError("image token bounds out of range")


@dataclass(frozen=True, slots=True)
class VisualSampling:
    """Greedy by default: an evaluation should be repeatable, and the response grammar already bounds the answer."""

    temperature: float = 0.0
    top_p: float = 1.0
    top_k: int = 1
    min_p: float = 0.0
    presence_penalty: float = 0.0
    repeat_penalty: float = 1.0
    seed: int = 321

    def __post_init__(self) -> None:
        numbers = (
            self.temperature,
            self.top_p,
            self.min_p,
            self.presence_penalty,
            self.repeat_penalty,
        )
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in numbers):
            raise ValueError("sampling values must be finite numbers")
        if not (
            0.0 <= self.temperature <= 2.0 and 0.0 < self.top_p <= 1.0 and 0.0 <= self.min_p <= 1.0
        ):
            raise ValueError("sampling value out of range")
        if not (0.0 <= self.presence_penalty <= 2.0 and 1.0 <= self.repeat_penalty <= 2.0):
            raise ValueError("penalty out of range")
        if not (1 <= self.top_k <= 1000 and 0 <= self.seed <= 2**31 - 1):
            raise ValueError("top_k or seed out of range")


# ------------------------------------------------------------------------------------------------------------- images


def inspect_image(path: Path) -> tuple[str, int, int]:
    """``(media type, width, height)`` of a PNG or JPEG, from its signature and header only; refuse anything else.

    At most 8 MiB and 4096 x 4096. Only the first 256 KiB is read, and no image decoder is involved."""

    try:
        size = path.stat().st_size
        if not path.is_file():
            raise _refuse("image_missing")
        if not 0 < size <= MAX_IMAGE_BYTES:
            raise _refuse("image_size_out_of_range")
        with path.open("rb") as handle:
            head = handle.read(_HEADER_BYTES)
    except FileNotFoundError as exc:
        raise _refuse("image_missing") from exc
    except OSError as exc:
        raise _refuse("image_unreadable") from exc
    if head.startswith(_PNG_SIGNATURE):
        if head[12:16] != b"IHDR" or len(head) < 24:
            raise _refuse("image_header_invalid")
        media, width, height = (
            "image/png",
            int.from_bytes(head[16:20], "big"),
            int.from_bytes(head[20:24], "big"),
        )
    elif head.startswith(b"\xff\xd8\xff"):
        media, dimensions = "image/jpeg", _jpeg_dimensions(head)
        if dimensions is None:
            raise _refuse("image_header_invalid")
        width, height = dimensions
    else:
        raise _refuse("image_not_png_or_jpeg")
    if not (0 < width <= MAX_IMAGE_SIDE and 0 < height <= MAX_IMAGE_SIDE):
        raise _refuse("image_dimensions_out_of_range")
    return media, width, height


def _jpeg_dimensions(head: bytes) -> tuple[int, int] | None:
    index = 2
    while index + 4 <= len(head):
        if head[index] != 0xFF:
            return None
        marker = head[index + 1]
        if marker == 0xFF:
            index += 1
            continue
        if marker in _SOF_MARKERS:
            if index + 9 > len(head):
                return None
            return int.from_bytes(head[index + 7 : index + 9], "big"), int.from_bytes(
                head[index + 5 : index + 7], "big"
            )
        if marker == 0xD8 or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            index += 2
            continue
        length = int.from_bytes(head[index + 2 : index + 4], "big")
        if length < 2:
            return None
        index += 2 + length
    return None


# ------------------------------------------------------------------------------------------------------------ checking


def _is_number(token: str) -> bool:
    try:
        return math.isfinite(float(token))
    except ValueError:
        return False


def _flag_shaped(token: str) -> bool:
    return token.startswith("-") and not _is_number(token)


def check_visual_argv(argv: list[str], *, free_text: bool = False, use_jinja: bool = False) -> None:
    """Raise :class:`VisualArgvRefused` unless ``argv`` is exactly the closed visual vocabulary in a safe shape.

    Beyond the allow-list: every value-taking flag has a value that is not itself flag-shaped, no flag repeats (except one
    ``--image`` per image, one or two), exactly one ``--mmproj`` and one ``-m``, an image and a prompt file are present, and the
    CPU-only settings (``-ngl 0``, ``-mmdev none``, ``--no-mmproj-offload``, ``--offline``) are all there.

    ``free_text`` is the diagnostic control (PR-AI-VL-222): the one difference is that no ``--json-schema-file`` is given (and
    one is refused), so the answer is unconstrained text. It adds no flag to the vocabulary."""

    counts: Counter[str] = Counter()
    values: dict[str, list[str]] = {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if not isinstance(token, str) or not _flag_shaped(token):
            raise _refuse("stray_value", str(token)[:40])
        if use_jinja and token == _GEMMA_TEMPLATE_FLAG:
            counts[token] += 1
            index += 1
            continue
        if token in VISUAL_REFUSED_FLAGS:
            raise _refuse("forbidden_flag", token)
        if token not in VISUAL_ALLOWED_FLAGS:
            raise _refuse("flag_not_allow_listed", token)
        counts[token] += 1
        if token in VISUAL_SWITCHES:
            index += 1
            continue
        if index + 1 >= len(argv) or _flag_shaped(argv[index + 1]) or argv[index + 1] == "":
            raise _refuse("missing_value", token)
        values.setdefault(token, []).append(argv[index + 1])
        index += 2
    for flag in _AT_MOST_ONCE:
        if counts[flag] > 1:
            raise _refuse("flag_repeated", flag)
    if use_jinja and counts[_GEMMA_TEMPLATE_FLAG] != 1:
        raise _refuse("gemma_template_flag_required")
    if counts["--mmproj"] != 1:
        raise _refuse("exactly_one_mmproj_required")
    expected_schema = 0 if free_text else 1
    if counts["-m"] != 1 or counts["-f"] != 1 or counts["--json-schema-file"] != expected_schema:
        raise _refuse("model_prompt_and_schema_required")
    if counts["--image"] not in (1, 2):
        raise _refuse("one_or_two_images_required")
    if (
        counts["--offline"] != 1
        or counts["--no-mmproj-offload"] != 1
        or values.get("-ngl") != ["0"]
        or values.get("-mmdev") != ["none"]
    ):
        raise _refuse("cpu_only_offline_settings_required")
    numeric = (
        "-c", "-n", "-t", "--temp", "--top-p", "--top-k", "--min-p", "--presence-penalty", "--repeat-penalty",
        "--seed", "--prio", "--image-min-tokens", "--image-max-tokens",
    )  # fmt: skip
    for flag in numeric:
        for value in values.get(flag, []):
            if not _is_number(value):
                raise _refuse("value_not_a_number", flag)


def argv_shape(argv: list[str]) -> list[str]:
    """``argv`` with every path replaced by its role, so the shape (flags and numeric settings) can be hashed and compared
    without the temporary paths, which differ on every run."""

    shaped: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        shaped.append(token)
        if token in _ROLE_OF_FLAG and index + 1 < len(argv):
            shaped.append(_ROLE_OF_FLAG[token])
            index += 2
        else:
            index += 1
    return shaped


def argv_shape_digest(argv: list[str]) -> str:
    """SHA-256 of the path-free shape: evidence of what was launched that names no path, prompt or image."""

    return hashlib.sha256("\0".join(argv_shape(argv)).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------------------------ building


def _inside(path: Path, root: Path, code: str) -> Path:
    try:
        resolved = Path(path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _refuse(code, "does not exist") from exc
    base = Path(root).resolve()
    if not resolved.is_file() or not (resolved == base or base in resolved.parents):
        raise _refuse(code, "not a file inside its allowed directory")
    return resolved


def _prompt_file(path: Path, work_dir: Path) -> Path:
    resolved = _inside(path, work_dir, "prompt_file_outside_work_dir")
    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise _refuse("prompt_file_unreadable") from exc
    if not text.strip():
        raise _refuse("prompt_file_empty")
    if "<__media__>" in text:
        raise _refuse("reserved_media_marker_in_prompt")
    return resolved


def build_visual_argv(
    *,
    model_path: Path,
    projector_path: Path,
    prompt_file: Path,
    schema_file: Path | None,
    image_paths: list[Path],
    evaluation_root: Path,
    work_dir: Path,
    limits: VisualLimits | None = None,
    sampling: VisualSampling | None = None,
    free_text: bool = False,
    use_jinja: bool = False,
) -> list[str]:
    """Arguments (without the executable) for one single-turn, CPU-only, offline image question.

    ``free_text`` (the diagnostic control only) takes ``schema_file=None`` and emits no ``--json-schema-file``; a schema file
    given with it, or none given without it, is refused.

    The model and the one projector must be files inside ``evaluation_root``; the prompt, schema and images must be files inside
    the private ``work_dir``. An empty prompt file or a missing image is refused because ``mtmd-cli`` is single-turn only when
    it is given both (otherwise it would sit in an interactive chat reading stdin). The result is checked by
    :func:`check_visual_argv` before it is returned."""

    limits = limits if limits is not None else VisualLimits()
    sampling = sampling if sampling is not None else VisualSampling()
    if not 1 <= len(image_paths) <= 2:
        raise _refuse("one_or_two_images_required")
    model = _inside(model_path, evaluation_root, "model_outside_evaluation_root")
    projector = _inside(projector_path, evaluation_root, "projector_outside_evaluation_root")
    if model == projector:
        raise _refuse("projector_is_the_model")
    prompt = _prompt_file(prompt_file, work_dir)
    if free_text != (schema_file is None):
        raise _refuse("schema_file_does_not_match_the_request_mode")
    schema = (
        None
        if schema_file is None
        else _inside(schema_file, work_dir, "schema_file_outside_work_dir")
    )
    images = [_inside(path, work_dir, "image_outside_work_dir") for path in image_paths]
    for image in images:
        if "," in str(image):
            raise _refuse("image_path_has_csv_separator")
        inspect_image(image)
    argv = [
        "--offline",
        "-ngl",
        "0",
        "--no-mmproj-offload",
        "-mmdev",
        "none",
        "--prio",
        "-1",
        "-m",
        str(model),
        "--mmproj",
        str(projector),
    ]
    for image in images:
        argv += ["--image", str(image)]
    argv += [
        "-f",
        str(prompt),
    ]
    if schema is not None:
        argv += ["--json-schema-file", str(schema)]
    argv += [
        "-c",
        str(limits.context_tokens),
        "-n",
        str(limits.max_new_tokens),
        "-t",
        str(limits.threads),
        "--image-min-tokens",
        str(limits.image_min_tokens),
        "--image-max-tokens",
        str(limits.image_max_tokens),
        "--temp",
        repr(float(sampling.temperature)),
        "--top-p",
        repr(float(sampling.top_p)),
        "--top-k",
        str(int(sampling.top_k)),
        "--min-p",
        repr(float(sampling.min_p)),
        "--presence-penalty",
        repr(float(sampling.presence_penalty)),
        "--repeat-penalty",
        repr(float(sampling.repeat_penalty)),
        "--seed",
        str(int(sampling.seed)),
    ]
    if use_jinja:
        argv.append(_GEMMA_TEMPLATE_FLAG)
    check_visual_argv(argv, free_text=free_text, use_jinja=use_jinja)
    return argv


__all__ = [
    "MAX_IMAGE_BYTES",
    "MAX_IMAGE_SIDE",
    "VISION_BUILD_ID",
    "VISION_TOOL",
    "VISUAL_ALLOWED_FLAGS",
    "VISUAL_REFUSED_FLAGS",
    "VISUAL_SWITCHES",
    "VISUAL_VALUE_FLAGS",
    "VisualArgvRefused",
    "VisualLimits",
    "VisualSampling",
    "argv_shape",
    "argv_shape_digest",
    "build_visual_argv",
    "check_visual_argv",
    "inspect_image",
]
