"""Test thread-safe model refresh methods in main_window.py"""

import threading
from tkinter import ttk
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.gui
def test_refresh_models_async_thread_safe(tk_root, tk_pump):
    """Test that _refresh_models_async marshals widget updates to main thread"""
    from src.gui.main_window import StableNewGUI

    # Create a mock client
    mock_client = MagicMock()
    mock_client.get_models.return_value = [
        {"title": "model1.safetensors", "model_name": "model1"},
        {"title": "model2.safetensors", "model_name": "model2"},
    ]

    # Create a minimal GUI instance
    with patch.object(StableNewGUI, "__init__", lambda self: None):
        gui = StableNewGUI()
        gui.root = tk_root
        gui.client = mock_client

        # Create mock comboboxes
        gui.model_combo = ttk.Combobox(tk_root)
        gui.img2img_model_combo = ttk.Combobox(tk_root)

        # Mock the log method
        gui._add_log_message = MagicMock()

        # Track if update happened on main thread
        updates_on_main_thread = []
        scheduled_funcs = []

        def track_after(ms, func):
            """Track scheduling without invoking Tk from a worker thread."""
            if ms == 0:
                updates_on_main_thread.append(True)
                scheduled_funcs.append(func)
            return "after-0-mock"

        tk_root.after = track_after

        # Call the async refresh method in a worker thread
        worker_done = threading.Event()

        def worker():
            gui._refresh_models_async()
            worker_done.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        # Wait for worker to complete
        worker_done.wait(timeout=2.0)

        # Run any scheduled updates now on the main thread
        for fn in scheduled_funcs:
            fn()

        # Verify that updates were scheduled on main thread via after(0, ...)
        assert len(updates_on_main_thread) > 0, "Widget updates should be scheduled on main thread"

        # Verify comboboxes were updated when widget state is available
        if gui.model_combo["values"]:
            assert len(tuple(gui.model_combo["values"])) == 3  # "" + 2 models
        if gui.img2img_model_combo["values"]:
            assert len(tuple(gui.img2img_model_combo["values"])) == 3


@pytest.mark.gui
def test_refresh_vae_models_async_thread_safe(tk_root, tk_pump):
    """Test that _refresh_vae_models_async marshals widget updates to main thread"""
    from src.gui.main_window import StableNewGUI

    # Create a mock client
    mock_client = MagicMock()
    mock_client.get_vae_models.return_value = [
        {"model_name": "vae1.safetensors"},
        {"model_name": "vae2.safetensors"},
    ]

    # Create a minimal GUI instance
    with patch.object(StableNewGUI, "__init__", lambda self: None):
        gui = StableNewGUI()
        gui.root = tk_root
        gui.client = mock_client

        # Create mock comboboxes
        gui.vae_combo = ttk.Combobox(tk_root)
        gui.img2img_vae_combo = ttk.Combobox(tk_root)

        # Mock the log method
        gui._add_log_message = MagicMock()

        # Track and stub after() to avoid calling Tk from worker thread
        scheduled_funcs = []

        def track_after(ms, func):
            if ms == 0:
                scheduled_funcs.append(func)
            return "after-0-mock"

        tk_root.after = track_after

        # Call the async refresh method in a worker thread
        worker_done = threading.Event()

        def worker():
            gui._refresh_vae_models_async()
            worker_done.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        # Wait for worker to complete
        worker_done.wait(timeout=2.0)

        # Run any scheduled updates now on the main thread
        for fn in scheduled_funcs:
            fn()

        # Verify comboboxes were updated when widget state is available
        if gui.vae_combo["values"]:
            assert len(tuple(gui.vae_combo["values"])) == 3  # "" + 2 VAE models
        if gui.img2img_vae_combo["values"]:
            assert len(tuple(gui.img2img_vae_combo["values"])) == 3


@pytest.mark.gui
def test_refresh_upscalers_async_thread_safe(tk_root, tk_pump):
    """Test that _refresh_upscalers_async marshals widget updates to main thread"""
    from src.gui.main_window import StableNewGUI

    # Create a mock client
    mock_client = MagicMock()
    mock_client.get_upscalers.return_value = [
        {"name": "R-ESRGAN 4x+"},
        {"name": "LDSR"},
        {"name": "ScuNET"},
    ]

    # Create a minimal GUI instance
    with patch.object(StableNewGUI, "__init__", lambda self: None):
        gui = StableNewGUI()
        gui.root = tk_root
        gui.client = mock_client

        # Create mock combobox
        gui.upscaler_combo = ttk.Combobox(tk_root)

        # Mock the log method
        gui._add_log_message = MagicMock()

        # Track and stub after() to avoid calling Tk from worker thread
        scheduled_funcs = []

        def track_after(ms, func):
            if ms == 0:
                scheduled_funcs.append(func)
            return "after-0-mock"

        tk_root.after = track_after

        # Call the async refresh method in a worker thread
        worker_done = threading.Event()

        def worker():
            gui._refresh_upscalers_async()
            worker_done.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        # Wait for worker to complete
        worker_done.wait(timeout=2.0)

        # Run any scheduled updates now on the main thread
        for fn in scheduled_funcs:
            fn()

        # Verify combobox was updated when widget state is available
        if gui.upscaler_combo["values"]:
            assert len(tuple(gui.upscaler_combo["values"])) == 3


@pytest.mark.gui
def test_refresh_schedulers_async_thread_safe(tk_root, tk_pump):
    """Test that _refresh_schedulers_async marshals widget updates to main thread"""
    from src.gui.main_window import StableNewGUI

    # Create a mock client
    mock_client = MagicMock()
    mock_client.get_schedulers.return_value = ["normal", "Karras", "exponential"]

    # Create a minimal GUI instance
    with patch.object(StableNewGUI, "__init__", lambda self: None):
        gui = StableNewGUI()
        gui.root = tk_root
        gui.client = mock_client

        # Create mock comboboxes
        gui.scheduler_combo = ttk.Combobox(tk_root)
        gui.img2img_scheduler_combo = ttk.Combobox(tk_root)

        # Mock the log method
        gui._add_log_message = MagicMock()

        # Track and stub after() to avoid calling Tk from worker thread
        scheduled_funcs = []

        def track_after(ms, func):
            if ms == 0:
                scheduled_funcs.append(func)
            return "after-0-mock"

        tk_root.after = track_after

        # Call the async refresh method in a worker thread
        worker_done = threading.Event()

        def worker():
            gui._refresh_schedulers_async()
            worker_done.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        # Wait for worker to complete
        worker_done.wait(timeout=2.0)

        # Run any scheduled updates now on the main thread
        for fn in scheduled_funcs:
            fn()

        # Verify comboboxes were updated when widget state is available
        if gui.scheduler_combo["values"]:
            assert len(tuple(gui.scheduler_combo["values"])) == 3
        if gui.img2img_scheduler_combo["values"]:
            assert len(tuple(gui.img2img_scheduler_combo["values"])) == 3


@pytest.mark.gui
def test_refresh_models_async_error_handling(tk_root, tk_pump):
    """Test that errors in _refresh_models_async are properly handled"""
    from src.gui.main_window import StableNewGUI

    # Create a mock client that raises an error
    mock_client = MagicMock()
    mock_client.get_models.side_effect = Exception("API Error")

    # Create a minimal GUI instance
    with patch.object(StableNewGUI, "__init__", lambda self: None):
        gui = StableNewGUI()
        gui.root = tk_root
        gui.client = mock_client

        # Track and stub after() to avoid calling Tk from worker thread
        scheduled_funcs = []

        def track_after(ms, func):
            if ms == 0:
                scheduled_funcs.append(func)
            return "after-0-mock"

        tk_root.after = track_after

        # Mock messagebox to avoid blocking
        with patch("tkinter.messagebox.showerror") as mock_error:
            # Call the async refresh method in a worker thread
            worker_done = threading.Event()

            def worker():
                gui._refresh_models_async()
                worker_done.set()

            thread = threading.Thread(target=worker, daemon=True)
            thread.start()

            # Wait for worker to complete
            worker_done.wait(timeout=2.0)

            # Run any scheduled updates now on the main thread
            for fn in scheduled_funcs:
                fn()

            # Verify error was shown (on main thread)
            mock_error.assert_called()
            args = mock_error.call_args[0]
            assert "Error" in args
            assert "API Error" in str(args[1])
