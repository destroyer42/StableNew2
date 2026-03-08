#!/usr/bin/env python3
"""Run specific test to check for regressions."""

import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from tests.controller.test_pack_draft_to_normalized_preview_v2 import test_on_pipeline_add_packs_to_job_populates_preview_metadata
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as tmp:
    try:
        test_on_pipeline_add_packs_to_job_populates_preview_metadata(Path(tmp))
        print('TEST PASSED')
    except Exception as e:
        print(f'TEST FAILED: {e}')
        import traceback
        traceback.print_exc()