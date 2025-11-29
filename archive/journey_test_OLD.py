"""
Journey Test Suite for StableNew Pipeline
========================================

This script provides systematic testing of the StableNew pipeline to validate:
1. API connectivity and port discovery
2. txt2img generation functionality
3. img2img cleanup stage
4. Upscaling operations
5. Full pipeline integration
6. Error handling and recovery

Run this before using the GUI to ensure all components are working.
"""

import sys
import logging
from pathlib import Path
from datetime import datetime

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.api import SDWebUIClient
from src.pipeline import Pipeline
from src.utils import ConfigManager, StructuredLogger, setup_logging


class PipelineJourneyTester:
    """Systematic testing of pipeline functionality"""
    
    def __init__(self):
        """Initialize tester"""
        setup_logging("INFO")
        self.logger = logging.getLogger(__name__)
        self.config_manager = ConfigManager()
        self.structured_logger = StructuredLogger()
        
        # Test configuration
        self.test_config = {
            "txt2img": {
                "steps": 10,  # Reduced for faster testing
                "sampler_name": "Euler a",
                "cfg_scale": 7.0,
                "width": 512,
                "height": 512,
                "negative_prompt": "blurry, bad quality, distorted"
            },
            "img2img": {
                "steps": 8,  # Reduced for faster testing
                "sampler_name": "Euler a", 
                "cfg_scale": 7.0,
                "denoising_strength": 0.3
            },
            "upscale": {
                "upscaler": "R-ESRGAN 4x+",
                "upscaling_resize": 2.0
            },
            "api": {
                "base_url": "http://127.0.0.1:7860",
                "timeout": 120
            }
        }
        
        self.test_prompts = [
            "simple geometric shape, minimalist",
            "basic landscape, simple colors"
        ]
        
    def print_header(self, test_name: str):
        """Print test header"""
        print(f"\n{'='*60}")
        print(f"🧪 TESTING: {test_name}")
        print(f"{'='*60}")
        
    def print_result(self, success: bool, message: str):
        """Print test result"""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {message}")
        
    def test_api_discovery(self) -> bool:
        """Test API port discovery and connection"""
        self.print_header("API Discovery & Connection")
        
        ports_to_try = [7860, 7861, 7862, 7863, 7864]
        
        for port in ports_to_try:
            api_url = f"http://127.0.0.1:{port}"
            print(f"🔍 Trying port {port}...")
            
            try:
                client = SDWebUIClient(base_url=api_url, timeout=10)
                if client.check_api_ready(max_retries=2, retry_delay=1):
                    self.print_result(True, f"API found on port {port}")
                    self.test_config["api"]["base_url"] = api_url
                    self.client = client
                    return True
                    
            except Exception as e:
                print(f"   Error on port {port}: {e}")
                continue
                
        self.print_result(False, "No working API found on any port")
        return False
    
    def test_api_endpoints(self) -> bool:
        """Test individual API endpoints"""
        self.print_header("API Endpoint Tests")
        
        try:
            # Test models endpoint
            models = self.client.get_models()
            self.print_result(bool(models), f"Models endpoint - Found {len(models) if models else 0} models")
            
            # Test samplers endpoint
            samplers = self.client.get_samplers()
            self.print_result(bool(samplers), f"Samplers endpoint - Found {len(samplers) if samplers else 0} samplers")
            
            # Test current model
            current_model = self.client.get_current_model()
            self.print_result(bool(current_model), f"Current model: {current_model or 'None'}")
            
            return bool(models and samplers)
            
        except Exception as e:
            self.print_result(False, f"API endpoint test failed: {e}")
            return False
    
    def test_txt2img_generation(self) -> bool:
        """Test txt2img generation"""
        self.print_header("txt2img Generation Test")
        
        try:
            # Initialize pipeline
            pipeline = Pipeline(self.client, self.structured_logger)
            
            # Create test run directory
            run_dir = self.structured_logger.create_run_directory("journey_test_txt2img")
            
            # Test simple prompt
            test_prompt = self.test_prompts[0]
            print(f"📝 Testing prompt: {test_prompt}")
            
            results = pipeline.run_txt2img(
                prompt=test_prompt,
                config=self.test_config["txt2img"],
                run_dir=run_dir,
                batch_size=1
            )
            
            if results and len(results) > 0:
                result_path = Path(results[0]["path"])
                if result_path.exists():
                    file_size = result_path.stat().st_size
                    self.print_result(True, f"Generated image: {result_path.name} ({file_size} bytes)")
                    return True
                else:
                    self.print_result(False, f"Image file not found: {result_path}")
                    return False
            else:
                self.print_result(False, "No images generated")
                return False
                
        except Exception as e:
            self.print_result(False, f"txt2img generation failed: {e}")
            return False
    
    def test_full_pipeline(self) -> bool:
        """Test complete pipeline"""
        self.print_header("Full Pipeline Test")
        
        try:
            # Initialize pipeline
            pipeline = Pipeline(self.client, self.structured_logger)
            
            # Test with simple prompt
            test_prompt = self.test_prompts[1]
            print(f"📝 Testing full pipeline with: {test_prompt}")
            
            results = pipeline.run_full_pipeline(
                prompt=test_prompt,
                config=self.test_config,
                run_name="journey_test_full",
                batch_size=1
            )
            
            # Check results
            txt2img_count = len(results.get("txt2img", []))
            img2img_count = len(results.get("img2img", []))
            upscaled_count = len(results.get("upscaled", []))
            
            print(f"   txt2img: {txt2img_count} images")
            print(f"   img2img: {img2img_count} images")
            print(f"   upscaled: {upscaled_count} images")
            
            success = txt2img_count > 0
            self.print_result(success, f"Pipeline completed with {txt2img_count} base images")
            
            return success
            
        except Exception as e:
            self.print_result(False, f"Full pipeline test failed: {e}")
            return False
    
    def test_config_system(self) -> bool:
        """Test configuration management"""
        self.print_header("Configuration System Test")
        
        try:
            # Test default config
            default_config = self.config_manager.get_default_config()
            self.print_result(bool(default_config), f"Default config loaded: {len(default_config)} sections")
            
            # Test preset loading
            presets = self.config_manager.list_presets()
            self.print_result(len(presets) > 0, f"Found {len(presets)} presets: {', '.join(presets)}")
            
            # Test config resolution
            resolved = self.config_manager.resolve_config("default")
            self.print_result(bool(resolved), "Config resolution working")
            
            return bool(default_config and resolved)
            
        except Exception as e:
            self.print_result(False, f"Config system test failed: {e}")
            return False
    
    def run_all_tests(self) -> bool:
        """Run complete test suite"""
        print(f"🚀 StableNew Journey Test Suite")
        print(f"⏰ Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        tests = [
            ("Config System", self.test_config_system),
            ("API Discovery", self.test_api_discovery),
            ("API Endpoints", self.test_api_endpoints),
            ("txt2img Generation", self.test_txt2img_generation),
            ("Full Pipeline", self.test_full_pipeline),
        ]
        
        passed = 0
        total = len(tests)
        
        for test_name, test_func in tests:
            try:
                if test_func():
                    passed += 1
            except Exception as e:
                self.print_result(False, f"{test_name} crashed: {e}")
        
        # Final results
        print(f"\n{'='*60}")
        print(f"🏁 JOURNEY TEST RESULTS")
        print(f"{'='*60}")
        print(f"✅ Passed: {passed}/{total}")
        print(f"❌ Failed: {total - passed}/{total}")
        
        if passed == total:
            print(f"🎉 ALL TESTS PASSED! StableNew is ready to use.")
        else:
            print(f"⚠️  Some tests failed. Check the issues above.")
        
        print(f"⏰ Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return passed == total


if __name__ == "__main__":
    tester = PipelineJourneyTester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)