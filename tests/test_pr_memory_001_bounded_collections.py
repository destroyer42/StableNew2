"""
Test PR-MEMORY-001: Bound Unbounded Collections

Verifies that collections are properly bounded to prevent memory leaks.
"""

import pytest
from src.queue.job_queue import JobQueue
from src.queue.job_model import Job, JobPriority, JobStatus
from src.controller.process_auto_scanner_service import ProcessAutoScannerSummary


class TestBoundedCollections:
    """Test that unbounded collections are properly capped."""
    
    def test_finalized_jobs_bounded_to_100(self):
        """JobQueue._finalized_jobs should be capped at 100 entries."""
        from src.queue.job_history_store import JSONLJobHistoryStore
        import tempfile
        
        # Create queue with history store (needed for finalization)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            temp_path = f.name
        
        try:
            history_store = JSONLJobHistoryStore(path=temp_path)
            queue = JobQueue(history_store=history_store)
            
            # Submit and complete 150 jobs
            for i in range(150):
                job = Job(job_id=f"job-{i}", priority=JobPriority.NORMAL)
                queue.submit(job)
                queue.mark_completed(f"job-{i}", result={"success": True})
            
            # Check that finalized_jobs is bounded to 100
            assert len(queue._finalized_jobs) <= 100, \
                f"Expected max 100 finalized jobs, got {len(queue._finalized_jobs)}"
            
            # Check that deque order is maintained
            assert len(queue._finalized_jobs_order) <= 100, \
                f"Expected max 100 in deque, got {len(queue._finalized_jobs_order)}"
            
            # Oldest jobs should be evicted (first 50)
            assert "job-0" not in queue._finalized_jobs
            assert "job-49" not in queue._finalized_jobs
            
            # Newest jobs should be retained (last 100)
            assert "job-50" in queue._finalized_jobs
            assert "job-149" in queue._finalized_jobs
        finally:
            import os
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_finalized_jobs_clears_payload(self):
        """Job payloads should be cleared when finalized."""
        from src.queue.job_history_store import JSONLJobHistoryStore
        import tempfile
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            temp_path = f.name
        
        try:
            history_store = JSONLJobHistoryStore(path=temp_path)
            queue = JobQueue(history_store=history_store)
            
            # Create job with payload
            job = Job(job_id="test-job", priority=JobPriority.NORMAL)
            job.payload = {"large": "data" * 1000}  # Simulate large payload
            
            queue.submit(job)
            queue.mark_completed("test-job", result={"success": True})
            
            # Verify payload was cleared
            finalized_job = queue._finalized_jobs.get("test-job")
            assert finalized_job is not None
            assert finalized_job.payload is None, "Payload should be cleared on finalization"
        finally:
            import os
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_scanner_killed_list_bounded_to_100(self):
        """ProcessAutoScannerSummary.killed should be capped at 100 entries."""
        summary = ProcessAutoScannerSummary()
        
        # Add 150 killed process entries
        for i in range(150):
            summary.add_killed({
                "pid": i,
                "name": f"process-{i}",
                "memory_mb": 100.0,
                "idle_sec": 300.0,
                "reason": "idle/memory"
            })
        
        # Check that killed list is bounded to 100
        assert len(summary.killed) == 100, \
            f"Expected exactly 100 killed entries, got {len(summary.killed)}"
        
        # Should keep the last 100 (newest entries)
        assert summary.killed[0]["pid"] == 50, "Oldest entries should be evicted"
        assert summary.killed[-1]["pid"] == 149, "Newest entries should be retained"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
