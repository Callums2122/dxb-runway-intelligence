from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from dxb_runway.database import Database
from dxb_runway.intelligence import (
    analyse_opportunity, chat_conversation, chat_evidence, forget_intelligence_memory, import_vehicle_history,
    intelligence_memories, learning_directive, save_chat_message, save_intelligence_memory,
    save_chat_attachments, write_intelligence_snapshot,
)


def _database(tmp_path: Path) -> Database:
    return Database(tmp_path / "runway-intelligence.db")


def _write_messy_history(path: Path) -> None:
    rows = [
        ["ALBA CARS HISTORICAL STOCK EXPORT"],
        ["Generated report", "Everything below should be retained"],
        ["Sold For", "Variant", "Date Bought", "Manufacturer", "Date Sold", "Buy Price", "Model", "Year", "Internal Comment"],
        [285000, "S line", "01/01/2026", "Audi", "08/01/2026", 230000, "Q8", 2024, "fast clean car"],
        [270000, "S line", "02/02/2026", "Audi", "18/02/2026", 225000, "Q8", 2023, "second example"],
        [240000, "Black Edition", "05/03/2026", "Audi", "20/04/2026", 218000, "Q8", 2022, "slower trim"],
        ["", "Unknown", "bad date", "", "", "", "", "", "never discard me"],
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)


def test_messy_import_preserves_raw_and_quarantines_bad_rows(tmp_path: Path) -> None:
    db = _database(tmp_path)
    source = tmp_path / "mixed columns.csv"
    _write_messy_history(source)

    summary = import_vehicle_history(db, source)

    assert summary.rows == 4
    assert summary.usable == 3
    assert summary.review == 1
    assert summary.archived_path.exists()
    record = db.query("SELECT * FROM intelligence_records WHERE make='Audi' AND model='Q8' ORDER BY id LIMIT 1")[0]
    assert record["trim"] == "S Line"
    assert record["model_year"] == 2024
    assert json.loads(record["raw_json"])["Internal Comment"] == "fast clean car"
    bad = db.query("SELECT * FROM intelligence_records WHERE review_reason<>''")[0]
    assert "never discard me" in bad["raw_json"]


def test_duplicate_import_is_retained_but_excluded_from_analysis(tmp_path: Path) -> None:
    db = _database(tmp_path)
    source = tmp_path / "history.csv"
    _write_messy_history(source)

    import_vehicle_history(db, source)
    second = import_vehicle_history(db, source)

    assert second.duplicates == 4
    assert len(db.query("SELECT id FROM intelligence_records")) == 8
    result = analyse_opportunity(db, make="Audi", model="Q8", trim="S line")
    assert result["sample_size"] == 3
    assert result["identical_trim_samples"] == 2


def test_chat_screenshot_is_copied_and_persisted_with_message(tmp_path: Path) -> None:
    db = _database(tmp_path)
    screenshot = tmp_path / "deal-drive.png"
    screenshot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"market-evidence")
    message_id = save_chat_message(db, "user", "Challenge the price using this listing")

    saved = save_chat_attachments(db, message_id, [screenshot])
    conversation = chat_conversation(db)

    assert len(saved) == 1
    assert Path(saved[0]["stored_path"]).exists()
    assert conversation[0]["attachments"][0]["original_name"] == "deal-drive.png"


def test_exact_trim_has_priority_and_trim_position_is_reported(tmp_path: Path) -> None:
    db = _database(tmp_path)
    source = tmp_path / "history.csv"
    _write_messy_history(source)
    import_vehicle_history(db, source)

    result = analyse_opportunity(
        db, make="Audi", model="Q8", trim="S line", model_year=2024,
        purchase_price_aed=235000, expected_sale_price_aed=285000,
    )

    assert result["weights"]["time_to_sell"] == 50
    assert result["identical_trim_samples"] == 2
    assert result["median_days"] < 20
    assert result["trim_position"].startswith("Trim rank 1 of 2")
    assert result["decision"] in {"BUY", "NEGOTIATE", "AVOID"}


def test_no_matching_model_never_invents_a_grade(tmp_path: Path) -> None:
    db = _database(tmp_path)
    source = tmp_path / "history.csv"
    _write_messy_history(source)
    import_vehicle_history(db, source)

    result = analyse_opportunity(db, make="Toyota", model="Supra", trim="GR")

    assert result["grade"] == "NO GRADE"
    assert result["decision"] == "INSUFFICIENT DATA"


def test_snapshot_contains_index_and_every_retained_row(tmp_path: Path) -> None:
    db = _database(tmp_path); source = tmp_path / "history.csv"; _write_messy_history(source)
    import_vehicle_history(db, source); import_vehicle_history(db, source)

    index_path, history_path, context_path = write_intelligence_snapshot(db)

    index = json.loads(index_path.read_text())
    assert index["total_rows_retained"] == 8 and index["usable_rows"] == 3
    assert len(history_path.read_text().splitlines()) == 8
    assert "RUNWAY SNAPSHOT" in context_path.read_text() and '"Q8"' in context_path.read_text()


def test_explicit_owner_learning_is_durable_and_injected(tmp_path: Path) -> None:
    db = _database(tmp_path)
    instruction = "Add seasonality into every recommendation"
    assert learning_directive(instruction) == instruction
    assert learning_directive("Is an Audi Q8 worth buying?") is None
    memory_id = save_intelligence_memory(db, instruction)
    save_intelligence_memory(db, instruction.upper())
    save_chat_message(db, "user", instruction)
    save_chat_message(db, "assistant", "Understood.")

    assert len(intelligence_memories(db)) == 1
    evidence = chat_evidence(db)
    assert evidence["learned_preferences"] == [instruction.upper()]
    assert [message["role"] for message in evidence["recent_conversation"]] == ["user", "assistant"]
    context_path = write_intelligence_snapshot(db)[2]
    assert "OWNER-APPROVED LEARNED PREFERENCES" in context_path.read_text()
    assert instruction.upper() in context_path.read_text()

    forget_intelligence_memory(db, memory_id)
    assert intelligence_memories(db) == []


def test_chat_evidence_contains_authoritative_live_stock_snapshot(tmp_path: Path) -> None:
    db = _database(tmp_path)
    db.set_performance_budget(date.today().strftime("%Y-%m"), 2_000_000)
    db.add_vehicle(vehicle_name="Audi Q8", purchase_price_aed=227_000, expected_sale_price_aed=285_000, purchased_date=date.today().isoformat(), purchase_type="cash")
    db.add_vehicle(vehicle_name="Mercedes E-Class", purchase_price_aed=285_000, expected_sale_price_aed=305_000, purchased_date=date.today().isoformat(), purchase_type="consignment")

    stock = chat_evidence(db)["live_stock"]

    assert stock["count"] == 2
    assert stock["cash_purchase_count"] == 1 and stock["consignment_count"] == 1
    assert stock["cash_invested_aed"] == 227_000
    assert stock["cash_budget_remaining_aed"] == 1_773_000
    assert stock["total_expected_stock_profit_aed"] == 78_000
    assert stock["vehicles"][0]["vehicle"] in {"Audi Q8", "Mercedes E-Class"}
