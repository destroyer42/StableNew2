"""JT-NJR — Modern NJR Journey Test Pattern (PR-TEST-003).

This test demonstrates the MODERN journey test pattern that uses the full
canonical execution path while mocking only at the HTTP transport layer.

Pattern:
    PromptPack → Builder → NJR → Queue → Runner → History
    
    Mock ONLY: requests.Session.request (HTTP transport)
    Execute REAL: Builder logic, runner stages, executor, history recording

This is the preferred pattern for new journey tests.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.api.client import SDWebUIClient
from tests.helpers.job_helpers import make_test_njr
from tests.journeys.journey_helpers_v2 import run_njr_journey


@pytest.mark.journey
def test_njr_txt2img_canonical_path():
    """Test txt2img execution through full NJR canonical path.
    
    This test validates:
    - NJR → Runner executes all stages correctly
    - HTTP mocking at transport layer allows full pipeline logic execution
    - History entry reflects actual execution state
    """
    
    # Step 1: Create a test NJR
    njr = make_test_njr(
        job_id="test-njr-001",
        positive_prompt="A beautiful sunset over mountains, photorealistic",
        negative_prompt="blurry, ugly, distorted",
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
    with patch.object(api_client._session, 'request') as mock_request:
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
        entry = run_njr_journey(njr, api_client, timeout_seconds=10.0)
        
        # Step 5: Verify execution
        assert entry is not None
        assert entry.job_id == njr.job_id
        assert entry.status.value == "completed"
        
        # Verify HTTP was called (runner executed)
        assert mock_request.called, "HTTP transport should have been invoked"
        
        # Verify the request was made to txt2img endpoint
        call_args = mock_request.call_args
        request_url = call_args[1].get('url') or call_args[0][1]
        assert "/sdapi/v1/txt2img" in request_url, f"Expected txt2img endpoint, got {request_url}"


# NOTE: The remaining journey tests (test_jt01-jt06) should be refactored to use
# the run_njr_journey() pattern demonstrated above. Key changes needed:
#
# 1. Replace `with patch("src.api.client.ApiClient.generate_images")` 
#    with `with patch.object(api_client._session, 'request')`
#
# 2. Use run_njr_journey(njr, api_client) instead of start_run_and_wait(controller)
#
# 3. Remove GUI/AppController dependencies where possible
#
# 4. Mock HTTP responses at transport layer, not API method layer
#
# See PR-TEST-003 documentation for full migration guide.


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
