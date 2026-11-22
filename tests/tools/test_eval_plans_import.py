import argparse
import hashlib
import json

import pytest

from src.state.workspace_paths import WorkspacePaths
from src.video.video_eval_import import import_suite
from src.video.video_eval_suite import SUITE_SCHEMA, EvalSuiteError, load_eval_suite
from tools import eval_plans_import
from tools.qualification import eval_plan_output


def _source(tmp_path):
    source = tmp_path / "scattered"
    source.mkdir()
    image = source / "input.png"
    image.write_bytes(b"source bytes")
    suite = source / "20261122_example.suite.json"
    suite.write_text(
        json.dumps(
            {
                "schema": SUITE_SCHEMA,
                "suite_id": "example",
                "cases": [
                    {
                        "case_id": "portrait",
                        "image": "input.png",
                        "prompt": "walk",
                        "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                    }
                ],
                "arms": [{"arm_id": "base", "backend": "svd_native"}],
            }
        ),
        encoding="utf-8",
    )
    return suite, image


def test_import_is_read_only_by_default_and_preserves_source_and_hash(
    tmp_path, monkeypatch, capsys
):
    suite, image = _source(tmp_path)
    original = hashlib.sha256(suite.read_bytes()).hexdigest()
    private = suite.parent / "collector.private.json"
    private.write_text("private contents", encoding="utf-8")
    root = tmp_path / "Output" / "eval_plans"
    monkeypatch.setattr(eval_plans_import, "configured_eval_plans_root", lambda: root)
    args = ["--from", str(suite.parent)]

    assert eval_plans_import.main(args) == 0
    output = capsys.readouterr().out
    assert "Would copy" in output and f"Skipped private suite: {private.name}" in output
    assert "private contents" not in output
    assert not root.exists()

    assert eval_plans_import.main([*args, "--apply"]) == 0
    target = root / "video" / suite.name
    assert json.loads(target.read_bytes())["cases"][0]["image"] == str(image.resolve())
    assert load_eval_suite(target).cases[0].image_path == image.resolve()
    assert hashlib.sha256(suite.read_bytes()).hexdigest() == original
    assert not (root / "video" / private.name).exists()
    assert (root / "README.md").is_file()
    assert (root / "templates" / "video_eval_three_engines.suite.json").is_file()
    log = root / "_imported" / "imports.jsonl"
    assert json.loads(log.read_bytes())["source_sha256"] == original

    before = target.read_bytes()
    assert eval_plans_import.main([*args, "--apply"]) == 0
    assert target.read_bytes() == before
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1


def test_changed_pinned_image_is_refused_before_writing(tmp_path):
    suite, image = _source(tmp_path)
    image.write_bytes(b"changed")
    root = tmp_path / "canonical"
    with pytest.raises(EvalSuiteError, match="changed since the suite pinned"):
        import_suite(suite, root, apply=True)
    assert not root.exists()


def test_qualification_default_preserves_explicit_paths_and_requires_external_root(
    tmp_path,
    monkeypatch,
    capsys,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(eval_plan_output, "workspace_paths", WorkspacePaths(repo))
    parser = argparse.ArgumentParser()
    with pytest.raises(SystemExit, match="2"):
        eval_plan_output.plan_output(parser, None, "fun354", filename="plan.json")
    assert "--out is required" in capsys.readouterr().err
    assert not (repo / "output").exists()
    explicit = tmp_path / "explicit.json"
    assert eval_plan_output.plan_output(parser, explicit, "fun354") == explicit

    canonical = tmp_path / "canonical"
    presets = repo / "presets"
    presets.mkdir()
    (presets / "settings.json").write_text(
        json.dumps({"eval_plans_dir": str(canonical)}), encoding="utf-8"
    )
    result = eval_plan_output.plan_output(parser, None, "fun354", filename="plan.json")
    assert result.parent.parent == canonical / "qualification/fun354"
    assert result.name == "plan.json"
    assert (canonical / "README.md").is_file()
