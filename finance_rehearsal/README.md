# Fictional finance and migration rehearsals

Development only. These files do not read the Noor database, verify evidence, import or modify any records, post accounts, calculate a company profit, or authorize deployment. The sample amounts and sign-offs are fictional. Do not place real company data in this build.

## Finance rehearsal

Run `python scripts/finance_rehearsal.py finance_rehearsal/fictional_finance.json` from the project root. Currency values are strings in naira with at most two decimal places; never floats. Categories are unsigned: gross sales, sales returns/discounts, cost of sales, operating expenses, other income, other expenses and tax. The calculation subtracts returns and costs and adds other income. It assumes that a qualified accountant has already classified amounts and calculated cost of sales under a documented policy; it does not calculate inventory costing, tax, accruals or physical production yields. It does not treat customer payments, handovers or bank deposits as additional revenue. These categories and treatment are illustrative, not decisions for Noor.

Each category needs a separately labelled control, including an explicit zero where appropriate. Opening and closing cash, bank, inventory, receivables and payables each need separately labelled ledger and evidence amounts. This is a limited comparison, not a complete trial balance or proof of reconciliation; it cannot verify the figures, evidence independence, completeness, authorization, date alignment, journal balancing, exclusions or policy. Unique references guard only obvious duplication. Personnel and policy entries are self-declared strings, not authentication, proof of approval or real sign-off. It blocks arithmetic output on recorded differences or missing required data. Even a matching result remains **draft rehearsal only**, not reliable or approved profit. A proper P&L requires independent reconciliation and traceability to the source and ledger, a period lock, approvals, correction/audit controls, and a policy signed by authorized people. The actual application continues to show no profit.

## Migration rehearsal controls

Run `python scripts/migration_manifest.py finance_rehearsal/fictional_migration.json`. The manifest is an example of comparing manually declared row counts and totals by unit for a particular mapping. Exclusions must have an approval reference; unresolved rows or mismatches block a matching result. Missing values are errors, not zero. Snapshot IDs, references, counts and approvals are just operator statements. Matching totals cannot prove correct row-level mapping, deduplication, linked records, source completeness, balances, independent approval or a safe migration. A row may map to multiple target rows; those mappings require a different signed reconciliation method, not forced counts. Unit controls cannot mix kilograms, bags, packs, naira or distinct products. This script has no database connection and creates no target records.

For an actual migration, first identify source systems and owners and obtain authorization. Inventory schema and source-of-truth; use a consistent isolated backup copy, never a live database. Document reviewed mappings and handling of omissions, pending handovers, payment duplication and corrections. Define opening quantities and monetary values with evidence and authorized reconciliation. Build and test a source-specific importer with protected credentials, immutable identifiers, row-level exception reports, idempotency, foreign-key checks, independent totals, restore and rollback; only then rehearse on a disposable target. Separately approve freeze, final reconciliation, cutover and security controls. None of this package is a real importer or authorization to deploy.

## Decisions to confirm before implementing company P&L

1. Revenue recognition: customer sale versus transfer to sales manager; direct sales, returns, discounts, credit and tax. A handover and an onward sale must not both count as sales revenue.
2. Cost of sales: pooled-material valuation and opening values, treatment of cleaning losses, missing weights, production/packaging costs, overheads and by-products.
3. Period boundaries, treatment of operating and other expenses, taxes, bad debts and unsettled balances, approved source reports and independent sign-off responsibilities.
4. Scope and evidence for opening/closing stock, cash, bank, customer receivables and supplier payables, including unresolved exceptions.

No management/accountant decisions, company source, balances, evidence or approvals have been supplied here.
