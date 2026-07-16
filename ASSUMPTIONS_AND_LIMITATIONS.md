# Assumptions and known limitations

## Financial assumptions

- GBP/AED conversion uses the user's manual rate at calculation time. AED is primary and GBP is shown as an approximate translation calculated by dividing AED by the stored AED-per-GBP rate.
- Version 1.2 ships with the Central Bank of the UAE mid-rate snapshot of 4.928313 AED per GBP, published 14 July 2026. There are no hidden network calls, so later rates must be entered manually in Settings.
- Salary is earned at the band determined by assigned purchasing budget and paid at the end of a completed month.
- Commission applies to the full eligible monthly profit at the highest threshold achieved, then receives a payment date exactly two calendar months after the earned month-end.
- KPI deductions reduce estimated total earnings but never make it negative.
- A refundable deposit is unavailable cash until an income transaction marks its refund. It is not counted as ordinary expenditure.
- Credit purchases increase expenditure and card debt while leaving cash unchanged. Cross-currency purchases use the current manual rate.
- Transactions marked as one-off setup costs retain their real cash or card impact but are excluded from ordinary monthly expenditure and budget-consumption analytics.
- Pending commission is displayed as earned income but is excluded from cash, spendable cash, net wealth and daily allowance.
- The protected fund and outstanding deposits are excluded from spendable cash. Credit limits are excluded from net wealth.
- The default safe allowance looks across a 90-day protection window after the guaranteed-income contribution to essentials.
- Overview runway uses the current saved budget when available, otherwise the baseline settings. It includes card minimum payments when no debt-repayment budget is set and simulates the gap to the next salary date before applying monthly guaranteed income.
- `999+ days` means the current guaranteed monthly cash flow is non-negative; it is not a literal infinite forecast.
- Vehicle commission uses realised sale profit (`actual sale price − purchase price`) for the selected sold month. The achieved monthly tier rate is applied to the full non-negative aggregate eligible profit.
- The supplied 2026 month-of-year target schedule is reused when viewing later years until the employer publishes a replacement schedule.

## Product limitations

- The application is a planning tool, not regulated financial, tax, legal or employment advice.
- PDF reports are intentionally summary-led; receipt images are not embedded.
- CSV import accepts the included header format and skips exact same-day amount/merchant duplicates.
- New credit-card purchases and repayments are linked to a selected card. Balances and available credit update from those transactions; existing balances from older versions remain the opening position.
- In-app reminders appear on the calendar; no background Windows toast service runs while the app is closed.
- Encrypted backups require the password used to create them. Passwords are never stored and cannot be recovered.
- The executable is unsigned. Windows SmartScreen may warn on first launch; production distribution should use an Authenticode certificate.
