import threading

from src.controller.app_controller import AppController
from src.controller.job_service import JobService


class StubJobService:
    def __init__(self):
        self.callbacks = {}
        self.status_callbacks = {}

    def register_callback(self, event: str, cb):
        self.callbacks[event] = cb

    def set_status_callback(self, name: str, cb):
        self.status_callbacks[name] = cb


def test_event_marshaling():
    scheduled = []
    main_thread_id = threading.get_ident()
    stub = StubJobService()

    ac = AppController(
        main_window=None,
        job_service=stub,
        ui_scheduler=lambda fn: scheduled.append(fn),
        threaded=False,
    )

    ran = {"flag": False, "thread": None}

    def handler(job):
        ran["flag"] = True
        ran["thread"] = threading.get_ident()

    # Patch the controller handler and re-register wrappers
    ac._on_job_started = handler
    ac._setup_queue_callbacks()

    cb = stub.callbacks.get(JobService.EVENT_JOB_STARTED)
    assert cb is not None

    def invoke():
        cb("job-123")

    t = threading.Thread(target=invoke)
    t.start()
    t.join()

    # Handler should not have run inline from background thread
    assert not ran["flag"]
    assert len(scheduled) == 1

    # Execute scheduled callable on main thread
    scheduled[0]()

    assert ran["flag"]
    assert ran["thread"] == main_thread_id


def test_status_callback_marshaling():
    scheduled = []
    main_thread_id = threading.get_ident()
    stub = StubJobService()

    ac = AppController(
        main_window=None,
        job_service=stub,
        ui_scheduler=lambda fn: scheduled.append(fn),
        threaded=False,
    )

    ran = {"flag": False, "thread": None}

    def status_cb(name, status):
        ran["flag"] = True
        ran["thread"] = threading.get_ident()

    ac._on_job_status_for_panels = status_cb
    ac._setup_queue_callbacks()

    cb = stub.status_callbacks.get("gui_queue_history")
    assert cb is not None

    def invoke():
        cb("gui_queue_history", {"some": "status"})

    t = threading.Thread(target=invoke)
    t.start()
    t.join()

    assert not ran["flag"]
    assert len(scheduled) == 1

    scheduled[0]()

    assert ran["flag"]
    assert ran["thread"] == main_thread_id
