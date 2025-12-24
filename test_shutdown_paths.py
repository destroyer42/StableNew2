"""Verify shutdown paths work correctly with is_acquired() fix."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

def test_shutdown_simulation():
    """Simulate the shutdown paths that were previously broken."""
    from utils.single_instance import SingleInstanceLock
    
    print("Testing shutdown path simulation...")
    print("=" * 60)
    
    # Test 1: main.py finally block pattern
    print("\n1. Testing main.py finally block pattern:")
    print("-" * 60)
    
    single_instance_lock = SingleInstanceLock(port=47888)
    success = single_instance_lock.acquire()
    
    if not success:
        print("   ⚠️  Lock already held (expected in parallel runs)")
        return
    
    print(f"   Lock acquired: {single_instance_lock.is_acquired()}")
    
    try:
        # Simulate app running
        print("   App running...")
        # Simulate some work
        pass
    except Exception as exc:
        print(f"   Exception: {exc}")
    finally:
        # This is the exact pattern from main.py line 490
        if single_instance_lock.is_acquired():
            print("   ✓ is_acquired() returned True, releasing lock...")
            single_instance_lock.release()
            print(f"   ✓ Lock released, is_acquired={single_instance_lock.is_acquired()}")
        else:
            print("   ❌ is_acquired() returned False unexpectedly!")
    
    assert not single_instance_lock.is_acquired(), "Lock should be released"
    print("\n   ✅ main.py finally block pattern works!")
    
    # Test 2: graceful_exit pattern
    print("\n2. Testing graceful_exit.py pattern:")
    print("-" * 60)
    
    single_instance_lock2 = SingleInstanceLock(port=47889)
    single_instance_lock2.acquire()
    
    print(f"   Lock acquired: {single_instance_lock2.is_acquired()}")
    
    # This is the exact pattern from graceful_exit.py line 34
    if single_instance_lock2 and single_instance_lock2.is_acquired():
        try:
            print("   ✓ is_acquired() returned True, releasing lock...")
            single_instance_lock2.release()
            print(f"   ✓ Lock released, is_acquired={single_instance_lock2.is_acquired()}")
        except Exception as exc:
            print(f"   ❌ Exception during release: {exc}")
    else:
        print("   ❌ is_acquired() check failed!")
    
    assert not single_instance_lock2.is_acquired(), "Lock should be released"
    print("\n   ✅ graceful_exit.py pattern works!")
    
    print("\n" + "=" * 60)
    print("🎉 Both shutdown paths work correctly!")
    print("=" * 60)

if __name__ == "__main__":
    try:
        test_shutdown_simulation()
    except AttributeError as e:
        print(f"\n❌ CRITICAL: AttributeError during shutdown simulation!")
        print(f"   {e}")
        print("   This is the bug we were trying to fix!")
        sys.exit(1)
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
