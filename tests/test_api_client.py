"""Test API client functionality"""

from unittest.mock import MagicMock

import requests
import requests_mock

from src.api.client import SDWebUIClient
from src.api.types import GenerateErrorCode

API_BASE_URL = "http://127.0.0.1:7860"


class TestSDWebUIClient:
    """Test suite for the SD WebUI API client"""

    def setup_method(self):
        """Setup for each test"""
        self.client = SDWebUIClient()
        self.client.set_options_write_enabled(True)

    def test_init(self):
        """Test client initialization"""
        assert self.client.base_url == API_BASE_URL

    def test_check_api_ready_success(self):
        """Test successful API readiness check"""
        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/sd-models", json=[{"title": "model1.safetensors"}])
            assert self.client.check_api_ready() is True

    def test_check_api_ready_failure(self):
        """Test failed API readiness check (retry waits are faked; policy tests own backoff)"""
        self.client._sleep = MagicMock()
        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/sd-models", exc=requests.exceptions.ConnectTimeout)
            assert self.client.check_api_ready() is False
        # the retry-safe GET still backed off between attempts; only the real wait is removed
        self.client._sleep.assert_called()

    def test_txt2img_success(self):
        """Test successful txt2img call"""
        with requests_mock.Mocker() as m:
            m.post(f"{API_BASE_URL}/sdapi/v1/txt2img", json={"images": ["test_image_base64"]})
            response = self.client.txt2img({})
            assert response is not None
            assert "images" in response

    def test_txt2img_failure(self):
        """Test failed txt2img call"""
        with requests_mock.Mocker() as m:
            m.post(f"{API_BASE_URL}/sdapi/v1/txt2img", status_code=500)
            response = self.client.txt2img({})
            assert response is None

    def test_img2img_success(self):
        """Test successful img2img call"""
        with requests_mock.Mocker() as m:
            m.post(f"{API_BASE_URL}/sdapi/v1/img2img", json={"images": ["test_image_base64"]})
            response = self.client.img2img({})
            assert response is not None
            assert "images" in response

    def test_upscale_success(self):
        """Test successful upscale call"""
        with requests_mock.Mocker() as m:
            m.post(
                f"{API_BASE_URL}/sdapi/v1/extra-single-image",
                json={"image": "upscaled_image_base64"},
            )
            response = self.client.upscale_image("dummy_base64", "R-ESRGAN 4x+", 2.0)
            assert response is not None
            assert "image" in response

    def test_get_models_success(self):
        """Test successful get_models call"""
        with requests_mock.Mocker() as m:
            m.get(
                f"{API_BASE_URL}/sdapi/v1/sd-models",
                json=[{"title": "model1"}, {"title": "model2"}],
            )
            models = self.client.get_models()
            assert [m["title"] for m in models] == ["model1", "model2"]

    def test_get_models_failure_enters_short_cooldown(self):
        """Repeated callers should not re-hit sd-models immediately after a hard failure."""
        self.client._request_context = MagicMock()
        failure_ctx = MagicMock()
        failure_ctx.__enter__.return_value = None
        failure_ctx.__exit__.return_value = None
        self.client._request_context.return_value = failure_ctx

        first = self.client.get_models()
        second = self.client.get_models()

        assert first == []
        assert second == []
        self.client._request_context.assert_called_once()

    def test_get_models_skips_requests_during_startup_probe_grace(self):
        self.client._request_context = MagicMock()
        self.client.set_startup_probe_grace(15.0)

        models = self.client.get_models()

        assert models == []
        self.client._request_context.assert_not_called()

    def test_get_vae_models_failure_enters_short_cooldown(self):
        """Repeated callers should not re-hit sd-vae immediately after a hard failure."""
        self.client._request_context = MagicMock()
        failure_ctx = MagicMock()
        failure_ctx.__enter__.return_value = None
        failure_ctx.__exit__.return_value = None
        self.client._request_context.return_value = failure_ctx

        first = self.client.get_vae_models()
        second = self.client.get_vae_models()

        assert first == []
        assert second == []
        self.client._request_context.assert_called_once()

    def test_get_vae_models_skips_requests_during_startup_probe_grace(self):
        self.client._request_context = MagicMock()
        self.client.set_startup_probe_grace(15.0)

        vaes = self.client.get_vae_models()

        assert vaes == []
        self.client._request_context.assert_not_called()

    def test_set_startup_probe_grace_does_not_shrink_existing_window(self):
        self.client.set_startup_probe_grace(30.0)
        original_until = self.client._startup_probe_grace_until

        self.client.set_startup_probe_grace(5.0)

        assert self.client._startup_probe_grace_until >= original_until

    def test_get_current_model_success(self):
        """Test successful get_current_model call"""
        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/options", json={"sd_model_checkpoint": "current_model"})
            model = self.client.get_current_model()
            assert model == "current_model"

    def test_reset_stale_progress_state_interrupts_until_idle(self):
        self.client.interrupt = MagicMock(return_value=True)
        self.client.get_progress_snapshot = MagicMock(
            side_effect=[
                {"progress": 1.0, "state": {"job": "txt2img"}},
                {"progress": 0.0, "state": {}},
            ]
        )
        self.client._sleep = MagicMock()

        assert self.client.reset_stale_progress_state(timeout_s=2.0, poll_interval_s=0.1) is True
        self.client.interrupt.assert_called_once()

    def test_reset_stale_progress_state_returns_false_when_interrupt_rejected(self):
        self.client.interrupt = MagicMock(return_value=False)
        self.client.get_progress_snapshot = MagicMock()

        assert self.client.reset_stale_progress_state(timeout_s=1.0, poll_interval_s=0.1) is False
        self.client.get_progress_snapshot.assert_not_called()

    def test_get_options_success(self):
        """Ensure get_options returns parsed dict."""
        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/options", json={"jpeg_quality": 80})
            opts = self.client.get_options()
            assert opts["jpeg_quality"] == 80

    def test_update_options_posts_payload(self):
        """Ensure update_options POSTs with the provided payload."""
        with requests_mock.Mocker() as m:
            m.post(f"{API_BASE_URL}/sdapi/v1/options", json={"ok": True})
            payload = {"jpeg_quality": 90}
            updated = self.client.update_options(payload)
            assert updated["ok"] is True
            assert m.last_request.json() == payload

    def _upscale_defaults_client(self) -> SDWebUIClient:
        client = SDWebUIClient()
        client.set_options_write_enabled(True)
        client._sleep = MagicMock()  # retry backoff is not under test
        return client

    @staticmethod
    def _options_posts(mocker: requests_mock.Mocker) -> list:
        return [
            r
            for r in mocker.request_history
            if r.method == "POST" and r.path == "/sdapi/v1/options"
        ]

    def test_apply_upscale_performance_defaults_posts_all_options_when_advertised(self):
        """A WebUI that advertises every option receives the full conservative payload once."""
        client = self._upscale_defaults_client()
        with requests_mock.Mocker() as m:
            m.get(
                f"{API_BASE_URL}/sdapi/v1/options",
                json={
                    "img_max_size_mp": 200,
                    "ESRGAN_tile": 192,
                    "ESRGAN_tile_overlap": 8,
                    "DAT_tile": 192,
                    "DAT_tile_overlap": 8,
                    "upscaling_max_images_in_cache": 5,
                },
            )
            m.post(f"{API_BASE_URL}/sdapi/v1/options", json={})

            outcome = client.apply_upscale_performance_defaults()

            posts = self._options_posts(m)
            assert len(posts) == 1
            assert posts[0].json() == {
                "img_max_size_mp": 8.0,
                "ESRGAN_tile": 768,
                "ESRGAN_tile_overlap": 64,
                "DAT_tile": 768,
                "DAT_tile_overlap": 64,
                "upscaling_max_images_in_cache": 4,
            }
        assert set(outcome.applied) == set(posts[0].json())
        assert outcome.unsupported == ()
        assert outcome.skipped_reason is None and outcome.error is None

    def test_apply_upscale_performance_defaults_omits_options_the_webui_does_not_advertise(self):
        """Forge answers an unknown option key with HTTP 500 and rejects the write; send none."""
        client = self._upscale_defaults_client()
        with requests_mock.Mocker() as m:
            m.get(
                f"{API_BASE_URL}/sdapi/v1/options",
                json={
                    "img_max_size_mp": 200,
                    "ESRGAN_tile": 192,
                    "ESRGAN_tile_overlap": 8,
                    "upscaling_max_images_in_cache": 5,
                    "jpeg_quality": 80,
                },
            )
            m.post(f"{API_BASE_URL}/sdapi/v1/options", json={})

            outcome = client.apply_upscale_performance_defaults()

            posts = self._options_posts(m)
            assert len(posts) == 1
            assert posts[0].json() == {
                "img_max_size_mp": 8.0,
                "ESRGAN_tile": 768,
                "ESRGAN_tile_overlap": 64,
                "upscaling_max_images_in_cache": 4,
            }
        assert set(outcome.applied) == {
            "img_max_size_mp",
            "ESRGAN_tile",
            "ESRGAN_tile_overlap",
            "upscaling_max_images_in_cache",
        }
        assert set(outcome.unsupported) == {"DAT_tile", "DAT_tile_overlap"}
        assert outcome.error is None

    def test_apply_upscale_performance_defaults_skips_write_when_nothing_is_advertised(self):
        client = self._upscale_defaults_client()
        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/options", json={"jpeg_quality": 80})
            post_mock = m.post(f"{API_BASE_URL}/sdapi/v1/options", json={})

            outcome = client.apply_upscale_performance_defaults()

            assert post_mock.called is False
        assert outcome.applied == ()
        assert outcome.skipped_reason == "no_supported_options"
        assert set(outcome.unsupported) == {
            "img_max_size_mp",
            "ESRGAN_tile",
            "ESRGAN_tile_overlap",
            "DAT_tile",
            "DAT_tile_overlap",
            "upscaling_max_images_in_cache",
        }

    def test_apply_upscale_performance_defaults_does_not_write_blind_when_options_unreadable(self):
        """An unreadable options listing is not "everything unsupported" and is not cached."""
        client = self._upscale_defaults_client()
        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/options", status_code=500, text="boom")
            post_mock = m.post(f"{API_BASE_URL}/sdapi/v1/options", json={})

            outcome = client.apply_upscale_performance_defaults()

            assert post_mock.called is False
        assert outcome.applied == ()
        assert outcome.error

        # the failure must not poison later reads: a healthy listing is picked up afresh
        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/options", json={"ESRGAN_tile": 192})
            m.post(f"{API_BASE_URL}/sdapi/v1/options", json={})
            client._last_options_post_ts = float("-inf")  # the interval throttle is not under test

            outcome = client.apply_upscale_performance_defaults()

            assert self._options_posts(m)[0].json() == {"ESRGAN_tile": 768}
        assert outcome.applied == ("ESRGAN_tile",)

    def test_apply_upscale_performance_defaults_reports_a_rejected_write_without_raising(self):
        client = self._upscale_defaults_client()
        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/options", json={"ESRGAN_tile": 192})
            m.post(f"{API_BASE_URL}/sdapi/v1/options", status_code=500, text="KeyError")

            outcome = client.apply_upscale_performance_defaults()

        assert outcome.applied == ()
        assert outcome.error
        assert outcome.skipped_reason is None

    def test_apply_upscale_performance_defaults_is_silent_in_safe_mode(self):
        client = self._upscale_defaults_client()
        client.set_options_write_enabled(False)
        with requests_mock.Mocker() as m:
            outcome = client.apply_upscale_performance_defaults()

            assert m.request_history == []
        assert outcome.applied == ()
        assert outcome.skipped_reason == "safe_mode"

    def test_ensure_safe_upscale_defaults_clamps_values(self):
        """ensure_safe_upscale_defaults should clamp oversized values and POST payload."""
        client = SDWebUIClient()
        client.set_options_write_enabled(True)

        with requests_mock.Mocker() as m:
            m.get(
                f"{API_BASE_URL}/sdapi/v1/options",
                json={
                    "img_max_size_mp": 32,
                    "ESRGAN_tile": 2048,
                    "ESRGAN_tile_overlap": 160,
                    "DAT_tile": 1024,
                    "DAT_tile_overlap": 64,
                },
            )
            m.post(f"{API_BASE_URL}/sdapi/v1/options", json={"ok": True})

            client.ensure_safe_upscale_defaults(max_img_mp=8.0, max_tile=768, max_overlap=128)

            payload = m.last_request.json()
            assert payload["img_max_size_mp"] == 8.0
            assert payload["ESRGAN_tile"] == 768
            assert payload["ESRGAN_tile_overlap"] == 128
            assert payload["DAT_tile"] == 768
            assert "DAT_tile_overlap" not in payload, "values within limits should stay untouched"

    def test_ensure_safe_upscale_defaults_no_changes_skips_post(self):
        """When values already safe, ensure_safe_upscale_defaults should not POST."""
        client = SDWebUIClient()
        client.set_options_write_enabled(True)

        with requests_mock.Mocker() as m:
            m.get(
                f"{API_BASE_URL}/sdapi/v1/options",
                json={
                    "img_max_size_mp": 4.0,
                    "ESRGAN_tile": 512,
                    "ESRGAN_tile_overlap": 64,
                    "DAT_tile": 640,
                    "DAT_tile_overlap": 32,
                },
            )
            post_mock = m.post(f"{API_BASE_URL}/sdapi/v1/options", json={"ok": True})

            client.ensure_safe_upscale_defaults(max_img_mp=8.0, max_tile=768, max_overlap=128)

            assert post_mock.called is False

    def test_free_vram_skips_refresh_checkpoints_by_default(self):
        """Default VRAM cleanup must not block on refresh-checkpoints."""
        client = SDWebUIClient()
        client._request_context = MagicMock()

        assert client.free_vram(unload_model=False, force_gc=False) is False
        client._request_context.assert_not_called()

    def test_free_vram_refresh_checkpoints_is_explicit_and_single_attempt(self):
        """Aggressive checkpoint refresh should be opt-in and bounded."""
        client = SDWebUIClient()
        context = MagicMock()
        context.__enter__.return_value = object()
        context.__exit__.return_value = None
        client._request_context = MagicMock(return_value=context)

        assert (
            client.free_vram(
                unload_model=False,
                force_gc=False,
                refresh_checkpoints=True,
            )
            is True
        )

        client._request_context.assert_called_once_with(
            "post",
            "/sdapi/v1/refresh-checkpoints",
            timeout=5.0,
            max_retries=1,
        )


def test_generate_images_connection_loss_on_first_post_is_outcome_unknown_not_crash_recovery():
    """A generation POST whose response is lost after dispatch is an unknown outcome.

    PR-HARDEN-008 Phase 2B / PR-HTTP-100: it is never replayed and never classified as a WebUI
    crash, so the runner's crash/connection recovery and queue-retry paths (which would replay the
    dispatched job) are not triggered; the diagnostics context still identifies the request and
    session. The lost response is the very first POST outcome; a definite HTTP error response is a
    different contract (one dispatched attempt, covered by test_http_100_definite_http_fail_fast).
    """

    client = SDWebUIClient()
    client.set_options_write_enabled(True)
    session_id = client._session_id

    with requests_mock.Mocker() as m:
        m.post(
            f"{API_BASE_URL}/sdapi/v1/txt2img",
            [
                {"exc": requests.exceptions.ConnectionError("Connection refused")},
                {"status_code": 200, "json": {"images": ["must-never-be-requested"]}},
            ],
        )

        outcome = client.generate_images(stage="txt2img", payload={})

        assert m.call_count == 1, "the lost-response POST must be dispatched once and never replayed"

    assert outcome.error is not None
    assert outcome.error.code == GenerateErrorCode.OUTCOME_UNKNOWN
    diagnostics = outcome.error.details.get("diagnostics") if outcome.error.details else None
    assert diagnostics is not None
    assert diagnostics.get("webui_unavailable") is False
    assert diagnostics.get("crash_suspected") is False
    request_summary = diagnostics.get("request_summary")
    assert request_summary is not None
    assert request_summary.get("endpoint") == "/sdapi/v1/txt2img"
    assert request_summary.get("method") == "POST"
    assert request_summary.get("session_id") == session_id
