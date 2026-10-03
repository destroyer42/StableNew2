"""Reproducible Windows runtime authority (PR-RUNTIME-DEPS-100).

Deterministic and GPU-free: it checks the repository-owned exact constraints, the drift
verifier, and the bootstrap's install policy. The real clean-environment proof is runtime
evidence, not something CI (Linux) can reproduce.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from tools.runtime import verify_runtime_pins as verifier

ROOT = Path(__file__).resolve().parents[2]
CONSTRAINTS = ROOT / "constraints" / "windows-py312-cu130.txt"


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _requirement_lines(rel_path: str) -> list[str]:
    return [
        line.split("#", 1)[0].strip()
        for line in _read(rel_path).splitlines()
        if line.split("#", 1)[0].strip()
    ]


@pytest.fixture(scope="module")
def pins() -> dict[str, str]:
    return verifier.parse_constraints(CONSTRAINTS.read_text(encoding="utf-8"))


# --- Constraints file -------------------------------------------------------------------------


def test_constraints_declare_their_exact_target() -> None:
    header = "\n".join(
        line for line in CONSTRAINTS.read_text(encoding="utf-8").splitlines() if line.startswith("#")
    )

    assert "Windows" in header
    assert "CPython 3.12" in header
    assert "CUDA 13.0" in header and "cu130" in header
    assert "RTX 4070 Ti" in header
    assert "clean disposable environment" in header


def test_constraints_are_exact_unique_and_free_of_paths_urls_and_editables(pins) -> None:
    text = CONSTRAINTS.read_text(encoding="utf-8")

    assert pins  # parse_constraints rejects ranges, duplicates and anything not name==version
    for forbidden in ("file:", "://", "git+", "@ ", "-e ", "--", "\\", "C:/", "codex"):
        assert forbidden not in "\n".join(
            line.split("#", 1)[0] for line in text.splitlines()
        ), forbidden
    assert all(Version(version) for version in pins.values())  # parseable PEP 440 versions
    assert list(pins) == sorted(pins)  # reviewable, stable ordering


def test_constraints_pin_every_direct_dependency(pins) -> None:
    for rel_path in ("requirements.txt", "requirements-svd.txt"):
        for line in _requirement_lines(rel_path):
            requirement = Requirement(line)
            name = verifier.normalize_name(requirement.name)
            assert name in pins, f"{rel_path}: {name} is not pinned in the runtime constraints"
            assert requirement.specifier.contains(pins[name], prereleases=True), (
                f"{rel_path}: {line} contradicts the exact pin {name}=={pins[name]}"
            )


def test_pyproject_svd_extra_matches_requirements_svd_without_contradiction() -> None:
    extra = tomllib.loads(_read("pyproject.toml"))["project"]["optional-dependencies"]["svd"]

    assert sorted(extra) == sorted(_requirement_lines("requirements-svd.txt"))


def test_torch_family_is_pinned_to_the_cuda_build_and_resolver_is_pinned(pins) -> None:
    assert pins["torch"].endswith("+cu130")
    assert pins["torchvision"].endswith("+cu130")  # facexlib/CodeFormer require torchvision
    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", pins["pip"])  # the resolver is part of the runtime
    assert pins["opencv-python"].startswith("5.")  # same-version headless swap is deferred


# --- Drift verifier ---------------------------------------------------------------------------


def test_normalized_names_match_regardless_of_case_and_separators() -> None:
    assert verifier.normalize_name("Pillow") == "pillow"
    assert verifier.normalize_name("typing_extensions") == "typing-extensions"
    assert verifier.normalize_name("huggingface.hub") == "huggingface-hub"


def test_matching_environment_passes_and_extra_packages_are_ignored() -> None:
    pins = {"torch": "2.14.0+cu130", "pillow": "12.3.0"}
    installed = {"torch": "2.14.0+cu130", "pillow": "12.3.0", "ruff": "0.14.9"}

    assert verifier.find_mismatches(pins, installed) == []


def test_missing_and_wrong_version_packages_fail_with_clear_messages() -> None:
    pins = {"diffusers": "0.40.0", "numpy": "2.5.3", "pillow": "12.3.0"}

    problems = verifier.find_mismatches(pins, {"diffusers": "0.41.0", "numpy": "2.5.3"})

    assert problems == [
        "diffusers: installed 0.41.0, expected 0.40.0",
        "pillow: missing (expected 12.3.0)",
    ]


def test_torch_local_version_identifiers_are_compared_exactly() -> None:
    assert verifier.versions_equal("2.14.0+cu130", "2.14.0+cu130")
    assert not verifier.versions_equal("2.14.0", "2.14.0+cu130")  # CPU build is drift
    assert not verifier.versions_equal("2.14.0+cpu", "2.14.0+cu130")
    assert not verifier.versions_equal("2.14.1+cu130", "2.14.0+cu130")


def test_parse_constraints_rejects_ranges_duplicates_and_requirement_syntax() -> None:
    assert verifier.parse_constraints("# c\n\nTorch==2.14.0+cu130  # note\n") == {
        "torch": "2.14.0+cu130"
    }
    for bad in ("torch>=2.4", "torch", "-e .", "git+https://x/y.git", "torch==1\ntorch==2"):
        with pytest.raises(verifier.ConstraintsError):
            verifier.parse_constraints(bad)


def test_cli_reports_drift_actionably_with_exit_status(tmp_path, monkeypatch, capsys) -> None:
    constraints = tmp_path / "pins.txt"
    constraints.write_text("torch==2.14.0+cu130\npillow==12.3.0\n", encoding="utf-8")
    monkeypatch.setattr(verifier, "installed_versions", lambda: {"torch": "2.14.0", "pillow": "12.3.0"})

    assert verifier.main(["--constraints", str(constraints)]) == 1

    err = capsys.readouterr().err
    assert "RUNTIME DRIFT: 1 of 2" in err
    assert "torch: installed 2.14.0, expected 2.14.0+cu130" in err
    assert "bootstrap_windows.ps1" in err


def test_cli_success_output_is_one_compact_line(tmp_path, monkeypatch, capsys) -> None:
    constraints = tmp_path / "pins.txt"
    constraints.write_text("pillow==12.3.0\n", encoding="utf-8")
    monkeypatch.setattr(verifier, "installed_versions", lambda: {"pillow": "12.3.0"})

    assert verifier.main(["--constraints", str(constraints)]) == 0

    captured = capsys.readouterr()
    assert captured.err == "" and len(captured.out.strip().splitlines()) == 1


def test_cli_distinguishes_an_unreadable_constraints_file(tmp_path, capsys) -> None:
    assert verifier.main(["--constraints", str(tmp_path / "missing.txt")]) == 2
    assert "UNREADABLE" in capsys.readouterr().err


# --- Bootstrap install policy ------------------------------------------------------------------


def _bootstrap() -> str:
    return _read("scripts/bootstrap_windows.ps1")


def _install_commands() -> list[str]:
    return [line.strip() for line in _bootstrap().splitlines() if '"-m", "pip", "install"' in line]


def test_every_bootstrap_install_after_pip_is_constrained() -> None:
    installs = _install_commands()
    resolving = [line for line in installs if '"pip==$pipVersion"' not in line]

    assert len(resolving) == 3  # torch family, base requirements, SVD requirements
    assert all('"-c", $ConstraintsFile' in line for line in resolving)


def test_bootstrap_pins_pip_instead_of_upgrading_the_resolver() -> None:
    script = _bootstrap()
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))

    assert "--upgrade" not in code
    assert 'Get-ConstraintPin -Name "pip"' in script
    assert '"pip==$pipVersion"' in script


def test_torch_family_comes_from_the_cuda_index_and_cpu_torch_is_guarded() -> None:
    script = _bootstrap()
    torch_line = next(line for line in _install_commands() if '"torch", "torchvision"' in line)

    assert '"--index-url", $CudaIndexUrl' in torch_line
    assert script.index('"torch", "torchvision"') < script.index('"-r", $requirements')
    assert "Assert-CudaTorch" in script.split("Assert-RuntimePins\n")[0]


def test_check_only_mode_never_installs_and_still_verifies_runtime_drift() -> None:
    script = _bootstrap()
    check_only_branch = script[script.index("if ($CheckOnly) {") : script.index("} else {\n    $pythonExe")]

    assert '"install"' not in check_only_branch
    assert "Remove-Item" not in check_only_branch
    # Both modes reach the drift verification after the mode-specific branch.
    assert script.index("Assert-RuntimePins\n") > script.index("} else {\n    $pythonExe")
    assert "pip\", \"check\"" in script and "verify_runtime_pins.py" in script


def test_unsupported_python_is_still_rejected_before_any_install() -> None:
    script = _bootstrap()

    assert "'^3\\.12\\.'" in script
    assert script.index("Get-PythonVersion -Executable $pythonExe") < script.index('"-m", "venv"')


def test_linux_github_ci_is_not_coupled_to_the_windows_cuda_resolution() -> None:
    assert "constraints/" not in _read(".github/workflows/ci.yml")
    assert "windows-py312-cu130" not in _read(".github/workflows/ci.yml")
