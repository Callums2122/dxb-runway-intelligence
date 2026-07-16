-- DXB RUNWAY schema v5. Applied incrementally by src/dxb_runway/database.py.
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE categories (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL DEFAULT 'expense',
  monthly_limit_aed REAL NOT NULL DEFAULT 0, essential_default INTEGER NOT NULL DEFAULT 0,
  color TEXT NOT NULL DEFAULT '#4dd8ff'
);
CREATE TABLE transactions (
  id INTEGER PRIMARY KEY, amount REAL NOT NULL CHECK(amount >= 0),
  currency TEXT NOT NULL CHECK(currency IN ('AED','GBP')), occurred_at TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('income','expense')), category_id INTEGER REFERENCES categories(id),
  merchant TEXT NOT NULL DEFAULT '', payment_method TEXT NOT NULL, recurring INTEGER NOT NULL DEFAULT 0,
  notes TEXT NOT NULL DEFAULT '', receipt_path TEXT, refundable_deposit INTEGER NOT NULL DEFAULT 0,
  essential INTEGER NOT NULL DEFAULT 0, tags TEXT NOT NULL DEFAULT '', deleted_at TEXT,
  highlighted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE credit_cards (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'GBP', credit_limit REAL NOT NULL,
  current_balance REAL NOT NULL DEFAULT 0, statement_day INTEGER NOT NULL DEFAULT 1,
  due_day INTEGER NOT NULL DEFAULT 20, minimum_payment REAL NOT NULL DEFAULT 0,
  apr REAL NOT NULL DEFAULT 0, promo_end TEXT
);
CREATE TABLE earnings (
  id INTEGER PRIMARY KEY, year INTEGER NOT NULL, month INTEGER NOT NULL, purchasing_budget_aed REAL NOT NULL,
  eligible_profit_aed REAL NOT NULL, average_margin_aed REAL NOT NULL DEFAULT 24700,
  deductions_aed REAL NOT NULL DEFAULT 0, tier TEXT NOT NULL, salary_aed REAL NOT NULL,
  commission_aed REAL NOT NULL, earned_date TEXT NOT NULL, payment_date TEXT NOT NULL,
  received INTEGER NOT NULL DEFAULT 0, UNIQUE(year, month)
);
CREATE TABLE budgets (
  id INTEGER PRIMARY KEY, month TEXT NOT NULL, category_id INTEGER REFERENCES categories(id),
  planned_aed REAL NOT NULL, rollover INTEGER NOT NULL DEFAULT 0, UNIQUE(month, category_id)
);
CREATE TABLE reminders (
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, event_date TEXT NOT NULL, event_type TEXT NOT NULL,
  notes TEXT NOT NULL DEFAULT '', completed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE goals (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, target_value REAL NOT NULL DEFAULT 1,
  current_value REAL NOT NULL DEFAULT 0, achieved_at TEXT
);
CREATE TABLE exchange_rates (
  id INTEGER PRIMARY KEY, recorded_at TEXT NOT NULL, gbp_aed REAL NOT NULL CHECK(gbp_aed > 0)
);
CREATE TABLE schema_audit (
  id INTEGER PRIMARY KEY, version INTEGER NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE attachments (
  id INTEGER PRIMARY KEY, transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  stored_path TEXT NOT NULL, original_name TEXT NOT NULL, added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE vehicles (
  id INTEGER PRIMARY KEY, vehicle_name TEXT NOT NULL,
  purchase_price_aed REAL NOT NULL CHECK(purchase_price_aed >= 0),
  expected_sale_price_aed REAL NOT NULL CHECK(expected_sale_price_aed >= 0), purchased_date TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'stock' CHECK(status IN ('stock','sold')), sold_price_aed REAL,
  sold_date TEXT, notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE performance_months (
  month TEXT PRIMARY KEY, purchasing_budget_aed REAL NOT NULL DEFAULT 3000000 CHECK(purchasing_budget_aed >= 0),
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
PRAGMA user_version=6;
