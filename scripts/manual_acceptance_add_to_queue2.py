import threading
import time
from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.queue.job_queue import JobQueue


class DummyPipelineController:
    def __init__(self):
        self.enqueued = 0

    def enqueue_draft_jobs(self, run_config=None):
        # Simulate enqueuing one job
        self.enqueued += 1
        return 1


def main():
    scheduled = []

    def ui_scheduler(fn):
        # Simulate scheduling onto UI thread by executing immediately
        scheduled.append(fn)
        fn()

    job_service = JobService(JobQueue())
    pipeline_controller = DummyPipelineController()

    controller = AppController(main_window=None, job_service=job_service, pipeline_controller=pipeline_controller, ui_scheduler=ui_scheduler, threaded=False)

    start = time.time()
    # Simulate Add to Queue click
    controller.on_add_job_to_queue_v2()
    duration = time.time() - start

    print(f"Add-to-Queue handler returned in {duration:.3f}s")
    print(f"Scheduled callables: {len(scheduled)}")
    print(f"PipelineController enqueued count: {pipeline_controller.enqueued}")


if __name__ == '__main__':
    main()
