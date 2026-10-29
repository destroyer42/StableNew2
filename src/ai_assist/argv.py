"""The only way a command line or child environment for the offline runtime is made. Pure.

Every flag comes from a closed constant list and every value from a typed parameter, so no input can produce a network
option (``-hf``, ``-mu``, ``-dr``, ``--connect``, ``--ui-mcp-proxy``), a multimodal projector, a listening address or any
flag that is not named here. Execution is CPU-only and offline by construction (owner decisions D2, D3, D8). Prompt text and
the JSON Schema go to the child as files, never on the command line, which other processes can read.

The flag spellings below are PROVISIONAL until PR-AI-111 validates them against the pinned build; a spelling the build does
not accept makes the child exit non-zero (``UNAVAILABLE``), it can never widen what is allowed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

#: The complete vocabulary. Anything else is refused by :func:`assert_argv_allowed`.
ALLOWED_FLAGS: frozenset[str] = frozenset(
    {
        "-m",
        "-f",
        "--json-schema-file",
        "-c",
        "-n",
        "-t",
        "-ngl",
        "--offline",
        "--temp",
        "--top-k",
        "--top-p",
        "--presence-penalty",
        "--seed",
        "--no-display-prompt",
        "--no-conversation",
        "--reasoning",
        "--prio",
        "--log-disable",
    }
)

#: Flags that must never appear, listed so a test can prove the builder cannot emit them.
FORBIDDEN_FLAGS: frozenset[str] = frozenset(
    {
        "-hf",
        "--hf-repo",
        "-hfd",
        "--hf-repo-draft",
        "-mu",
        "--model-url",
        "-dr",
        "--docker-repo",
        "-mmu",
        "--mmproj-url",
        "--mmproj",
        "--connect",
        "--ui-mcp-proxy",
        "--host",
        "--port",
        "--api-key",
        "--webui",
        "--media-path",
        "--lora",
        "--control-vector",
        "--rpc",
    }
)

#: The minimum a native Windows child needs to start. Nothing else is inherited.
_INHERITED_VARIABLES = ("SystemRoot", "windir", "TEMP", "TMP", "COMSPEC", "PATHEXT")


@dataclass(frozen=True, slots=True)
class Sampling:
    """Non-thinking sampling recommended by the Qwen3.5 model card (a starting point; PR-AI-111 may change it)."""

    temperature: float = 0.7
    top_p: float = 0.8
    top_k: int = 20
    presence_penalty: float = 1.5
    seed: int = 321


@dataclass(frozen=True, slots=True)
class RunLimits:
    context_tokens: int = 4096
    max_new_tokens: int = 768
    threads: int = 8
    timeout_seconds: float = 90.0
    max_stdout_bytes: int = 256 * 1024

    def __post_init__(self) -> None:
        if not 512 <= self.context_tokens <= 32768:
            raise ValueError("context_tokens out of range")
        if not 16 <= self.max_new_tokens <= self.context_tokens:
            raise ValueError("max_new_tokens out of range")
        if not 1 <= self.threads <= 64:
            raise ValueError("threads out of range")
        if not (math.isfinite(self.timeout_seconds) and 1.0 <= self.timeout_seconds <= 600.0):
            raise ValueError("timeout_seconds out of range")
        if not 1024 <= self.max_stdout_bytes <= 4 * 1024 * 1024:
            raise ValueError("max_stdout_bytes out of range")


def build_argv(
    model_path: Path,
    prompt_file: Path,
    schema_file: Path,
    limits: RunLimits,
    sampling: Sampling = Sampling(),  # noqa: B008 - frozen dataclass default
) -> list[str]:
    """Arguments (without the executable) for one CPU-only, offline, non-interactive completion."""

    argv = [
        "--offline",
        "-ngl",
        "0",
        "--log-disable",
        "--no-display-prompt",
        "--no-conversation",
        "--reasoning",
        "off",
        "--prio",
        "-1",
        "-m",
        str(model_path),
        "-f",
        str(prompt_file),
        "--json-schema-file",
        str(schema_file),
        "-c",
        str(limits.context_tokens),
        "-n",
        str(limits.max_new_tokens),
        "-t",
        str(limits.threads),
        "--temp",
        repr(float(sampling.temperature)),
        "--top-p",
        repr(float(sampling.top_p)),
        "--top-k",
        str(int(sampling.top_k)),
        "--presence-penalty",
        repr(float(sampling.presence_penalty)),
        "--seed",
        str(int(sampling.seed)),
    ]
    assert_argv_allowed(argv)
    return argv


def assert_argv_allowed(argv: list[str], allowed: frozenset[str] = ALLOWED_FLAGS) -> None:
    """Raise if any flag-shaped token is not in the closed vocabulary (values may be negative numbers or paths).

    ``allowed`` defaults to the production vocabulary; a qualification contract may pass its own closed superset."""

    for token in argv:
        if token in FORBIDDEN_FLAGS:
            raise ValueError(f"forbidden runtime flag: {token}")
    index = 0
    while index < len(argv):
        token = argv[index]
        if token.startswith("-") and not _is_number(token):
            if token not in allowed:
                raise ValueError(f"runtime flag is not allow-listed: {token}")
            # Every allowed flag except the switches takes exactly one value; skip it so a path is never read as a flag.
            if token not in _SWITCHES:
                index += 1
        index += 1


_SWITCHES = frozenset({"--offline", "--no-display-prompt", "--no-conversation", "--log-disable"})


def _is_number(token: str) -> bool:
    try:
        float(token)
    except ValueError:
        return False
    return True


def build_environment(
    runtime_dir: Path, base: Mapping[str, str], work_dir: Path | None = None
) -> dict[str, str]:
    """A scrubbed child environment: no proxy variables, no GPU, no Hub access, and nothing else inherited.

    ``base`` is the parent environment (passed in so tests need not touch the real one).
    """

    environment = {name: base[name] for name in _INHERITED_VARIABLES if name in base}
    environment["PATH"] = str(runtime_dir)
    environment["CUDA_VISIBLE_DEVICES"] = "-1"
    environment["HF_HUB_OFFLINE"] = "1"
    environment["TRANSFORMERS_OFFLINE"] = "1"
    environment["LLAMA_ARG_OFFLINE"] = "1"
    environment["NO_PROXY"] = "*"
    if work_dir is not None:
        environment["TEMP"] = environment["TMP"] = str(work_dir)
    return environment


__all__ = [
    "ALLOWED_FLAGS",
    "FORBIDDEN_FLAGS",
    "RunLimits",
    "Sampling",
    "assert_argv_allowed",
    "build_argv",
    "build_environment",
]
