"""Windows shell entry point for the registered StableNew Operator URI."""

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    from src.app.site_pairing_protocol import dispatch_protocol

    try:
        dispatch_protocol(root, sys.argv[1])
    except (OSError, ValueError):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
