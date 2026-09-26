"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatCurrency } from "@/lib/utils";
import { cn } from "@/lib/utils";
import { LucideIcon } from "lucide-react";

interface KpiCardProps {
  label: string;
  value: number;
  icon: LucideIcon;
  tone?: "default" | "accent" | "olive";
  format?: "currency" | "number";
}

export function KpiCard({
  label,
  value,
  icon: Icon,
  tone = "default",
  format = "currency",
}: KpiCardProps) {
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    const duration = 700;
    const start = performance.now();
    let raf: number;
    function tick(now: number) {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(value * eased);
      if (progress < 1) raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);

  const toneClasses = {
    default: "bg-surface text-olive",
    accent: "bg-accent text-olive",
    olive: "bg-olive text-white",
  }[tone];

  return (
    <Card className={cn("overflow-hidden", tone !== "default" && toneClasses)}>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle
          className={cn(tone === "olive" ? "text-white/80" : undefined)}
        >
          {label}
        </CardTitle>
        <Icon
          className={cn(
            "h-4 w-4",
            tone === "olive" ? "text-accent" : "text-olive-soft"
          )}
        />
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-semibold tabular-nums">
          {format === "currency" ? formatCurrency(display) : Math.round(display)}
        </p>
      </CardContent>
    </Card>
  );
}
