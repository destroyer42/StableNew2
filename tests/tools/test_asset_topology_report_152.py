"""PR-IMG-MODELS-152 report CLI: offline by default, redacted, cache-read-only, explicit Forge reconciliation only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.assets import topology_fixtures_152 as fx
from tools import asset_topology_report as cli


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    webui = fx.webui_tree(tmp_path / "webui")
    fx.safetensors(
        webui / "models/Stable-diffusion/Not Working/v1-5.safetensors", fx.unet_bundle("sd1")
    )
    fx.safetensors(webui / "embeddings/e.safetensors", fx.sdxl_embedding())
    fx.safetensors(webui / "models/embeddings/e.safetensors", fx.sd1_embedding())
    return webui


def run(tree: Path, tmp_path: Path, *extra: str) -> int:
    return cli.main(
        ["--webui-root", str(tree), "--cache-path", str(tmp_path / "cache.json"), *extra]
    )


def test_default_run_is_offline_redacted_and_leaves_the_cache_untouched(
    tree, tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(
        cli,
        "_forge_state",
        lambda url: pytest.fail("the default report must not contact a runtime"),
    )
    out = tmp_path / "report.json"
    assert run(tree, tmp_path, "--json", str(out)) == 0
    text = out.read_text(encoding="utf-8")
    report = json.loads(text)
    assert report["redaction"] == "labels_only" and str(tmp_path) not in text
    assert report["runtime"]["status"] == "not_requested"
    assert report["counts"]["observed_files"] == 3 and report["counts"]["identity_verified"] == 0
    assert not (tmp_path / "cache.json").exists()
    assert "Asset topology" in capsys.readouterr().out


def test_json_to_stdout_and_explicit_path_inclusion(tree, tmp_path, capsys):
    assert run(tree, tmp_path, "--json", "-", "--include-paths") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["redaction"] == "absolute_paths_included"
    assert all("path" in row for row in report["files"]["items"])


def test_a_quota_stop_exits_nonzero_and_says_the_report_is_incomplete(tree, tmp_path, capsys):
    assert run(tree, tmp_path, "--max-files", "1", "--json", "-") == 3
    report = json.loads(capsys.readouterr().out)
    assert (
        report["completeness"]["complete"] is False
        and report["completeness"]["truncated_by"] == "max_files"
    )


def test_forge_reconciliation_is_opt_in_and_uses_the_supplied_endpoint_only(
    tree, tmp_path, capsys, monkeypatch
):
    seen = []

    def fake(url: str) -> dict:
        seen.append(url)
        return {"status": "unverified_runtime", "runtime_identity": "unknown"}

    monkeypatch.setattr(cli, "_forge_state", fake)
    assert run(tree, tmp_path, "--forge-url", "http://127.0.0.1:7860", "--json", "-") == 0
    assert seen == ["http://127.0.0.1:7860"]
    assert json.loads(capsys.readouterr().out)["runtime"]["status"] == "unverified_runtime"


def test_unconfigured_root_is_a_clear_error(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli.AssetRegistry, "observation_roots", lambda self: ())
    monkeypatch.setattr(cli, "AssetRegistry", lambda *a, **k: type("R", (), {"webui_root": None})())
    assert cli.main(["--cache-path", str(tmp_path / "c.json")]) == 2
    assert "No WebUI root" in capsys.readouterr().err


def test_the_cli_installs_no_persistent_signal_handler(tree, tmp_path):
    import signal

    before = signal.getsignal(signal.SIGINT)
    run(tree, tmp_path)
    assert signal.getsignal(signal.SIGINT) is before
