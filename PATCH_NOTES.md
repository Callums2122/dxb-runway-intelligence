# DXB RUNWAY patch notes

This document records shipped DXB RUNWAY changes. Planned Alba Cars purchasing work is deliberately kept separate in [ALBA_TRAINING_PROJECTION.md](ALBA_TRAINING_PROJECTION.md).

## Current release — 1.7.7

### Tier earnings preview

- Added Tier 3, Tier 2 and Tier 1 total-pay cards above the monthly percentage table.
- Each card calculates salary plus commission from the selected month's saved purchasing budget and tier target.
- Every projection is shown in AED with an approximate GBP conversion and updates immediately with shared settings.

## 1.7.6

### Monthly tier overview and global salary

- Added a 12-month Vehicle Desk table showing each month's purchasing budget, every tier target percentage, commission rate and achieved tier.
- Added monthly base salary editing beside the selected month's budget controls.
- Saving salary updates the app-wide setting and immediately recalculates current earnings across the app.

## 1.7.5

### Scheduled inspections

- Placed Add to inspection directly beside Sold on Customer Contact.
- Adding a customer to Inspection now opens a calendar date picker.
- The chosen inspection date is saved and displayed as the first column in Inspection.

## 1.7.4

### Inspection pipeline

- Added an Inspection tab under Leads for customers whose vehicles have progressed beyond caller follow-up.
- Added a Move to inspection action that removes the customer from the three-day contact queue while preserving their details, offers and notes.
- Inspection records can be edited, marked sold or returned to today's caller list.

## 1.7.3

### Customer vehicle model years

- Replaced the vehicle-age number input with a model-year dropdown covering 2018 through 2026.
- Customer lists and notes now show the model year before the vehicle, such as `2021 Jeep Wrangler`.
- Existing age-based customer records are displayed as their equivalent model year without losing their saved details.

## 1.7.2

### Dismissible customer notes

- Added a Close Notes button to dismiss the customer notes panel.
- Closing notes clears the lead selection so the panel stays hidden until another lead is clicked.

## 1.7.1

### Contact countdowns and conversation notes

- Kept the exact next-contact date and added a live days-left, due-today or overdue label.
- Added a customer notes panel that appears when a customer row is selected.
- Added timestamped conversation notes with quick entry.
- Added individual note deletion while preserving the main customer record.

## 1.7.0

### Three-day customer rapport tracker

- Added Customer Contact under Leads with focused Today, Tomorrow and All Customers views.
- Added customer, vehicle, mileage, age, phone suffix, valuation, cash offer and consignment offer tracking.
- New customers enter today's queue in green by default.
- Added red strong-rapport marking.
- Added a manual Contacted action that resets the follow-up date by exactly three days.
- Added a Sold action that removes the customer from daily queues while preserving the searchable record.
- Kept overdue customers visible in today's queue until they are manually advanced.

## 1.6.2

### Commission month cues

- Added the year to every Vehicle Desk month option.
- Highlighted the current month in green.
- Highlighted the month two months behind in orange to show the commission being paid now.

## 1.6.1

### Clean rolling Vehicle Desk

- Replaced the full date control with a simple January-to-December month selector.
- Each month name automatically points to its latest occurrence; August 2025 becomes August 2026 when August 2026 starts.
- Kept all earlier monthly data intact.
- Added Vehicle History under Misc / Other for compact year-on-year comparison.

## 1.6.0

### Dedicated Stock Level

- Added Stock Level under Leads as the single home for all unsold vehicles.
- Added cash purchase and consignment stock types.
- Added stock creation, removal and mark-as-sold actions.
- Consignment owner payouts contribute to vehicle profit without consuming the cash purchasing budget.
- Marking a vehicle sold removes it from Stock Level and moves it into Vehicle Desk's monthly sold history.
- Removed current-stock controls and tables from Vehicle Desk so it focuses on realised performance and commission.

## 1.5.1

### Instant navigation

- Removed the whole-page opacity effect that forced complex tables and charts through an off-screen repaint.
- Page changes are now immediate while sidebar interaction feedback remains.
- Updated Windows, Apple Silicon macOS and Intel macOS packages from the same verified source.
- No financial calculations, workflows or stored user data changed.

## 1.5.0 — Premium desktop refresh

- Introduced the current local-first personal-CFO visual system.
- Refined typography, spacing, cards, forms, tables and navigation states across the application.
- Added brighter chart and progress accents without reducing desktop information density.
- Added category-led transaction icons and clearer metric hierarchy.
- Preserved every existing financial feature and calculation.

## 1.4.1 — Workspace navigation

- Made Overview a standalone dashboard destination.
- Organised the sidebar into colour-coded Leads, Money tracking and Misc / other sections.
- Preserved compact sidebar behaviour and keyboard navigation.

## 1.4.0 — Monthly payments and budgets

- Replaced the spreadsheet-style budget screen with a monthly payments dashboard.
- Added rent amount and due-date tracking.
- Connected rent due dates to Calendar and rent payments to Transactions.
- Added clear monthly paid, spent and remaining amounts for everyday categories.

## 1.3.3 — Financial calendar redesign

- Replaced the stock calendar presentation with a custom rounded monthly view.
- Added event dots, a clearer selected-day panel and a Today shortcut.
- Debounced mouse-wheel navigation so one gesture moves only one month.

## 1.3.2 — Unified earnings

- Removed the duplicate Salary + commission navigation page.
- Made Vehicle Desk the single operational source for vehicle profit and earnings.
- Connected Vehicle Desk earnings to Overview, Calendar and Reports automatically.

## 1.3.1 — Total earned

- Kept Commission earned as commission-only.
- Added Total earned, combining live commission with the exact purchasing-budget salary band.
- Added AED and GBP equivalents to both values.

## 1.3.0 — Native macOS releases

- Added native Apple Silicon and Intel macOS application builds.
- Added Mac command-key shortcuts and platform-neutral local-data language.
- Added portable backup transfer guidance between Windows and macOS.
- Added automated macOS tests, packaging and ad-hoc signature verification on GitHub.

## 1.2.10 — Full-row transaction highlights

- Replaced the transaction highlight star with a persistent amber full-row treatment.
- Preserved the highlighted-only filter and transaction-note tooltips.

## 1.2.9 — GBP 1,700 monthly spending cap

- Anchored the daily spending guide to an editable GBP 1,700 monthly cap.
- Converted the cap through the single stored GBP/AED rate.
- Made eligible Transactions reduce the monthly and daily remaining amounts immediately.

## 1.2.8 — Daily spending guide

- Added today's spending limit, today's eligible spending and the amount left today to Overview.
- Connected all three values directly to Transactions.
- Excluded deposits, setup costs and credit-card repayments from normal daily spending.

## 1.2.7 — Operating runway

- Made setup-adjusted operating runway the primary Overview headline.
- Retained actual-cash runway for safety and transparency.
- Prevented card-funded setup costs from being treated as available cash.

## 1.2.6 — Relocation and setup costs

- Added one-off setup-cost classification to Transactions.
- Preserved the real cash or debt impact of setup costs.
- Excluded setup costs from normal monthly expenditure, budget usage and spending reports.

## 1.2.5 — Fully synchronised Overview

- Connected runway to saved budgets, card minimums, salary income and salary timing.
- Connected live cash Transactions, protected funds, deposits and debt.
- Added an explanatory live-basis line showing the inputs behind the runway result.

## 1.2.4 — Transaction-linked credit cards

- Connected new credit-card purchases and repayments to a selected card.
- Made Debt Control balances change through Transactions.
- Limited card editing to the credit limit so balances could not be manually contradicted.

## 1.2.3 — Editable and removable cards

- Added credit-card editing and deletion.
- Added direct available-credit entry during card setup.
- Calculated current balance as credit limit minus available credit.

## 1.2.2 — Transaction reminders

- Added persistent transaction highlighting.
- Added a highlighted-only transaction filter.

## 1.2.1 — Vehicle purchasing budget remaining

- Added AED and GBP purchasing-budget remaining to Vehicle Desk.
- Included every vehicle bought in the selected month, whether currently in stock or already sold.

## 1.2.0 — Vehicle Desk

- Added current-month vehicle stock and expected profit.
- Added atomic stock-to-sold movement so sold vehicles leave current stock immediately.
- Added monthly sold history without deleting earlier months.
- Added realised profit, tier progress and live commission calculations.
- Added monthly purchasing budgets and automatic month-specific targets.

## 1.1 — Dual-currency workspace

- Kept AED as the primary operating currency.
- Added consistent GBP equivalents across balances, Transactions, debt, earnings, scenarios, budgets and reports.
- Centralised conversion through one editable GBP/AED rate.

## Initial local-first foundation

- Built a completely local SQLite financial workspace with no required account, cloud database, telemetry or analytics.
- Added Overview, Transactions, Debt Control, Scenario Lab, Budgets, Calendar, Momentum, Reports and Settings.
- Separated cash, protected funds, refundable deposits, debt and pending commission.
- Added local receipts, CSV import/export, duplicate protection, reversible deletion, PDF reports and encrypted portable backups.

## Verification

The current codebase is covered by 43 automated tests plus packaged Windows and native macOS build checks. Detailed calculation and runtime evidence is maintained in [VERIFICATION.md](VERIFICATION.md).
