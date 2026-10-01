"use client";

import { useMemo, useState } from "react";
import { DollarSign, TrendingUp, TrendingDown, Plus, Sparkles, Wallet } from "lucide-react";
import Link from "next/link";
import { useLedger } from "@/lib/use-ledger";
import { useCash } from "@/lib/use-cash";
import { KpiCard } from "@/components/kpi-card";
import { GeneralInfoCard } from "@/components/general-info-card";
import { LedgerFormModal } from "@/components/ledger-form-modal";
import { CategoryBreakdownChart } from "@/components/charts/category-breakdown-chart";
import { MonthlyTrendChart } from "@/components/charts/monthly-trend-chart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default function DashboardPage() {
  const sales = useLedger("sales");
  const expenses = useLedger("expenses");
  const cash = useCash();
  const [quickAdd, setQuickAdd] = useState<"sales" | "expenses" | null>(null);

  const totalSales = useMemo(
    () => sales.entries.reduce((s, e) => s + e.amount, 0),
    [sales.entries]
  );
  const totalExpenses = useMemo(
    () => expenses.entries.reduce((s, e) => s + e.amount, 0),
    [expenses.entries]
  );
  const net = totalSales - totalExpenses;

  const categoryData = useMemo(() => {
    const map = new Map<string, number>();
    for (const e of expenses.entries) {
      map.set(e.category, (map.get(e.category) ?? 0) + e.amount);
    }
    return Array.from(map.entries()).map(([name, value]) => ({ name, value }));
  }, [expenses.entries]);

  const monthlyData = useMemo(() => {
    const map = new Map<string, { sales: number; expenses: number }>();
    function bucket(dateStr: string | undefined, key: "sales" | "expenses", amount: number) {
      const d = dateStr ? new Date(dateStr) : new Date();
      const label = d.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
      const entry = map.get(label) ?? { sales: 0, expenses: 0 };
      entry[key] += amount;
      map.set(label, entry);
    }
    sales.entries.forEach((e) => bucket(e.sale_date ?? e.created_at, "sales", e.amount));
    expenses.entries.forEach((e) => bucket(e.expense_date ?? e.created_at, "expenses", e.amount));
    return Array.from(map.entries()).map(([month, v]) => ({ month, ...v }));
  }, [sales.entries, expenses.entries]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-olive">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            A live snapshot of your business finances.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setQuickAdd("sales")}>
            <Plus className="h-4 w-4" /> Sale
          </Button>
          <Button variant="outline" onClick={() => setQuickAdd("expenses")}>
            <Plus className="h-4 w-4" /> Expense
          </Button>
          <Button asChild>
            <Link href="/advisor">
              <Sparkles className="h-4 w-4" /> Ask advisor
            </Link>
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="Net profit / loss" value={net} icon={DollarSign} tone="olive" />
        <KpiCard label="Total sales" value={totalSales} icon={TrendingUp} tone="accent" />
        <KpiCard label="Total expenses" value={totalExpenses} icon={TrendingDown} />
        <KpiCard label="Cash balance" value={cash.balance} icon={Wallet} />
      </div>

      <GeneralInfoCard />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base font-semibold text-olive">
              Expense breakdown by category
            </CardTitle>
          </CardHeader>
          <CardContent>
            <CategoryBreakdownChart data={categoryData} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base font-semibold text-olive">
              Monthly sales vs. expenses
            </CardTitle>
          </CardHeader>
          <CardContent>
            <MonthlyTrendChart data={monthlyData} />
          </CardContent>
        </Card>
      </div>

      {quickAdd && (
        <LedgerFormModal
          kind={quickAdd}
          open={!!quickAdd}
          onOpenChange={(open) => !open && setQuickAdd(null)}
          onSubmit={async (input) => {
            if (quickAdd === "sales") {
              const created = await sales.create(input);
              await cash.refresh();
              return created;
            }
            return expenses.create(input);
          }}
        />
      )}
    </div>
  );
}
