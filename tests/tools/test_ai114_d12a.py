"""PR-AI-QUAL-114 D12a machinery with a fake archive and a fake runner. No downloaded binary is ever launched."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.ai_assist.argv import ALLOWED_FLAGS  # noqa: E402
from src.utils.managed_process import ProcessOutcome  # noqa: E402
from tools.qualification.ai111 import d12a  # noqa: E402

CLI = b"fake llama-cli"
COMPLETION = b"fake llama-completion"
FILES = {
    "llama-cli.exe": CLI,
    "llama-completion.exe": COMPLETION,
    "ggml.dll": b"fake ggml",
    "LICENSE-X": b"licence text",
}
HELP_FULL = "\n".join(f"  {flag}  value" for flag in sorted(ALLOWED_FLAGS))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pins(cli: bytes = CLI, completion: bytes = COMPLETION) -> dict[str, str]:
    return {"llama-completion.exe": _sha(completion), "llama-cli.exe": _sha(cli)}


def _archive(
    tmp_path: Path, files: dict[str, bytes] | None = None
) -> tuple[Path, dict[str, object]]:
    files = files or FILES
    path = tmp_path / "fake.zip"
    with zipfile.ZipFile(path, "w") as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)
    intent = {"bytes": path.stat().st_size, "sha256": _sha(path.read_bytes())}
    return path, intent


def _manifest(tmp_path: Path, archive: Path, files: dict[str, bytes] | None = None) -> Path:
    files = files or FILES
    document = {
        "archive_sha256": _sha(archive.read_bytes()),
        "members": {
            n: {"sha256": _sha(d), "bytes": len(d)}
            for n, d in files.items()
            if not n.startswith("LICENSE")
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class FakeMonitor:
    """The surface ``run_d12a`` uses, with canned results; the real runner/ETW path is covered by the ownership tests."""

    def __init__(self, outcomes: list[ProcessOutcome], violations: list[str] | None = None) -> None:
        self.outcomes = list(outcomes)
        self.violations = violations or []
        self.records: list[SimpleNamespace] = []
        self.canary_report = {"passed": True}
        self.ready_problems: list[str] = []
        self.launched: list[list[str]] = []
        self.roots: tuple[tuple[Path, ...], tuple[Path, ...]] | None = None

    def provider_problems(self) -> list[str]:
        return []

    def bind_evidence(self, directory: Path) -> None:
        pass

    def bind_roots(self, *, read_roots, write_roots) -> None:
        self.roots = (read_roots, write_roots)

    def run_canary(self) -> dict[str, object]:
        return self.canary_report

    def readiness(self) -> list[str]:
        return self.ready_problems

    def runner(self):
        def run(command, **kwargs):
            self.launched.append(list(command))
            assert kwargs["timeout_seconds"] == 10.0 and kwargs["max_stdout_bytes"] == 64 * 1024
            assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "-1"
            self.records.append(
                SimpleNamespace(
                    number=len(self.records) + 1,
                    violations=list(self.violations),
                    connections=[],
                    files=[],
                    process={"complete": True, "active_after_teardown": 0, "total_processes": 1},
                )
            )
            return self.outcomes.pop(0)

        return run

    def session_records(self):
        return self.records

    def summary(self) -> dict[str, object]:
        return {"requests_monitored": len(self.records)}


def _run(tmp_path: Path, monitor: FakeMonitor, files=None, **overrides):
    archive, intent = _archive(tmp_path, files)
    manifest = _manifest(tmp_path, archive, files)
    return d12a.run_d12a(
        archive=archive,
        passive_manifest=manifest,
        evidence_root=tmp_path / "run",
        monitor=monitor,  # type: ignore[arg-type]
        authorization_text="owner D12a",
        attestation="test attestation",
        intent=intent,
        authorized_members=overrides.pop("members_pin", _pins()),
        passive_manifest_sha256=overrides.pop("manifest_sha", None),
        **overrides,
    )


def _ok(text: str) -> ProcessOutcome:
    return ProcessOutcome(returncode=0, stdout=text.encode(), contained=True)


def _both(help_a: str = HELP_FULL, help_b: str = HELP_FULL) -> list[ProcessOutcome]:
    """Outcomes for llama-completion.exe (version, help) then llama-cli.exe (version, help)."""

    return [_ok("v-completion"), _ok(help_a), _ok("v-cli"), _ok(help_b)]


def test_pass_runs_exactly_the_two_commands_of_each_authorized_member(tmp_path: Path) -> None:
    monitor = FakeMonitor(_both())
    result = _run(tmp_path, monitor)
    assert result["verdict"] == "PASS", result
    assert [(Path(c[0]).name, *c[1:]) for c in monitor.launched] == [
        ("llama-completion.exe", "--version"),
        ("llama-completion.exe", "--help"),
        ("llama-cli.exe", "--version"),
        ("llama-cli.exe", "--help"),
    ]
    for name in ("llama-completion.exe", "llama-cli.exe"):
        assert result["members"][name]["verdict"] == "PASS"
        assert result["members"][name]["compatibility"]["required_flags_missing"] == []
    evidence = tmp_path / "run" / "d12a"
    for name in (
        "authorization.json",
        "pre-launch-verification.json",
        "post-run-verification.json",
        "result.json",
        "llama-completion.help.stdout.txt",
        "llama-cli.version.stdout.txt",
    ):
        assert (evidence / name).is_file()
    assert monitor.roots is not None
    read_roots, write_roots = monitor.roots
    assert write_roots == (evidence / "scratch",)
    assert evidence / "runtime" in read_roots
    assert not list((evidence / "runtime").rglob("*.gguf"))


def test_missing_flag_is_a_compatibility_failure_not_a_substitution(tmp_path: Path) -> None:
    text = HELP_FULL.replace("--json-schema-file", "--grammar-only")
    result = _run(tmp_path, FakeMonitor(_both(help_a=text)))
    assert result["verdict"] == "FAIL"
    completion = result["members"]["llama-completion.exe"]
    assert completion["compatibility"]["required_flags_missing"] == ["--json-schema-file"]
    # the other member is judged on its own help: nothing is silently read across, and nothing is substituted
    assert result["members"]["llama-cli.exe"]["verdict"] == "PASS"


def test_truncated_help_with_missing_flags_is_inconclusive() -> None:
    assert d12a.analyze_help("--offline only", truncated=True)["verdict"] == "INCONCLUSIVE"
    assert d12a.analyze_help("--offline only", truncated=False)["verdict"] == "FAIL"
    assert d12a.analyze_help("", truncated=False)["verdict"] == "INCONCLUSIVE"


def test_short_flags_are_not_matched_inside_other_words() -> None:
    assert not d12a.flag_in_text("-c", "--context-shift and a-c")
    assert d12a.flag_in_text("-c", "  -c, --ctx-size N")


def test_nonzero_exit_ends_that_member_only(tmp_path: Path) -> None:
    monitor = FakeMonitor(
        [ProcessOutcome(returncode=3, contained=True), _ok("v-cli"), _ok(HELP_FULL)]
    )
    result = _run(tmp_path, monitor)
    assert result["verdict"] == "FAIL" and len(monitor.launched) == 3
    assert [Path(c[0]).name for c in monitor.launched] == [
        "llama-completion.exe",
        "llama-cli.exe",
        "llama-cli.exe",
    ]
    assert result["members"]["llama-completion.exe"]["verdict"] == "FAIL"
    assert result["members"]["llama-cli.exe"]["verdict"] == "PASS"


def test_monitor_findings_stop_the_run(tmp_path: Path) -> None:
    monitor = FakeMonitor(_both(), violations=["file_access_outside_policy"])
    result = _run(tmp_path, monitor)
    assert result["verdict"] == "FAIL" and len(monitor.launched) == 1
    assert "file_access_outside_policy" in result["stopped"]
    # a security stop ends the whole run: the second member is never launched and is reported as not run
    assert result["members"]["llama-cli.exe"]["verdict"] == "NOT TESTED"


def test_unready_monitor_launches_nothing(tmp_path: Path) -> None:
    monitor = FakeMonitor([])
    monitor.ready_problems = ["files: the canary did not show this channel detecting a known event"]
    result = _run(tmp_path, monitor)
    assert result["verdict"] == "NOT TESTED" and monitor.launched == []


@pytest.mark.parametrize("which", ["llama-completion.exe", "llama-cli.exe"])
def test_wrong_member_hash_refuses_before_extraction(tmp_path: Path, which: str) -> None:
    with pytest.raises(d12a.D12aRefused, match=which):
        _run(tmp_path, FakeMonitor([]), members_pin={**_pins(), which: "0" * 64})
    assert not (tmp_path / "run" / "d12a").exists()


def test_the_authorized_members_are_the_physical_sessions_pinned_launchers() -> None:
    from tools.qualification.ai111 import physical

    assert d12a.AUTHORIZED_MEMBERS == physical.LAUNCHABLE_MEMBERS
    assert (
        list(d12a.AUTHORIZED_MEMBERS)[0] == "llama-completion.exe"
    )  # the preferred Stage A launcher runs first


def test_unlisted_active_member_refuses(tmp_path: Path) -> None:
    archive, intent = _archive(tmp_path, {**FILES, "extra.dll": b"x"})
    manifest = _manifest(tmp_path, archive, FILES)  # the manifest lacks extra.dll
    document = json.loads(manifest.read_text())
    document["archive_sha256"] = intent["sha256"]
    manifest.write_text(json.dumps(document))
    with pytest.raises(d12a.D12aRefused, match="not in the passive manifest"):
        d12a.verify_archive_members(archive, d12a.load_passive_manifest(manifest, intent["sha256"]))


def test_changed_member_refuses(tmp_path: Path) -> None:
    archive, intent = _archive(tmp_path)
    manifest = _manifest(tmp_path, archive)
    document = json.loads(manifest.read_text())
    document["members"]["ggml.dll"]["sha256"] = "1" * 64
    manifest.write_text(json.dumps(document))
    with pytest.raises(d12a.D12aRefused, match="differs from the passive manifest"):
        d12a.verify_archive_members(archive, d12a.load_passive_manifest(manifest, intent["sha256"]))


@pytest.mark.parametrize(
    "name", ["../evil.dll", "/abs.dll", "C:evil.dll", "a\\b.dll", "a/../../b.dll"]
)
def test_unsafe_member_paths_refuse(tmp_path: Path, name: str) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(zipfile.ZipInfo(name), b"x")
    with pytest.raises(d12a.D12aRefused):
        d12a.verify_archive_members(archive, {})


def test_model_like_member_refuses(tmp_path: Path) -> None:
    archive = tmp_path / "m.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("weights.gguf", b"x")
    with pytest.raises(d12a.D12aRefused, match="model-like"):
        d12a.verify_archive_members(archive, {})


def test_the_passive_manifest_itself_is_pinned(tmp_path: Path) -> None:
    with pytest.raises(d12a.D12aRefused, match="not the recorded one"):
        _run(tmp_path, FakeMonitor([]), manifest_sha="0" * 64)
    assert not (tmp_path / "run" / "d12a").exists()


def test_the_recorded_manifest_pin_matches_the_real_passive_evidence_when_present() -> None:
    real = Path(
        "C:/Users/rob/projects/StableNew-main/reports/ai111/downloads-reverified-20261023/binary-entry-hashes.json"
    )
    if not real.is_file():
        pytest.skip("passive evidence not on this host")
    assert _sha(real.read_bytes()) == d12a.PASSIVE_MANIFEST_SHA256
    members = json.loads(real.read_text())["members"]
    for name, pinned in d12a.AUTHORIZED_MEMBERS.items():
        assert members[name]["sha256"] == pinned


def test_a_loadable_file_in_the_working_directory_stops_before_launch(tmp_path: Path) -> None:
    class Planting(FakeMonitor):
        def bind_roots(self, *, read_roots, write_roots) -> None:
            super().bind_roots(read_roots=read_roots, write_roots=write_roots)
            (write_roots[0] / "ggml-cpu-evil.dll").write_bytes(b"x")

    monitor = Planting(_both())
    result = _run(tmp_path, monitor)
    assert result["verdict"] == "FAIL" and monitor.launched == []
    assert "working directory" in result["stopped"]


def test_a_loadable_file_appearing_during_a_command_is_a_violation(tmp_path: Path) -> None:
    class Dropping(FakeMonitor):
        def runner(self):
            inner = super().runner()

            def run(command, **kwargs):
                outcome = inner(command, **kwargs)
                (Path(kwargs["cwd"]) / "ggml-cpu-evil.dll").write_bytes(b"x")
                return outcome

            return run

    result = _run(tmp_path, Dropping(_both()))
    assert result["verdict"] == "FAIL"
    assert "loadable_file_in_working_directory" in result["stopped"]


def test_output_over_the_cap_is_inconclusive_not_a_compatibility_failure(tmp_path: Path) -> None:
    cut = ProcessOutcome(
        returncode=1, stdout=HELP_FULL.encode()[:40], output_truncated=True, contained=True
    )
    result = _run(tmp_path, FakeMonitor([_ok("v"), cut, _ok("v"), _ok(HELP_FULL)]))
    assert result["verdict"] == "INCONCLUSIVE", result
    completion = result["members"]["llama-completion.exe"]
    assert "authorized" in completion["stopped"]
    assert completion["compatibility"]["help_truncated_at_cap"] is True
    assert result["members"]["llama-cli.exe"]["verdict"] == "PASS"


def test_the_result_names_each_member_and_the_archive_it_covers(tmp_path: Path) -> None:
    result = _run(tmp_path, FakeMonitor(_both()))
    assert result["members"]["llama-cli.exe"]["sha256"] == _sha(CLI)
    assert result["members"]["llama-completion.exe"]["sha256"] == _sha(COMPLETION)
    assert len(result["archive_sha256"]) == 64


def test_extraction_tamper_is_caught_before_the_next_launch(tmp_path: Path) -> None:
    class Tampering(FakeMonitor):
        def runner(self):
            inner = super().runner()

            def run(command, **kwargs):
                outcome = inner(command, **kwargs)
                (Path(command[0]).parent / "ggml.dll").write_bytes(b"swapped")
                return outcome

            return run

    monitor = Tampering(_both())
    result = _run(tmp_path, monitor)
    assert result["verdict"] == "FAIL" and len(monitor.launched) == 1
    assert "tree changed before launch" in result["stopped"]
