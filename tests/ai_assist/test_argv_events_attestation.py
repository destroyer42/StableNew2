"""Egress is closed by construction; the event record cannot hold content; attestation is an operator statement."""

from __future__ import annotations

import json
import random
import string
from pathlib import Path

import pytest

from src.ai_assist.argv import (
    ALLOWED_FLAGS,
    FORBIDDEN_FLAGS,
    RunLimits,
    Sampling,
    assert_argv_allowed,
    build_argv,
    build_environment,
)
from src.ai_assist.attestation import read_attestation, record_attestation
from src.ai_assist.events import EventLog
from src.ai_assist.paths import attestation_path, resolve_ai_root


def _paths(rng: random.Random) -> tuple[Path, Path, Path]:
    alphabet = string.ascii_letters + string.digits + " _-.()"

    def name(ext: str) -> Path:
        return Path("C:/data") / (
            "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 40))) + ext
        )

    return name(".gguf"), name(".txt"), name(".json")


def test_argv_is_cpu_only_offline_and_contains_no_forbidden_flag_for_any_input() -> None:
    rng = random.Random(110)
    for _ in range(200):
        model, prompt, schema = _paths(rng)
        limits = RunLimits(
            context_tokens=rng.choice([512, 4096, 32768]),
            max_new_tokens=rng.choice([16, 256, 512]),
            threads=rng.randint(1, 64),
            timeout_seconds=rng.choice([1.0, 90.0, 600.0]),
        )
        argv = build_argv(model, prompt, schema, limits, Sampling(seed=rng.randint(0, 2**31)))
        assert "--offline" in argv
        assert argv[argv.index("-ngl") + 1] == "0"
        assert not FORBIDDEN_FLAGS & set(argv)
        flags = {
            token
            for token in argv
            if token.startswith("-") and not token[1:].replace(".", "").isdigit()
        }
        assert flags <= ALLOWED_FLAGS
        assert str(prompt) in argv and "barn" not in " ".join(argv)


def test_allow_list_refuses_every_forbidden_or_unknown_flag() -> None:
    for flag in sorted(FORBIDDEN_FLAGS):
        with pytest.raises(ValueError):
            assert_argv_allowed(["--offline", flag, "x"])
    with pytest.raises(ValueError):
        assert_argv_allowed(["--some-new-flag", "1"])
    with pytest.raises(ValueError):
        assert_argv_allowed(["-m", "-hf"])  # a forbidden token is refused even in value position


def test_no_network_or_projector_flag_is_even_in_the_allow_list() -> None:
    assert not FORBIDDEN_FLAGS & ALLOWED_FLAGS
    assert {
        "-hf",
        "-mu",
        "-dr",
        "--connect",
        "--ui-mcp-proxy",
        "--mmproj",
        "--host",
    } <= FORBIDDEN_FLAGS


def test_run_limits_reject_out_of_range_values() -> None:
    for bad in (
        {"context_tokens": 100},
        {"threads": 0},
        {"timeout_seconds": float("nan")},
        {"max_new_tokens": 5},
    ):
        with pytest.raises(ValueError):
            RunLimits(**bad)


def test_child_environment_is_scrubbed_cpu_only_and_offline(tmp_path: Path) -> None:
    parent = {
        "SystemRoot": "C:\\Windows",
        "TEMP": "C:\\Temp",
        "HTTP_PROXY": "http://proxy",
        "HTTPS_PROXY": "http://proxy",
        "ALL_PROXY": "x",
        "HF_TOKEN": "secret",
        "AWS_SECRET_ACCESS_KEY": "secret",
        "CUDA_VISIBLE_DEVICES": "0",
        "PATH": "C:\\everything",
    }
    environment = build_environment(tmp_path / "runtime", parent, tmp_path / "work")
    assert environment["CUDA_VISIBLE_DEVICES"] == "-1"
    assert environment["NO_PROXY"] == "*"
    assert environment["HF_HUB_OFFLINE"] == "1" and environment["LLAMA_ARG_OFFLINE"] == "1"
    assert environment["PATH"] == str(tmp_path / "runtime")
    assert environment["TEMP"] == environment["TMP"] == str(tmp_path / "work")
    for leaked in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "HF_TOKEN", "AWS_SECRET_ACCESS_KEY"):
        assert leaked not in environment


def test_event_log_accepts_only_whitelisted_short_scalars(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    assert log.append({"request_id": "r1", "outcome": "suggestion", "elapsed_ms": 12})
    with pytest.raises(ValueError):
        log.append({"request_id": "r1", "prompt": "a red barn"})
    with pytest.raises(ValueError):
        log.append({"reason": "x" * 500})
    with pytest.raises(ValueError):
        log.append({"reason": ["a", "b"]})
    assert [r["request_id"] for r in log.tail()] == ["r1"]


def test_attestation_is_an_operator_statement_and_blank_or_corrupt_means_not_attested(
    tmp_path: Path,
) -> None:
    assert read_attestation(tmp_path) is None
    with pytest.raises(ValueError):
        record_attestation(tmp_path, "   ")
    record_attestation(tmp_path, "Windows Firewall rule 'Block StableNew AI' on llama-cli.exe")
    document = read_attestation(tmp_path)
    assert document is not None and document["verified_by_stablenew"] is False
    attestation_path(tmp_path).write_text("{corrupt", encoding="utf-8")
    assert read_attestation(tmp_path) is None
    attestation_path(tmp_path).write_text(
        json.dumps({"schema_version": 1, "statement": " "}), encoding="utf-8"
    )
    assert read_attestation(tmp_path) is None


def test_ai_root_is_user_data_never_repository_relative() -> None:
    assert resolve_ai_root(
        environ={"LOCALAPPDATA": "C:/Users/u/AppData/Local"}, system_name="Windows"
    ) == Path("C:/Users/u/AppData/Local/StableNew/ManagedAi")
    assert resolve_ai_root(environ={"STABLENEW_AI_DIR": "D:/ai"}) == Path("D:/ai")
    assert resolve_ai_root(environ={}, system_name="Linux", home_dir="/home/u") == Path(
        "/home/u/.local/share/StableNew/ManagedAi"
    )


def test_no_llama_variable_is_inherited_and_the_offline_switch_is_forced_on(tmp_path: Path) -> None:
    parent = {
        "SystemRoot": r"C:\Windows",
        "LLAMA_ARG_MODEL": "evil.gguf",
        "LLAMA_ARG_HF_REPO": "someone/model",
        "LLAMA_ARG_HOST": "0.0.0.0",
        "LLAMA_ARG_PORT": "8080",
        "LLAMA_ARG_N_GPU_LAYERS": "99",
        "LLAMA_ARG_OFFLINE": "0",
        "LLAMA_ARG_API_KEY": "k",
        "LLAMA_CACHE": r"C:\cache",
        "LLAMA_LOG_FILE": r"C:\log.txt",
        "llama_arg_lower": "x",
    }
    environment = build_environment(tmp_path / "runtime", parent, tmp_path / "work")
    assert {k for k in environment if k.upper().startswith("LLAMA")} == {"LLAMA_ARG_OFFLINE"}
    assert environment["LLAMA_ARG_OFFLINE"] == "1"
    assert set(environment) <= {
        "SystemRoot",
        "TEMP",
        "TMP",
        "PATH",
        "CUDA_VISIBLE_DEVICES",
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
        "LLAMA_ARG_OFFLINE",
        "NO_PROXY",
    }
