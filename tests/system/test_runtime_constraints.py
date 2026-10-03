"""Reproducible Windows runtime authority (PR-RUNTIME-DEPS-100, profiles by PR-POSTPROC-100).

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
CONSTRAINTS = ROOT / "constraints" / "windows-py314-cu130.txt"


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _requirement_lines(rel_path: str) -> list[str]:
    return [
        line.split("#", 1)[0].strip()
        for line in _read(rel_path).splitlines()
        if line.split("#", 1)[0].strip()
    ]


@pytest.fixture(scope="module")
def profiles() -> verifier.RuntimeProfiles:
    return verifier.parse_profiles(CONSTRAINTS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pins(profiles) -> dict[str, str]:
    return profiles.all_pins


# --- Constraints file -------------------------------------------------------------------------


def test_constraints_declare_their_exact_target() -> None:
    header = "\n".join(
        line for line in CONSTRAINTS.read_text(encoding="utf-8").splitlines() if line.startswith("#")
    )

    assert "Windows" in header
    assert "CPython 3.14" in header and "standard-GIL" in header
    assert "CUDA 13.0" in header and "cu130" in header
    assert "RTX 4070 Ti" in header
    assert "clean disposable CPython 3.14.x environments" in header


def test_constraints_are_exact_unique_and_free_of_paths_urls_and_editables(pins) -> None:
    text = CONSTRAINTS.read_text(encoding="utf-8")

    assert pins  # parse_constraints rejects ranges, duplicates and anything not name==version
    for forbidden in ("file:", "://", "git+", "@ ", "-e ", "--", "\\", "C:/", "codex"):
        assert forbidden not in "\n".join(
            line.split("#", 1)[0] for line in text.splitlines()
        ), forbidden
    assert all(Version(version) for version in pins.values())  # parseable PEP 440 versions
    for profile in (profiles_of(text).core, profiles_of(text).postprocess):
        assert list(profile) == sorted(profile)  # reviewable, stable ordering per profile


def profiles_of(text: str) -> verifier.RuntimeProfiles:
    return verifier.parse_profiles(text)


def test_constraints_pin_every_direct_dependency_in_its_own_profile(profiles) -> None:
    expected = {
        "requirements.txt": profiles.core,
        "requirements-svd.txt": profiles.core,
        "requirements-postprocess.txt": profiles.postprocess,
    }
    for rel_path, profile in expected.items():
        for line in _requirement_lines(rel_path):
            requirement = Requirement(line)
            name = verifier.normalize_name(requirement.name)
            assert name in profile, f"{rel_path}: {name} is not pinned in its runtime profile"
            assert requirement.specifier.contains(profile[name], prereleases=True), (
                f"{rel_path}: {line} contradicts the exact pin {name}=={profile[name]}"
            )


def test_pyproject_extras_match_the_requirement_files() -> None:
    extras = tomllib.loads(_read("pyproject.toml"))["project"]["optional-dependencies"]

    assert sorted(extras["svd"]) == sorted(_requirement_lines("requirements-svd.txt"))
    assert sorted(extras["postprocess"]) == sorted(_requirement_lines("requirements-postprocess.txt"))


def test_profiles_do_not_overlap_and_core_excludes_restoration_only_packages(profiles) -> None:
    restoration_only = {"spandrel", "spandrel-extra-arches", "codeformer", "lpips", "einops"}
    retired = {"basicsr", "gfpgan", "facexlib", "filterpy"}  # not in any supported profile

    assert not set(profiles.core) & set(profiles.postprocess)
    assert not restoration_only & set(profiles.core)  # core SVD never needs the restoration stack
    assert restoration_only <= set(profiles.postprocess)
    assert not retired & set(profiles.all_pins)  # the legacy stack is not in any profile
    assert set(profiles.postprocess_markers) == {"spandrel", "spandrel-extra-arches"}
    for line in _requirement_lines("requirements-svd.txt"):
        assert Requirement(line).name.lower() not in restoration_only | retired


def test_torch_family_is_pinned_to_the_cuda_build_and_resolver_is_pinned(profiles, pins) -> None:
    assert pins["torch"].endswith("+cu130")
    # torchvision is core: transformers' default CLIPImageProcessor backend (SVD conditioning).
    assert profiles.core["torchvision"].endswith("+cu130")
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
    assert "RUNTIME DRIFT: 1 pinned package problem(s)" in err
    assert "[core] torch: installed 2.14.0, expected 2.14.0+cu130" in err
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


# --- Profile semantics: core required, postprocess optional ------------------------------------

_PROFILE_TEXT = """
torch==2.14.0+cu130
pillow==12.3.0
# profile: postprocess
# profile-marker: spandrel, spandrel-extra-arches
spandrel==0.4.2
facexlib==0.3.0
"""


def _evaluate(installed: dict[str, str], *, with_postprocess: bool = False):
    return verifier.evaluate(
        verifier.parse_profiles(_PROFILE_TEXT), installed, with_postprocess=with_postprocess
    )


_CORE_ONLY = {"torch": "2.14.0+cu130", "pillow": "12.3.0"}


def test_profile_directives_split_pins_and_record_markers() -> None:
    parsed = verifier.parse_profiles(_PROFILE_TEXT)

    assert parsed.core == {"torch": "2.14.0+cu130", "pillow": "12.3.0"}
    assert parsed.postprocess == {"spandrel": "0.4.2", "facexlib": "0.3.0"}
    assert parsed.postprocess_markers == ("spandrel", "spandrel-extra-arches")
    with pytest.raises(verifier.ConstraintsError, match="unknown profile"):
        verifier.parse_profiles("# profile: gpu\n")


def test_core_only_environment_is_valid_and_postprocess_is_absent_by_design() -> None:
    assert _evaluate(_CORE_ONLY) == ([], "absent")


def test_missing_core_package_still_fails_even_when_postprocess_is_absent() -> None:
    problems, state = _evaluate({"torch": "2.14.0+cu130"})

    assert problems == ["[core] pillow: missing (expected 12.3.0)"]
    assert state == "absent"


def test_requesting_postprocess_requires_the_whole_optional_profile() -> None:
    problems, state = _evaluate(_CORE_ONLY, with_postprocess=True)

    assert state == "incomplete"
    assert problems == [
        "[postprocess] facexlib: missing (expected 0.3.0)",
        "[postprocess] spandrel: missing (expected 0.4.2)",
    ]


def test_installed_marker_package_makes_an_incomplete_optional_stack_an_error() -> None:
    problems, state = _evaluate({**_CORE_ONLY, "spandrel": "0.4.2"})

    assert state == "incomplete"
    assert problems == ["[postprocess] facexlib: missing (expected 0.3.0)"]


def test_complete_optional_profile_passes_and_is_reported_complete() -> None:
    installed = {**_CORE_ONLY, "spandrel": "0.4.2", "facexlib": "0.3.0"}

    assert _evaluate(installed) == ([], "complete")


def test_drifted_optional_package_fails_even_when_the_profile_was_not_requested() -> None:
    # facexlib alone does not make the profile "present" (it is shared with other installs),
    # but if it is installed it must still match its pin.
    problems, state = _evaluate({**_CORE_ONLY, "facexlib": "0.2.5"})

    assert state == "absent"
    assert problems == ["[postprocess] facexlib: installed 0.2.5, expected 0.3.0"]


def test_unpinned_legacy_extras_never_fail_a_core_environment() -> None:
    legacy = {**_CORE_ONLY, "codeformer": "0.0.11", "lpips": "0.1.4", "scipy": "1.18.1"}

    assert _evaluate(legacy) == ([], "absent")


def test_cli_reports_profile_state_and_requires_postprocess_on_request(
    tmp_path, monkeypatch, capsys
) -> None:
    constraints = tmp_path / "pins.txt"
    constraints.write_text(_PROFILE_TEXT, encoding="utf-8")
    monkeypatch.setattr(verifier, "installed_versions", lambda: dict(_CORE_ONLY))

    assert verifier.main(["--constraints", str(constraints)]) == 0
    assert "postprocess profile absent (optional, not required)" in capsys.readouterr().out

    assert verifier.main(["--constraints", str(constraints), "--with-postprocess"]) == 1
    err = capsys.readouterr().err
    assert "(postprocess profile: incomplete)" in err and "-WithPostprocess" in err


# --- Bootstrap install policy ------------------------------------------------------------------


def _bootstrap() -> str:
    return _read("scripts/bootstrap_windows.ps1")


def _install_commands() -> list[str]:
    return [line.strip() for line in _bootstrap().splitlines() if '"-m", "pip", "install"' in line]


def test_every_bootstrap_install_after_pip_is_constrained() -> None:
    installs = _install_commands()
    resolving = [line for line in installs if '"pip==$pipVersion"' not in line]

    # torch family, base requirements, SVD requirements, and the optional postprocess requirements
    assert len(resolving) == 4
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


def test_postprocess_stack_is_installed_only_on_request_and_core_never_installs_it() -> None:
    script = _bootstrap()
    postprocess_line = next(
        line for line in _install_commands() if "$postprocessRequirements" in line
    )
    guard = script.index("if ($WithPostprocess) {\n        Invoke-CheckedProcess")

    assert "[switch]$WithPostprocess" in script
    assert guard < script.index(postprocess_line) < script.index("Assert-CudaTorch\n}")
    # Torch family stays core (torchvision backs SVD image conditioning), never postprocess-gated.
    torch_line = next(line for line in _install_commands() if '"torch", "torchvision"' in line)
    assert "$WithPostprocess" not in torch_line
    # The verifier requires the optional profile only when it was requested.
    assert '$verifierArguments += "--with-postprocess"' in script


def test_unsupported_python_is_still_rejected_before_any_install() -> None:
    script = _bootstrap()

    assert "'^3\\.14\\.'" in script
    assert script.index("Get-PythonVersion -Executable $pythonExe") < script.index('"-m", "venv"')


def test_linux_github_ci_is_not_coupled_to_the_windows_cuda_resolution() -> None:
    assert "constraints/" not in _read(".github/workflows/ci.yml")
    assert "windows-py314-cu130" not in _read(".github/workflows/ci.yml")
