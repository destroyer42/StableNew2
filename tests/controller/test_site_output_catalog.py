from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.app.site_output_catalog import SiteOutputCatalog, SiteOutputError
from src.app.site_queue_bridge import SiteSession
from src.gui import site_connection_dialog
from src.video.video_eval_run import RUN_SCHEMA
from tests.controller.test_site_queue_bridge import request

RUN_ID = "20261116_134153_example_a19ba141"


def _save(path: Path, contents: dict) -> None:
    path.write_text(json.dumps(contents), encoding="utf-8")


@pytest.fixture
def report(tmp_path):
    output = tmp_path / "output"
    directory = output / "video_eval" / RUN_ID
    directory.mkdir(parents=True)
    (output / "source.png").write_bytes(b"source")
    (output / "clip.mp4").write_bytes(b"clip")
    private = tmp_path / "private.png"
    private.write_bytes(b"private")

    jobs = [
        {"job_id": "first", "case_id": "case-one", "arm_id": "baseline"},
        {"job_id": "second", "case_id": "case-two", "arm_id": "baseline"},
    ]
    manifest = {
        "schema": RUN_SCHEMA,
        "run_id": RUN_ID,
        "arms": [{"arm_id": "baseline", "label": "Baseline"}],
        "cases": [
            {
                "case_id": "case-one",
                "image": str(output / "source.png"),
                "image_sha256": hashlib.sha256(b"source").hexdigest(),
                "prompt": "private prompt",
            },
            {
                "case_id": "case-two",
                "image": str(private),
                "image_sha256": hashlib.sha256(b"private").hexdigest(),
            },
        ],
        "jobs": jobs,
    }
    metrics = {
        "schema": "stablenew.video-eval-report.v1",
        "run_id": RUN_ID,
        "cells": [
            {
                **job,
                "state": "playable",
                "path": "output/clip.mp4",
                "artifact_sha256": hashlib.sha256(b"clip").hexdigest(),
            }
            for job in jobs
        ],
    }
    _save(directory / "run.json", manifest)
    _save(directory / "metrics.json", metrics)
    (directory / "index.html").write_text("<script>bad()</script>", encoding="utf-8")
    (output / "video_eval" / "20261117_130000_incomplete").mkdir()
    return output, directory, metrics


def test_site_reports_and_reads_only_hash_matched_media_from_approved_folder(report):
    output, _directory, _metrics = report
    catalog = SiteOutputCatalog(output)
    assert catalog.list_runs() == [RUN_ID]
    view = catalog.get_run(RUN_ID)
    assert "private" not in json.dumps(view)
    one, two = view["clips"]
    assert one["case"] == "case-one"
    assert catalog.read_media(one["clip"]) == ("video/mp4", b"clip")
    assert catalog.read_media(one["source"]) == ("image/png", b"source")
    assert two["source"] is None
    with pytest.raises(SiteOutputError, match="unknown_media"):
        catalog.read_media("index.html")
    (output / "clip.mp4").write_bytes(b"different")
    with pytest.raises(SiteOutputError, match="media_changed"):
        catalog.read_media(one["clip"])


def test_report_must_match_manifest_and_current_folder_grant(report):
    output, directory, metrics = report
    session = SiteSession()
    options = {"token": session.code}
    route = "/v1/output/runs"
    assert request(session, "GET", route, **options)[0] == 403
    session.set_output_folder(output)
    assert request(session, "OPTIONS", route)[0] == 204
    assert request(session, "GET", route, **options)[2] == {"runs": [RUN_ID]}
    assert request(session, "GET", route + "/" + RUN_ID, **options)[0] == 200
    assert request(session, "GET", route + "/../secret", **options)[0] == 404
    metrics["cells"][0]["arm_id"] = "mismatched"
    _save(directory / "metrics.json", metrics)
    assert request(session, "GET", route + "/" + RUN_ID, **options)[2] == {
        "error": "invalid_report"
    }
    session.set_output_folder(None)
    assert request(session, "GET", route, **options)[2] == {"error": "output_folder_not_shared"}
    session.revoke()
    assert request(session, "GET", route, **options)[0] == 401


def test_operator_site_registers_a_visible_toolbar_button_without_opening_connection(monkeypatch):
    native_dialog = Mock()
    monkeypatch.setattr(
        site_connection_dialog, "SiteConnectionDialog", Mock(return_value=native_dialog)
    )
    button = Mock()
    constructor = Mock(return_value=button)
    monkeypatch.setattr(site_connection_dialog.ttk, "Button", constructor)
    header = Mock()
    header.grid_size.return_value = (8, 1)

    site_connection_dialog.install_site_connection_control(Mock(), Mock(), header)

    constructor.assert_called_once_with(
        header, text="Operator Site", style="Secondary.TButton", command=native_dialog.open
    )
    button.grid.assert_called_once_with(row=0, column=8, padx=4, pady=4)
    native_dialog.open.assert_not_called()


def test_site_routes_one_selected_slot_to_the_existing_empty_desktop_draft(tmp_path):
    from src.app.site_pack_catalog import SitePackCatalog
    from src.controller.app_controller import AppController
    from src.gui.app_state_v2 import AppStateV2
    from src.gui.site_connection_dialog import PreviewQueueConnection
    from src.utils.prompt_packs import PromptPackInfo

    pack = tmp_path / "two_slots.json"
    _save(
        pack,
        {
            "schema_version": 1,
            "pack_data": {"name": "two_slots", "slots": [{"text": "first"}, {"text": "second"}]},
            "preset_data": {},
        },
    )
    app = AppController(main_window=None, threaded=False, pipeline_runner=None)
    app.app_state = AppStateV2()
    app._packs_dir = tmp_path
    app.packs = [PromptPackInfo("two_slots", pack)]
    session = SiteSession()
    session.share_packs(SitePackCatalog(tmp_path, app.packs))
    confirmation = Mock(return_value=True)
    connection = PreviewQueueConnection(app, session, Mock(), confirmation)
    auth = {"token": session.code}
    packs = request(session, "GET", "/v1/promptpacks", **auth)[2]["packs"]
    key = packs[0]["id"]
    description = request(session, "GET", f"/v1/promptpacks/{key}", **auth)[2]
    body = json.dumps({"pack_id": key, "revision": description["revision"], "slots": [1]}).encode()
    assert request(session, "POST", "/v1/prepare", body=body, **auth)[0] == 202
    assert app.app_state.job_draft.packs == []
    connection.tick()
    confirmation.assert_called_once()
    assert session.preparation()["state"] == "draft_added"
    assert [entry.pack_row_index for entry in app.app_state.job_draft.packs] == [1]
    assert request(session, "POST", "/v1/prepare", body=body, **auth)[0] == 202
    connection.tick()
    assert session.preparation()["state"] == "desktop_draft_open"
    confirmation.assert_called_once()


def test_remote_draft_revision_never_overwrites_native_draft():
    from src.contracts import PackJobEntry
    from src.gui.app_state_v2 import AppStateV2

    state = AppStateV2()
    initial = state.preview_revision
    state.add_job_draft_part("desktop prompt", "")
    row = PackJobEntry("pack", "Pack", {})
    assert state.add_packs_to_job_draft([row], expected_empty_revision=initial) is False
    assert (
        state.add_packs_to_job_draft([row], expected_empty_revision=state.preview_revision) is False
    )
    assert state.job_draft.parts[0].positive_prompt == "desktop prompt"
    assert state.job_draft.packs == []
