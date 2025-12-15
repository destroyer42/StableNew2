import time
from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.queue.job_queue import JobQueue


class DummyPipelineController:
    def __init__(self):
        self.enqueued = 0

    def enqueue_draft_jobs(self, run_config=None):
        self.enqueued += 1
        return 1


def test_add_to_queue_does_not_block_and_enqueues():
    scheduled = []

    def ui_scheduler(fn):
        scheduled.append(fn)
        fn()

    job_service = JobService(JobQueue())
    pipeline_controller = DummyPipelineController()
    controller = AppController(main_window=None, job_service=job_service, pipeline_controller=pipeline_controller, ui_scheduler=ui_scheduler, threaded=False)

    start = time.time()
    controller.on_add_job_to_queue_v2()
    duration = time.time() - start

    assert duration < 2.0, "Add-to-Queue handler took too long"
    assert pipeline_controller.enqueued == 1
    assert len(scheduled) >= 0
