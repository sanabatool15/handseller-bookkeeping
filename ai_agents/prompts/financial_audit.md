# Financial Audit Prompt Template

You are auditing the monthly ledger for organization `{org_id}` covering
`{year}-{month:02d}`.

Ledger CSV (from `ledger://{org_id}/monthly.csv`):

```csv
{ledger_csv}
```

Perform an audit:
1. Flag any transactions that look duplicated, miscategorized, or unusually
   large relative to the rest of the ledger.
2. Reconcile total sales vs total expenses and confirm the net profit figure.
3. List any missing or suspicious data (e.g. expenses with no voucher
   reference).

Return your findings as a short bulleted list, ending with an overall
"Audit status: clean" or "Audit status: needs review" verdict.
