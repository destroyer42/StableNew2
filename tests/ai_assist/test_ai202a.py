"""AI-202a: the production runtime invocation, the visible failure reason and the attestation binding (D19).

Hermetic: a fake child launched through the real ``run_bounded``, fake manifests and temporary roots. No llama.cpp binary,
archive or model is touched or run; the flag proof itself lives in ``docs/work_packages/AI-202_invocation_and_selector.md``.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from src.ai_assist.argv import (
    ALLOWED_FLAGS,
    FORBIDDEN_FLAGS,
    PRODUCTION_ALLOWED_FLAGS,
    RunLimits,
    Sampling,
    assert_argv_allowed,
    build_argv,
    build_production_argv,
)
from src.ai_assist.attestation import (
    attestation_covers,
    read_attestation,
    read_covers,
    record_attestation,
)
from src.ai_assist.contracts import MAX_RUNTIME_DETAIL_BYTES, OutcomeCode, RuntimeDetail
from src.ai_assist.events import EventLog
from src.ai_assist.manifests import load_runtime_manifest
from src.ai_assist.paths import attestation_path, events_path
from src.ai_assist.runtime import strip_end_of_text
from src.ai_assist.service import ServicePolicy
from src.ai_assist.status import (
    EGRESS_ATTESTED,
    EGRESS_NOT_ATTESTED,
    EGRESS_NOT_COVERED,
    RUNTIME_MANIFEST_PATH,
    read_status,
)
from src.gui_v2.ai_suggestion_view import runtime_detail_text

from .conftest import Install, attest, request_for
from .test_service_runtime import SpawnSpy, make_service

PINNED_BUILDS = ("b11840-cpu", "b11960-cpu")
#: Flags the production argv emits, each registered for ``LLAMA_EXAMPLE_COMPLETION`` (directly or through
#: ``LLAMA_EXAMPLE_COMMON``) in common/arg.cpp at tags b11840 and b11960 (see the AI-202 work package for line references).
ACCEPTED_BY_COMPLETION = frozenset(
    {
        "--offline",
        "-ngl",
        "--no-display-prompt",
        "--no-conversation",
        "--reasoning",
        "--prio",
        "-m",
        "-f",
        "--json-schema-file",
        "-c",
        "-n",
        "-t",
        "--temp",
        "--top-p",
        "--top-k",
        "--presence-penalty",
        "--seed",
    }
)
LIMITS = RunLimits()
FAST = RunLimits(timeout_seconds=20.0)


def _argv(builder=build_production_argv) -> list[str]:
    return builder(Path("m.gguf"), Path("p.txt"), Path("s.json"), LIMITS, Sampling())


def _flags(argv: list[str]) -> set[str]:
    return {t for t in argv if t.startswith("-") and not t.lstrip("-").replace(".", "").isdigit()}


# -- the pinned builds launch the tool that accepts the argv -------------------------------------------------------------


@pytest.mark.parametrize("build_id", PINNED_BUILDS)
def test_pinned_builds_launch_llama_completion_and_pin_its_impl_library(build_id: str) -> None:
    manifest = load_runtime_manifest(RUNTIME_MANIFEST_PATH)
    assert not manifest.problems
    build = manifest.find(build_id)
    assert build is not None and build.qualified is False
    assert build.executable == "llama-completion.exe"
    # The tool is a thin launcher: it loads its implementation library from the same directory, so both are hashed.
    assert {"llama-completion.exe", "llama-completion-impl.dll"} <= set(build.files)


def test_production_argv_is_the_frozen_argv_without_log_disable() -> None:
    frozen, production = _argv(build_argv), _argv()
    assert "--log-disable" in frozen
    assert "--log-disable" not in production
    assert production == [token for token in frozen if token != "--log-disable"]
    assert _flags(production) <= ACCEPTED_BY_COMPLETION
    assert (
        "--no-conversation" in production
    )  # raw prompt, not interactive, exits after one generation
    assert not {"-cnv", "--conversation", "-i", "--interactive", "-if", "--jinja"} & set(production)


def test_the_frozen_vocabulary_is_untouched_and_production_is_a_strict_subset() -> None:
    assert (
        "--log-disable" in ALLOWED_FLAGS
    )  # frozen AI-111/AI-115 plans digest this set and build_argv
    assert PRODUCTION_ALLOWED_FLAGS == ALLOWED_FLAGS - {"--log-disable"}
    assert not FORBIDDEN_FLAGS & PRODUCTION_ALLOWED_FLAGS
    with pytest.raises(ValueError):
        assert_argv_allowed(["--log-disable"], PRODUCTION_ALLOWED_FLAGS)
    for extra in ("--single-turn", "-st", "--simple-io", "--no-warmup", "-sysf", "--host", "-hf"):
        with pytest.raises(ValueError):
            assert_argv_allowed([extra], PRODUCTION_ALLOWED_FLAGS)
    assert_argv_allowed(_argv(), PRODUCTION_ALLOWED_FLAGS)


def test_the_runtime_launches_the_production_argv(installation: Install, tmp_path: Path) -> None:
    record = tmp_path / "record.json"
    outcome = make_service(installation).run(request_for("ok", extra=f"TEST_RECORD:{record}"))
    assert outcome.ok
    argv = json.loads(record.read_text(encoding="utf-8"))["argv"]
    assert "--log-disable" not in argv and "--no-conversation" in argv


# -- the tool's own end-of-text line -------------------------------------------------------------------------------------


def test_strip_end_of_text_removes_only_a_trailing_marker() -> None:
    assert strip_end_of_text(b'{"a": 1} [end of text]\n') == b'{"a": 1}'
    assert strip_end_of_text(b'{"a": 1} [end of text]\r\n') == b'{"a": 1}'
    assert strip_end_of_text(b'{"a": 1}') == b'{"a": 1}'
    inner = b'{"a": "[end of text] kept"}'
    assert strip_end_of_text(inner + b" [end of text]\n") == inner
    assert strip_end_of_text(inner) == inner


def test_a_generation_followed_by_the_end_of_text_line_is_a_valid_suggestion(
    installation: Install,
) -> None:
    outcome = make_service(installation).run(request_for("end_marker"))
    assert outcome.code is OutcomeCode.SUGGESTION and outcome.runtime_detail is None


# -- exit code and bounded raw detail ------------------------------------------------------------------------------------


def test_a_failing_child_reports_its_exit_code_and_the_tail_of_stderr(
    installation: Install,
) -> None:
    outcome = make_service(installation).run(request_for("stderr_fail"))
    assert (outcome.code, outcome.reason) == (OutcomeCode.UNAVAILABLE, "child_exit_nonzero")
    assert outcome.details["exit_code"] == 7
    detail = outcome.runtime_detail
    assert detail is not None and detail.exit_code == 7
    assert "error: invalid argument: --no-conversation" in detail.stderr_tail
    assert "HEAD-OF-STDERR" not in detail.stderr_tail  # the end is kept, not the start
    assert len(detail.stderr_tail.encode("utf-8")) <= MAX_RUNTIME_DETAIL_BYTES
    assert detail.stdout_head == ""
    shown = runtime_detail_text(detail)
    assert shown.startswith("Exit code: 7") and "stderr (last part):" in shown


def test_malformed_output_keeps_a_bounded_stdout_head_in_memory_only(installation: Install) -> None:
    outcome = make_service(installation).run(request_for("malformed_echo"))
    assert (outcome.code, outcome.reason) == (OutcomeCode.MALFORMED, "not_json")
    detail = outcome.runtime_detail
    assert detail is not None and detail.stdout_head.startswith("{not json a red barn")
    assert len(detail.stdout_head.encode("utf-8")) <= MAX_RUNTIME_DETAIL_BYTES
    assert "stdout (first part):" in runtime_detail_text(detail)


def test_a_refusal_never_carries_stdout_and_a_suggestion_carries_no_detail(
    installation: Install,
) -> None:
    service = make_service(installation)
    refused = service.run(request_for("status_refused", request_id="r-refused"))
    assert refused.code is OutcomeCode.REFUSED_BY_MODEL
    assert refused.runtime_detail is None or refused.runtime_detail.stdout_head == ""
    assert service.run(request_for("ok", request_id="r-ok")).runtime_detail is None


def test_event_log_records_the_integer_exit_code_and_no_runtime_text(installation: Install) -> None:
    service = make_service(installation)
    service.run(request_for("stderr_fail", request_id="r-fail"))
    service.run(request_for("malformed_echo", request_id="r-bad", extra="SECRETPROMPTWORDS"))
    log = events_path(installation.root)
    records = EventLog(log).tail(5)
    failed = next(r for r in records if r["request_id"] == "r-fail")
    assert failed["exit_code"] == 7 and type(failed["exit_code"]) is int
    text = log.read_text(encoding="utf-8")
    for forbidden in (
        "HEAD-OF-STDERR",
        "invalid argument",
        "red barn",
        "{not json",
        "SECRETPROMPTWORDS",
    ):
        assert forbidden not in text
    assert not list(installation.root.rglob("*.log"))  # nothing else was written either


def test_runtime_detail_hides_its_text_from_repr_and_has_no_event_field() -> None:
    detail = RuntimeDetail(2, "secret-stderr", "secret-stdout")
    assert "secret" not in repr(detail)
    assert detail.has_text and runtime_detail_text(None) == ""
    assert runtime_detail_text(RuntimeDetail(0)) == "Exit code: 0"


# -- attestation binding (D19) -------------------------------------------------------------------------------------------


def test_attestation_covers_only_the_named_builds_and_executables(tmp_path: Path) -> None:
    record_attestation(
        tmp_path,
        "Windows Firewall outbound block",
        [("b11840-cpu", "llama-completion.exe"), ("b11960-cpu", "llama-completion.exe")],
    )
    assert read_covers(tmp_path) == (
        ("b11840-cpu", "llama-completion.exe"),
        ("b11960-cpu", "llama-completion.exe"),
    )
    assert attestation_covers(tmp_path, "b11960-cpu", "llama-completion.exe")
    assert attestation_covers(tmp_path, "b11960-cpu", "LLAMA-COMPLETION.EXE")
    assert not attestation_covers(tmp_path, "b11960-cpu", "llama-cli.exe")
    assert not attestation_covers(tmp_path, "b99999-cpu", "llama-completion.exe")


def test_a_legacy_free_text_attestation_covers_nothing(tmp_path: Path) -> None:
    record_attestation(tmp_path, "Windows Firewall rule on llama-cli.exe")
    assert read_attestation(tmp_path) is not None  # still a readable operator statement
    assert read_covers(tmp_path) == ()
    assert not attestation_covers(tmp_path, "b11840-cpu", "llama-completion.exe")
    attestation_path(tmp_path).write_text(
        json.dumps({"schema_version": 2, "statement": "x"}), encoding="utf-8"
    )
    assert read_covers(tmp_path) == ()
    attestation_path(tmp_path).write_text(
        json.dumps({"schema_version": 2, "statement": "x", "covers": [{"build_id": 1}]}),
        encoding="utf-8",
    )
    assert read_covers(tmp_path) == ()


@pytest.mark.parametrize(
    "covers",
    [
        [],
        [("", "llama-completion.exe")],
        [("b1", "")],
        [("b1", "llama-completion")],
        [("b1", "..\\evil.exe")],
        [("b1", "sub/llama-completion.exe")],
        [("../b1", "llama-completion.exe")],
    ],
)
def test_attestation_refuses_unsafe_or_empty_coverage(tmp_path: Path, covers) -> None:
    with pytest.raises(ValueError):
        record_attestation(tmp_path, "rule", covers)
    assert read_attestation(tmp_path) is None


STRICT = ServicePolicy(strict_offline=True, watch_interval_seconds=0.05)


def test_the_service_refuses_an_unbound_attestation_before_spawning(installation: Install) -> None:
    spy = SpawnSpy()
    service = make_service(installation, policy=STRICT, runner=spy)
    build = installation.build

    ids = itertools.count()

    def refused() -> None:
        outcome = service.run(request_for("ok", request_id=f"r-refused-{next(ids)}"))
        assert outcome.code is OutcomeCode.EGRESS_NOT_ATTESTED and outcome.suggestion is None
        assert outcome.reason == "operator_attestation_missing"

    refused()  # no record
    record_attestation(installation.root, "free text only")  # legacy
    refused()
    record_attestation(installation.root, "other exe", [(build.build_id, "llama-cli-other.exe")])
    refused()
    record_attestation(installation.root, "other build", [("b0001-cpu", build.executable)])
    refused()
    assert spy.calls == 0
    attest(installation)
    assert service.run(request_for("ok", request_id="r-ok")).ok and spy.calls == 1


def test_status_tells_attested_from_not_covered_from_not_attested(installation: Install) -> None:
    def egress() -> str:
        return read_status(installation.root, installation.manifest, installation.registry).egress

    assert egress() == EGRESS_NOT_ATTESTED
    record_attestation(installation.root, "legacy statement")
    assert egress() == EGRESS_NOT_COVERED
    record_attestation(
        installation.root, "wrong build", [("b0001-cpu", installation.build.executable)]
    )
    assert egress() == EGRESS_NOT_COVERED
    attest(installation)
    assert egress() == EGRESS_ATTESTED
