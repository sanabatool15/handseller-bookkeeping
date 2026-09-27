"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

export function MonthlyTrendChart({
  data,
}: {
  data: { month: string; sales: number; expenses: number }[];
}) {
  if (data.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
        No data yet
      </div>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart data={data}>
        <defs>
          <linearGradient id="salesGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#2F3D21" stopOpacity={0.5} />
            <stop offset="100%" stopColor="#2F3D21" stopOpacity={0.02} />
          </linearGradient>
          <linearGradient id="expensesGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#D8DB7C" stopOpacity={0.7} />
            <stop offset="100%" stopColor="#D8DB7C" stopOpacity={0.05} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#E3E6D4" />
        <XAxis dataKey="month" tick={{ fontSize: 12 }} stroke="#6B7460" />
        <YAxis tick={{ fontSize: 12 }} stroke="#6B7460" />
        <Tooltip
          formatter={(value) => `$${Number(value).toFixed(2)}`}
          contentStyle={{
            borderRadius: 8,
            border: "1px solid #E3E6D4",
            fontSize: 12,
          }}
        />
        <Area
          type="monotone"
          dataKey="sales"
          stroke="#2F3D21"
          fill="url(#salesGradient)"
          strokeWidth={2}
          animationDuration={900}
        />
        <Area
          type="monotone"
          dataKey="expenses"
          stroke="#A9AC4A"
          fill="url(#expensesGradient)"
          strokeWidth={2}
          animationDuration={900}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
