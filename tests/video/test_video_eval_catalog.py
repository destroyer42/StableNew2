import json

from src.state.workspace_paths import WorkspacePaths
from src.video.video_eval_catalog import list_plans, list_runs
from src.video.video_eval_run import RUN_SCHEMA
from src.video.video_eval_suite import SUITE_SCHEMA


def test_plan_paths_are_read_only_and_support_one_override(tmp_path):
    workspace = WorkspacePaths(tmp_path)
    assert workspace.eval_plans_dir("video", "custom") == tmp_path / "custom/eval_plans/video"
    assert workspace.eval_plans_dir("video", override="alternate") == tmp_path / "alternate/video"
    assert list_plans(workspace.eval_plans_dir("video")) == []
    assert list_runs(tmp_path / "output") == []
    assert list(tmp_path.iterdir()) == []


def test_catalog_validates_plans_and_lists_failures_without_reading_private_sidecars(tmp_path):
    (tmp_path / "source.png").write_bytes(b"pinned by the existing loader")
    valid = tmp_path / "valid.json"  # the schema, rather than the suffix, identifies a suite
    valid.write_text(
        json.dumps(
            {
                "schema": SUITE_SCHEMA,
                "suite_id": "motion",
                "cases": [{"case_id": "walk", "image": "source.png", "prompt": "walk"}],
                "arms": [
                    {
                        "arm_id": "candidate",
                        "backend": "video_workflow",
                        "form": {"workflow_id": "candidate", "experimental_opt_in": True},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "invalid.suite.json").write_text("{}", encoding="utf-8")
    (tmp_path / "sidecar.private.json").write_text("private", encoding="utf-8")
    good, bad = (
        next(entry for entry in list_plans(tmp_path) if entry.path.name == name)
        for name in ("valid.json", "invalid.suite.json")
    )
    assert "motion — 1 cases × 1 arms (1 jobs) · experimental" in good.label
    assert not good.error
    assert "unsupported eval suite schema" in bad.error
    assert len(list_plans(tmp_path)) == 2


def test_run_catalog_lists_unbuilt_and_built_with_manifest_identity_and_rating_count(tmp_path):
    def write_run(run_id):
        directory = tmp_path / "video_eval" / run_id
        directory.mkdir(parents=True)
        (directory / "run.json").write_text(
            json.dumps(
                {
                    "schema": RUN_SCHEMA,
                    "run_id": run_id,
                    "created_at": "2026-11-18T04:00:00+00:00",
                    "suite": {"suite_id": "motion"},
                    "jobs": [{"job_id": "a"}, {"job_id": "b"}],
                }
            ),
            encoding="utf-8",
        )
        return directory

    built = write_run("20261118_040000_motion_12345678")
    newest = write_run("20261119_040000_motion_12345678")
    (built / "metrics.json").write_text("{}", encoding="utf-8")
    html = built / "index.html"
    html.touch()
    (built / "ratings.csv").write_text(
        "case_id,arm_id,job_id,rating_1_to_5\nwalk,base,a,4\nwalk,other,b,\nwalk,old,c,5\n",
        encoding="utf-8",
    )
    run, report = list_runs(tmp_path)
    assert run.path == newest
    assert report.report_path == html
    assert "2026-11-18 04:00 · motion · 2 jobs · report built · rated 1/2" in report.label
    assert list_runs(tmp_path, include_unbuilt=False) == [report]
