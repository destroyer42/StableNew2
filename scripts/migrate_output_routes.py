from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.state.output_routing import migrate_legacy_output_tree, rebalance_output_tree


def main() -> int:
    payload = {
        "migrate": migrate_legacy_output_tree("output"),
        "rebalance": rebalance_output_tree("output"),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
