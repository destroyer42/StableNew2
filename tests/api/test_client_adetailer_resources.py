"""
Test ADetailer resource retrieval methods in SDWebUIClient.

Covers:
- get_adetailer_models() parsing and fallback
- get_adetailer_detectors() delegation to models
- Regression prevention for dropdown population
"""

from __future__ import annotations

import requests_mock

from src.api.client import SDWebUIClient

API_BASE_URL = "http://127.0.0.1:7860"


class TestADetailerResources:
    """Test suite for ADetailer model/detector resource methods."""

    def setup_method(self):
        """Setup for each test."""
        self.client = SDWebUIClient(base_url=API_BASE_URL)

    def test_get_adetailer_models_from_scripts_api(self):
        """Test successful retrieval of ADetailer models from scripts API."""
        mock_response = {
            "txt2img": [
                {
                    "name": "ADetailer",
                    "args": [
                        {
                            "label": "ADetailer model",
                            "choices": [
                                "face_yolov8n.pt",
                                "face_yolov8s.pt",
                                "hand_yolov8n.pt",
                                "hand_yolov8s.pt",
                                "person_yolov8n-seg.pt",
                                "person_yolov8s-seg.pt",
                                "mediapipe_face_full",
                                "mediapipe_face_short",
                            ],
                        }
                    ],
                }
            ]
        }

        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/scripts", json=mock_response)
            models = self.client.get_adetailer_models()

        assert len(models) == 8
        assert "face_yolov8n.pt" in models
        assert "hand_yolov8s.pt" in models
        assert "mediapipe_face_full" in models

    def test_get_adetailer_models_finds_choices_without_label(self):
        """Test that model detection works even if 'label' doesn't contain 'model'."""
        mock_response = {
            "txt2img": [
                {
                    "name": "ADetailer",
                    "args": [
                        {
                            "choices": [
                                "face_yolov8n.pt",
                                "hand_yolov8n.pt",
                                "person_yolov8s.pt",
                                "mediapipe_face_mesh",
                            ]
                        }
                    ],
                }
            ]
        }

        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/scripts", json=mock_response)
            models = self.client.get_adetailer_models()

        assert len(models) == 4
        assert "face_yolov8n.pt" in models
        assert "mediapipe_face_mesh" in models

    def test_get_adetailer_models_fallback_on_api_failure(self):
        """Test fallback to default models when API is unavailable."""
        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/scripts", status_code=500)
            models = self.client.get_adetailer_models()

        # Should return comprehensive default list
        assert len(models) == 10
        assert "face_yolov8n.pt" in models
        assert "face_yolov8s.pt" in models
        assert "hand_yolov8n.pt" in models
        assert "hand_yolov8s.pt" in models
        assert "person_yolov8n-seg.pt" in models
        assert "person_yolov8s-seg.pt" in models
        assert "mediapipe_face_full" in models
        assert "mediapipe_face_short" in models
        assert "mediapipe_face_mesh" in models
        assert "mediapipe_face_mesh_eyes_only" in models

    def test_get_adetailer_models_fallback_on_connection_error(self):
        """Test fallback when connection fails."""
        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/scripts", exc=ConnectionError("No connection"))
            models = self.client.get_adetailer_models()

        assert len(models) == 10
        assert "face_yolov8n.pt" in models

    def test_get_adetailer_models_fallback_on_empty_response(self):
        """Test fallback when API returns no ADetailer script."""
        mock_response = {"txt2img": [{"name": "SomeOtherScript", "args": []}]}

        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/scripts", json=mock_response)
            models = self.client.get_adetailer_models()

        # Should use defaults since ADetailer not found
        assert len(models) == 10

    def test_get_adetailer_models_ignores_short_choice_lists(self):
        """Test that sanity check ignores suspiciously short choice lists."""
        mock_response = {
            "txt2img": [
                {
                    "name": "ADetailer",
                    "args": [
                        {"label": "Some setting", "choices": ["yes", "no"]},  # Only 2 items
                        {
                            "label": "ADetailer model",
                            "choices": [
                                "face_yolov8n.pt",
                                "hand_yolov8n.pt",
                                "person_yolov8s.pt",
                                "mediapipe_face_full",
                            ],
                        },
                    ],
                }
            ]
        }

        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/scripts", json=mock_response)
            models = self.client.get_adetailer_models()

        # Should get the 4-item list, not the 2-item list
        assert len(models) == 4
        assert "face_yolov8n.pt" in models

    def test_get_adetailer_detectors_returns_same_as_models(self):
        """Test that detectors method returns same list as models (no separate detector list)."""
        mock_response = {
            "txt2img": [
                {
                    "name": "ADetailer",
                    "args": [
                        {
                            "choices": [
                                "face_yolov8n.pt",
                                "face_yolov8s.pt",
                                "hand_yolov8n.pt",
                                "hand_yolov8s.pt",
                                "person_yolov8n-seg.pt",  # Need >3 for sanity check
                                "mediapipe_face_mesh",
                            ]
                        }
                    ],
                }
            ]
        }

        with requests_mock.Mocker() as m:
            # Mock it twice since get_adetailer_detectors calls get_adetailer_models internally
            m.get(f"{API_BASE_URL}/sdapi/v1/scripts", json=mock_response)
            models = self.client.get_adetailer_models()

            # Reset mocker for second call
            m.get(f"{API_BASE_URL}/sdapi/v1/scripts", json=mock_response)
            detectors = self.client.get_adetailer_detectors()

        # Both should return identical lists
        assert len(models) == 6
        assert len(detectors) == 6
        assert models == detectors
        assert "face_yolov8n.pt" in detectors
        assert "hand_yolov8n.pt" in detectors
        assert "mediapipe_face_mesh" in detectors

    def test_get_adetailer_detectors_fallback(self):
        """Test that detectors use same fallback as models."""
        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/scripts", status_code=404)
            detectors = self.client.get_adetailer_detectors()

        # Should return same 10-item default list as models
        assert len(detectors) == 10
        assert "face_yolov8n.pt" in detectors
        assert "mediapipe_face_full" in detectors


class TestADetailerResourcesRegression:
    """Regression tests to prevent dropdown population issues."""

    def setup_method(self):
        """Setup for each test."""
        self.client = SDWebUIClient(base_url=API_BASE_URL)

    def test_regression_empty_dropdowns_prevented(self):
        """
        REGRESSION TEST: Ensure dropdowns never end up empty.
        
        Background: User reported ADetailer dropdowns showed only default 3 models
        instead of all ~10 available. This ensures we always have comprehensive defaults.
        """
        # Even with total API failure, we should get populated defaults
        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/scripts", exc=Exception("Total failure"))
            models = self.client.get_adetailer_models()

        # Must have at least 10 models
        assert len(models) >= 10
        # Must include both yolo variants
        assert any("yolo" in m for m in models)
        # Must include mediapipe variants
        assert any("mediapipe" in m for m in models)

    def test_regression_models_and_detectors_consistent(self):
        """
        REGRESSION TEST: Ensure model and detector dropdowns show same list.
        
        Background: User confusion about two dropdowns. ADetailer extension only
        uses ad_model parameter, so both dropdowns should show detection models.
        """
        mock_response = {
            "txt2img": [
                {
                    "name": "ADetailer",
                    "args": [{"choices": ["face_yolov8n.pt", "hand_yolov8n.pt"]}],
                }
            ]
        }

        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/scripts", json=mock_response)
            models = self.client.get_adetailer_models()
            detectors = self.client.get_adetailer_detectors()

        # Both should return identical lists
        assert models == detectors
