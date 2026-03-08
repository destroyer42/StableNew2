"""Quick test of JobHistoryStore background writer."""
import time
from pathlib import Path
import tempfile
import sys

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.history.job_history_store import JobHistoryStore
from src.history.history_record import HistoryRecord

def test_background_writer():
    """Test that background writer works correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store_path = Path(tmpdir) / "test_history.jsonl"
        
        print("Creating JobHistoryStore...")
        store = JobHistoryStore(store_path)
        
        # Verify writer thread is running
        writer_thread = getattr(store, "_writer_thread", None)
        if not writer_thread:
            print("❌ Writer thread not created")
            return False
        
        if not writer_thread.is_alive():
            print("❌ Writer thread not alive")
            return False
        
        print(f"✅ Writer thread running: {writer_thread.name}")
        
        # Append some records
        print("Appending 10 test records...")
        for i in range(10):
            record = HistoryRecord(
                id=f"test-job-{i}",
                timestamp=time.time(),
                status="completed"
            )
            store.append(record)
        
        # Give writer time to process
        print("Waiting for writer to process...")
        time.sleep(1.0)
        
        # Read back records
        print("Reading records...")
        records = store.list_jobs()
        print(f"✅ Found {len(records)} records")
        
        if len(records) != 10:
            print(f"❌ Expected 10 records, got {len(records)}")
            return False
        
        # Test shutdown
        print("Shutting down writer thread...")
        store.shutdown()
        
        if writer_thread.is_alive():
            print("❌ Writer thread did not terminate")
            return False
        
        print("✅ Writer thread terminated cleanly")
        
        # Verify write queue is empty
        write_queue = getattr(store, "_write_queue", None)
        if write_queue and not write_queue.empty():
            print("❌ Write queue not empty after shutdown")
            return False
        
        print("✅ All tests passed!")
        return True

if __name__ == "__main__":
    success = test_background_writer()
    sys.exit(0 if success else 1)
