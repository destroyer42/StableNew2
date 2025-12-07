# NOTE: WebUI readiness checks have moved to src.api.healthcheck.wait_for_webui_ready.
# This module is kept only as a compatibility shim and is a candidate for archive/.

from src.api.healthcheck import wait_for_webui_ready  # use the new unified contract
# --- Compatibility shim class for GUI code expecting a service object ---


# --- Compatibility shim class for GUI code expecting a service object ---

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

# --- Compatibility shim class for GUI code expecting a service object ---


class WebUIDiscovery:
    def __init__(
        self, base_url: str = "http://127.0.0.1", start_port: int = 7860, max_attempts: int = 5
    ):
        self.base_url = base_url
        self.start_port = start_port
        self.max_attempts = max_attempts

    def discover(self, timeout: tuple[float, float] | None = (1.5, 6.0)) -> dict:
        """
        Try to locate the WebUI API and return a dict compatible with GUI expectations.
        Returns a dict with keys:
          - url (str|None)
          - accessible (bool)
          - models_loaded (bool)
          - samplers_available (bool)
          - errors (list[str])
          - model_count (int, optional)
          - sampler_count (int, optional)
        """
        url = find_webui_api_port(self.base_url, self.start_port, self.max_attempts)
        if not url:
            return {
                "url": None,
                "accessible": False,
                "models_loaded": False,
                "samplers_available": False,
                "errors": [
                    f"WebUI not found on ports {self.start_port}-{self.start_port + self.max_attempts - 1}"
                ],
            }

        # Optionally tighten requests' per-call timeouts by overriding requests.Session defaults,
        # but for now just rely on validate_webui_health() internal timeouts.
        health = validate_webui_health(url)
        health["url"] = url  # ensure url is always present
        return health

    def ensure_ready(self, api_url: str, max_wait_seconds: int = 60) -> bool:
        """Block until the API reports a loaded model (or timeout)."""
        # delegate to the canonical healthcheck; keep legacy arg name for callers
        return wait_for_webui_ready(api_url, timeout=max_wait_seconds)

    def launch_if_needed(self, webui_path: Path, wait_time: int = 10) -> bool:
        """Try to launch WebUI if not already running; returns True if available."""
        # If already up, cheap exit:
        existing = find_webui_api_port(self.base_url, self.start_port, self.max_attempts)
        if existing:
            logger.info(f"WebUI already running at {existing}")
            return True
        return launch_webui_safely(webui_path, timeout=wait_time)


"""Utility functions for WebUI API discovery"""

import logging
import subprocess
import time
from pathlib import Path

import requests
from src.utils.logging_helpers_v2 import build_run_session_id, format_launch_message

logger = logging.getLogger(__name__)


def _normalize_candidate_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "http://127.0.0.1:7860"
    if value.isdigit():
        return f"http://127.0.0.1:{value}"
    if value.startswith(":"):
        return f"http://127.0.0.1{value}"
    if value.startswith(("http://", "https://")):
        return value.rstrip("/")
    if value.startswith("://"):
        return f"http{value}".rstrip("/")
    return f"http://{value}".rstrip("/")


def _probe_api(url: str, timeout: float = 5.0) -> bool:
    try:
        response = requests.get(f"{url.rstrip('/')}/sdapi/v1/sd-models", timeout=timeout)
        return response.status_code == 200
    except Exception:
        return False


def find_webui_api_port(
    base_url: str = "http://127.0.0.1", start_port: int = 7860, max_attempts: int = 5
) -> str | None:
    """
    Find the actual port where WebUI API is running.

    WebUI auto-increments ports when 7860 is busy, so this tries common ports.

    Args:
        base_url: Base URL without port
        start_port: Starting port to check (default: 7860)
        max_attempts: Maximum number of ports to try

    Returns:
        Full URL of working API or None if not found
    """
    override = os.getenv("STABLENEW_WEBUI_BASE_URL")
    if override:
        candidate = _normalize_candidate_url(override)
        if _probe_api(candidate):
            logger.info("Using STABLENEW_WEBUI_BASE_URL=%s", candidate)
            return candidate
        logger.warning("STABLENEW_WEBUI_BASE_URL unreachable: %s", candidate)

    base = (base_url or "http://127.0.0.1").rstrip("/")

    for i in range(max_attempts):
        port = start_port + i
        test_url = f"{base}:{port}"

        try:
            # Quick health check
            response = requests.get(f"{test_url}/sdapi/v1/sd-models", timeout=5)
            if response.status_code == 200:
                logger.info(f"Found WebUI API at {test_url}")
                return test_url
        except Exception:
            continue

    logger.warning(
        f"Could not find WebUI API on ports {start_port}-{start_port + max_attempts - 1}"
    )
    return None


def _wait_for_webui_ready_legacy(api_url: str, max_wait_seconds: int = 60) -> bool:
    """Legacy helper – kept only for reference; no longer used at runtime."""
    # ...legacy implementation...


def launch_webui_safely(webui_path: Path, timeout: int = 60) -> bool:
    """
    Launch the Stable Diffusion WebUI if the executable exists.
    Returns True if the process was started (or already running), False otherwise.
    """
    logger = logging.getLogger(__name__)

    if not webui_path.exists():
        logger.warning("WebUI path does not exist: %s", webui_path)
        return False

    try:
        existing_url = find_webui_api_port()
        if existing_url:
            logger.info("WebUI already running at %s", existing_url)
            return True

        cmd = [str(webui_path)]
        cwd = str(webui_path.parent)
        creationflags = 0
        if sys.platform.startswith("win"):
            creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)

        run_session_id = build_run_session_id()
        logger.info("Launching WebUI via %s (cwd=%s)", cmd, cwd)
        process = subprocess.Popen(cmd, cwd=cwd, creationflags=creationflags)
        launch_msg = format_launch_message(
            run_session_id=run_session_id,
            pid=getattr(process, "pid", None),
            command=cmd,
            cwd=cwd,
        )
        logger.info(launch_msg)

        # Give the launcher a brief head start; readiness is probed elsewhere.
        time.sleep(min(max(timeout, 1), 5))
        return True

    except Exception as e:
        logger.exception("Failed to launch WebUI: %s", e)
        return False


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


if __name__ == "__main__":
    info = WebUIDiscovery().discover()
    print("Discover:", info)
