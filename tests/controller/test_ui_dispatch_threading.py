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
