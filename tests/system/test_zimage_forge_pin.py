"""Read-only pin verification binds the actual owned command, source and managed marker."""

import json
from types import SimpleNamespace

import pytest

from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1 as P
from src.utils import managed_forge_runtime as runtime


@pytest.mark.parametrize("failure", [None, "head", "dirty", "marker", "cwd", "command", "unavailable"])
def test_pin_and_ownership_layout_are_verified_without_runtime_mutation(tmp_path, monkeypatch, failure):
    install = tmp_path / "neo"
    install.mkdir()
    contract = runtime.load_manifest()
    (install / contract["install"]["marker"]).write_text(json.dumps({
        "revision": "wrong" if failure == "marker" else P.forge_revision, "status": "verified",
    }), encoding="utf-8")
    command = runtime.build_launch_profile(contract, install_dir=install, model_home=tmp_path / "models", port=7871)["command"]
    calls = []

    def read(argv, **kwargs):
        calls.append(argv)
        if failure == "unavailable":
            raise OSError("git absent")
        text = ("wrong" if failure == "head" else P.forge_revision) if "rev-parse" in argv else (" M tracked.py" if failure == "dirty" else "")
        return SimpleNamespace(stdout=text)

    monkeypatch.setattr(runtime.subprocess, "run", read)
    cwd = str(install / ("other" if failure == "cwd" else "source"))
    if failure == "command":
        command[1] = "alternate.py"
    if failure:
        with pytest.raises(runtime.ManagedForgeUnavailable):
            runtime.verify_pinned_launch(command, cwd, P.forge_revision)
    else:
        assert runtime.verify_pinned_launch(command, cwd, P.forge_revision)["revision"] == P.forge_revision
        assert len(calls) == 2 and all("-C" in c for c in calls)
