"""Markers for tests that need the optional ``svd`` extra (NumPy / OpenCV).

``numpy`` and ``opencv-python`` are declared only in the ``svd`` extra
(``requirements-svd.txt``), not in the base ``requirements.txt`` that CI and a plain
developer install use. Offline qualification tools that decode/render video need them,
so those tests skip with an explicit reason when the capability is absent.
"""

from __future__ import annotations

import importlib.util

import pytest

requires_numpy = pytest.mark.skipif(
    importlib.util.find_spec("numpy") is None,
    reason="numpy is optional (svd extra, requirements-svd.txt)",
)
requires_cv2 = pytest.mark.skipif(
    importlib.util.find_spec("cv2") is None,
    reason="opencv-python is optional (svd extra, requirements-svd.txt)",
)
