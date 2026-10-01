"""Canonical NJR path with only the HTTP transport mocked.

NJR -> JobService.submit_njrs -> SQLite queue/repository -> PipelineRunner.run_njr
-> executor -> /sdapi/v1/txt2img (mocked transport) -> repository history.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

from src.api.client import SDWebUIClient
from tests.helpers.job_helpers import make_test_njr
from tests.helpers.njr_queue_harness import run_njr_via_queue


def test_njr_txt2img_executes_via_queue_runner_and_hits_txt2img_endpoint():
    """Execute a txt2img NJR through JobService -> SQLite -> run_njr with HTTP mocked.

    This test validates:
    - NJR → Runner executes all stages correctly
    - HTTP mocking at transport layer allows full pipeline logic execution
    - History entry reflects actual execution state
    """

    # Step 1: Create a test NJR
    njr = make_test_njr(
        job_id="test-njr-001",
        prompt="A beautiful sunset over mountains, photorealistic",
        base_model="sdxl",
        config={
            "sampler": "Euler",
            "scheduler": "Karras",
            "steps": 20,
            "cfg_scale": 7.0,
            "width": 1024,
            "height": 1024,
            "batch_size": 1,
        },
    )

    # Verify NJR structure
    assert njr.positive_prompt == "A beautiful sunset over mountains, photorealistic"
    assert njr.base_model == "sdxl"
    assert njr.config["sampler"] == "Euler"
    assert njr.config["steps"] == 20

    # Step 2: Create API client
    api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")

    # Step 3: Mock HTTP transport layer (NOT the generate_images method)
    with patch.object(api_client._session, "request") as mock_request:
        # Create mock HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "images": [
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            ],
            "parameters": {
                "prompt": njr.positive_prompt,
                "negative_prompt": njr.negative_prompt or "",
                "seed": njr.seed,
                "steps": 20,
                "cfg_scale": 7.0,
                "sampler_name": "Euler",
                "scheduler": "Karras",
                "width": 1024,
                "height": 1024,
            },
        }
        mock_response.raise_for_status = Mock()  # No-op, success response
        mock_request.return_value = mock_response

        # Step 4: Execute through canonical runner path
        entry = run_njr_via_queue(njr, api_client, timeout_seconds=10.0)

        # Step 5: Verify execution
        assert entry is not None
        assert entry.job_id == njr.job_id
        assert entry.status.value == "completed"

        # Verify HTTP was called (runner executed)
        assert mock_request.called, "HTTP transport should have been invoked"

        # Verify the request was made to txt2img endpoint
        call_args = mock_request.call_args
        request_url = call_args[1].get("url") or call_args[0][1]
        assert "/sdapi/v1/txt2img" in request_url, f"Expected txt2img endpoint, got {request_url}"
