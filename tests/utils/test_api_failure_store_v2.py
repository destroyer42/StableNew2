import json

from src.utils.api_failure_store_v2 import clear_api_failures, get_api_failures, record_api_failure


SAMPLE_IMAGE_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGMA"
    "AQAABQABDQottAAAAABJRU5ErkJggg=="
)


def test_api_failure_store_records_and_limits():
    clear_api_failures()
    record_api_failure(
        stage="upscale",
        endpoint="/sdapi/v1/extra-single-image",
        method="POST",
        payload={"image": SAMPLE_IMAGE_BASE64},
        status_code=500,
        response_text="Invalid encoded image",
        error_message="HTTPError",
    )
    record_api_failure(
        stage="txt2img",
        endpoint="/sdapi/v1/txt2img",
        method="POST",
        payload={"prompt": "test"},
        status_code=400,
        response_text="Bad request",
        error_message="ValueError",
    )
    failures = get_api_failures(limit=1)
    assert len(failures) == 1
    latest = failures[0]
    assert latest.stage == "txt2img"
    assert latest.image_base64 is None
    all_failures = get_api_failures(limit=10)
    assert len(all_failures) == 2
    assert all_failures[1].endpoint == "/sdapi/v1/extra-single-image"
