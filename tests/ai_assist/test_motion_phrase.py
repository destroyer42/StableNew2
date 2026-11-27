"""ASSIST-FIX motion phrase: an image goes only to an approved vision model, reduced and without metadata."""

from __future__ import annotations

import base64
import io
import json

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from src.ai_assist import framing, validators
from src.ai_assist.contracts import (
    MAX_IMAGE_BYTES,
    SUGGESTION_SCHEMA_ID,
    AssistRequest,
    OutcomeCode,
    SuggestionKind,
)
from src.ai_assist.events import EventLog
from src.ai_assist.image import prepare_image
from src.ai_assist.paths import events_path
from src.ai_assist.remote_preview import write_remote_approval

from .test_remote_preview import LFM, Worker, service_for

JPEG = b"\xff\xd8" + b"0" * 16
KIND = SuggestionKind.MOTION_PHRASE


def request(**more) -> AssistRequest:
    values = {"positive_text": "a barn in a field", "image_jpeg": JPEG, **more}
    return AssistRequest("m1", KIND, **values)


def answer(phrase: str) -> str:
    return json.dumps(
        {"schema": SUGGESTION_SCHEMA_ID, "status": "ok", "kind": KIND.value, "phrase": phrase}
    )


def test_the_image_is_reduced_and_carries_no_metadata(tmp_path) -> None:
    info = PngInfo()
    info.add_text("parameters", "zzsecret prompt")
    path = tmp_path / "source.png"
    Image.new("RGBA", (2000, 1000), (10, 20, 30, 255)).save(path, pnginfo=info)
    data = prepare_image(path)
    assert len(data) <= MAX_IMAGE_BYTES and b"zzsecret" not in data
    with Image.open(io.BytesIO(data)) as result:
        assert result.format == "JPEG" and result.size == (512, 256)


def test_a_motion_request_needs_an_image_and_no_other_kind_may_carry_one() -> None:
    with pytest.raises(ValueError):
        request(image_jpeg=b"")
    with pytest.raises(ValueError):
        request(image_jpeg=b"\x89PNG")
    with pytest.raises(ValueError):
        request(image_jpeg=b"\xff\xd8" + b"0" * MAX_IMAGE_BYTES)
    with pytest.raises(ValueError):
        AssistRequest("r", SuggestionKind.PROMPT_REWRITE, "a barn", image_jpeg=JPEG)
    assert request().digest() != request(image_jpeg=JPEG + b"1").digest()
    assert "0000" not in repr(request())


def test_the_prompt_is_data_and_the_schema_bounds_the_phrase() -> None:
    prompt = framing.render_prompt(request())
    assert framing.BEGIN_MARKER in prompt and "a barn in a field" in prompt
    schema = framing.build_json_schema(request())
    assert schema["required"] == ["schema", "status", "kind", "phrase"]
    assert schema["properties"]["phrase"]["type"] == "string"


@pytest.mark.parametrize(
    ("phrase", "code"),
    [
        ("slow push in while grass sways", OutcomeCode.SUGGESTION),
        ("", OutcomeCode.MALFORMED),
        ("two\nlines", OutcomeCode.MALFORMED),
        ("pan <lora:x:1>", OutcomeCode.MALFORMED),
        ("[[season]] drifts", OutcomeCode.MALFORMED),
        ("x" * 400, OutcomeCode.MALFORMED),
        ("I cannot describe that", OutcomeCode.REFUSED_BY_MODEL),
    ],
)
def test_only_a_plain_single_line_phrase_is_accepted(phrase, code) -> None:
    result = validators.validate_output(answer(phrase), request())
    assert result.code is code
    if code is OutcomeCode.SUGGESTION:
        assert result.suggestion.motion_phrase == phrase


def test_the_image_travels_only_in_the_images_field_and_is_never_recorded(installation) -> None:
    worker = Worker()
    worker.output = answer("the camera pushes in slowly")
    service, spy, _ = service_for(installation, worker)
    outcome = service.run(request())
    assert outcome.ok and outcome.suggestion.motion_phrase == "the camera pushes in slowly"
    body = json.loads(worker.calls[-1][1])
    assert body["images"] == [base64.b64encode(JPEG).decode()]
    event = json.dumps(EventLog(events_path(installation.root)).tail(1)[0])
    assert body["images"][0] not in event and "barn" not in event and spy.calls == 0


def test_text_requests_send_no_images_field(installation) -> None:
    worker = Worker()
    service, _spy, _ = service_for(installation, worker)
    service.run(AssistRequest("t", SuggestionKind.PROMPT_REWRITE, "a barn <lora:barn:0.8>"))
    assert "images" not in json.loads(worker.calls[-1][1])


def test_a_model_without_vision_is_never_sent_the_image(installation) -> None:
    worker = Worker()
    service, spy, remote = service_for(installation, worker)
    write_remote_approval(installation.root, LFM)
    remote.select_model(LFM)
    outcome = service.run(request())
    assert (outcome.code, outcome.reason) == (OutcomeCode.UNAVAILABLE, "image_model_unsupported")
    assert not [1 for path, _ in worker.calls if path == "/api/generate"] and spy.calls == 0


def test_the_local_runtime_never_receives_an_image_request(installation) -> None:
    worker = Worker()
    worker.failures["/api/version"] = "disconnected"
    service, spy, _ = service_for(installation, worker)
    outcome = service.run(request())
    assert (outcome.code, outcome.reason) == (OutcomeCode.UNAVAILABLE, "image_needs_remote")
    assert spy.calls == 0
