from unittest import mock

from src.controller.queue_execution_controller import QueueExecutionController
from src.queue.job_model import JobStatus


def test_queue_execution_controller_proxies_calls():
    executor = mock.Mock()
    controller = QueueExecutionController(job_controller=executor)

    controller.submit(lambda: None)
    controller.cancel("job-1")
    controller.observe("k", lambda *_: None)
    controller.clear_observer("k")

    executor.submit_pipeline_run.assert_called_once()
    executor.cancel_job.assert_called_once_with("job-1")
    executor.set_status_callback.assert_called_once()
    executor.clear_status_callback.assert_called_once_with("k")


def test_queue_execution_controller_status_callbacks_and_cancel():
    executor = mock.Mock()
    saved_callback = {}

    def capture(key, cb):
        saved_callback["cb"] = cb

    executor.set_status_callback.side_effect = capture
    controller = QueueExecutionController(job_controller=executor)
    controller.register_status_callback("k", lambda *_: None)
    assert "cb" in saved_callback

    controller.cancel_job("abc")
    executor.cancel_job.assert_called_with("abc")
