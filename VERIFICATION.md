# Verification record

Verified on Windows 10 x64 with Python 3.12.10, PySide6 6.9.1 and PyInstaller 6.14.2.

## Automated verification

- 41 tests pass: timed and monthly runway calculations, live Overview input integration, official-rate snapshot and dual formatting, default-versus-custom rate migration, vehicle stock/sold transitions, monthly sales history, per-month performance budgets, month-specific commission targets, persistent transaction highlighting, card-specific purchases and repayments, limit-only card editing/deletion, migration health, credit/debt mutations, cross-currency handling, local receipt storage, deletion undo, duplicate detection, portable and encrypted backup/restore, PDF export, onboarding and all major screens.
- Every module compiles under Python 3.12.

## Manual calculation checks

For an AED 3,000,000 January purchasing budget:

| Eligible profit | Result | Rate | Commission |
|---:|---|---:|---:|
| AED 284,999 | Baseline | 4% | AED 11,399.96 |
| AED 285,000 | Tier 3 | 5% | AED 14,250.00 |
| AED 345,000 | Tier 2 | 6.5% | AED 22,425.00 |
| AED 420,000 | Tier 1 | 8% | AED 33,600.00 |

- January commission is scheduled for 31 March; November commission for 30 January of the following year.
- At AED 24,700 average eligible profit per vehicle, AED 285,000 requires 12 vehicles after rounding up.
- The shipped official snapshot is 1 GBP = AED 4.928313, published by the Central Bank of the UAE on 14 July 2026.
- GBP equivalents are consistently calculated as `AED ÷ 4.928313`; AED remains the primary planning currency.
- Cross-currency card purchases use the same stored rate; deleting and restoring a transaction reverses and reapplies the converted debt.

## Safety invariant checks

Given AED 10,000 cash, AED 3,000 protected fund, AED 1,000 unavailable deposit, AED 2,000 card debt, AED 19,000 unused credit and AED 50,000 pending commission:

- Spendable cash: AED 6,000
- Net wealth: AED 9,000
- Available credit: AED 17,000, displayed only as debt capacity
- Pending commission: displayed separately and excluded from spendable cash and net wealth

## Runtime and visual checks

- Source application launched and captured all ten major screens at 1480×920.
- Dashboard, transactions, debt, earnings, scenarios, budgets, calendar, momentum, reports and settings inspected for clipping and inconsistent spacing.
- First-run onboarding rendered and inspected.
- Version 1.1 dual-currency layouts were re-rendered and inspected on the dashboard, transactions, debt, earnings, scenarios, budgets, reports and settings screens.
- Version 1.2 Vehicle Desk was rendered and inspected with current stock, sold-month history, AED/GBP profit and live commission.
- Version 1.2.1 adds AED/GBP purchasing budget remaining, calculated from all vehicles bought in the selected month regardless of current stock/sold status.
- Version 1.2.2 adds persistent amber transaction highlights and a highlighted-only filter.
- Version 1.2.3 adds per-card editing and deletion in Debt Control. Available credit is entered directly and the current balance is calculated as card limit minus available credit.
- Version 1.2.4 links new credit-card purchases and repayments to a selected card. Debt Control balances now change through transactions, while card editing changes only the limit.
- Version 1.2.5 synchronises Overview runway with saved budgets, card minimum payments, salary-engine income, calendar salary timing, live cash transactions, protected funds, deposits and debt. A visible live-basis line explains the inputs.
- Version 1.2.6 adds one-off setup-cost classification. Setup transactions keep their real cash/debt impact and remain in the ledger, while normal monthly expenditure, budget usage, charts and spending reports exclude them.
- Version 1.2.7 displays the setup-adjusted operating runway as the Overview headline while retaining the actual-cash runway in the status text. Marked cash setup costs are added back only to the operating view; card-funded setup costs are not treated as cash.
- Version 1.2.8 adds a live daily spending guide to Overview. Today's limit is the remaining normal monthly budget divided by the inclusive number of days left; today's eligible Transactions reduce the displayed amount left immediately.
- Version 1.2.9 anchors the daily guide to an editable GBP 1,700 monthly spending cap, converted to AED using the single stored exchange rate before eligible monthly Transactions are deducted.
- Version 1.2.10 replaces the transaction highlight star with a stronger full-row amber treatment while preserving persistent state, tooltips and the highlighted-only filter.
- Version 1.3.0 adds native GitHub-hosted macOS application builds for Apple Silicon and Intel, Mac command-key shortcuts, platform-neutral local-data wording and a Windows-to-Mac backup transfer guide. The workflow runs all automated tests on each target before packaging and verifies the ad-hoc app signature.
- Version 1.3.1 makes Vehicle Desk earnings explicit: Commission earned remains commission-only, while Total earned combines the live commission with the exact base salary selected by the month's purchasing-budget band.
- Version 1.3.2 removes the duplicate Salary + commission navigation tab. Vehicle Desk now automatically upserts its exact monthly result into pending earnings, preserving Overview pending commission, salary inputs, Calendar payment dates and Reports without a second manual calculator.
- The version 1.2 one-file executable was launched with representative vehicle data and produced a complete packaged Vehicle Desk screenshot after its extraction/paint cycle.
- One-file `DXB RUNWAY.exe` launched and captured a dashboard screenshot.
- Inno Setup installer compiled, silently installed into a disposable directory, and the installed executable launched and captured the transactions screen.
- The known QtCharts combined area/overlay ownership crash found during QA was removed; the stable antialiased line-chart implementation was re-tested.

The executable and installer are unsigned; see the limitations document for the expected SmartScreen warning and production code-signing recommendation.
