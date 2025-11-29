"""
StableNew WebUI Launcher
========================

This script safely launches the Stable Diffusion WebUI with API enabled
and provides detailed feedback on the startup process.
"""

import subprocess
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.utils.webui_discovery import find_webui_api_port, validate_webui_health


def launch_webui():
    """Launch WebUI with detailed progress reporting"""
    print("🚀 StableNew WebUI Launcher")
    print("=" * 50)

    # Check if already running
    existing_url = find_webui_api_port()
    if existing_url:
        print(f"✅ WebUI already running at {existing_url}")
        health = validate_webui_health(existing_url)

        if health["models_loaded"]:
            print(f"📦 Models: {health.get('model_count', 0)} loaded")
        if health["samplers_available"]:
            print(f"🔧 Samplers: {health.get('sampler_count', 0)} available")

        print("✅ Ready to use!")
        return True

    # Find WebUI installation
    webui_path = Path("C:/Users/rober/stable-diffusion-webui/webui-user.bat")

    if not webui_path.exists():
        print(f"❌ WebUI not found at: {webui_path}")
        print("Please check your installation path.")
        return False

    print(f"📁 WebUI found at: {webui_path}")
    print("🔄 Starting WebUI with API enabled...")

    try:
        # Launch WebUI
        if sys.platform == "win32":
            process = subprocess.Popen(
                f'"{webui_path}" --api',
                cwd=webui_path.parent,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                shell=True,
            )
        else:
            process = subprocess.Popen(
                [str(webui_path), "--api"],
                cwd=webui_path.parent,
            )

        print("⏳ Waiting for WebUI to start...")

        # Wait up to 60 seconds for startup
        for attempt in range(60):
            time.sleep(1)

            # Check if process crashed
            if process.poll() is not None:
                print("❌ WebUI process crashed during startup")
                return False

            # Check for API
            api_url = find_webui_api_port()
            if api_url:
                print("✅ WebUI started successfully!")
                print(f"🔗 API URL: {api_url}")

                # Perform health check
                print("🔍 Checking WebUI health...")
                health = validate_webui_health(api_url)

                if health["accessible"]:
                    print("✅ API accessible")

                    if health["models_loaded"]:
                        print(f"📦 Models loaded: {health.get('model_count', 0)}")
                    else:
                        print("⚠️ No models loaded yet - may still be initializing")

                    if health["samplers_available"]:
                        print(f"🔧 Samplers available: {health.get('sampler_count', 0)}")

                    if health["errors"]:
                        print("⚠️ Issues detected:")
                        for error in health["errors"]:
                            print(f"   - {error}")

                    print("🎉 WebUI is ready for StableNew!")
                    return True
                else:
                    print("❌ API not accessible")
                    return False

            # Show progress
            if attempt % 10 == 0 and attempt > 0:
                print(f"⏳ Still waiting... ({attempt}/60 seconds)")

        print("❌ WebUI startup timeout - process may still be starting")
        return False

    except Exception as e:
        print(f"❌ Failed to launch WebUI: {e}")
        return False


if __name__ == "__main__":
    success = launch_webui()

    if success:
        print("\n" + "=" * 50)
        print("✅ SUCCESS! You can now:")
        print("1. Run: python -m src.main (for GUI)")
        print("2. Run: python journey_test.py (to test)")
        print("3. Run: python -m src.cli --prompt 'test' --preset default")
    else:
        print("\n" + "=" * 50)
        print("❌ FAILED! Please:")
        print("1. Check WebUI installation")
        print("2. Try running webui-user.bat manually")
        print("3. Ensure no firewall is blocking the connection")

    input("\nPress Enter to exit...")
    sys.exit(0 if success else 1)
