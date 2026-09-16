"""Adapters for retained legacy fixtures; locked files remain unchanged."""
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def counter_contract_data():
    """Make the fixture's synchronous active-high rst explicit for the current schema."""
    data = json.loads((FIXTURES / "counter_contract.json").read_text())
    data["clock_reset"] = {"clock": "clk", "reset": "rst", "reset_active": "high", "reset_kind": "synchronous"}
    return data
