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
FILES = {"llama-cli.exe": CLI, "ggml.dll": b"fake ggml", "LICENSE-X": b"licence text"}
HELP_FULL = "\n".join(f"  {flag}  value" for flag in sorted(ALLOWED_FLAGS))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
        intent=intent,
        authorized_member_sha256=overrides.pop("member_sha", _sha(CLI)),
        **overrides,
    )


def _ok(text: str) -> ProcessOutcome:
    return ProcessOutcome(returncode=0, stdout=text.encode(), contained=True)


def test_pass_runs_exactly_the_two_authorized_commands(tmp_path: Path) -> None:
    monitor = FakeMonitor([_ok("version: 1 (b11840)"), _ok(HELP_FULL)])
    result = _run(tmp_path, monitor)
    assert result["verdict"] == "PASS", result
    assert [c[1:] for c in monitor.launched] == [["--version"], ["--help"]]
    assert all(Path(c[0]).name == "llama-cli.exe" for c in monitor.launched)
    assert result["compatibility"]["required_flags_missing"] == []
    evidence = tmp_path / "run" / "d12a"
    for name in (
        "authorization.json",
        "pre-launch-verification.json",
        "post-run-verification.json",
        "result.json",
    ):
        assert (evidence / name).is_file()
    assert monitor.roots is not None
    read_roots, write_roots = monitor.roots
    assert write_roots == (evidence / "scratch",)
    assert evidence / "runtime" in read_roots
    assert not list((evidence / "runtime").rglob("*.gguf"))


def test_missing_flag_is_a_compatibility_failure_not_a_substitution(tmp_path: Path) -> None:
    text = HELP_FULL.replace("--json-schema-file", "--grammar-only")
    result = _run(tmp_path, FakeMonitor([_ok("v"), _ok(text)]))
    assert result["verdict"] == "FAIL"
    assert result["compatibility"]["required_flags_missing"] == ["--json-schema-file"]


def test_truncated_help_with_missing_flags_is_inconclusive() -> None:
    assert d12a.analyze_help("--offline only", truncated=True)["verdict"] == "INCONCLUSIVE"
    assert d12a.analyze_help("--offline only", truncated=False)["verdict"] == "FAIL"
    assert d12a.analyze_help("", truncated=False)["verdict"] == "INCONCLUSIVE"


def test_short_flags_are_not_matched_inside_other_words() -> None:
    assert not d12a.flag_in_text("-c", "--context-shift and a-c")
    assert d12a.flag_in_text("-c", "  -c, --ctx-size N")


def test_nonzero_exit_stops_before_help(tmp_path: Path) -> None:
    monitor = FakeMonitor([ProcessOutcome(returncode=3, contained=True)])
    result = _run(tmp_path, monitor)
    assert result["verdict"] == "FAIL" and len(monitor.launched) == 1


def test_monitor_findings_stop_the_run(tmp_path: Path) -> None:
    monitor = FakeMonitor([_ok("v"), _ok(HELP_FULL)], violations=["file_access_outside_policy"])
    result = _run(tmp_path, monitor)
    assert result["verdict"] == "FAIL" and len(monitor.launched) == 1
    assert "file_access_outside_policy" in result["stopped"]


def test_unready_monitor_launches_nothing(tmp_path: Path) -> None:
    monitor = FakeMonitor([])
    monitor.ready_problems = ["files: the canary did not show this channel detecting a known event"]
    result = _run(tmp_path, monitor)
    assert result["verdict"] == "NOT TESTED" and monitor.launched == []


def test_wrong_member_hash_refuses_before_extraction(tmp_path: Path) -> None:
    with pytest.raises(d12a.D12aRefused):
        _run(tmp_path, FakeMonitor([]), member_sha="0" * 64)
    assert not (tmp_path / "run" / "d12a").exists()


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


def test_extraction_tamper_is_caught_before_the_next_launch(tmp_path: Path) -> None:
    class Tampering(FakeMonitor):
        def runner(self):
            inner = super().runner()

            def run(command, **kwargs):
                outcome = inner(command, **kwargs)
                (Path(command[0]).parent / "ggml.dll").write_bytes(b"swapped")
                return outcome

            return run

    monitor = Tampering([_ok("v"), _ok(HELP_FULL)])
    result = _run(tmp_path, monitor)
    assert result["verdict"] == "FAIL" and len(monitor.launched) == 1
    assert "tree changed before launch" in result["stopped"]
