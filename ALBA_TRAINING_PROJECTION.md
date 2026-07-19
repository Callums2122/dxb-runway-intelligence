# Alba Cars training projection

> **Status: provisional discovery plan — not an approved Alba Cars workflow and not approved or scheduled for implementation.**

This projection records how DXB RUNWAY might support a future vehicle-purchasing role after the real Alba Cars process, terminology, systems, permissions and commission rules are learned during training. It intentionally avoids pretending those details are already known.

## Current boundary

- DXB RUNWAY remains the current personal financial and vehicle-performance application.
- No Alba-specific workflow, automation, integration or artificial-intelligence access has been approved.
- No company information should be entered into DXB RUNWAY or an AI service without Alba Cars authorisation.
- Training observations must be separated from confirmed company policy.
- Existing Vehicle Desk functionality should not be expanded until the actual purchase lifecycle is mapped.

## Discovery objective

Training should answer four questions before software design begins:

1. How does a potential vehicle enter Alba's purchasing process?
2. How is it valued, inspected, approved, negotiated and attributed?
3. Which costs, dates and profit figures determine performance and commission?
4. Which company systems and data may be connected to local software or AI?

## Information to capture during training

### Lead intake

- Lead sources and ownership
- Assignment rules
- Required seller and vehicle information
- Duplicate-lead handling
- Response-time expectations
- Systems, inboxes and marketplaces used

### Appraisal

- How comparable vehicles are selected
- GCC/import and specification treatment
- Mileage, history and condition adjustments
- Preparation, inspection, transport, warranty and administration costs
- Target offer and walk-away price rules
- Required evidence and documents

### Approval and negotiation

- Individual purchasing authority
- Manager or department approval stages
- Offer submission channels
- Negotiation rules
- Rejection reasons
- Audit or compliance requirements

### Purchase to stock

- When a vehicle becomes purchased stock
- When budget is considered used
- Required handover information
- Inspection and preparation workflow
- Responsibility for listing and pricing
- Vehicle attribution rules

### Sale and performance

- Which sold date and profit value count toward performance
- Eligible and ineligible profit adjustments
- Commission targets, rate changes and deductions
- Treatment of returns, cancellations and post-sale costs
- Aged-stock and markdown rules
- Reporting cadence and management KPIs

### Data and permissions

- Permitted company data
- Personally identifiable seller information
- Approved AI and cloud services
- Marketplace terms and available feeds or exports
- Retention, backup and deletion requirements
- Who can authorise integrations and automated messages

## Provisional future navigation

The following is a discovery hypothesis only. Names, order and responsibilities must be revised after training.

```text
OVERVIEW

LEADS / PURCHASING
├── Deal Inbox          potential vehicles before purchase
├── Appraisal Desk      comparable evidence, costs and offer limits
├── Market Radar        authorised market and price-change signals
├── Vehicle Desk        purchased stock and sold performance
├── Purchase Journal    training notes, decisions and lessons
├── Calendar
└── Scenario Lab

MONEY TRACKING
├── Transactions
├── Debt Control
└── Budgets

MISC / OTHER
├── Momentum
├── Reports
└── Settings
```

Only Purchase Journal could reasonably be considered before process discovery, because it would capture flexible notes rather than enforce an assumed workflow. Even that tab should not be built until its data boundary is agreed.

## Provisional system responsibilities

### DXB RUNWAY

- Remain the deterministic source for budgets, stock, realised profit and commission calculations.
- Store only approved data.
- Require human confirmation for status and financial changes.

### GPT-5.6

- Potentially normalise authorised listing information.
- Potentially compare photographs, specifications and inspection documents.
- Potentially prepare appraisal evidence, risks and negotiation briefs.
- Never determine the final purchase decision or replace physical verification.

### OpenClaw

- Potentially schedule authorised market checks and internal reminders.
- Potentially assemble a daily purchasing brief from approved sources.
- Require human approval for external messages, database writes and commands.
- Never submit offers, contact sellers or commit funds autonomously.

## Implementation gates

No Alba-specific phase should start until its gate is passed.

### Gate 1 — Process map

- Training lifecycle documented end to end
- Terminology confirmed
- Required fields and statuses confirmed
- Purchasing and commission rules confirmed

### Gate 2 — Permission and data boundary

- Alba authorises the intended use
- Approved data sources identified
- Personal and company data separated
- AI, cloud and marketplace restrictions documented

### Gate 3 — Read-only prototype

- Deal recommendations operate in shadow mode
- No external messages or automated purchases
- Human appraisals compared with system outputs
- Errors and missing evidence recorded

### Gate 4 — Controlled operational use

- Accuracy thresholds agreed with management
- Human approval remains mandatory
- Audit history and rollback verified
- Performance reviewed before expanding automation

## Provisional success measures

Exact targets must be established from Alba's historical baseline. Candidate measures include:

- Realised profit per vehicle
- Total realised profit
- Profit per deployed budget dirham
- Profit per invested-dirham-day
- Median days to sale
- 30-, 45- and 60-day sell-through
- Expected-versus-realised profit error
- Preparation-cost variance
- Purchase saving against original asking price
- Profit and sell-through by lead source
- Aged-stock exposure
- Commission-tier forecast accuracy

## Explicit non-goals before training

- No unauthorised scraping
- No automatic seller messages
- No automatic offer submission
- No autonomous purchasing
- No invented approval workflow
- No assumed inspection checklist
- No unverified commission logic
- No company or seller data mixed into the personal database

## Review point

After the first structured period of Alba training, this projection should be rewritten from evidence. The first implementation decision should then be whether Deal Inbox, Purchase Journal or no additional tab best matches the confirmed process.
