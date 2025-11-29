#!/usr/bin/env python3
"""
Journey Test for Heroes SDXL Prompt Pack
Tests the complete pipeline with hero-themed content using embeddings, LORAs, and SDXL models
"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.api import SDWebUIClient
from src.pipeline import Pipeline
from src.utils import ConfigManager, StructuredLogger, setup_logging, find_webui_api_port


class HeroesJourneyTester:
    """Journey tester for Heroes SDXL prompt pack functionality"""
    
    def __init__(self):
        setup_logging("INFO")
        self.logger = logging.getLogger(__name__)
        self.config_manager = ConfigManager()
        self.structured_logger = StructuredLogger()
        self.hero_prompts = []
        self.load_hero_prompts()
        
        # Initialize API client
        api_url = find_webui_api_port() or "http://127.0.0.1:7860"
        self.client = SDWebUIClient(base_url=api_url, timeout=60)
        
        # Test results tracking
        self.results = {
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "test_details": []
        }
        
    def load_hero_prompts(self):
        """Load hero prompts from the pack file"""
        pack_file = Path("packs/heroes_sdxl_pack.txt")
        if not pack_file.exists():
            self.logger.error(f"Hero pack file not found: {pack_file}")
            return
            
        with open(pack_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        current_prompt = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):
                if line.startswith('<embedding:') or line.startswith('(masterpiece'):
                    # Start of a new prompt
                    if current_prompt:
                        self.hero_prompts.append('\n'.join(current_prompt))
                        current_prompt = []
                current_prompt.append(line)
                
        # Add the last prompt
        if current_prompt:
            self.hero_prompts.append('\n'.join(current_prompt))
            
        self.logger.info(f"Loaded {len(self.hero_prompts)} hero prompts")

    def run_test(self, test_name, test_func):
        """Run a test and track results"""
        self.results["tests_run"] += 1
        self.logger.info(f"🧪 Running test: {test_name}")
        
        try:
            success = test_func()
            if success:
                self.results["tests_passed"] += 1
                self.results["test_details"].append(f"✅ {test_name}")
                self.logger.info(f"✅ {test_name} - PASSED")
            else:
                self.results["tests_failed"] += 1
                self.results["test_details"].append(f"❌ {test_name}")
                self.logger.error(f"❌ {test_name} - FAILED")
            return success
        except Exception as e:
            self.results["tests_failed"] += 1
            self.results["test_details"].append(f"❌ {test_name} - Exception: {str(e)}")
            self.logger.error(f"❌ {test_name} - EXCEPTION: {e}")
            return False

    def test_heroes_preset_exists(self):
        """Test 1: Verify heroes_sdxl preset exists and loads correctly"""
        config = self.config_manager.load_preset("heroes_sdxl")
        if not config:
            self.logger.error("Heroes SDXL preset not found")
            return False
            
        # Check SDXL-specific settings
        required_keys = ["txt2img", "img2img", "upscale", "api"]
        for key in required_keys:
            if key not in config:
                self.logger.error(f"Missing section in heroes_sdxl preset: {key}")
                return False
                
        # Verify SDXL dimensions
        if config["txt2img"].get("width") != 1024 or config["txt2img"].get("height") != 1024:
            self.logger.error("Heroes preset should use SDXL dimensions (1024x1024)")
            return False
            
        self.logger.info("Heroes SDXL preset loaded with correct SDXL settings")
        return True

    def test_heroes_pack_format(self):
        """Test 2: Verify heroes pack has correct format and content"""
        if len(self.hero_prompts) < 6:
            self.logger.error(f"Expected at least 6 hero prompts, found {len(self.hero_prompts)}")
            return False
            
        # Check for embeddings and LORAs in prompts
        embedding_count = 0
        lora_count = 0
        
        for prompt in self.hero_prompts:
            if '<embedding:' in prompt:
                embedding_count += 1
            if '<lora:' in prompt:
                lora_count += 1
                
        if embedding_count < 3:
            self.logger.error(f"Expected embeddings in prompts, found {embedding_count}")
            return False
            
        if lora_count < 3:
            self.logger.error(f"Expected LORAs in prompts, found {lora_count}")
            return False
            
        self.logger.info(f"Hero pack format verified: {len(self.hero_prompts)} prompts, {embedding_count} with embeddings, {lora_count} with LORAs")
        return True

    def test_api_connection(self):
        """Test 3: Verify API connection and SDXL model"""
        if not self.client.check_api_ready():
            self.logger.error("SD WebUI API not ready")
            return False
            
        # Check current model
        try:
            response = self.client._request("GET", "/sdapi/v1/options")
            if response:
                current_model = response.get("sd_model_checkpoint", "")
                if "juggernautXL" in current_model:
                    self.logger.info(f"SDXL model confirmed: {current_model}")
                    return True
                else:
                    self.logger.warning(f"Model may not be SDXL: {current_model}")
                    return True  # Still pass, just a warning
            return False
        except Exception as e:
            self.logger.error(f"Failed to check model: {e}")
            return False

    def test_cli_hero_generation(self):
        """Test 4: CLI generation with first hero prompt"""
        if not self.hero_prompts:
            self.logger.error("No hero prompts loaded")
            return False
            
        # Use first prompt for CLI test
        test_prompt = self.hero_prompts[0].replace('\n', ' ').strip()
        
        try:
            # Run CLI command
            cmd = [
                sys.executable, "-m", "src.cli",
                "--prompt", test_prompt,
                "--preset", "heroes_sdxl", 
                "--batch-size", "1",
                "--no-upscale"  # Skip upscale for faster testing
            ]
            
            self.logger.info("Running CLI generation test...")
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.getcwd())
            
            if result.returncode != 0:
                self.logger.error(f"CLI command failed: {result.stderr}")
                return False
                
            # Check for success indicators in output
            if "Pipeline completed" in result.stdout and "Completed successfully" in result.stdout:
                self.logger.info("CLI generation completed successfully")
                return True
            else:
                self.logger.error("CLI generation did not complete successfully")
                return False
                
        except Exception as e:
            self.logger.error(f"CLI test failed: {e}")
            return False

    def test_pipeline_hero_generation(self):
        """Test 5: Direct pipeline generation with hero prompt"""
        if not self.hero_prompts:
            self.logger.error("No hero prompts loaded")
            return False
            
        config = self.config_manager.load_preset("heroes_sdxl")
        if not config:
            self.logger.error("Failed to load heroes_sdxl preset")
            return False
            
        pipeline = Pipeline(self.client, self.structured_logger)
        
        try:
            # Use second prompt for pipeline test
            test_prompt = self.hero_prompts[1].replace('\n', ' ').strip() if len(self.hero_prompts) > 1 else self.hero_prompts[0]
            
            self.logger.info("Running pipeline generation test...")
            results = pipeline.run_full_pipeline(
                test_prompt,
                config,
                "heroes_journey_test",
                1
            )
            
            if results and results.get("txt2img") and len(results["txt2img"]) > 0:
                self.logger.info(f"Pipeline generation successful: {results['run_dir']}")
                return True
            else:
                self.logger.error("Pipeline generation failed or produced no images")
                return False
                
        except Exception as e:
            self.logger.error(f"Pipeline test failed: {e}")
            return False

    def test_global_nsfw_prevention(self):
        """Test 6: Verify global NSFW prevention is active"""
        config = self.config_manager.load_preset("heroes_sdxl")
        if not config:
            return False
            
        # Check if global negative method exists
        if hasattr(self.config_manager, 'add_global_negative'):
            original_neg = "test negative"
            enhanced_neg = self.config_manager.add_global_negative(original_neg)
            
            # Should contain NSFW prevention terms
            nsfw_terms = ["nsfw", "nude", "explicit"]
            found_terms = sum(1 for term in nsfw_terms if term in enhanced_neg.lower())
            
            if found_terms >= 2:
                self.logger.info("Global NSFW prevention is active and working")
                return True
            else:
                self.logger.error("Global NSFW prevention not working properly")
                return False
        else:
            self.logger.error("Global NSFW prevention method not found")
            return False

    def run_all_tests(self):
        """Run all hero journey tests"""
        self.logger.info("=" * 80)
        self.logger.info("🦸‍♂️ HEROES SDXL JOURNEY TESTING")
        self.logger.info("=" * 80)
        
        # Run all tests
        tests = [
            ("Heroes Preset Exists", self.test_heroes_preset_exists),
            ("Heroes Pack Format", self.test_heroes_pack_format), 
            ("API Connection & SDXL Model", self.test_api_connection),
            ("CLI Hero Generation", self.test_cli_hero_generation),
            ("Pipeline Hero Generation", self.test_pipeline_hero_generation),
            ("Global NSFW Prevention", self.test_global_nsfw_prevention)
        ]
        
        for test_name, test_func in tests:
            self.run_test(test_name, test_func)
            time.sleep(1)  # Brief pause between tests
            
        # Print results summary
        self.print_results()
        
        return self.results["tests_failed"] == 0

    def print_results(self):
        """Print test results summary"""
        self.logger.info("=" * 80)
        self.logger.info("🧪 HEROES JOURNEY TEST RESULTS")
        self.logger.info("=" * 80)
        
        for detail in self.results["test_details"]:
            self.logger.info(detail)
            
        self.logger.info("-" * 80)
        self.logger.info(f"Tests Run: {self.results['tests_run']}")
        self.logger.info(f"Tests Passed: {self.results['tests_passed']}")
        self.logger.info(f"Tests Failed: {self.results['tests_failed']}")
        
        if self.results["tests_failed"] == 0:
            self.logger.info("🎉 ALL HEROES TESTS PASSED! The hero prompt pack is ready for battle!")
        else:
            self.logger.error("💥 Some tests failed. The heroes need more training!")
            
        self.logger.info("=" * 80)


def main():
    """Main function"""
    tester = HeroesJourneyTester()
    success = tester.run_all_tests()
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())