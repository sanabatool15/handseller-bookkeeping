"use client";

import { Receipt, TrendingUp, Hash } from "lucide-react";
import { useLedger } from "@/lib/use-ledger";
import { useCustomers } from "@/lib/use-customers";
import { LedgerTable } from "@/components/ledger-table";
import { KpiCard } from "@/components/kpi-card";

export default function SalesPage() {
  const { entries, loading, create, update, remove } = useLedger("sales");
  const { customers } = useCustomers(); // optional dropdown; a failed load just leaves it empty
  const total = entries.reduce((sum, e) => sum + e.amount, 0);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-olive">Sales</h1>
        <p className="text-sm text-muted-foreground">
          Track every sale your business logs.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <KpiCard label="Total sales" value={total} icon={TrendingUp} tone="olive" />
        <KpiCard label="Entries" value={entries.length} icon={Hash} format="number" />
        <KpiCard
          label="Average sale"
          value={entries.length ? total / entries.length : 0}
          icon={Receipt}
        />
      </div>

      <LedgerTable
        kind="sales"
        entries={entries}
        loading={loading}
        onCreate={create}
        onUpdate={update}
        onDelete={remove}
        customers={customers}
      />
    </div>
  );
}
