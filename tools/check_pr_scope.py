#!/usr/bin/env python
import sys

FORBIDDEN_PREFIXES = ("src/gui", "src/controller", "src/pipeline", "src/api")


def main(paths: list[str]) -> int:
    for path in paths:
        for prefix in FORBIDDEN_PREFIXES:
            if path.replace("\\", "/").startswith(prefix):
                print(f"Forbidden path touched: {path}", file=sys.stderr)
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
