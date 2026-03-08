"""
WebUI Wrapper Script - Prevents orphaned WebUI processes

This wrapper:
1. Checks if StableNew GUI is running before starting WebUI
2. Periodically checks the lock during WebUI execution
3. Terminates WebUI if StableNew GUI exits

This prevents the infinite restart loop from orphaned processes.
"""
import subprocess
import sys
import time
from pathlib import Path

# Add parent directory to path to import StableNew modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.single_instance import SingleInstanceLock


def main():
    if len(sys.argv) < 2:
        print("Usage: python webui_wrapper.py <webui_command> [args...]", file=sys.stderr)
        sys.exit(1)
    
    # Check if StableNew GUI is running
    if not SingleInstanceLock.is_gui_running():
        print("[WebUI Wrapper] StableNew GUI is not running. Refusing to start WebUI.", file=sys.stderr)
        print("[WebUI Wrapper] This prevents orphaned WebUI processes.", file=sys.stderr)
        sys.exit(1)
    
    command = sys.argv[1:]
    print(f"[WebUI Wrapper] Starting WebUI: {' '.join(command)}")
    
    # Start WebUI process
    process = subprocess.Popen(command, shell=True if command[0].endswith('.bat') else False)
    
    # Monitor process and check lock periodically
    check_interval = 5.0  # Check every 5 seconds
    last_check = time.time()
    
    while True:
        # Check if process has exited
        exit_code = process.poll()
        if exit_code is not None:
            print(f"[WebUI Wrapper] WebUI process exited with code {exit_code}")
            sys.exit(exit_code)
        
        # Periodically check if StableNew GUI is still running
        if time.time() - last_check >= check_interval:
            if not SingleInstanceLock.is_gui_running():
                print("[WebUI Wrapper] StableNew GUI has exited. Terminating WebUI.", file=sys.stderr)
                process.terminate()
                try:
                    process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    print("[WebUI Wrapper] WebUI did not terminate gracefully, killing...", file=sys.stderr)
                    process.kill()
                sys.exit(1)
            last_check = time.time()
        
        time.sleep(0.5)


if __name__ == "__main__":
    main()
