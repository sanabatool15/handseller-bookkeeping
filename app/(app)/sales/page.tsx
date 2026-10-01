"use client";

import { Receipt, TrendingUp, Hash } from "lucide-react";
import { useState } from "react";
import { useLedger, ledgerErrorMessage } from "@/lib/use-ledger";
import { useCustomers } from "@/lib/use-customers";
import { useProducts } from "@/lib/use-products";
import { LedgerTable } from "@/components/ledger-table";
import { KpiCard } from "@/components/kpi-card";

export default function SalesPage() {
  const { entries, loading, error, create, update, remove } = useLedger("sales");
  const [actionError, setActionError] = useState<string | null>(null);
  const { customers } = useCustomers(); // optional dropdown; a failed load just leaves it empty
  const { products, refresh: refreshProducts } = useProducts(); // line-items editor; stock changes with each sale
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

      {(actionError ?? error) && <p className="text-sm text-danger">{actionError ?? error}</p>}

      <LedgerTable
        kind="sales"
        entries={entries}
        loading={loading}
        onCreate={async (input) => {
          try {
            return await create(input);
          } finally {
            await refreshProducts(); // stock shown in the dropdown stays current
          }
        }}
        onUpdate={update}
        onDelete={async (id) => {
          setActionError(null);
          try {
            await remove(id); // voiding gives the stock back
          } catch (e) {
            setActionError(ledgerErrorMessage(e, "Could not delete sale"));
          }
          await refreshProducts();
        }}
        customers={customers}
        products={products}
      />
    </div>
  );
}
