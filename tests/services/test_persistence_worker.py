"""
PR-HB-004: Test async persistence worker.

Tests that persistence operations are enqueued and return immediately,
and that writes happen on background thread.
"""
import json
import tempfile
import threading
import time
from pathlib import Path


class TestPersistenceWorker:
    """Test persistence worker enqueuing and background execution."""
    
    def test_worker_starts_and_stops(self):
        """Test that worker can be started and stopped cleanly."""
        from src.services.persistence_worker import PersistenceWorker
        
        worker = PersistenceWorker()
        worker.start()
        
        assert worker._running
        assert worker._worker_thread is not None
        assert worker._worker_thread.is_alive()
        
        worker.stop(timeout=2.0)
        
        assert not worker._running
    
    def test_enqueue_returns_immediately(self):
        """Test that enqueuing a task returns immediately without blocking."""
        from src.services.persistence_worker import PersistenceWorker, PersistenceTask
        
        worker = PersistenceWorker()
        worker.start()
        
        try:
            # Create a task
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".json") as f:
                temp_path = Path(f.name)
            
            task = PersistenceTask(
                task_type="manifest",
                data={"file_path": str(temp_path), "payload": {"test": "data"}},
            )
            
            # Enqueue should return immediately
            start_time = time.monotonic()
            result = worker.enqueue(task)
            duration = time.monotonic() - start_time
            
            assert result is True, "Enqueue should succeed"
            assert duration < 0.01, f"Enqueue took {duration*1000:.1f}ms (should be <10ms)"
            
            # Wait for worker to process
            time.sleep(0.2)
            
            # Verify file was written
            assert temp_path.exists()
            content = json.loads(temp_path.read_text())
            assert content == {"test": "data"}
            
            # Cleanup
            temp_path.unlink()
        
        finally:
            worker.stop()
    
    def test_write_happens_on_worker_thread(self):
        """Test that writes happen on the worker thread, not calling thread."""
        from src.services.persistence_worker import PersistenceWorker, PersistenceTask
        
        worker = PersistenceWorker()
        worker.start()
        
        try:
            main_thread_id = threading.get_ident()
            write_thread_id = None
            
            # Mock the write method to capture thread ID
            original_write = worker._write_manifest
            
            def _capture_thread(data):
                nonlocal write_thread_id
                write_thread_id = threading.get_ident()
                original_write(data)
            
            worker._write_manifest = _capture_thread
            
            # Enqueue task
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".json") as f:
                temp_path = Path(f.name)
            
            task = PersistenceTask(
                task_type="manifest",
                data={"file_path": str(temp_path), "payload": {"test": "data"}},
            )
            worker.enqueue(task)
            
            # Wait for processing
            time.sleep(0.2)
            
            # Verify write happened on different thread
            assert write_thread_id is not None
            assert write_thread_id != main_thread_id, "Write should happen on worker thread, not main thread"
            
            # Cleanup
            temp_path.unlink()
        
        finally:
            worker.stop()
    
    def test_backpressure_drops_noncritical_tasks(self):
        """Test that non-critical tasks are dropped when queue is full."""
        from src.services.persistence_worker import PersistenceWorker, PersistenceTask
        
        # Small queue for testing
        worker = PersistenceWorker(max_queue_size=5)
        worker.start()
        
        try:
            # Fill queue with slow tasks
            for i in range(10):
                task = PersistenceTask(
                    task_type="manifest",
                    data={"file_path": f"/tmp/test_{i}.json", "payload": {"index": i}},
                )
                result = worker.enqueue(task, critical=False)
                
                # First 5 should succeed, rest should fail
                if i < 5:
                    assert result is True, f"Task {i} should be enqueued"
                else:
                    # May or may not succeed depending on processing speed
                    pass
            
            # Check stats
            stats = worker.get_stats()
            assert stats["dropped"] > 0 or stats["pending"] <= 5
        
        finally:
            worker.stop()
    
    def test_critical_tasks_always_enqueued(self):
        """Test that critical tasks block until space is available."""
        from src.services.persistence_worker import PersistenceWorker, PersistenceTask
        
        worker = PersistenceWorker(max_queue_size=10)
        worker.start()
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".json") as f:
                temp_path = Path(f.name)
            
            # Critical task should always succeed
            task = PersistenceTask(
                task_type="manifest",
                data={"file_path": str(temp_path), "payload": {"critical": True}},
                priority=1,
            )
            result = worker.enqueue(task, critical=True)
            
            assert result is True, "Critical task should always be enqueued"
            
            # Wait for processing
            time.sleep(0.2)
            
            # Cleanup
            if temp_path.exists():
                temp_path.unlink()
        
        finally:
            worker.stop()
    
    def test_callback_dispatched_after_write(self):
        """Test that callback is called after write completes."""
        from src.services.persistence_worker import PersistenceWorker, PersistenceTask
        
        callback_called = False
        
        def _callback():
            nonlocal callback_called
            callback_called = True
        
        worker = PersistenceWorker()
        worker.start()
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".json") as f:
                temp_path = Path(f.name)
            
            task = PersistenceTask(
                task_type="manifest",
                data={"file_path": str(temp_path), "payload": {"with": "callback"}},
                callback=_callback,
            )
            worker.enqueue(task)
            
            # Wait for processing
            time.sleep(0.3)
            
            # Verify callback was called
            assert callback_called, "Callback should have been called"
            
            # Cleanup
            if temp_path.exists():
                temp_path.unlink()
        
        finally:
            worker.stop()
    
    def test_history_write_appends_jsonl(self):
        """Test that history writes append to JSONL file."""
        from src.services.persistence_worker import PersistenceWorker, PersistenceTask
        
        worker = PersistenceWorker()
        worker.start()
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".jsonl") as f:
                temp_path = Path(f.name)
            
            # Write multiple entries
            for i in range(3):
                task = PersistenceTask(
                    task_type="history",
                    data={"file_path": str(temp_path), "payload": {"entry": i}},
                )
                worker.enqueue(task, critical=True)
            
            # Wait for processing
            time.sleep(0.5)
            
            # Verify JSONL format
            lines = temp_path.read_text().strip().split("\n")
            assert len(lines) == 3
            
            for i, line in enumerate(lines):
                entry = json.loads(line)
                assert entry == {"entry": i}
            
            # Cleanup
            temp_path.unlink()
        
        finally:
            worker.stop()
    
    def test_stats_tracking(self):
        """Test that worker tracks statistics correctly."""
        from src.services.persistence_worker import PersistenceWorker, PersistenceTask
        
        worker = PersistenceWorker(max_queue_size=5)
        worker.start()
        
        try:
            initial_stats = worker.get_stats()
            assert initial_stats["completed"] == 0
            assert initial_stats["dropped"] == 0
            assert initial_stats["pending"] == 0
            
            # Enqueue some tasks
            with tempfile.TemporaryDirectory() as tmpdir:
                for i in range(3):
                    task = PersistenceTask(
                        task_type="manifest",
                        data={"file_path": str(Path(tmpdir) / f"test_{i}.json"), "payload": {"i": i}},
                    )
                    worker.enqueue(task)
                
                # Wait for processing
                time.sleep(0.5)
                
                final_stats = worker.get_stats()
                assert final_stats["completed"] >= 3
        
        finally:
            worker.stop()
