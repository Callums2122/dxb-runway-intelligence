from __future__ import annotations

import csv
import base64
import json
import os
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
import zipfile

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


SCHEMA_VERSION = 27


MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS categories (
      id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL DEFAULT 'expense',
      monthly_limit_aed REAL NOT NULL DEFAULT 0, essential_default INTEGER NOT NULL DEFAULT 0, color TEXT NOT NULL DEFAULT '#4dd8ff'
    );
    CREATE TABLE IF NOT EXISTS transactions (
      id INTEGER PRIMARY KEY, amount REAL NOT NULL CHECK(amount >= 0), currency TEXT NOT NULL CHECK(currency IN ('AED','GBP')),
      occurred_at TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('income','expense')),
      category_id INTEGER REFERENCES categories(id), merchant TEXT NOT NULL DEFAULT '', payment_method TEXT NOT NULL,
      recurring INTEGER NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '', receipt_path TEXT,
      refundable_deposit INTEGER NOT NULL DEFAULT 0, essential INTEGER NOT NULL DEFAULT 0,
      tags TEXT NOT NULL DEFAULT '', deleted_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(occurred_at);
    CREATE TABLE IF NOT EXISTS credit_cards (
      id INTEGER PRIMARY KEY, name TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'GBP', credit_limit REAL NOT NULL,
      current_balance REAL NOT NULL DEFAULT 0, statement_day INTEGER NOT NULL DEFAULT 1, due_day INTEGER NOT NULL DEFAULT 20,
      minimum_payment REAL NOT NULL DEFAULT 0, apr REAL NOT NULL DEFAULT 0, promo_end TEXT
    );
    CREATE TABLE IF NOT EXISTS earnings (
      id INTEGER PRIMARY KEY, year INTEGER NOT NULL, month INTEGER NOT NULL, purchasing_budget_aed REAL NOT NULL,
      eligible_profit_aed REAL NOT NULL, average_margin_aed REAL NOT NULL DEFAULT 24700, deductions_aed REAL NOT NULL DEFAULT 0,
      tier TEXT NOT NULL, salary_aed REAL NOT NULL, commission_aed REAL NOT NULL, earned_date TEXT NOT NULL,
      payment_date TEXT NOT NULL, received INTEGER NOT NULL DEFAULT 0, UNIQUE(year, month)
    );
    CREATE TABLE IF NOT EXISTS budgets (
      id INTEGER PRIMARY KEY, month TEXT NOT NULL, category_id INTEGER REFERENCES categories(id), planned_aed REAL NOT NULL,
      rollover INTEGER NOT NULL DEFAULT 0, UNIQUE(month, category_id)
    );
    CREATE TABLE IF NOT EXISTS reminders (
      id INTEGER PRIMARY KEY, title TEXT NOT NULL, event_date TEXT NOT NULL, event_type TEXT NOT NULL,
      notes TEXT NOT NULL DEFAULT '', completed INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS goals (
      id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, target_value REAL NOT NULL DEFAULT 1,
      current_value REAL NOT NULL DEFAULT 0, achieved_at TEXT
    );
    CREATE TABLE IF NOT EXISTS exchange_rates (
      id INTEGER PRIMARY KEY, recorded_at TEXT NOT NULL, gbp_aed REAL NOT NULL CHECK(gbp_aed > 0)
    );
    """,
    2: """
    CREATE TABLE IF NOT EXISTS schema_audit (
      id INTEGER PRIMARY KEY, version INTEGER NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    3: """
    CREATE TABLE IF NOT EXISTS attachments (
      id INTEGER PRIMARY KEY, transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
      stored_path TEXT NOT NULL, original_name TEXT NOT NULL, added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    4: """
    UPDATE settings SET value='4.928313' WHERE key='gbp_aed_rate' AND value='4.75';
    INSERT OR IGNORE INTO settings(key,value) VALUES ('gbp_aed_rate_updated_at','2026-07-14');
    INSERT OR IGNORE INTO settings(key,value) VALUES ('gbp_aed_rate_source','Central Bank of the UAE');
    """,
    5: """
    CREATE TABLE IF NOT EXISTS vehicles (
      id INTEGER PRIMARY KEY,
      vehicle_name TEXT NOT NULL,
      purchase_price_aed REAL NOT NULL CHECK(purchase_price_aed >= 0),
      expected_sale_price_aed REAL NOT NULL CHECK(expected_sale_price_aed >= 0),
      purchased_date TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'stock' CHECK(status IN ('stock','sold')),
      sold_price_aed REAL,
      sold_date TEXT,
      notes TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_vehicles_stock_month ON vehicles(status, purchased_date);
    CREATE INDEX IF NOT EXISTS idx_vehicles_sold_month ON vehicles(status, sold_date);
    CREATE TABLE IF NOT EXISTS performance_months (
      month TEXT PRIMARY KEY,
      purchasing_budget_aed REAL NOT NULL DEFAULT 3000000 CHECK(purchasing_budget_aed >= 0),
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    6: """
    ALTER TABLE transactions ADD COLUMN highlighted INTEGER NOT NULL DEFAULT 0;
    """,
    7: """
    ALTER TABLE transactions ADD COLUMN credit_card_id INTEGER REFERENCES credit_cards(id) ON DELETE SET NULL;
    ALTER TABLE transactions ADD COLUMN card_effect INTEGER NOT NULL DEFAULT 0;
    CREATE INDEX IF NOT EXISTS idx_transactions_credit_card ON transactions(credit_card_id);
    """,
    8: """
    ALTER TABLE transactions ADD COLUMN budget_excluded INTEGER NOT NULL DEFAULT 0;
    """,
    9: """
    ALTER TABLE budgets ADD COLUMN due_date TEXT;
    """,
    10: """
    ALTER TABLE vehicles ADD COLUMN purchase_type TEXT NOT NULL DEFAULT 'cash'
      CHECK(purchase_type IN ('cash','consignment'));
    """,
    11: """
    CREATE TABLE IF NOT EXISTS customer_contacts (
      id INTEGER PRIMARY KEY,
      customer_name TEXT NOT NULL,
      vehicle_name TEXT NOT NULL,
      phone_last5 TEXT NOT NULL,
      mileage INTEGER NOT NULL DEFAULT 0 CHECK(mileage >= 0),
      vehicle_age_years INTEGER NOT NULL DEFAULT 0 CHECK(vehicle_age_years >= 0),
      vehicle_price_aed REAL NOT NULL DEFAULT 0 CHECK(vehicle_price_aed >= 0),
      cash_offer_aed REAL NOT NULL DEFAULT 0 CHECK(cash_offer_aed >= 0),
      consignment_offer_aed REAL NOT NULL DEFAULT 0 CHECK(consignment_offer_aed >= 0),
      rapport TEXT NOT NULL DEFAULT 'green' CHECK(rapport IN ('green','red')),
      last_contacted_date TEXT,
      next_contact_date TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','sold')),
      sold_date TEXT,
      notes TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_customer_contacts_due ON customer_contacts(status,next_contact_date);
    CREATE INDEX IF NOT EXISTS idx_customer_contacts_lookup ON customer_contacts(customer_name,vehicle_name,phone_last5);
    """,
    12: """
    CREATE TABLE IF NOT EXISTS customer_contact_notes (
      id INTEGER PRIMARY KEY,
      customer_id INTEGER NOT NULL REFERENCES customer_contacts(id) ON DELETE CASCADE,
      note_text TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_customer_contact_notes_customer ON customer_contact_notes(customer_id,created_at DESC,id DESC);
    """,
    13: """
    ALTER TABLE customer_contacts ADD COLUMN pipeline_stage TEXT NOT NULL DEFAULT 'caller'
      CHECK(pipeline_stage IN ('caller','inspection'));
    CREATE INDEX IF NOT EXISTS idx_customer_contacts_pipeline ON customer_contacts(pipeline_stage,status);
    """,
    14: """
    ALTER TABLE customer_contacts ADD COLUMN inspection_date TEXT;
    CREATE INDEX IF NOT EXISTS idx_customer_contacts_inspection_date ON customer_contacts(pipeline_stage,inspection_date);
    """,
    15: """
    CREATE TABLE IF NOT EXISTS message_templates (
      id INTEGER PRIMARY KEY,
      title TEXT NOT NULL,
      message_text TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_message_templates_title ON message_templates(title);
    """,
    16: """
    ALTER TABLE vehicles ADD COLUMN initial_owner_payout_aed REAL;
    """,
    17: """
    CREATE TABLE IF NOT EXISTS daily_tasks (
      id INTEGER PRIMARY KEY,
      task_date TEXT NOT NULL,
      title TEXT NOT NULL,
      completed INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      completed_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_daily_tasks_date ON daily_tasks(task_date,completed,created_at);
    """,
    18: """
    CREATE TABLE IF NOT EXISTS kpi_calls (
      id INTEGER PRIMARY KEY,
      called_at TEXT NOT NULL,
      phone_number TEXT NOT NULL,
      call_count INTEGER NOT NULL DEFAULT 1 CHECK(call_count > 0),
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_kpi_calls_date ON kpi_calls(called_at);
    CREATE TABLE IF NOT EXISTS kpi_work_days (
      work_date TEXT PRIMARY KEY,
      hours REAL NOT NULL CHECK(hours >= 0 AND hours <= 24),
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    19: """
    CREATE TABLE IF NOT EXISTS gym_profile (
      id INTEGER PRIMARY KEY CHECK(id=1),
      weight_kg REAL NOT NULL DEFAULT 70,
      height_cm REAL NOT NULL DEFAULT 175,
      calorie_target INTEGER NOT NULL DEFAULT 2200,
      protein_target_g INTEGER NOT NULL DEFAULT 140,
      carb_target_g INTEGER NOT NULL DEFAULT 230,
      fat_target_g INTEGER NOT NULL DEFAULT 70,
      fibre_target_g INTEGER NOT NULL DEFAULT 30,
      water_target_ml INTEGER NOT NULL DEFAULT 2500,
      training_days INTEGER NOT NULL DEFAULT 3,
      goal TEXT NOT NULL DEFAULT 'Body recomposition',
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    INSERT OR IGNORE INTO gym_profile(id) VALUES (1);
    CREATE TABLE IF NOT EXISTS gym_food_entries (
      id INTEGER PRIMARY KEY,
      entry_date TEXT NOT NULL,
      meal_name TEXT NOT NULL,
      calories REAL NOT NULL DEFAULT 0 CHECK(calories >= 0),
      protein_g REAL NOT NULL DEFAULT 0 CHECK(protein_g >= 0),
      carbs_g REAL NOT NULL DEFAULT 0 CHECK(carbs_g >= 0),
      fat_g REAL NOT NULL DEFAULT 0 CHECK(fat_g >= 0),
      fibre_g REAL NOT NULL DEFAULT 0 CHECK(fibre_g >= 0),
      source TEXT NOT NULL DEFAULT 'Manual',
      notes TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_gym_food_date ON gym_food_entries(entry_date,id);
    CREATE TABLE IF NOT EXISTS gym_workouts (
      id INTEGER PRIMARY KEY,
      workout_date TEXT NOT NULL,
      session_name TEXT NOT NULL,
      duration_min INTEGER NOT NULL DEFAULT 0 CHECK(duration_min >= 0),
      notes TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_gym_workouts_date ON gym_workouts(workout_date,id);
    CREATE TABLE IF NOT EXISTS gym_exercise_logs (
      id INTEGER PRIMARY KEY,
      workout_id INTEGER NOT NULL REFERENCES gym_workouts(id) ON DELETE CASCADE,
      exercise_name TEXT NOT NULL,
      set_count INTEGER NOT NULL DEFAULT 3 CHECK(set_count > 0),
      reps INTEGER NOT NULL DEFAULT 8 CHECK(reps > 0),
      weight_kg REAL NOT NULL DEFAULT 0 CHECK(weight_kg >= 0),
      rir INTEGER NOT NULL DEFAULT 2 CHECK(rir >= 0 AND rir <= 5)
    );
    CREATE TABLE IF NOT EXISTS gym_measurements (
      id INTEGER PRIMARY KEY,
      measured_date TEXT NOT NULL,
      weight_kg REAL NOT NULL CHECK(weight_kg > 0),
      waist_cm REAL NOT NULL DEFAULT 0 CHECK(waist_cm >= 0),
      chest_cm REAL NOT NULL DEFAULT 0 CHECK(chest_cm >= 0),
      arm_cm REAL NOT NULL DEFAULT 0 CHECK(arm_cm >= 0),
      thigh_cm REAL NOT NULL DEFAULT 0 CHECK(thigh_cm >= 0),
      notes TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_gym_measurements_date ON gym_measurements(measured_date,id);
    CREATE TABLE IF NOT EXISTS gym_habits (
      log_date TEXT PRIMARY KEY,
      water_ml INTEGER NOT NULL DEFAULT 0 CHECK(water_ml >= 0),
      bowel_movement INTEGER NOT NULL DEFAULT 0,
      stool_score INTEGER NOT NULL DEFAULT 0 CHECK(stool_score >= 0 AND stool_score <= 7),
      sleep_hours REAL NOT NULL DEFAULT 0 CHECK(sleep_hours >= 0 AND sleep_hours <= 24),
      notes TEXT NOT NULL DEFAULT '',
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS gym_meals (
      id INTEGER PRIMARY KEY,
      name TEXT NOT NULL UNIQUE,
      restaurant TEXT NOT NULL,
      provider TEXT NOT NULL,
      calories REAL NOT NULL,
      protein_g REAL NOT NULL,
      carbs_g REAL NOT NULL,
      fat_g REAL NOT NULL,
      fibre_g REAL NOT NULL,
      price_aed REAL NOT NULL DEFAULT 0,
      route TEXT NOT NULL DEFAULT 'Balanced',
      notes TEXT NOT NULL DEFAULT '',
      source_url TEXT NOT NULL DEFAULT '',
      checked_on TEXT NOT NULL DEFAULT '',
      active INTEGER NOT NULL DEFAULT 1
    );
    """,
    20: """
    CREATE TABLE IF NOT EXISTS gym_water_entries (
      id INTEGER PRIMARY KEY,
      entry_date TEXT NOT NULL,
      amount_ml INTEGER NOT NULL CHECK(amount_ml > 0),
      label TEXT NOT NULL DEFAULT 'Water',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_gym_water_date ON gym_water_entries(entry_date,id DESC);
    """,
    21: """
    CREATE TABLE IF NOT EXISTS intelligence_import_batches (
      id INTEGER PRIMARY KEY,
      file_name TEXT NOT NULL,
      stored_name TEXT NOT NULL,
      sha256 TEXT NOT NULL,
      file_size INTEGER NOT NULL DEFAULT 0,
      sheet_count INTEGER NOT NULL DEFAULT 1,
      source_rows INTEGER NOT NULL DEFAULT 0,
      usable_rows INTEGER NOT NULL DEFAULT 0,
      review_rows INTEGER NOT NULL DEFAULT 0,
      duplicate_rows INTEGER NOT NULL DEFAULT 0,
      imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_intelligence_batches_sha ON intelligence_import_batches(sha256,imported_at DESC);
    CREATE TABLE IF NOT EXISTS intelligence_records (
      id INTEGER PRIMARY KEY,
      batch_id INTEGER NOT NULL REFERENCES intelligence_import_batches(id) ON DELETE RESTRICT,
      sheet_name TEXT NOT NULL DEFAULT '',
      source_row INTEGER NOT NULL,
      raw_json TEXT NOT NULL,
      row_hash TEXT NOT NULL,
      duplicate_of INTEGER REFERENCES intelligence_records(id) ON DELETE SET NULL,
      external_id TEXT NOT NULL DEFAULT '',
      make TEXT NOT NULL DEFAULT '',
      model TEXT NOT NULL DEFAULT '',
      trim TEXT NOT NULL DEFAULT '',
      model_year INTEGER,
      mileage INTEGER,
      purchase_date TEXT,
      sold_date TEXT,
      advertised_price_aed REAL,
      purchase_price_aed REAL,
      sold_price_aed REAL,
      preparation_cost_aed REAL NOT NULL DEFAULT 0,
      purchase_type TEXT NOT NULL DEFAULT '',
      specification TEXT NOT NULL DEFAULT '',
      sales_channel TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT '',
      data_quality REAL NOT NULL DEFAULT 0,
      review_reason TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_intelligence_vehicle ON intelligence_records(make,model,trim,model_year);
    CREATE INDEX IF NOT EXISTS idx_intelligence_dates ON intelligence_records(purchase_date,sold_date);
    CREATE INDEX IF NOT EXISTS idx_intelligence_row_hash ON intelligence_records(row_hash);
    """,
    22: """
    CREATE TABLE IF NOT EXISTS intelligence_trim_catalog (
      id INTEGER PRIMARY KEY,
      make TEXT NOT NULL,
      model TEXT NOT NULL,
      trim TEXT NOT NULL,
      trim_rank INTEGER,
      trim_count INTEGER,
      market TEXT NOT NULL DEFAULT 'UAE',
      generation TEXT NOT NULL DEFAULT '',
      aliases_json TEXT NOT NULL DEFAULT '[]',
      source TEXT NOT NULL DEFAULT 'Imported evidence',
      source_url TEXT NOT NULL DEFAULT '',
      researched_at TEXT,
      confidence TEXT NOT NULL DEFAULT 'unverified',
      UNIQUE(make,model,trim,market,generation)
    );
    CREATE INDEX IF NOT EXISTS idx_intelligence_trim_lookup ON intelligence_trim_catalog(make,model,trim);
    """,
    23: """
    CREATE TABLE IF NOT EXISTS intelligence_chat_messages (
      id INTEGER PRIMARY KEY,
      role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
      message TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS intelligence_policy_audit (
      id INTEGER PRIMARY KEY,
      event_type TEXT NOT NULL,
      detail TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    24: """
    CREATE TABLE IF NOT EXISTS intelligence_memories (
      id INTEGER PRIMARY KEY,
      memory_text TEXT NOT NULL,
      normalized_text TEXT NOT NULL UNIQUE,
      source TEXT NOT NULL DEFAULT 'conversation',
      active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_intelligence_memories_active ON intelligence_memories(active,created_at DESC);
    """,
    25: """
    CREATE TABLE IF NOT EXISTS intelligence_chat_attachments (
      id INTEGER PRIMARY KEY,
      message_id INTEGER NOT NULL REFERENCES intelligence_chat_messages(id) ON DELETE CASCADE,
      stored_path TEXT NOT NULL,
      original_name TEXT NOT NULL,
      mime_type TEXT NOT NULL,
      file_size INTEGER NOT NULL CHECK(file_size > 0),
      sha256 TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_intelligence_chat_attachments_message
      ON intelligence_chat_attachments(message_id,id);
    """,
    26: """
    CREATE TABLE IF NOT EXISTS deal_drive_sync_runs (
      id INTEGER PRIMARY KEY,
      started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      completed_at TEXT,
      status TEXT NOT NULL CHECK(status IN ('running','success','failed')),
      country_code TEXT NOT NULL DEFAULT 'AE',
      requested_limit INTEGER NOT NULL,
      offer_count INTEGER NOT NULL DEFAULT 0,
      detail TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS deal_drive_market_offers (
      id INTEGER PRIMARY KEY,
      sync_run_id INTEGER NOT NULL REFERENCES deal_drive_sync_runs(id) ON DELETE CASCADE,
      offer_id TEXT NOT NULL,
      captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      source_name TEXT NOT NULL DEFAULT '', external_id TEXT NOT NULL DEFAULT '', listing_url TEXT NOT NULL DEFAULT '',
      price_aed REAL, market_price_aed REAL, market_price_diff REAL,
      brand TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', model_version TEXT NOT NULL DEFAULT '',
      generation TEXT NOT NULL DEFAULT '', modification TEXT NOT NULL DEFAULT '', trim TEXT NOT NULL DEFAULT '',
      model_year INTEGER, mileage_km REAL, regional_spec TEXT NOT NULL DEFAULT '', seller_type TEXT NOT NULL DEFAULT '',
      published_at TEXT, source_updated_at TEXT, deleted INTEGER NOT NULL DEFAULT 0,
      price_history_json TEXT NOT NULL DEFAULT '[]', raw_json TEXT NOT NULL,
      UNIQUE(sync_run_id,offer_id)
    );
    CREATE INDEX IF NOT EXISTS idx_deal_drive_offer_vehicle ON deal_drive_market_offers(brand,model,trim,model_year);
    CREATE INDEX IF NOT EXISTS idx_deal_drive_offer_run ON deal_drive_market_offers(sync_run_id);
    """,
    27: """
    ALTER TABLE deal_drive_market_offers ADD COLUMN address TEXT NOT NULL DEFAULT '';
    ALTER TABLE deal_drive_market_offers ADD COLUMN latitude REAL;
    ALTER TABLE deal_drive_market_offers ADD COLUMN longitude REAL;
    ALTER TABLE deal_drive_market_offers ADD COLUMN seller_id TEXT NOT NULL DEFAULT '';
    ALTER TABLE deal_drive_market_offers ADD COLUMN seller_name TEXT NOT NULL DEFAULT '';
    ALTER TABLE deal_drive_market_offers ADD COLUMN active_market INTEGER NOT NULL DEFAULT 1;
    ALTER TABLE deal_drive_market_offers ADD COLUMN duplicate_of_offer_id TEXT;
    ALTER TABLE deal_drive_market_offers ADD COLUMN exclusion_reason TEXT NOT NULL DEFAULT '';
    ALTER TABLE deal_drive_market_offers ADD COLUMN comparison_weight REAL;
    """,
}


DEFAULT_CATEGORIES = [
    ("Accommodation", 1, "#7f75ff"), ("Transport", 1, "#4dd8ff"), ("Groceries", 1, "#31d69b"),
    ("Restaurants", 0, "#f4b740"), ("Phone", 1, "#70a5ff"), ("Utilities", 1, "#9b8cff"),
    ("Visa/administration", 1, "#ac93ff"), ("Flight/relocation", 1, "#5ad6c8"),
    ("Clothing", 0, "#df79d6"), ("Entertainment", 0, "#ff7ba6"), ("Subscriptions", 0, "#f6cc62"),
    ("Debt repayment", 1, "#ff8a4c"), ("Emergency", 1, "#ff5d73"), ("Miscellaneous", 0, "#7f8ba8"),
    ("Salary", 1, "#31d69b"), ("Commission", 1, "#40e0b2"), ("Refund", 1, "#79e3bc"),
]


DEFAULT_SETTINGS = {
    "gbp_aed_rate": "4.928313", "gbp_aed_rate_updated_at": "2026-07-14",
    "gbp_aed_rate_source": "Central Bank of the UAE", "uk_cash_gbp": "2000", "available_credit_gbp": "4000",
    "salary_aed": "6000", "rent_aed": "4500", "security_deposit_aed": "1000",
    "transport_aed": "2000", "food_aed": "1250", "emergency_fund_aed": "3000",
    "monthly_spending_cap_gbp": "1700",
    "start_date": "2026-07-27", "arrival_date": "2026-07-23", "onboarding_complete": "0",
    "why_i_moved": "Build a stronger future with patience, focus and options.", "quote": "Protect the runway. Earn the upside.",
    "theme": "dark", "start_of_month": "1", "currency_preference": "AED",
}


DEFAULT_GYM_MEALS = [
    ("Healthy Chicken Bowl", "Healthy Bowl", "Talabat", 499, 38, 48, 16, 8, 33, "Best all-rounder", "Brown rice, roast chicken, vegetables and avocado; fibre is estimated.", "https://www.talabat.com/uae/restaurant/795479/healthy-bowl-al-hudaiba?aid=4577", "2026-08-12"),
    ("Oven Baked Chicken With Rice Bowl", "Healthy Bowl", "Talabat", 428, 36, 51, 10, 6, 30, "Lean meal", "Chicken breast, rice and broccoli; fibre is estimated.", "https://www.talabat.com/uae/restaurant/795479/healthy-bowl-al-hudaiba?aid=4577", "2026-08-12"),
    ("Chicken Burrito Bowl", "Healthy Bowl", "Talabat", 428, 36, 51, 10, 9, 35, "High fibre", "Brown rice, beans, vegetables and chicken; fibre is estimated.", "https://www.talabat.com/uae/restaurant/795479/healthy-bowl-al-hudaiba?aid=4577", "2026-08-12"),
    ("Healthy Chicken Tikka Bowl", "Healthy Bowl", "Talabat", 408, 32, 48, 9, 5, 33, "Lean meal", "Tikka chicken and rice; add a vegetable side when possible.", "https://www.talabat.com/uae/restaurant/795479/healthy-bowl-al-hudaiba?aid=4577", "2026-08-12"),
    ("Tokyo Chicken Bowl", "Kcal", "Deliveroo / search other apps", 442, 49.9, 31, 14.4, 6, 54, "High protein", "Chicken, vegetables and carrot noodles; fibre is estimated.", "https://deliveroo.ae/en/menu/Dubai/lower-satwa/kcal-the-original-healthy-restaurant-satwa", "2026-08-12"),
    ("Chipotle Chicken Bowl", "Kcal", "Deliveroo / search other apps", 400, 40, 27.5, 16, 8, 54, "High protein", "Includes listed guacamole and salsa; fibre is estimated.", "https://deliveroo.ae/en/menu/Dubai/lower-satwa/kcal-the-original-healthy-restaurant-satwa", "2026-08-12"),
    ("Sweet Chilli Chicken Bowl", "Kcal", "Deliveroo / search other apps", 422, 41.5, 36.1, 14.8, 7, 56, "High protein", "Vegetables and cauliflower rice; fibre and price are estimates.", "https://deliveroo.ae/en/menu/Dubai/lower-satwa/kcal-the-original-healthy-restaurant-satwa", "2026-08-12"),
    ("Manila-Style Chicken Sisig", "Under500", "Deliveroo / search other apps", 487, 34, 47, 17, 5, 35, "Balanced", "Chicken with brown rice; fibre is estimated.", "https://deliveroo.ae/en/menu/Dubai/marina/under-500-dubai-marina", "2026-08-12"),
    ("Summer Chicken", "Better", "Deliveroo / search other apps", 264.5, 22, 25, 8.5, 5, 75, "Light meal", "Small meal; pair with fruit or yogurt if it leaves you hungry.", "https://deliveroo.ae/en/menu/dubai/dubai-business-bay/better", "2026-08-12"),
    ("High Protein Chicken Quinoa Bowl", "Healthy Bowl JVC", "Deliveroo / search other apps", 610, 48, 55, 22, 11, 81, "High fibre", "Menu does not publish macros; values are a conservative ingredient estimate. Dressing on the side.", "https://deliveroo.ae/en/menu/dubai/jumeirah-village-circle/healthy-bowl-jvc", "2026-08-12"),
]


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.receipts_dir = self.path.parent / "receipts"
        self.receipts_dir.mkdir(exist_ok=True)
        self.intelligence_imports_dir = self.path.parent / "intelligence_imports"
        self.intelligence_imports_dir.mkdir(exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        with self.connect() as connection:
            current = connection.execute("PRAGMA user_version").fetchone()[0]
            for version in range(current + 1, SCHEMA_VERSION + 1):
                if version == 6:
                    columns = {row[1] for row in connection.execute("PRAGMA table_info(transactions)").fetchall()}
                    if "highlighted" not in columns:
                        connection.executescript(MIGRATIONS[version])
                elif version == 7:
                    columns = {row[1] for row in connection.execute("PRAGMA table_info(transactions)").fetchall()}
                    if "credit_card_id" not in columns:
                        connection.execute("ALTER TABLE transactions ADD COLUMN credit_card_id INTEGER REFERENCES credit_cards(id) ON DELETE SET NULL")
                    if "card_effect" not in columns:
                        connection.execute("ALTER TABLE transactions ADD COLUMN card_effect INTEGER NOT NULL DEFAULT 0")
                    connection.execute("CREATE INDEX IF NOT EXISTS idx_transactions_credit_card ON transactions(credit_card_id)")
                elif version == 8:
                    columns = {row[1] for row in connection.execute("PRAGMA table_info(transactions)").fetchall()}
                    if "budget_excluded" not in columns:
                        connection.execute("ALTER TABLE transactions ADD COLUMN budget_excluded INTEGER NOT NULL DEFAULT 0")
                elif version == 9:
                    columns = {row[1] for row in connection.execute("PRAGMA table_info(budgets)").fetchall()}
                    if "due_date" not in columns:
                        connection.execute("ALTER TABLE budgets ADD COLUMN due_date TEXT")
                elif version == 10:
                    columns = {row[1] for row in connection.execute("PRAGMA table_info(vehicles)").fetchall()}
                    if "purchase_type" not in columns:
                        connection.executescript(MIGRATIONS[version])
                elif version == 13:
                    columns = {row[1] for row in connection.execute("PRAGMA table_info(customer_contacts)").fetchall()}
                    if "pipeline_stage" not in columns:
                        connection.execute("ALTER TABLE customer_contacts ADD COLUMN pipeline_stage TEXT NOT NULL DEFAULT 'caller' CHECK(pipeline_stage IN ('caller','inspection'))")
                    connection.execute("CREATE INDEX IF NOT EXISTS idx_customer_contacts_pipeline ON customer_contacts(pipeline_stage,status)")
                elif version == 14:
                    columns = {row[1] for row in connection.execute("PRAGMA table_info(customer_contacts)").fetchall()}
                    if "inspection_date" not in columns:
                        connection.execute("ALTER TABLE customer_contacts ADD COLUMN inspection_date TEXT")
                    connection.execute("CREATE INDEX IF NOT EXISTS idx_customer_contacts_inspection_date ON customer_contacts(pipeline_stage,inspection_date)")
                elif version == 16:
                    columns = {row[1] for row in connection.execute("PRAGMA table_info(vehicles)").fetchall()}
                    if "initial_owner_payout_aed" not in columns:
                        connection.execute("ALTER TABLE vehicles ADD COLUMN initial_owner_payout_aed REAL")
                elif version == 27:
                    columns = {row[1] for row in connection.execute("PRAGMA table_info(deal_drive_market_offers)").fetchall()}
                    definitions = {
                        "address":"TEXT NOT NULL DEFAULT ''", "latitude":"REAL", "longitude":"REAL",
                        "seller_id":"TEXT NOT NULL DEFAULT ''", "seller_name":"TEXT NOT NULL DEFAULT ''",
                        "active_market":"INTEGER NOT NULL DEFAULT 1", "duplicate_of_offer_id":"TEXT",
                        "exclusion_reason":"TEXT NOT NULL DEFAULT ''", "comparison_weight":"REAL",
                    }
                    for column, definition in definitions.items():
                        if column not in columns: connection.execute(f"ALTER TABLE deal_drive_market_offers ADD COLUMN {column} {definition}")
                else:
                    connection.executescript(MIGRATIONS[version])
                connection.execute(f"PRAGMA user_version={version}")
                if version >= 2:
                    connection.execute("INSERT INTO schema_audit(version) VALUES (?)", (version,))
            # Recover safely if an interrupted app replacement stamped v19 before its
            # new Gym tables reached disk. All statements are CREATE IF NOT EXISTS.
            gym_tables={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'gym_%'").fetchall()}
            if "gym_meals" not in gym_tables:
                connection.executescript(MIGRATIONS[19])
            gym_tables={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'gym_%'").fetchall()}
            if "gym_water_entries" not in gym_tables:
                connection.executescript(MIGRATIONS[20])
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.executemany(
                "INSERT OR IGNORE INTO categories(name, essential_default, color) VALUES (?,?,?)", DEFAULT_CATEGORIES
            )
            connection.executemany("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", DEFAULT_SETTINGS.items())
            connection.executemany(
                "INSERT OR IGNORE INTO gym_meals(name,restaurant,provider,calories,protein_g,carbs_g,fat_g,fibre_g,price_aed,route,notes,source_url,checked_on) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                DEFAULT_GYM_MEALS,
            )

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(connection.execute(sql, params).fetchall())

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self.connect() as connection:
            cursor = connection.execute(sql, params)
            return int(cursor.lastrowid or cursor.rowcount)

    def get_setting(self, key: str, default: str = "") -> str:
        rows = self.query("SELECT value FROM settings WHERE key=?", (key,))
        return str(rows[0]["value"]) if rows else default

    def set_setting(self, key: str, value: str | int | float) -> None:
        self.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, str(value)))

    def all_settings(self) -> dict[str, str]:
        return {str(row["key"]): str(row["value"]) for row in self.query("SELECT key,value FROM settings")}

    def mobile_sync_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        """Return the small, read-only dataset mirrored to the private phone app."""
        vehicles = [dict(row) for row in self.query(
            "SELECT id,vehicle_name,purchase_price_aed,expected_sale_price_aed,purchased_date,status,"
            "sold_price_aed,sold_date,notes,purchase_type,initial_owner_payout_aed,updated_at "
            "FROM vehicles ORDER BY id"
        )]
        months = [dict(row) for row in self.query(
            "SELECT month,purchasing_budget_aed,updated_at FROM performance_months ORDER BY month"
        )]
        earnings = [dict(row) for row in self.query(
            "SELECT year,month,purchasing_budget_aed,eligible_profit_aed,tier,salary_aed,commission_aed,"
            "payment_date,received FROM earnings ORDER BY year,month"
        )]
        return {"vehicles": vehicles, "months": months, "earnings": earnings}

    def daily_tasks(self, task_date: str | None = None) -> list[sqlite3.Row]:
        chosen_date=str(task_date or date.today().isoformat())[:10]
        date.fromisoformat(chosen_date)
        return self.query("SELECT * FROM daily_tasks WHERE task_date=? ORDER BY completed ASC,created_at ASC,id ASC",(chosen_date,))

    def add_daily_task(self, title: str, task_date: str | None = None) -> int:
        clean_title=str(title).strip()
        if not clean_title: raise ValueError("Task cannot be empty")
        chosen_date=str(task_date or date.today().isoformat())[:10]
        date.fromisoformat(chosen_date)
        return self.execute("INSERT INTO daily_tasks(task_date,title) VALUES (?,?)",(chosen_date,clean_title))

    def set_daily_task_completed(self, task_id: int, completed: bool) -> None:
        if not self.query("SELECT id FROM daily_tasks WHERE id=?",(task_id,)): raise ValueError("Task does not exist")
        self.execute("UPDATE daily_tasks SET completed=?,completed_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END WHERE id=?",(int(completed),int(completed),task_id))

    def delete_daily_task(self, task_id: int) -> None:
        if self.execute("DELETE FROM daily_tasks WHERE id=?",(task_id,))!=1: raise ValueError("Task does not exist")

    def add_kpi_calls(self, phone_number: str, call_count: int = 1, called_at: str | None = None) -> int:
        phone=str(phone_number).strip(); count=int(call_count); chosen_date=str(called_at or date.today().isoformat())[:10]
        if not phone: raise ValueError("Phone number is required")
        if count<1: raise ValueError("Call count must be at least one")
        date.fromisoformat(chosen_date)
        return self.execute("INSERT INTO kpi_calls(called_at,phone_number,call_count) VALUES (?,?,?)",(chosen_date,phone,count))

    def kpi_calls(self, month: str) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM kpi_calls WHERE substr(called_at,1,7)=? ORDER BY called_at DESC,id DESC",(month,))

    def delete_kpi_call(self, call_id: int) -> None:
        if self.execute("DELETE FROM kpi_calls WHERE id=?",(call_id,))!=1: raise ValueError("Call log does not exist")

    def save_kpi_work_day(self, work_date: str, hours: float) -> None:
        chosen_date=str(work_date)[:10]; date.fromisoformat(chosen_date); value=float(hours)
        if value<0 or value>24: raise ValueError("Hours must be between 0 and 24")
        self.execute("INSERT INTO kpi_work_days(work_date,hours) VALUES (?,?) ON CONFLICT(work_date) DO UPDATE SET hours=excluded.hours,updated_at=CURRENT_TIMESTAMP",(chosen_date,value))

    def kpi_work_days(self, month: str) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM kpi_work_days WHERE substr(work_date,1,7)=? ORDER BY work_date DESC",(month,))

    def gym_profile(self) -> sqlite3.Row:
        return self.query("SELECT * FROM gym_profile WHERE id=1")[0]

    def save_gym_profile(self, values: dict[str, Any]) -> None:
        allowed=("weight_kg","height_cm","calorie_target","protein_target_g","carb_target_g","fat_target_g","fibre_target_g","water_target_ml","training_days","goal")
        pairs=[(key,values[key]) for key in allowed if key in values]
        if not pairs: return
        numeric={"weight_kg","height_cm","calorie_target","protein_target_g","carb_target_g","fat_target_g","fibre_target_g","water_target_ml","training_days"}
        if any(float(value)<=0 for key,value in pairs if key in numeric): raise ValueError("Gym targets must be greater than zero")
        self.execute(f"UPDATE gym_profile SET {','.join(f'{key}=?' for key,_ in pairs)},updated_at=CURRENT_TIMESTAMP WHERE id=1",tuple(value for _,value in pairs))

    def gym_food_entries(self, entry_date: str | None = None) -> list[sqlite3.Row]:
        chosen=str(entry_date or date.today().isoformat())[:10]; date.fromisoformat(chosen)
        return self.query("SELECT * FROM gym_food_entries WHERE entry_date=? ORDER BY id DESC",(chosen,))

    def add_gym_food(self, values: dict[str, Any]) -> int:
        chosen=str(values.get("entry_date") or date.today().isoformat())[:10]; date.fromisoformat(chosen)
        name=str(values.get("meal_name","")).strip()
        if not name: raise ValueError("Meal name is required")
        numbers=[max(0,float(values.get(key,0) or 0)) for key in ("calories","protein_g","carbs_g","fat_g","fibre_g")]
        return self.execute("INSERT INTO gym_food_entries(entry_date,meal_name,calories,protein_g,carbs_g,fat_g,fibre_g,source,notes) VALUES (?,?,?,?,?,?,?,?,?)",(chosen,name,*numbers,str(values.get("source","Manual")),str(values.get("notes","")).strip()))

    def delete_gym_food(self, entry_id: int) -> None:
        if self.execute("DELETE FROM gym_food_entries WHERE id=?",(entry_id,))!=1: raise ValueError("Meal entry not found")

    def gym_daily_totals(self, entry_date: str | None = None) -> dict[str,float]:
        chosen=str(entry_date or date.today().isoformat())[:10]
        row=self.query("SELECT COALESCE(SUM(calories),0) calories,COALESCE(SUM(protein_g),0) protein_g,COALESCE(SUM(carbs_g),0) carbs_g,COALESCE(SUM(fat_g),0) fat_g,COALESCE(SUM(fibre_g),0) fibre_g FROM gym_food_entries WHERE entry_date=?",(chosen,))[0]
        return {key:float(row[key]) for key in row.keys()}

    def gym_habit(self, log_date: str | None = None) -> dict[str,Any]:
        chosen=str(log_date or date.today().isoformat())[:10]
        rows=self.query("SELECT * FROM gym_habits WHERE log_date=?",(chosen,))
        return dict(rows[0]) if rows else {"log_date":chosen,"water_ml":0,"bowel_movement":0,"stool_score":0,"sleep_hours":0,"notes":""}

    def save_gym_habit(self, log_date: str | None = None, **values: Any) -> None:
        chosen=str(log_date or date.today().isoformat())[:10]; date.fromisoformat(chosen)
        current=self.gym_habit(chosen); current.update(values)
        water=max(0,int(current.get("water_ml",0))); stool=max(0,min(7,int(current.get("stool_score",0)))); sleep=max(0,min(24,float(current.get("sleep_hours",0))))
        self.execute("INSERT INTO gym_habits(log_date,water_ml,bowel_movement,stool_score,sleep_hours,notes) VALUES (?,?,?,?,?,?) ON CONFLICT(log_date) DO UPDATE SET water_ml=excluded.water_ml,bowel_movement=excluded.bowel_movement,stool_score=excluded.stool_score,sleep_hours=excluded.sleep_hours,notes=excluded.notes,updated_at=CURRENT_TIMESTAMP",(chosen,water,int(bool(current.get("bowel_movement",0))),stool,sleep,str(current.get("notes","")).strip()))

    def add_gym_water(self, amount_ml: int, label: str = "Bottle", entry_date: str | None = None) -> int:
        chosen=str(entry_date or date.today().isoformat())[:10]; date.fromisoformat(chosen); amount=int(amount_ml)
        if amount<=0 or amount>5000: raise ValueError("Water amount must be between 1 ml and 5,000 ml")
        clean_label=str(label).strip() or "Water"
        with self.connect() as connection:
            cursor=connection.execute("INSERT INTO gym_water_entries(entry_date,amount_ml,label,created_at) VALUES (?,?,?,?)",(chosen,amount,clean_label,datetime.now().isoformat(timespec="seconds")))
            connection.execute(
                "INSERT INTO gym_habits(log_date,water_ml) VALUES (?,?) ON CONFLICT(log_date) DO UPDATE SET water_ml=water_ml+excluded.water_ml,updated_at=CURRENT_TIMESTAMP",
                (chosen,amount),
            )
            return int(cursor.lastrowid)

    def gym_water_entries(self, entry_date: str | None = None) -> list[sqlite3.Row]:
        chosen=str(entry_date or date.today().isoformat())[:10]; date.fromisoformat(chosen)
        return self.query("SELECT * FROM gym_water_entries WHERE entry_date=? ORDER BY id DESC",(chosen,))

    def delete_gym_water(self, entry_id: int) -> None:
        with self.connect() as connection:
            row=connection.execute("SELECT id,entry_date,amount_ml FROM gym_water_entries WHERE id=?",(entry_id,)).fetchone()
            if not row: raise ValueError("Water entry not found")
            connection.execute("DELETE FROM gym_water_entries WHERE id=?",(entry_id,))
            connection.execute("UPDATE gym_habits SET water_ml=MAX(0,water_ml-?),updated_at=CURRENT_TIMESTAMP WHERE log_date=?",(row["amount_ml"],row["entry_date"]))

    def gym_logging_streak(self, today: date | None = None) -> int:
        current=today or date.today()
        rows=self.query("SELECT entry_date day FROM gym_food_entries UNION SELECT entry_date day FROM gym_water_entries")
        logged={date.fromisoformat(str(row["day"])[:10]) for row in rows}
        cursor=current if current in logged else current-timedelta(days=1); streak=0
        while cursor in logged:
            streak+=1; cursor-=timedelta(days=1)
        return streak

    def add_gym_workout(self, workout_date: str, session_name: str, duration_min: int, exercises: list[dict[str,Any]], notes: str = "") -> int:
        chosen=str(workout_date)[:10]; date.fromisoformat(chosen); session=str(session_name).strip()
        if not session: raise ValueError("Session name is required")
        if not exercises: raise ValueError("Add at least one exercise")
        with self.connect() as connection:
            cursor=connection.execute("INSERT INTO gym_workouts(workout_date,session_name,duration_min,notes) VALUES (?,?,?,?)",(chosen,session,max(0,int(duration_min)),notes.strip()))
            workout_id=int(cursor.lastrowid)
            connection.executemany("INSERT INTO gym_exercise_logs(workout_id,exercise_name,set_count,reps,weight_kg,rir) VALUES (?,?,?,?,?,?)",[(workout_id,str(item["exercise_name"]),max(1,int(item["set_count"])),max(1,int(item["reps"])),max(0,float(item["weight_kg"])),max(0,min(5,int(item["rir"])))) for item in exercises])
            return workout_id

    def gym_workouts(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.query("SELECT w.*,COUNT(e.id) exercises,COALESCE(SUM(e.set_count*e.reps*e.weight_kg),0) volume_kg FROM gym_workouts w LEFT JOIN gym_exercise_logs e ON e.workout_id=w.id GROUP BY w.id ORDER BY workout_date DESC,w.id DESC LIMIT ?",(limit,))

    def gym_last_exercise(self, exercise_name: str) -> sqlite3.Row | None:
        rows=self.query(
            "SELECT e.*,w.workout_date,w.session_name FROM gym_exercise_logs e JOIN gym_workouts w ON w.id=e.workout_id "
            "WHERE e.exercise_name=? ORDER BY w.workout_date DESC,e.id DESC LIMIT 1",
            (str(exercise_name).strip(),),
        )
        return rows[0] if rows else None

    def add_gym_measurement(self, values: dict[str,Any]) -> int:
        chosen=str(values.get("measured_date") or date.today().isoformat())[:10]; date.fromisoformat(chosen); weight=float(values.get("weight_kg",0))
        if weight<=0: raise ValueError("Weight must be greater than zero")
        fields=[max(0,float(values.get(key,0) or 0)) for key in ("waist_cm","chest_cm","arm_cm","thigh_cm")]
        measurement_id=self.execute("INSERT INTO gym_measurements(measured_date,weight_kg,waist_cm,chest_cm,arm_cm,thigh_cm,notes) VALUES (?,?,?,?,?,?,?)",(chosen,weight,*fields,str(values.get("notes","")).strip()))
        self.save_gym_profile({"weight_kg":weight})
        return measurement_id

    def gym_measurements(self, limit: int = 100) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM gym_measurements ORDER BY measured_date DESC,id DESC LIMIT ?",(limit,))

    def delete_gym_measurement(self, measurement_id: int) -> None:
        if self.execute("DELETE FROM gym_measurements WHERE id=?",(measurement_id,))!=1: raise ValueError("Measurement not found")

    def gym_meals(self, search: str = "", provider: str = "") -> list[sqlite3.Row]:
        clauses=["active=1"]; params:list[Any]=[]
        if search:
            clauses.append("(name LIKE ? OR restaurant LIKE ? OR route LIKE ? OR notes LIKE ?)"); params.extend([f"%{search}%"]*4)
        if provider and provider!="All": clauses.append("provider LIKE ?"); params.append(f"%{provider}%")
        return self.query(f"SELECT * FROM gym_meals WHERE {' AND '.join(clauses)} ORDER BY protein_g/calories DESC,name",tuple(params))

    def save_credit_card(self, values: dict[str, Any], card_id: int | None = None) -> int:
        credit_limit = Decimal(str(values["credit_limit"]))
        if credit_limit < 0:
            raise ValueError("Credit limit cannot be negative")
        if card_id is None:
            params = (
                str(values.get("name", "")).strip() or "Credit card",
                values.get("currency", "GBP"),
                float(credit_limit),
                float(values.get("minimum_payment", 0)),
                float(values.get("apr", 0)),
            )
            return self.execute(
                "INSERT INTO credit_cards(name,currency,credit_limit,current_balance,minimum_payment,apr) "
                "VALUES (?,?,?,0,?,?)", params
            )
        if not self.query("SELECT id FROM credit_cards WHERE id=?", (card_id,)):
            raise ValueError("Credit card does not exist")
        self.execute("UPDATE credit_cards SET credit_limit=? WHERE id=?", (float(credit_limit), card_id))
        return card_id

    def delete_credit_card(self, card_id: int) -> None:
        self.execute("DELETE FROM credit_cards WHERE id=?", (card_id,))

    def add_transaction(self, values: dict[str, Any]) -> int:
        required = {"amount", "currency", "occurred_at", "kind", "payment_method"}
        if missing := required - values.keys():
            raise ValueError(f"Missing transaction fields: {', '.join(sorted(missing))}")
        values = dict(values)
        values["receipt_path"] = self._store_receipt(values.get("receipt_path"))
        card_id, card_effect = self._normalise_card_link(values)
        values["credit_card_id"], values["card_effect"] = card_id, card_effect
        columns = [
            "amount", "currency", "occurred_at", "kind", "category_id", "merchant", "payment_method",
            "recurring", "notes", "receipt_path", "refundable_deposit", "essential", "tags", "credit_card_id", "card_effect", "budget_excluded"
        ]
        params = tuple(values.get(column, 0 if column == "budget_excluded" else "" if column in {"merchant", "notes", "tags"} else None) for column in columns)
        transaction_id = self.execute(
            f"INSERT INTO transactions({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", params
        )
        if card_effect:
            self._adjust_card_balance(card_id, values["amount"], values["currency"], card_effect)
        return transaction_id

    def update_transaction(self, transaction_id: int, values: dict[str, Any]) -> None:
        allowed = {"amount", "currency", "occurred_at", "kind", "category_id", "merchant", "payment_method",
                   "recurring", "notes", "receipt_path", "refundable_deposit", "essential", "tags", "credit_card_id", "card_effect", "budget_excluded"}
        old_rows = self.query("SELECT * FROM transactions WHERE id=?", (transaction_id,))
        if not old_rows:
            raise ValueError("Transaction does not exist")
        old = old_rows[0]
        if old["card_effect"] and old["credit_card_id"]:
            self._adjust_card_balance(old["credit_card_id"], old["amount"], old["currency"], -int(old["card_effect"]))
        values = dict(values)
        values["receipt_path"] = self._store_receipt(values.get("receipt_path"))
        card_id, card_effect = self._normalise_card_link(values)
        values["credit_card_id"], values["card_effect"] = card_id, card_effect
        pairs = [(key, value) for key, value in values.items() if key in allowed]
        if not pairs:
            return
        self.execute(f"UPDATE transactions SET {','.join(f'{key}=?' for key, _ in pairs)} WHERE id=?",
                     tuple(value for _, value in pairs) + (transaction_id,))
        if card_effect:
            self._adjust_card_balance(card_id, values["amount"], values["currency"], card_effect)

    def soft_delete_transaction(self, transaction_id: int) -> None:
        rows = self.query("SELECT * FROM transactions WHERE id=? AND deleted_at IS NULL", (transaction_id,))
        if rows and rows[0]["card_effect"] and rows[0]["credit_card_id"]:
            self._adjust_card_balance(rows[0]["credit_card_id"], rows[0]["amount"], rows[0]["currency"], -int(rows[0]["card_effect"]))
        self.execute("UPDATE transactions SET deleted_at=CURRENT_TIMESTAMP WHERE id=?", (transaction_id,))

    def undo_delete(self, transaction_id: int) -> None:
        rows = self.query("SELECT * FROM transactions WHERE id=? AND deleted_at IS NOT NULL", (transaction_id,))
        if rows and rows[0]["card_effect"] and rows[0]["credit_card_id"]:
            self._adjust_card_balance(rows[0]["credit_card_id"], rows[0]["amount"], rows[0]["currency"], int(rows[0]["card_effect"]))
        self.execute("UPDATE transactions SET deleted_at=NULL WHERE id=?", (transaction_id,))

    def toggle_transaction_highlight(self, transaction_id: int) -> bool:
        rows = self.query("SELECT highlighted FROM transactions WHERE id=? AND deleted_at IS NULL", (transaction_id,))
        if not rows:
            raise ValueError("Transaction does not exist")
        highlighted = not bool(rows[0]["highlighted"])
        self.execute("UPDATE transactions SET highlighted=? WHERE id=?", (int(highlighted), transaction_id))
        return highlighted

    def _store_receipt(self, source: str | None) -> str | None:
        if not source:
            return None
        path = Path(source)
        if not path.exists() or not path.is_file():
            return source
        try:
            if path.resolve().is_relative_to(self.receipts_dir.resolve()):
                return str(path.resolve())
        except ValueError:
            pass
        target = self.receipts_dir / f"{uuid4().hex}{path.suffix.lower()}"
        shutil.copy2(path, target)
        return str(target)

    def _normalise_card_link(self, values: dict[str, Any]) -> tuple[int | None, int]:
        effect = int(values.get("card_effect") or (1 if values.get("kind") == "expense" and values.get("payment_method") == "Credit card" else 0))
        if effect not in {-1, 0, 1}:
            raise ValueError("Invalid credit-card transaction effect")
        card_id = values.get("credit_card_id")
        if effect and not card_id:
            cards = self.query("SELECT id FROM credit_cards ORDER BY id LIMIT 1")
            card_id = cards[0]["id"] if cards else None
        if effect and not card_id:
            raise ValueError("Choose a credit card for this transaction")
        return (int(card_id) if card_id else None), effect

    def _adjust_card_balance(self, card_id: int | None, amount: float, currency: str, direction: int) -> None:
        cards = self.query("SELECT id,currency,current_balance FROM credit_cards WHERE id=?", (card_id,))
        if not cards:
            raise ValueError("Credit card does not exist")
        card = cards[0]
        converted = Decimal(str(amount))
        rate = Decimal(self.get_setting("gbp_aed_rate", "4.928313"))
        if currency != card["currency"]:
            converted = converted * rate if currency == "GBP" else converted / rate
        converted = converted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        new_balance = max(Decimal("0"), Decimal(str(card["current_balance"])) + converted * direction)
        self.execute("UPDATE credit_cards SET current_balance=? WHERE id=?", (float(new_balance), card["id"]))

    def transactions(self, search: str = "", month: str | None = None, limit: int = 500) -> list[sqlite3.Row]:
        clauses, params = ["t.deleted_at IS NULL"], []
        if search:
            clauses.append("(t.merchant LIKE ? OR t.notes LIKE ? OR t.tags LIKE ? OR c.name LIKE ?)")
            params.extend([f"%{search}%"] * 4)
        if month:
            clauses.append("substr(t.occurred_at,1,7)=?")
            params.append(month)
        params.append(limit)
        return self.query(
            "SELECT t.*, c.name category, c.color category_color, cc.name credit_card_name FROM transactions t LEFT JOIN categories c ON c.id=t.category_id LEFT JOIN credit_cards cc ON cc.id=t.credit_card_id "
            f"WHERE {' AND '.join(clauses)} ORDER BY t.occurred_at DESC, t.id DESC LIMIT ?", tuple(params)
        )

    def find_duplicates(self, amount: float, occurred_at: str, merchant: str) -> list[sqlite3.Row]:
        day = occurred_at[:10]
        return self.query("SELECT * FROM transactions WHERE deleted_at IS NULL AND amount=? AND substr(occurred_at,1,10)=? AND merchant=?",
                          (amount, day, merchant))

    def add_vehicle(self, *, vehicle_name: str, purchase_price_aed: float, expected_sale_price_aed: float,
                    purchased_date: str, notes: str = "", purchase_type: str = "cash") -> int:
        name = vehicle_name.strip()
        if not name:
            raise ValueError("Vehicle name is required")
        if purchase_price_aed < 0 or expected_sale_price_aed < 0:
            raise ValueError("Vehicle prices cannot be negative")
        if purchase_type not in {"cash", "consignment"}:
            raise ValueError("Purchase type must be cash or consignment")
        return self.execute(
            "INSERT INTO vehicles(vehicle_name,purchase_price_aed,expected_sale_price_aed,purchased_date,notes,purchase_type,initial_owner_payout_aed) VALUES (?,?,?,?,?,?,?)",
            (name, purchase_price_aed, expected_sale_price_aed, purchased_date[:10], notes.strip(), purchase_type, purchase_price_aed if purchase_type=="consignment" else None),
        )

    def mark_vehicle_consignment(self,vehicle_id:int,owner_payout_aed:float)->None:
        if owner_payout_aed<=0: raise ValueError("Owner payout must be greater than zero")
        changed=self.execute("UPDATE vehicles SET purchase_type='consignment',purchase_price_aed=?,initial_owner_payout_aed=COALESCE(initial_owner_payout_aed,?),updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='stock'",(owner_payout_aed,owner_payout_aed,vehicle_id))
        if changed!=1: raise ValueError("Vehicle is no longer available in stock")

    def acquire_inspected_vehicle(self,customer_id:int,values:dict[str,Any])->int:
        name=str(values.get("vehicle_name","")).strip(); purchase_type=str(values.get("purchase_type","cash")); purchase=float(values.get("purchase_price_aed",0)); expected=float(values.get("expected_sale_price_aed",0)); purchased_date=str(values.get("purchased_date") or date.today().isoformat())[:10]; notes=str(values.get("notes","")).strip()
        if not name: raise ValueError("Vehicle name is required")
        if purchase<=0: raise ValueError("Purchase price or owner payout must be greater than zero")
        if expected<0: raise ValueError("Expected sale price cannot be negative")
        if purchase_type not in {"cash","consignment"}: raise ValueError("Purchase type must be cash or consignment")
        date.fromisoformat(purchased_date)
        with self.connect() as connection:
            customer=connection.execute("SELECT id FROM customer_contacts WHERE id=? AND status='active' AND pipeline_stage='inspection'",(customer_id,)).fetchone()
            if not customer: raise ValueError("Customer is no longer awaiting inspection")
            cursor=connection.execute("INSERT INTO vehicles(vehicle_name,purchase_price_aed,expected_sale_price_aed,purchased_date,notes,purchase_type,initial_owner_payout_aed) VALUES (?,?,?,?,?,?,?)",(name,purchase,expected,purchased_date,notes,purchase_type,purchase if purchase_type=="consignment" else None))
            connection.execute("UPDATE customer_contacts SET status='sold',sold_date=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(purchased_date,customer_id))
            return int(cursor.lastrowid)

    def stock_vehicles(self, purchase_month: str | None = None) -> list[sqlite3.Row]:
        if purchase_month:
            return self.query(
                "SELECT *, expected_sale_price_aed-purchase_price_aed expected_profit_aed FROM vehicles "
                "WHERE status='stock' AND substr(purchased_date,1,7)=? ORDER BY purchased_date DESC,id DESC",
                (purchase_month,),
            )
        return self.query(
            "SELECT *, expected_sale_price_aed-purchase_price_aed expected_profit_aed FROM vehicles "
            "WHERE status='stock' ORDER BY purchased_date DESC,id DESC"
        )

    def sold_vehicles(self, sold_month: str) -> list[sqlite3.Row]:
        return self.query(
            "SELECT *, sold_price_aed-purchase_price_aed realised_profit_aed FROM vehicles "
            "WHERE status='sold' AND substr(sold_date,1,7)=? ORDER BY sold_date DESC,id DESC",
            (sold_month,),
        )

    def monthly_vehicle_purchase_total(self, purchase_month: str) -> Decimal:
        rows = self.query(
            "SELECT COALESCE(SUM(purchase_price_aed),0) total FROM vehicles "
            "WHERE substr(purchased_date,1,7)=? AND purchase_type='cash'",
            (purchase_month,),
        )
        return Decimal(str(rows[0]["total"]))

    def active_cash_stock_total(self) -> Decimal:
        rows=self.query("SELECT COALESCE(SUM(purchase_price_aed),0) total FROM vehicles WHERE status='stock' AND purchase_type='cash'")
        return Decimal(str(rows[0]["total"]))

    def remove_stock_vehicle(self, vehicle_id: int) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM vehicles WHERE id=? AND status='stock'", (vehicle_id,)
            )
            if cursor.rowcount != 1:
                raise ValueError("Vehicle is no longer available in stock")

    def add_customer_contact(self, values: dict[str, Any]) -> int:
        name=str(values.get("customer_name","")).strip(); vehicle=str(values.get("vehicle_name","")).strip()
        phone="".join(character for character in str(values.get("phone_last5","")) if character.isdigit())
        rapport=str(values.get("rapport","green"))
        if not name or not vehicle:
            raise ValueError("Customer and vehicle are required")
        if len(phone)!=5:
            raise ValueError("Enter exactly the last 5 phone digits")
        if rapport not in {"green","red"}:
            raise ValueError("Rapport must be green or red")
        due=str(values.get("next_contact_date") or date.today().isoformat())[:10]
        return self.execute(
            "INSERT INTO customer_contacts(customer_name,vehicle_name,phone_last5,mileage,vehicle_age_years,vehicle_price_aed,cash_offer_aed,consignment_offer_aed,rapport,next_contact_date,notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (name,vehicle,phone,int(values.get("mileage",0)),int(values.get("vehicle_age_years",0)),float(values.get("vehicle_price_aed",0)),float(values.get("cash_offer_aed",0)),float(values.get("consignment_offer_aed",0)),rapport,due,str(values.get("notes","")).strip()),
        )

    def update_customer_contact(self, customer_id: int, values: dict[str, Any]) -> None:
        name=str(values.get("customer_name","")).strip(); vehicle=str(values.get("vehicle_name","")).strip()
        phone="".join(character for character in str(values.get("phone_last5","")) if character.isdigit())
        rapport=str(values.get("rapport","green"))
        if not name or not vehicle or len(phone)!=5 or rapport not in {"green","red"}:
            raise ValueError("Customer, vehicle, five phone digits and rapport are required")
        self.execute(
            "UPDATE customer_contacts SET customer_name=?,vehicle_name=?,phone_last5=?,mileage=?,vehicle_age_years=?,vehicle_price_aed=?,cash_offer_aed=?,consignment_offer_aed=?,rapport=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (name,vehicle,phone,int(values.get("mileage",0)),int(values.get("vehicle_age_years",0)),float(values.get("vehicle_price_aed",0)),float(values.get("cash_offer_aed",0)),float(values.get("consignment_offer_aed",0)),rapport,str(values.get("notes","")).strip(),customer_id),
        )

    def upsert_imported_customer_contact(self, values: dict[str, Any]) -> str:
        """Create or carefully enrich one caller using a WhatsApp export."""
        phone=str(values["phone_last5"]); matches=self.query("SELECT * FROM customer_contacts WHERE phone_last5=? AND status='active'",(phone,))
        if len(matches)>1: raise ValueError(f"more than one active customer has phone suffix {phone}")
        if not matches:
            customer_id=self.add_customer_contact({
                "customer_name":values["customer_name"],"vehicle_name":values["vehicle_name"],"phone_last5":phone,
                "mileage":values.get("mileage",0),"vehicle_age_years":values.get("model_year",0),
                "vehicle_price_aed":values.get("vehicle_price_aed",0),"cash_offer_aed":values.get("cash_offer_aed",0),
                "consignment_offer_aed":values.get("consignment_offer_aed",0),"rapport":values.get("rapport","green"),
                "next_contact_date":values.get("next_contact_date"),"notes":"Imported from WhatsApp",
            }); outcome="added"
        else:
            current=matches[0]; customer_id=int(current["id"])
            name=values["customer_name"] if current["customer_name"].startswith("WhatsApp seller") else current["customer_name"]
            vehicle=values["vehicle_name"] if values["vehicle_name"]!="Vehicle not identified" else current["vehicle_name"]
            with self.connect() as connection:
                connection.execute(
                    "UPDATE customer_contacts SET customer_name=?,vehicle_name=?,mileage=CASE WHEN ?>0 THEN ? ELSE mileage END,"
                    "vehicle_age_years=CASE WHEN ?>0 THEN ? ELSE vehicle_age_years END,vehicle_price_aed=CASE WHEN ?>0 THEN ? ELSE vehicle_price_aed END,"
                    "cash_offer_aed=CASE WHEN ?>0 THEN ? ELSE cash_offer_aed END,consignment_offer_aed=CASE WHEN ?>0 THEN ? ELSE consignment_offer_aed END,"
                    "rapport=CASE WHEN rapport='red' OR ?='red' THEN 'red' ELSE 'green' END,next_contact_date=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (name,vehicle,values.get("mileage",0),values.get("mileage",0),values.get("model_year",0),values.get("model_year",0),
                     values.get("vehicle_price_aed",0),values.get("vehicle_price_aed",0),values.get("cash_offer_aed",0),values.get("cash_offer_aed",0),
                     values.get("consignment_offer_aed",0),values.get("consignment_offer_aed",0),values.get("rapport","green"),values["next_contact_date"],customer_id),
                )
            outcome="updated"
        self.add_customer_contact_note(customer_id,str(values["note"]))
        return outcome

    def customer_contacts(self, *, due: str | None = None, search: str = "", include_sold: bool = False, stage: str | None = "caller") -> list[sqlite3.Row]:
        clauses=[]; params:list[Any]=[]
        if stage is not None:
            clauses.append("pipeline_stage=?"); params.append(stage)
        if not include_sold: clauses.append("status='active'")
        if due=="today":
            clauses.append("next_contact_date<=?"); params.append(date.today().isoformat())
        elif due=="tomorrow":
            clauses.append("next_contact_date=?"); params.append((date.today()+timedelta(days=1)).isoformat())
        if search:
            clauses.append("(customer_name LIKE ? OR vehicle_name LIKE ? OR phone_last5 LIKE ?)")
            params.extend([f"%{search}%"]*3)
        where=f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.query(
            f"SELECT * FROM customer_contacts {where} ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END,next_contact_date,customer_name",
            tuple(params),
        )

    def move_customer_to_inspection(self, customer_id: int, inspection_on: str | None = None) -> None:
        inspection_date=(inspection_on or date.today().isoformat())[:10]
        date.fromisoformat(inspection_date)
        changed=self.execute(
            "UPDATE customer_contacts SET pipeline_stage='inspection',inspection_date=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='active' AND pipeline_stage='caller'",
            (inspection_date,customer_id),
        )
        if changed!=1: raise ValueError("Customer is no longer in the caller list")

    def return_customer_to_callers(self, customer_id: int) -> None:
        changed=self.execute(
            "UPDATE customer_contacts SET pipeline_stage='caller',inspection_date=NULL,next_contact_date=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='active' AND pipeline_stage='inspection'",
            (date.today().isoformat(),customer_id),
        )
        if changed!=1: raise ValueError("Customer is no longer in inspection")

    def mark_customer_contacted(self, customer_id: int, contacted_on: str | None = None) -> None:
        contacted=date.fromisoformat((contacted_on or date.today().isoformat())[:10]); next_contact=contacted+timedelta(days=3)
        with self.connect() as connection:
            cursor=connection.execute(
                "UPDATE customer_contacts SET last_contacted_date=?,next_contact_date=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='active'",
                (contacted.isoformat(),next_contact.isoformat(),customer_id),
            )
            if cursor.rowcount!=1: raise ValueError("Customer is no longer active")

    def toggle_customer_rapport(self, customer_id: int) -> str:
        rows=self.query("SELECT rapport FROM customer_contacts WHERE id=?",(customer_id,))
        if not rows: raise ValueError("Customer not found")
        rapport="red" if rows[0]["rapport"]=="green" else "green"
        self.execute("UPDATE customer_contacts SET rapport=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(rapport,customer_id))
        return rapport

    def mark_customer_sold(self, customer_id: int, sold_on: str | None = None) -> None:
        with self.connect() as connection:
            cursor=connection.execute(
                "UPDATE customer_contacts SET status='sold',sold_date=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='active'",
                ((sold_on or date.today().isoformat())[:10],customer_id),
            )
            if cursor.rowcount!=1: raise ValueError("Customer is no longer active")

    def delete_customer_contact(self,customer_id:int)->None:
        if self.execute("DELETE FROM customer_contacts WHERE id=?",(customer_id,))!=1:
            raise ValueError("Customer not found")

    def customer_contact_notes(self, customer_id: int) -> list[sqlite3.Row]:
        return self.query(
            "SELECT * FROM customer_contact_notes WHERE customer_id=? ORDER BY created_at DESC,id DESC",
            (customer_id,),
        )

    def add_customer_contact_note(self, customer_id: int, note_text: str) -> int:
        note=note_text.strip()
        if not note: raise ValueError("Note cannot be empty")
        if not self.query("SELECT id FROM customer_contacts WHERE id=?",(customer_id,)): raise ValueError("Customer not found")
        return self.execute(
            "INSERT INTO customer_contact_notes(customer_id,note_text) VALUES (?,?)",
            (customer_id,note),
        )

    def message_templates(self) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM message_templates ORDER BY title COLLATE NOCASE,id")

    def save_message_template(self,title:str,message_text:str,template_id:int|None=None)->int:
        clean_title=title.strip(); clean_message=message_text.strip()
        if not clean_title or not clean_message: raise ValueError("Template title and message are required")
        if template_id is None:
            return self.execute("INSERT INTO message_templates(title,message_text) VALUES (?,?)",(clean_title,clean_message))
        changed=self.execute("UPDATE message_templates SET title=?,message_text=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(clean_title,clean_message,template_id))
        if changed!=1: raise ValueError("Template not found")
        return template_id

    def delete_message_template(self,template_id:int)->None:
        if self.execute("DELETE FROM message_templates WHERE id=?",(template_id,))!=1: raise ValueError("Template not found")

    def delete_customer_contact_note(self, customer_id: int, note_id: int) -> None:
        with self.connect() as connection:
            cursor=connection.execute(
                "DELETE FROM customer_contact_notes WHERE id=? AND customer_id=?",
                (note_id,customer_id),
            )
            if cursor.rowcount!=1: raise ValueError("Note not found")

    def sell_vehicle(self, vehicle_id: int, *, sold_price_aed: float, sold_date: str, final_owner_payout_aed:float|None=None) -> None:
        if sold_price_aed < 0:
            raise ValueError("Sale price cannot be negative")
        with self.connect() as connection:
            vehicle=connection.execute("SELECT purchase_type,purchase_price_aed,initial_owner_payout_aed FROM vehicles WHERE id=? AND status='stock'",(vehicle_id,)).fetchone()
            if not vehicle: raise ValueError("Vehicle is no longer available in stock")
            payout=float(vehicle["purchase_price_aed"])
            if vehicle["purchase_type"]=="consignment":
                payout=float(final_owner_payout_aed if final_owner_payout_aed is not None else payout)
                if payout<=0: raise ValueError("Final owner payout must be greater than zero")
            cursor = connection.execute(
                "UPDATE vehicles SET status='sold',sold_price_aed=?,sold_date=?,purchase_price_aed=?,initial_owner_payout_aed=CASE WHEN purchase_type='consignment' THEN COALESCE(initial_owner_payout_aed,purchase_price_aed) ELSE initial_owner_payout_aed END,updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND status='stock'",
                (sold_price_aed, sold_date[:10], payout, vehicle_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Vehicle is no longer available in stock")

    def return_vehicle_to_stock(self, vehicle_id: int) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE vehicles SET status='stock',sold_price_aed=NULL,sold_date=NULL,updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND status='sold'", (vehicle_id,)
            )
            if cursor.rowcount != 1:
                raise ValueError("Vehicle is not currently sold")

    def performance_budget(self, month: str) -> Decimal:
        rows = self.query("SELECT purchasing_budget_aed FROM performance_months WHERE month=?", (month,))
        if rows: return Decimal(str(rows[0]["purchasing_budget_aed"]))
        previous=self.query("SELECT purchasing_budget_aed FROM performance_months WHERE month<? ORDER BY month DESC LIMIT 1",(month,))
        return Decimal(str(previous[0]["purchasing_budget_aed"])) if previous else Decimal("3000000")

    def set_performance_budget(self, month: str, budget_aed: float) -> None:
        if budget_aed < 0:
            raise ValueError("Purchasing budget cannot be negative")
        self.execute(
            "INSERT INTO performance_months(month,purchasing_budget_aed) VALUES (?,?) "
            "ON CONFLICT(month) DO UPDATE SET purchasing_budget_aed=excluded.purchasing_budget_aed,updated_at=CURRENT_TIMESTAMP",
            (month, budget_aed),
        )

    def export_csv(self, destination: Path) -> None:
        rows = self.transactions(limit=100000)
        with destination.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Date", "Type", "Amount", "Currency", "Category", "Merchant", "Payment method", "Essential", "Tags", "Notes"])
            for row in rows:
                writer.writerow([row["occurred_at"], row["kind"], row["amount"], row["currency"], row["category"],
                                 row["merchant"], row["payment_method"], row["essential"], row["tags"], row["notes"]])

    def import_csv(self, source: Path) -> tuple[int, int]:
        imported = skipped = 0
        categories = {row["name"]: row["id"] for row in self.query("SELECT id,name FROM categories")}
        with source.open("r", newline="", encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                try:
                    amount = float(raw.get("Amount", raw.get("amount", "0")))
                    occurred = raw.get("Date", raw.get("date", date.today().isoformat()))
                    merchant = raw.get("Merchant", raw.get("merchant", "Imported"))
                    if self.find_duplicates(amount, occurred, merchant):
                        skipped += 1
                        continue
                    category = raw.get("Category", raw.get("category", "Miscellaneous"))
                    self.add_transaction({"amount": amount, "currency": raw.get("Currency", "AED").upper(),
                        "occurred_at": occurred, "kind": raw.get("Type", "expense").lower(),
                        "category_id": categories.get(category, categories.get("Miscellaneous")), "merchant": merchant,
                        "payment_method": raw.get("Payment method", "Debit card"), "recurring": 0,
                        "notes": raw.get("Notes", ""), "receipt_path": None, "refundable_deposit": 0,
                        "essential": int(raw.get("Essential", "0") or 0), "tags": raw.get("Tags", "imported")})
                    imported += 1
                except (ValueError, KeyError):
                    skipped += 1
        return imported, skipped

    def health_check(self) -> tuple[bool, str]:
        rows = self.query("PRAGMA integrity_check")
        version = self.query("PRAGMA user_version")[0][0]
        okay = bool(rows and rows[0][0] == "ok" and version == SCHEMA_VERSION)
        return okay, f"Integrity: {rows[0][0]}; schema v{version}/{SCHEMA_VERSION}"

    def backup(self, destination: Path, password: str | None = None) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_zip = destination.with_suffix(".tmp.zip") if password else destination
        with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(self.path, "dxb_runway.db")
            for receipt in self.receipts_dir.glob("**/*"):
                if receipt.is_file():
                    archive.write(receipt, f"receipts/{receipt.relative_to(self.receipts_dir)}")
            archive.writestr("manifest.json", json.dumps({"schema": SCHEMA_VERSION, "created": datetime.now().isoformat()}))
        if password:
            salt = os.urandom(16)
            kdf = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1)
            key = base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))
            encrypted = Fernet(key).encrypt(temp_zip.read_bytes())
            destination.write_bytes(b"DXBR2\n" + salt.hex().encode("ascii") + b"\n" + encrypted)
            temp_zip.unlink(missing_ok=True)
        return destination

    def restore(self, source: Path, password: str | None = None) -> None:
        raw = source.read_bytes()
        temp = source
        if raw.startswith(b"DXBR2\n"):
            if not password:
                raise ValueError("This backup requires its password")
            _, salt_hex, encrypted = raw.split(b"\n", 2)
            kdf = Scrypt(salt=bytes.fromhex(salt_hex.decode("ascii")), length=32, n=2**15, r=8, p=1)
            key = base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))
            try:
                decoded = Fernet(key).decrypt(encrypted)
            except Exception as error:
                raise ValueError("Incorrect password or damaged encrypted backup") from error
            temp = self.path.parent / "restore.tmp.zip"
            temp.write_bytes(decoded)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(self.path, self.path.with_name(f"pre-restore-{timestamp}.db"))
        with zipfile.ZipFile(temp) as archive:
            if "dxb_runway.db" not in archive.namelist():
                raise ValueError("Invalid DXB RUNWAY backup")
            archive.extract("dxb_runway.db", self.path.parent / "restore")
            shutil.copy2(self.path.parent / "restore" / "dxb_runway.db", self.path)
            for member in archive.namelist():
                if member.startswith("receipts/") and not member.endswith("/"):
                    archive.extract(member, self.path.parent / "restore")
                    target = self.receipts_dir / Path(member).relative_to("receipts")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(self.path.parent / "restore" / member, target)
        if temp != source:
            temp.unlink(missing_ok=True)
        self.migrate()

    def seed_demo(self) -> None:
        if self.query("SELECT COUNT(*) AS n FROM transactions")[0]["n"]:
            return
        categories = {row["name"]: row["id"] for row in self.query("SELECT id,name FROM categories")}
        today = date.today()
        card_id = self.execute("INSERT INTO credit_cards(name,currency,credit_limit,current_balance,statement_day,due_day,minimum_payment,apr,promo_end) VALUES (?,?,?,?,?,?,?,?,?)",
                               ("UK relocation card", "GBP", 4000, 620, 8, 28, 50, 24.9, "2027-03-01"))
        demo = [
            (6000, "AED", today.replace(day=1), "income", "Salary", "Alba Motors", "Bank transfer", 1),
            (4500, "AED", today.replace(day=min(2, today.day)), "expense", "Accommodation", "Dubai apartment", "Debit card", 1),
            (310, "AED", today - timedelta(days=2), "expense", "Groceries", "Carrefour", "Debit card", 1),
            (86, "AED", today - timedelta(days=1), "expense", "Transport", "RTA / taxi", "Credit card", 1),
            (74, "AED", today, "expense", "Restaurants", "Lunch", "Debit card", 0),
        ]
        for amount, currency, day, kind, category, merchant, payment, essential in demo:
            self.add_transaction({"amount": amount, "currency": currency, "occurred_at": f"{day.isoformat()}T12:00:00",
                "kind": kind, "category_id": categories[category], "merchant": merchant, "payment_method": payment,
                "recurring": category in {"Salary", "Accommodation"}, "notes": "Demo data", "receipt_path": None,
                "refundable_deposit": 0, "essential": essential, "tags": "demo",
                "credit_card_id": card_id if payment == "Credit card" else None})
        goals = [("First AED 10,000 month", 10000), ("First AED 20,000 month", 20000), ("First Tier 3 achievement", 1),
                 ("First Tier 2 achievement", 1), ("First Tier 1 achievement", 1), ("Credit-card debt cleared", 1),
                 ("Emergency fund fully funded", 3000), ("First AED 50,000 saved", 50000),
                 ("First AED 100,000 saved", 100000), ("Six months completed in Dubai", 6), ("Probation passed", 1)]
        self.execute("DELETE FROM goals")
        with self.connect() as connection:
            connection.executemany("INSERT INTO goals(name,target_value) VALUES (?,?)", goals)
        reminders = [("Salary payment", today.replace(day=calendar_last(today)), "salary"),
                     ("Card payment due", (today + timedelta(days=12)), "card"),
                     ("Rent", add_month(today, 1).replace(day=1), "rent")]
        with self.connect() as connection:
            connection.executemany("INSERT INTO reminders(title,event_date,event_type) VALUES (?,?,?)",
                                   [(t, d.isoformat(), k) for t, d, k in reminders])
        if not self.query("SELECT COUNT(*) AS n FROM vehicles")[0]["n"]:
            vehicles = [
                ("BMW M3", 215000, 239000, (today - timedelta(days=7)).isoformat(), "stock", None, None),
                ("Porsche Macan", 168000, 187500, (today - timedelta(days=4)).isoformat(), "stock", None, None),
                ("Mercedes C63", 192000, 219500, (today - timedelta(days=12)).isoformat(), "sold", 216700, (today - timedelta(days=2)).isoformat()),
            ]
            with self.connect() as connection:
                connection.executemany(
                    "INSERT INTO vehicles(vehicle_name,purchase_price_aed,expected_sale_price_aed,purchased_date,status,sold_price_aed,sold_date) VALUES (?,?,?,?,?,?,?)",
                    vehicles,
                )


def calendar_last(day: date) -> int:
    import calendar
    return calendar.monthrange(day.year, day.month)[1]


def add_month(day: date, count: int) -> date:
    import calendar
    index = day.month - 1 + count
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))
