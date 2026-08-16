# DXB RUNWAY Intelligence

Private, data-led vehicle purchasing intelligence for macOS and Windows. This is a separate edition of DXB RUNWAY with its own app identity, database and GitHub repository; installing it does not replace or overwrite the original app.

## What it does

- Imports messy CSV, TSV, TXT, XLS and XLSX vehicle-history exports, even when headers are shuffled or preceded by report titles.
- Preserves every original file and every source value. Bad rows enter review; duplicates remain auditable but are excluded from analytics.
- Normalises make, model, trim, year, dates and AED prices.
- Gives opportunities a deterministic grade and `BUY`, `NEGOTIATE`, `AVOID` or `INSUFFICIENT DATA` verdict.
- Weights time to sell at 50%, sample confidence at 15%, margin at 15%, ROI at 8%, consistency at 7% and seasonality at 5%.
- Prioritises identical make/model/trim examples; same-model vehicles contribute at reduced weight and the wider market is context only.
- Shows sample size, identical-trim samples, confidence, median days, realised margin, ROI and trim position.
- Adds the evidence grade to current Stock Level rows.
- Securely stores the full retained evidence for audit and injects a bounded aggregate snapshot into the dedicated OpenClaw workspace after each import.
- Provides a simple Runway chat powered by GPT-5.6 Luna at medium reasoning on the private VPS.
- Presents Ask Runway as its own RUNWAY AI sidebar page with conversational message bubbles, animated thinking feedback and typewriter-style responses.
- Uses the dedicated Runway agent portrait in the page header and every assistant message.
- Retains chat history locally and turns clear owner instructions such as “remember”, “from now on” or “add seasonality to the analysis” into durable, reviewable memory.
- Includes a Memory screen where learned preferences can be added or forgotten; memories are injected into future app and Discord analysis without granting the agent write access.

## AI safety boundary

The VPS agent is an adviser with no callable tools. OpenClaw's internal Codex execution mode is `auto`, but the agent's effective tool surface remains empty: it cannot access CRM/Odoo/company systems, execute shell commands, edit files, use a browser, send messages, contact customers, send email, make calls, spend money, use GitHub, create cron jobs or spawn agents. A bounded evidence snapshot is injected into its context, and only Callum and the explicitly bound `🤖・ask-runway` channel are accepted.

The deterministic local score owns the grade. The language model may explain the result but cannot change it. Imported spreadsheet text is untrusted data and can never override agent policy.

Runway does not silently learn from its own output. Only explicit owner instructions and rules added through the Memory screen become lasting preferences. This prevents a model mistake from turning into permanent policy.

Version-controlled policy files live in [`openclaw/`](openclaw/). The Discord migration script archives old categories rather than deleting them.

## Data locations

The app uses the Qt application identity `DXB RUNWAY Intelligence` and database `dxb_runway_intelligence.db`. Historical originals are copied into `intelligence_imports/`; AI snapshots are generated in `intelligence_sync/`. These locations are separate from the original DXB RUNWAY database.

## Run from source

Requirements: Python 3.12 and macOS 14+ or Windows 10/11.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
PYTHONPATH=src python -m dxb_runway.app --skip-onboarding
```

On Windows, activate with `.venv\\Scripts\\Activate.ps1` and set `$env:PYTHONPATH = "src"`.

## Test

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest
```

The suite covers data migrations, messy imports, duplicate retention, raw-value preservation, deterministic grading, full snapshot generation and the desktop UI.

## Build

GitHub Actions contains separate macOS Apple Silicon, macOS Intel and Windows workflows. Local macOS packaging uses:

```bash
python -m PyInstaller --noconfirm --clean DXB_RUNWAY_mac.spec
```

The resulting app is `dist/DXB RUNWAY Intelligence.app` with bundle identifier `com.callums2122.dxb-runway-intelligence`.
