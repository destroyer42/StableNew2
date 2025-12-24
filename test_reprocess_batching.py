"""Quick test to verify reprocessing batching logic."""
import sys
from pathlib import Path
import importlib.util

# Load reprocess_builder directly
spec = importlib.util.spec_from_file_location(
    "reprocess_builder",
    Path(__file__).parent / "src" / "pipeline" / "reprocess_builder.py"
)
reprocess_builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reprocess_builder)
ReprocessJobBuilder = reprocess_builder.ReprocessJobBuilder

def test_batching():
    """Test that we create the right number of jobs."""
    builder = ReprocessJobBuilder()
    
    # Create temp directory and dummy test images
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create 160 dummy image files
        test_images = []
        for i in range(160):
            img_path = Path(tmpdir) / f"image_{i:03d}.png"
            img_path.touch()  # Create empty file
            test_images.append(str(img_path))
        
        stages = ["adetailer", "upscale"]
        config = {"adetailer": {"ad_model": "face_yolov8n.pt"}}
        
        print(f"Testing with {len(test_images)} images")
        print("-" * 60)
        
        # Test batch_size=1 (one job per image)
        print("\n1. Batch size = 1 (one job per image)")
        jobs_created = 0
        for i, img_path in enumerate(test_images):
            njr = builder.build_reprocess_job(
                input_image_paths=[img_path],
                stages=stages,
                config=config,
            )
            jobs_created += 1
        print(f"   ✓ Created {jobs_created} jobs")
        assert jobs_created == 160, f"Expected 160 jobs, got {jobs_created}"
        
        # Test batch_size=10 (16 jobs total)
        print("\n2. Batch size = 10 (should create 16 jobs)")
        batch_size = 10
        jobs_created = 0
        for i in range(0, len(test_images), batch_size):
            batch = test_images[i:i+batch_size]
            njr = builder.build_reprocess_job(
                input_image_paths=batch,
                stages=stages,
                config=config,
            )
            jobs_created += 1
        print(f"   ✓ Created {jobs_created} jobs")
        assert jobs_created == 16, f"Expected 16 jobs, got {jobs_created}"
        
        # Test batch_size=100 (2 jobs total)
        print("\n3. Batch size = 100 (should create 2 jobs)")
        batch_size = 100
        jobs_created = 0
        for i in range(0, len(test_images), batch_size):
            batch = test_images[i:i+batch_size]
            njr = builder.build_reprocess_job(
                input_image_paths=batch,
                stages=stages,
                config=config,
            )
            jobs_created += 1
        print(f"   ✓ Created {jobs_created} jobs")
        assert jobs_created == 2, f"Expected 2 jobs, got {jobs_created}"
        
        print("\n" + "=" * 60)
        print("✅ All batching tests passed!")
        print("=" * 60)

if __name__ == "__main__":
    test_batching()
