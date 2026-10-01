"use client";

import { useState } from "react";
import { Landmark, ArrowDownToLine, ArrowUpFromLine, Scale } from "lucide-react";
import { useCash, useCashLedger, useCashSummary } from "@/lib/use-cash";
import { CashEntryType, CashLedgerFilters } from "@/lib/types";
import { KpiCard } from "@/components/kpi-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn, formatCurrency } from "@/lib/utils";

const TYPE_LABELS: Record<CashEntryType, string> = {
  sale: "Sale",
  sale_void: "Sale voided",
  expense: "Expense",
  expense_void: "Expense voided",
  adjustment: "Adjustment",
};
const TYPES = Object.keys(TYPE_LABELS) as CashEntryType[];

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** entry_date is a plain calendar date (YYYY-MM-DD): format it without timezone conversion. */
function formatEntryDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function signed(amount: number): string {
  return `${amount > 0 ? "+" : amount < 0 ? "-" : ""}${formatCurrency(Math.abs(amount))}`;
}

const EMPTY_FILTERS: CashLedgerFilters = { entryType: "", from: "", to: "" };

export default function CashPage() {
  const cash = useCash();
  const [filters, setFilters] = useState<CashLedgerFilters>(EMPTY_FILTERS);
  const [month, setMonth] = useState(currentMonth());
  const [year, monthNo] = month.split("-").map(Number);
  const ledger = useCashLedger(filters);
  const summary = useCashSummary(year, monthNo);
  const filtered = filters.entryType !== "" || filters.from !== "" || filters.to !== "";

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-olive">Cash</h1>
        <p className="text-sm text-muted-foreground">
          Every movement of money in and out, from sales and expenses. The balance can go below zero when you spend before cashing up.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <KpiCard label="Cash balance" value={cash.balance} icon={Landmark} tone="olive" />
      </div>
      {cash.error && <p className="text-sm text-danger">{cash.error}</p>}

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-lg font-semibold text-olive">Monthly summary</h2>
          <div>
            <Label htmlFor="cash-month">Month</Label>
            <Input
              id="cash-month"
              type="month"
              value={month}
              max={currentMonth()}
              onChange={(e) => e.target.value && setMonth(e.target.value)}
              className="w-44"
            />
          </div>
        </div>
        {summary.error && <p className="text-sm text-danger">{summary.error}</p>}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard label="Opening balance" value={summary.summary?.opening_balance ?? 0} icon={Scale} />
          <KpiCard label="Money in" value={summary.summary?.total_in ?? 0} icon={ArrowDownToLine} tone="accent" />
          <KpiCard label="Money out" value={summary.summary?.total_out ?? 0} icon={ArrowUpFromLine} />
          <KpiCard label="Closing balance" value={summary.summary?.closing_balance ?? 0} icon={Landmark} tone="olive" />
        </div>
        {summary.summary && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base font-semibold text-olive">Net by type this month</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
                {TYPES.map((t) => {
                  const v = summary.summary!.by_type[t] ?? 0;
                  return (
                    <li key={t} className="rounded-md border border-border px-3 py-2">
                      <p className="text-xs text-muted-foreground">{TYPE_LABELS[t]}</p>
                      <p className={cn("text-sm font-semibold tabular-nums", v > 0 && "text-success", v < 0 && "text-danger")}>
                        {signed(v)}
                      </p>
                    </li>
                  );
                })}
              </ul>
            </CardContent>
          </Card>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-olive">Ledger</h2>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <Label htmlFor="cash-type">Type</Label>
            <select
              id="cash-type"
              value={filters.entryType}
              onChange={(e) => setFilters({ ...filters, entryType: e.target.value as CashEntryType | "" })}
              className="flex h-10 w-48 rounded-md border border-border bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-olive-soft"
            >
              <option value="">All types</option>
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {TYPE_LABELS[t]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="cash-from">From</Label>
            <Input id="cash-from" type="date" value={filters.from} onChange={(e) => setFilters({ ...filters, from: e.target.value })} className="w-44" />
          </div>
          <div>
            <Label htmlFor="cash-to">To</Label>
            <Input id="cash-to" type="date" value={filters.to} onChange={(e) => setFilters({ ...filters, to: e.target.value })} className="w-44" />
          </div>
          {filtered && (
            <Button variant="ghost" onClick={() => setFilters(EMPTY_FILTERS)}>
              Clear filters
            </Button>
          )}
        </div>
        {ledger.error && <p className="text-sm text-danger">{ledger.error}</p>}

        <div className="overflow-x-auto rounded-lg border border-border bg-surface">
          <table className="w-full text-sm">
            <thead className="bg-base-2 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Reference</th>
                <th className="px-4 py-3 text-right">Amount</th>
                <th className="px-4 py-3 text-right">Balance after</th>
              </tr>
            </thead>
            <tbody>
              {ledger.loading && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                    Loading…
                  </td>
                </tr>
              )}
              {!ledger.loading && ledger.entries.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                    {filtered ? "No entries match these filters." : "No cash movements yet. Record a sale or an expense."}
                  </td>
                </tr>
              )}
              {ledger.entries.map((e) => (
                <tr key={e.id} className="border-t border-border">
                  <td className="px-4 py-3 whitespace-nowrap">{formatEntryDate(e.entry_date)}</td>
                  <td className="px-4 py-3">
                    <Badge variant={e.amount > 0 ? "success" : e.amount < 0 ? "danger" : "default"}>{TYPE_LABELS[e.entry_type] ?? e.entry_type}</Badge>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{e.ref_type ?? "-"}</td>
                  <td className={cn("px-4 py-3 text-right font-medium tabular-nums", e.amount > 0 && "text-success", e.amount < 0 && "text-danger")}>
                    {signed(e.amount)}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">{formatCurrency(e.balance_after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted-foreground">Showing the newest 200 entries. Balance after is the running balance when the entry was posted.</p>
      </section>
    </div>
  );
}
