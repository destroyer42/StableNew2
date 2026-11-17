from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

from src.app.site_pack_catalog import SitePackCatalog
from src.app.site_queue_bridge import SiteSession
from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.gui.app_state_v2 import AppStateV2
from src.gui.site_connection_dialog import PreviewQueueConnection
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.config import ConfigManager
from src.utils.prompt_packs import PromptPackInfo
from tests.controller.test_site_queue_bridge import request


def test_paired_create_rebuilds_owned_draft_and_queues_the_exact_compiled_jobs(tmp_path):
    pack = tmp_path / "create.json"
    pack.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pack_data": {
                    "name": "create",
                    "slots": [{"text": "forest at dawn"}, {"text": "open field"}],
                },
                "preset_data": {},
            }
        ),
        encoding="utf-8",
    )
    config = ConfigManager(presets_dir=tmp_path / "presets", packs_dir=tmp_path)
    app = AppController(main_window=None, threaded=False, pipeline_runner=None)
    app.app_state = AppStateV2()
    app.app_state.set_pipeline_stage_enabled("txt2img", True)
    app._config_manager = config
    app.packs = [PromptPackInfo("create", pack)]
    session = SiteSession(allow_promptpack_queue=True)
    session.share_packs(
        SitePackCatalog(
            tmp_path,
            app.packs,
            config.load_pack_config,
            {
                "models": ["draft_model.safetensors"],
                "vaes": ["draft_vae"],
                "samplers": ["Euler a"],
                "schedulers": ["Karras"],
            },
        )
    )
    approval = Mock(side_effect=AssertionError("desktop confirmation must not open"))
    connection = PreviewQueueConnection(app, session, approval, approval)
    auth = {"token": session.code}
    _, _, listing = request(session, "GET", "/v1/promptpacks", **auth)
    pack_id = listing["packs"][0]["id"]
    _, _, details = request(session, "GET", "/v1/promptpacks/" + pack_id, **auth)
    assert details["settings"]["model"]["choices"] == ["draft_model.safetensors"]
    body = {
        "pack_id": pack_id,
        "revision": details["revision"],
        "slots": [0, 1],
        "settings": {
            "model": "draft_model.safetensors",
            "vae": "draft_vae",
            "sampler": "Euler a",
            "scheduler": "Karras",
            "steps": 17,
            "cfg_scale": 4.5,
            "width": 768,
            "height": 512,
            "seed": 114,
            "subseed": 29,
            "subseed_strength": 0.25,
            "loop_count": 2,
        },
    }
    builder = PromptPackNormalizedJobBuilder(
        config_manager=config, job_builder=JobBuilderV2(), packs_dir=tmp_path
    )

    def prepare_and_build():
        status, _, draft = request(
            session, "POST", "/v1/prepare", body=json.dumps(body).encode(), **auth
        )
        assert status == 202
        connection.tick()
        assert session.preparation()["state"] == "draft_added"
        records = builder.build_jobs(app.app_state.job_draft.packs)
        assert len(records) == 4
        app.app_state.set_preview_jobs(records)
        connection.tick()
        preview = session.preview()
        assert preview["preparation_id"] == draft["request_id"]
        assert preview["desktop_confirmation"] is False
        return preview, records

    invalid = {**body, "settings": {"output_dir": "outside"}}
    assert request(session, "POST", "/v1/prepare", body=json.dumps(invalid).encode(), **auth)[
        2
    ] == {"error": "invalid_txt2img_settings"}
    previous, _ = prepare_and_build()
    body["settings"]["steps"] = 24
    current, records = prepare_and_build()
    assert current["preview_id"] != previous["preview_id"]
    assert session.request(previous["preview_id"])[0] == 409
    assert {job["settings"]["steps"] for job in current["jobs"]} == {24}
    for record in records:
        assert record.base_model == "draft_model.safetensors"
        assert record.batch_total == 2
        assert record.config["subseed"] == 29
        assert record.config["subseed_strength"] == 0.25
        assert record.config["scheduler"] == "Karras"
        assert record.config["vae"] == "draft_vae"
        assert record.sampler_name == "Euler a"
        assert (record.width, record.height, record.cfg_scale) == (768, 512, 4.5)
    repository = JobRepository(tmp_path / "queue.sqlite3")
    try:
        queue = JobQueue(repository=repository)
        runner = Mock(is_running=lambda: True)
        jobs = JobService(queue, runner=runner)
        app.job_service = jobs
        app.pipeline_controller = SimpleNamespace(
            submit_preview_jobs_to_queue=lambda records, **_kwargs: len(jobs.submit_njrs(records))
        )
        app._prepare_queue_run_config = dict
        app._spawn_tracked_thread = lambda *, target, args, **_kwargs: target(*args)
        assert not repository.list_jobs()
        assert session.request(current["preview_id"])[0] == 202
        connection.tick()
        connection.tick()
        assert session.receipt()["state"] == "queued"
        assert session.receipt()["job_ids"] == tuple(record.job_id for record in records)
        assert len(repository.list_jobs()) == 4
        runner.run_once.assert_not_called()
        approval.assert_not_called()
    finally:
        repository.close()
