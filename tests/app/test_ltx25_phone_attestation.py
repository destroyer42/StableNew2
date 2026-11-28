"""LTX-2.5 from a phone: the Operator Site's engine choice and the review gateway's Continue clip.

The Operator Site phone picks engines, so an LTX-2.5 arm needs the confirmed text version.  The review gateway phone
cannot pick engines; only Continue clip keeps a clip's engine, and its confirm screen states the text.  Real builder,
catalog and Storyboard service over fake jobs.  No GPU, Comfy, FFmpeg or network.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.app.review_gateway_protocol import scrub_text
from src.app.site_media_files import SiteOutputError
from src.app.site_phone_continue import compile_continuation
from src.app.site_phone_video import PhoneVideo
from src.controller.storyboard_submission_service import StoryboardSubmissionService
from src.video.licence_attestation import (
    ATTESTATION_KEY,
    LTX25_ATTESTATION_TEXT,
    LTX25_ATTESTATION_VERSION,
    recorded_attestation,
)
from src.video.storyboard_tree_store import StoryboardTreeStore
from src.video.workflow_admission import require_workflow_admission
from src.video.workflow_catalog_ltx25 import LTX25_ID, LTX25_VERSION
from src.video.workflow_catalog_wan_a14b import WAN_A14B_ID, WAN_A14B_VERSION
from tests.helpers.storyboard_380 import (
    REG,
    FakeRepository,
    builder,
    frames_out_job,
    source_image,
    unsmoothed_mp4,
)

# --- Operator Site: the engine is chosen on the phone ---------------------------------------------


def _ltx_arm(**extra: Any) -> dict[str, Any]:
    return {
        "workflow_id": LTX25_ID,
        "workflow_version": LTX25_VERSION,
        "experimental_opt_in": True,
        **extra,
    }


def _preview(tmp_path: Path, arm: dict[str, Any]):
    from src.video.video_workflow_njr_builder import sha256_file

    root = tmp_path / "output"
    path = source_image(root, (576, 1024))
    digest = sha256_file(path)
    item = SimpleNamespace(width=576, height=1024)
    library = SimpleNamespace(
        root=root,
        image=lambda _id: (item, b"", digest),
        path_for=lambda _item: path,
    )
    catalog = SimpleNamespace(scope="scope", library=library, require_active=lambda: None)
    video = PhoneVideo(SimpleNamespace())
    frames = 25 if arm["workflow_id"] == LTX25_ID else 81
    body = {
        "kind": "video",
        "scope": "scope",
        "sources": [{"id": "one", "digest": digest}],
        "arms": [arm],
        "prompt": "she waves",
        "negative_prompt": "",
        "seed": 7,
        "frames": frames,
    }
    return video.preview(catalog, body, evaluation=False)


def test_the_site_is_told_the_text_for_ltx_only() -> None:
    workflows = {
        item["workflow_id"]: item for item in PhoneVideo(SimpleNamespace()).options()["workflows"]
    }

    assert workflows[LTX25_ID][ATTESTATION_KEY] == {
        "version": LTX25_ATTESTATION_VERSION,
        "text": LTX25_ATTESTATION_TEXT,
    }
    assert ATTESTATION_KEY not in workflows[WAN_A14B_ID]


@pytest.mark.parametrize("extra", [{}, {ATTESTATION_KEY: "an-older-text"}, {ATTESTATION_KEY: True}])
def test_the_site_refuses_an_ltx_arm_without_the_current_confirmation(tmp_path, extra) -> None:
    with pytest.raises(SiteOutputError, match="licence_attestation_required"):
        _preview(tmp_path, _ltx_arm(**extra))


def test_the_site_records_the_confirmation_on_the_job(tmp_path) -> None:
    draft = _preview(tmp_path, _ltx_arm(**{ATTESTATION_KEY: LTX25_ATTESTATION_VERSION}))

    [njr] = draft.records
    record = recorded_attestation(njr.extra_metadata)
    assert record is not None and record["text_version"] == LTX25_ATTESTATION_VERSION
    require_workflow_admission(njr)


def test_the_site_accepts_no_confirmation_field_for_another_engine(tmp_path) -> None:
    arm = {
        "workflow_id": WAN_A14B_ID,
        "workflow_version": WAN_A14B_VERSION,
        "experimental_opt_in": False,
    }
    assert ATTESTATION_KEY not in _preview(tmp_path, arm).records[0].extra_metadata

    with pytest.raises(SiteOutputError, match="invalid_video_preview"):
        _preview(tmp_path, {**arm, ATTESTATION_KEY: LTX25_ATTESTATION_VERSION})


# --- review gateway: Continue clip keeps the clip's engine ----------------------------------------


class _Repository(FakeRepository):
    def list_recent_jobs(self, *, limit: int = 50, statuses: Any = None) -> list[Any]:
        return [
            SimpleNamespace(job_id=job.job_id, result=job.result)
            for job in reversed(list(self.jobs.values()))
            if not statuses or job.status in statuses
        ][:limit]


def _continue_setup(tmp_path: Path, form: dict[str, Any]) -> SimpleNamespace:
    from src.video.sequence_ledger import sha256_of

    source, job_id, _frames = frames_out_job(tmp_path, count=25, size=(768, 1344), form=form)
    repository = _Repository(jobs=dict(source.jobs), files=dict(source.files))
    service = StoryboardSubmissionService(
        njr_builder=builder(tmp_path),
        workflow_registry=REG,
        job_service=lambda: SimpleNamespace(submit_njrs=lambda *a: pytest.fail("not the phone")),
        repository=lambda: repository,
        store=StoryboardTreeStore(tmp_path / "trees"),
        output_root=lambda: str(tmp_path),
        draw_seed=lambda: 1,
    )
    clip = unsmoothed_mp4(source, job_id)
    return SimpleNamespace(service=service, clip=clip, digest=sha256_of(clip))


def _ltx_clip_form() -> dict[str, Any]:
    return {
        "workflow_id": LTX25_ID,
        "workflow_version": LTX25_VERSION,
        "prompt": "she waves",
        "seed": "11",
        "frame_count": 25,
        "experimental_opt_in": True,
    }


def test_continuing_an_ltx_clip_states_the_text_and_records_it_on_confirm(tmp_path) -> None:
    env = _continue_setup(tmp_path, _ltx_clip_form())
    compiled = compile_continuation(
        env.service, tmp_path, env.clip, env.digest, "she turns", 7, video=pytest.fail
    )

    assert compiled.build is not None, compiled.lines
    assert LTX25_ATTESTATION_TEXT in compiled.lines
    assert scrub_text(LTX25_ATTESTATION_TEXT, 200) == LTX25_ATTESTATION_TEXT  # shown unaltered
    assert LTX25_ATTESTATION_VERSION in compiled.identity  # a new text is shown again
    submitted: list[Any] = []

    def admit(njrs: list[Any]) -> list[str]:
        for njr in njrs:
            require_workflow_admission(njr)
        submitted.extend(njrs)
        return ["phone-1"]

    compiled.build(admit)

    [njr] = submitted
    assert recorded_attestation(njr.extra_metadata)["text_version"] == LTX25_ATTESTATION_VERSION


def test_continuing_another_engines_clip_is_unchanged(tmp_path) -> None:
    from tests.helpers.storyboard_380 import a14b_settings

    env = _continue_setup(tmp_path, a14b_settings(frame_count=25))
    compiled = compile_continuation(
        env.service, tmp_path, env.clip, env.digest, "she turns", 7, video=pytest.fail
    )

    assert LTX25_ATTESTATION_TEXT not in compiled.lines
    assert LTX25_ATTESTATION_VERSION not in compiled.identity
