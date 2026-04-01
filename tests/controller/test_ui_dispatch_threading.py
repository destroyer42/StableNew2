import threading

from src.controller.app_controller import AppController


def test_ui_dispatch_on_ui_thread_executes_immediately():
    called = []
    controller = AppController(main_window=None, ui_scheduler=None)
    controller._ui_thread_id = threading.get_ident()
    controller._ui_dispatch(lambda: called.append("ran"))
    assert called == ["ran"]


def test_ui_dispatch_on_background_thread_schedules():
    scheduled = []

    def fake_scheduler(fn):
        scheduled.append(fn)

    controller = AppController(main_window=None, ui_scheduler=fake_scheduler)
    controller._ui_thread_id = 12345  # fake UI thread id

    def background():
        controller._ui_dispatch(lambda: scheduled.append("scheduled"))

    t = threading.Thread(target=background)
    t.start()
    t.join()
    # The scheduler should have been called (not direct execution)
    assert any(callable(f) for f in scheduled)


def test_ui_dispatch_prefers_main_window_dispatcher_over_scheduler() -> None:
    scheduled = []
    main_window_calls = []

    def fake_scheduler(fn):
        scheduled.append(fn)

    class _MainWindow:
        def run_in_main_thread(self, cb):
            main_window_calls.append(cb)

    controller = AppController.__new__(AppController)
    controller._ui_scheduler = fake_scheduler
    controller.main_window = _MainWindow()
    controller._ui_thread_id = 12345

    def background():
        controller._ui_dispatch(lambda: main_window_calls.append("ran"))

    t = threading.Thread(target=background)
    t.start()
    t.join()

    assert len(scheduled) == 0
    assert len(main_window_calls) == 1
    assert callable(main_window_calls[0])


def test_ui_dispatch_later_prefers_main_window_dispatcher() -> None:
    scheduled = []

    class _MainWindow:
        def __init__(self) -> None:
            self.calls = []

        def run_in_main_thread_later(self, delay_ms, cb):
            self.calls.append((delay_ms, cb))

    controller = AppController.__new__(AppController)
    controller._ui_scheduler = lambda fn: scheduled.append(fn)
    controller.main_window = _MainWindow()

    controller._ui_dispatch_later(75, lambda: None)

    assert scheduled == []
    assert controller.main_window.calls
    delay_ms, cb = controller.main_window.calls[0]
    assert delay_ms == 75
    assert callable(cb)


def test_ui_dispatch_drops_callback_when_bootstrap_scheduler_rejects_cross_thread_tk_call() -> None:
    controller = AppController.__new__(AppController)
    controller.main_window = None
    controller._ui_thread_id = 12345
    controller._dispatch_via_root_after = lambda *_args, **_kwargs: False

    def _failing_scheduler(_fn):
        raise RuntimeError("main thread is not in main loop")

    controller._ui_scheduler = _failing_scheduler
    called = {"ran": False}

    def background() -> None:
        controller._ui_dispatch(lambda: called.__setitem__("ran", True))

    t = threading.Thread(target=background)
    t.start()
    t.join()

    assert called["ran"] is False
