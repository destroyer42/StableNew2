"""One-shot WebUI API health summary used by ``SDWebUIClient.check_api_ready``.

There is no port discovery here: the configured endpoint is the only endpoint (alternate ports are never probed).
Readiness waiting lives in ``src.api.healthcheck``; launching lives in the process managers.
"""

import requests


def validate_webui_health(api_url: str) -> dict:
    """
    Perform comprehensive health check on WebUI API.

    Args:
        api_url: WebUI API URL

    Returns:
        Dictionary with health check results
    """
    health_status = {
        "url": api_url,
        "accessible": False,
        "models_loaded": False,
        "samplers_available": False,
        "errors": [],
    }

    try:
        # Basic connectivity
        response = requests.get(f"{api_url}/sdapi/v1/sd-models", timeout=5)
        if response.status_code == 200:
            health_status["accessible"] = True
            models = response.json()
            health_status["models_loaded"] = len(models) > 0
            health_status["model_count"] = len(models)
        else:
            health_status["errors"].append(f"Models endpoint returned {response.status_code}")

    except requests.exceptions.ConnectionError:
        health_status["errors"].append("Connection refused - WebUI not running")
    except requests.exceptions.Timeout:
        health_status["errors"].append("Connection timeout - WebUI may be starting up")
    except Exception as e:
        health_status["errors"].append(f"Unexpected error: {e}")

    try:
        # Samplers check
        if health_status["accessible"]:
            response = requests.get(f"{api_url}/sdapi/v1/samplers", timeout=5)
            if response.status_code == 200:
                samplers = response.json()
                health_status["samplers_available"] = len(samplers) > 0
                health_status["sampler_count"] = len(samplers)

    except Exception as e:
        health_status["errors"].append(f"Samplers check failed: {e}")

    return health_status
