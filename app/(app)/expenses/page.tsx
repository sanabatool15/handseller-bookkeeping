"use client";

import { Wallet, TrendingDown, Hash } from "lucide-react";
import { useState } from "react";
import { useLedger, ledgerErrorMessage } from "@/lib/use-ledger";
import { LedgerTable } from "@/components/ledger-table";
import { KpiCard } from "@/components/kpi-card";

export default function ExpensesPage() {
  const { entries, loading, error, create, update, remove } = useLedger("expenses");
  const [actionError, setActionError] = useState<string | null>(null);
  const total = entries.reduce((sum, e) => sum + e.amount, 0);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-olive">Expenses</h1>
        <p className="text-sm text-muted-foreground">
          Every outgoing cost, with voucher references.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <KpiCard label="Total expenses" value={total} icon={TrendingDown} tone="olive" />
        <KpiCard label="Entries" value={entries.length} icon={Hash} format="number" />
        <KpiCard
          label="Average expense"
          value={entries.length ? total / entries.length : 0}
          icon={Wallet}
        />
      </div>

      <p className="text-xs text-muted-foreground">
        Expenses reduce your cash balance (see the Cash page); deleting one gives the money back.
      </p>
      {(actionError ?? error) && <p className="text-sm text-danger">{actionError ?? error}</p>}

      <LedgerTable
        kind="expenses"
        entries={entries}
        loading={loading}
        onCreate={create}
        onUpdate={update}
        onDelete={async (id) => {
          setActionError(null);
          try {
            await remove(id);
          } catch (e) {
            setActionError(ledgerErrorMessage(e, "Could not delete expense"));
          }
        }}
      />
    </div>
  );
}
