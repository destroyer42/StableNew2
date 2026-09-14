from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

output_routing = importlib.import_module("src.state.output_routing")


def main() -> int:
    payload = {
        "migrate": output_routing.migrate_legacy_output_tree("output"),
        "rebalance": output_routing.rebalance_output_tree("output"),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
