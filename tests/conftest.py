import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def have_tools() -> bool:
    return all(shutil.which(t) for t in ("iverilog", "vvp", "verilator", "yosys"))


def pytest_collection_modifyitems(config, items):
    skip = pytest.mark.skip(reason="EDA tools not on PATH (run on the cloud instance)")
    for item in items:
        if "cloud" in item.keywords and not have_tools():
            item.add_marker(skip)
