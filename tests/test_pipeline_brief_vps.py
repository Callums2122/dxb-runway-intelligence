from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "vps" / "pipeline_brief.py"
SPEC = importlib.util.spec_from_file_location("pipeline_brief", MODULE_PATH)
pipeline_brief = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pipeline_brief)


def test_parses_header_first_snapshot_using_default_date() -> None:
    values = [
        ["SN", "Name", "Car", "Time", "Salesperson", "Checked In", "Note"],
        ["DXB-1", "Customer", "BMW X5", "09:30", "Sales", "", ""],
        ["DXB-2", "Customer", "Audi Q7", "11:00", "Sales", "", ""],
    ]

    rows = pipeline_brief.parse_appointments(values, "2026-08-24")

    assert len(rows) == 2
    assert {row["date"] for row in rows} == {"2026-08-24"}


def test_explicit_date_marker_overrides_default_date() -> None:
    values = [
        ["2026 August 25"],
        ["SN", "Name", "Car", "Time", "Salesperson", "Checked In", "Note"],
        ["DXB-3", "Customer", "Porsche Cayenne", "12:00", "Sales", "", ""],
    ]

    rows = pipeline_brief.parse_appointments(values, "2026-08-24")

    assert len(rows) == 1
    assert rows[0]["date"] == "2026-08-25"
