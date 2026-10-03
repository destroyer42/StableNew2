"""The interpreter running the suite is the supported standard-GIL CPython 3.14 (PR-PY314-100)."""

from __future__ import annotations

import platform
import sys
import sysconfig

import pytest


@pytest.mark.skipif(sys.version_info[:2] != (3, 14), reason="runs under the supported 3.14 only")
def test_supported_interpreter_is_standard_gil_cpython_without_jit() -> None:
    assert platform.python_implementation() == "CPython"
    assert not sysconfig.get_config_var("Py_GIL_DISABLED")  # not the free-threaded 3.14t build
    assert sys._is_gil_enabled()
    jit = getattr(sys, "_jit", None)  # experimental JIT is never enabled by StableNew
    assert jit is None or not jit.is_enabled()
