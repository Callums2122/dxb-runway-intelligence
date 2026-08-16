# DXB RUNWAY patch notes

This document records shipped DXB RUNWAY changes. Planned Alba Cars purchasing work is deliberately kept separate in [ALBA_TRAINING_PROJECTION.md](ALBA_TRAINING_PROJECTION.md).

## Current release — 2.2.0

- Mobile Stock Level now mirrors live Mac cash and consignment vehicles.
- Mobile navigation replaces Leads with a compact Vehicle Desk and month view.
- The Mac remains the source of truth and privately refreshes the phone mirror after edits and every two minutes.
- Nutrition can now switch between today, yesterday or a chosen earlier date, with backfilled meals and water saved to the selected day.
- Stock Level now shows realistic (80%) and maximum (100%) projected tier/total pay from the expected profit of the vehicles currently held.
- Vehicle Desk now shows the AED profit required to reach every tier for each month, including the current KPI-adjusted percentage.
- Stock Level now grades current cars by days held and shows expected margin; Vehicle Performance groups all sold cars by model with average sale price, profit, margin and speed grade.
- Vehicle Performance now sits under Leads beside Stock Level and Vehicle Desk.
- Monthly tier cards and the percentage chart now show standard pre-KPI targets; the live tier tracker and achieved result continue to apply KPI reductions.
- The monthly chart now uses the selected month's saved purchasing budget consistently across every row until the budget is manually changed.

### Motivating nutrition and bottle logging

- Rebuilt Nutrition around a daily score, logging streak and one clear next-best action that changes as meals, protein, fibre and water are recorded.
- Added one-tap 330 ml, 500 ml, 750 ml and 1.5 L bottle buttons, custom bottle amounts, a time-stamped daily water list and safe removal of accidental entries.
- Added a fast researched-meal picker alongside a cleaner manual macro form, with immediate updates to all targets and recommendations.
- Kept bowel and Bristol-score logging as a small gut check while moving rarely changed daily targets out of the primary workflow.

## Previous release — 2.1.0

### Gym command centre

- Added a dedicated Gym section directly beneath Leads with focused Today, Training, Nutrition, Progress and Meals & Bowls pages.
- Added editable starting targets for calories, protein, carbohydrates, fat, fibre, water and training frequency, with daily progress and gut-health habits kept local in Runway.
- Added a three-day full-body resistance programme, exercise load/reps/RIR logging, workout history and training-volume tracking.
- Added weight, waist, chest, arm and thigh check-ins so progress is judged by trends rather than scale weight alone.
- Added a researched Dubai delivery-meal library with calories and macros, source links and price-check dates, plus a high-protein/high-fibre custom bowl builder that sends meals directly to today’s tracker.
- Added constipation-safe guidance, gradual fibre reminders and clear medical warning signs; the feature does not diagnose or prescribe treatment.
- Made the sidebar scroll cleanly so the expanded workspace remains usable on smaller Mac displays.
- Rebuilt Training around readable exercise names, target rep ranges, previous performance and properly sized inputs; RIR now uses plain-English effort choices instead of an unexplained stretched number column.

## Previous release — 2.0.4

### WhatsApp offer route calculator

- Added a focused offer calculator to WhatsApp Templates using listing price and cash offer.
- The app calculates the offer as a percentage of asking and recommends one of three routes: lead with the offer at 90% or above, ask flexibility first from 80% to 89.9%, or qualify motivation and expectations below 80%.
- Each route generates a short, ordered WhatsApp conversation with individually copyable messages and optional vehicle personalisation.
- Kept saved templates in their own uncluttered sub-tab so the existing customer search and smart fields remain unchanged.

## Previous release — 2.0.3

### Clean first-time setup

- New installations now start with the representative demo-data option switched off.
- This makes shared builds open as a genuinely blank workspace unless the new user deliberately opts into examples.
- Application bundles remain data-free; each Mac creates its own private local database on first launch.

## Previous release — 2.0.2

### Call KPI pace tracker

- Added an on-track indicator showing how far ahead or behind the required monthly call pace you are today.
- Added calls remaining, the daily average required from today through month-end and your current daily average.
- Past and future months now show an appropriate completed or not-started state instead of a misleading live pace.

## Previous release — 2.0.1

### Readable call-log dates

- Call log dates now display in full as `05 Aug 2026` instead of being truncated.
- Widened the date column so the complete date remains visible in the KPI tracker.

## Previous release — 2.0.0

### Focused WhatsApp contact import

- Customer Contact can now import hand-picked WhatsApp HTML chat exports directly from Downloads.
- The importer extracts the customer or phone suffix, vehicle and model year, mileage, asking price, cash/consignment offers and next follow-up date when those details are present.
- Unsaved phone-number contacts use the detected make and model as their name; existing contacts are safely enriched instead of duplicated.
- Rapport is set to red only for a strong two-way conversation and green for a normal follow-up. Every decision and the latest message are recorded in customer notes.
- Successfully processed exports are moved to the Mac Trash, keeping Downloads as a simple inbox. Work contacts, groups and unrelated ZIP files are ignored.

## Previous release — 1.9.2

### KPI tier-goal reduction correction

- Corrected KPI rewards so each hit removes 0.50 percentage points from the profit percentage required for every tier.
- Four KPI hits therefore reduce an August Tier 3 goal from 9.5% to 7.5%, while commission rates remain fixed at 4%, 5%, 6.5% and 8%.
- Vehicle Desk projections, tier status, monthly table and synced earnings now use the reduced tier goals.

## Previous release — 1.9.1

### KPI-linked Vehicle Desk commission

- Every KPI hit now adds 0.50 percentage points to the achieved Vehicle Desk commission rate for that month.
- Vehicle Desk shows the KPI hit count and combined rate bonus beside profit achievement.
- Baseline and Tier 1/2/3 projections, the monthly tier table, sold-vehicle commission and synced earnings all use the KPI-adjusted rate.

## Previous release — 1.9.0

### Monthly KPI tracker

- Added a KPI tracker for all eight targets in the supplied schedule, with a clear hit/in-progress state and 0.50% impact for each achieved KPI.
- Call Maestro uses a flexible 240-call monthly target (8 × 30), with phone-number, date and call-count logging rather than a rigid daily requirement.
- Added working-day hour logging for Bayzat Champion and automatic calculations from vehicle, stock, consignment, profit and budget data for the remaining KPIs.
- Added month selection, a detailed call history and automatic progress updates.

## Previous release — 1.8.8

### Today's to-do list

- Added a dedicated daily to-do tab with quick task entry, completion ticks and deletion.
- Only the current day's tasks appear, so each new day begins with a clean list while earlier days remain stored locally.
- Added at-a-glance totals for today's outstanding and completed tasks.

## Previous release — 1.8.7

### Combined stock value

- Stock Level now shows the combined expected selling value of every unsold vehicle.
- The total includes cash purchases and consignments and is displayed in AED and GBP.

## Previous release — 1.8.6

### Revolving live purchasing budget

- Added a prominent Stock Level bar showing available AED and GBP budget, cash tied up in active stock and percentage used.
- Only unsold cash-purchase vehicles consume the live budget; consignments remain excluded.
- Selling or removing a cash vehicle immediately releases its purchase cost back into available budget.
- Saved budget capacity carries forward when a new month begins instead of resetting to a default, while monthly performance snapshots remain stored.

## 1.8.5

### Complete consignment lifecycle

- Added Mark as consignment for existing stock, with an agreed owner payout; converted vehicles immediately stop using the cash purchasing budget.
- Consignment sales now verify both actual sale price and final owner payout, preserving the original agreed payout and including any extra negotiation profit in realised profit.
- Added explicit Return consignment to owner wording so a withdrawn vehicle can leave Stock Level without recording a sale.

## 1.8.4

### Inspection purchase to Stock Level

- Replaced Inspection's ambiguous Mark sold action with Bought · move to stock.
- The purchase confirmation pre-fills the inspected vehicle, cash offer and valuation, then requires verification of stock type, cost/owner payout, expected selling price, date and notes.
- Saving atomically adds the vehicle to Stock Level and closes the inspection customer record, preventing a partial move.

## 1.8.3

### Sold to another buyer

- Added a Sold to another buyer action on Customer Contact.
- A clear confirmation explains that the customer, vehicle details, offers, follow-up history and notes will be permanently removed.
- Confirming deletes the customer throughout DXB RUNWAY, including customer search and WhatsApp personalisation.

## 1.8.2

### Empty search and duplicate-customer results

- Split customer lookup into an always-empty search box and a separate matching-results dropdown.
- Multiple matches—including identical customer names—remain available for deliberate selection.
- Each result includes vehicle, phone suffix and Caller or Inspection status so duplicate names are easy to distinguish.
- Starting a new search clears the previous customer immediately.

## 1.8.1

### Scalable customer search

- Replaced the long personalisation dropdown with a searchable customer selector.
- Search matches any part of the customer name, vehicle or last five phone digits.
- Results include year/make/model, phone suffix and Caller or Inspection context, with a compact 12-result popup.
- Typing alone never reuses an old customer selection; a matching customer must be deliberately selected before smart fields can be copied.

## 1.8.0

### Personalised WhatsApp templates

- Added one-click smart fields for customer name and year/make/model inside the template editor.
- Added a customer selector that renders a live personalised message before copying.
- Copy is held back when a template needs customer details until a customer is chosen, preventing unfilled placeholders from reaching WhatsApp.

## 1.7.9

### WhatsApp message templates

- Added a WhatsApp templates tab under Leads with named, multi-line reusable messages.
- Templates can be added, previewed, edited and deleted locally.
- Copy message places the exact text on the Mac clipboard and confirms that it is ready to paste into WhatsApp.

## 1.7.8

### Inspection calendar sync

- Scheduled vehicle inspections now appear automatically on their chosen date in Calendar.
- Calendar inspection cards show the customer, model year, vehicle and phone suffix.
- Returning an inspection to callers or marking it sold removes the active inspection from Calendar.

## 1.7.7

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
