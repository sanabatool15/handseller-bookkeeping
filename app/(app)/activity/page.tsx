"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Activity, RefreshCw } from "lucide-react";
import { useActivityRequests, useRequestTimeline } from "@/lib/use-activity";
import { ActivityFilters, TxnEvent, TxnOutcome, TxnStep } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const OUTCOMES: Record<TxnOutcome, { label: string; variant: "default" | "success" | "danger" | "accent" }> = {
  committed: { label: "committed", variant: "success" },
  deadlock_retried: { label: "deadlock, retried", variant: "accent" },
  rolled_back: { label: "rolled back", variant: "danger" },
  rejected: { label: "rejected (business rule)", variant: "default" },
  in_progress: { label: "in progress", variant: "default" },
};

// Honest wording: the application cannot see lock waits, it only measures how long a call took.
const STEP_LABELS: Record<TxnStep, string> = {
  txn_started: "Transaction started",
  lock_wait_suspected: "Lock wait suspected (inferred from elapsed time, not observed)",
  deadlock_1205_caught: "Deadlock caught (SQL Server error 1205, chosen as victim)",
  lock_timeout_caught: "Lock timeout caught (error 1222)",
  retry_triggered: "Retry triggered",
  rolled_back: "Rolled back",
  committed: "Committed",
  business_rejected: "Rejected by a business rule (not an engine rollback)",
};
const STEP_VARIANT: Record<TxnStep, "default" | "success" | "danger" | "accent"> = {
  txn_started: "default",
  lock_wait_suspected: "accent",
  deadlock_1205_caught: "danger",
  lock_timeout_caught: "danger",
  retry_triggered: "accent",
  rolled_back: "danger",
  committed: "success",
  business_rejected: "default",
};

const OPERATIONS = [
  "record_sale",
  "void_sale",
  "record_expense",
  "void_expense",
  "adjust_entry_amount",
  "lab_race_sale_safe",
  "lab_race_sale_unsafe",
  "lab_deadlock",
  "lab_deadlock_fixed",
];

const SELECT_CLASS =
  "flex h-10 w-56 rounded-md border border-border bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-olive-soft";

function formatTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString(undefined, { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
}

function TimelineEvent({ e, t0 }: { e: TxnEvent; t0: number }) {
  const offset = Math.max(0, new Date(e.created_at).getTime() - t0);
  return (
    <li className="flex flex-col gap-1 rounded-md border border-border px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-20 shrink-0 text-xs tabular-nums text-muted-foreground">+{offset} ms</span>
        <Badge variant={STEP_VARIANT[e.step]}>{e.step}</Badge>
        <span className="text-sm">{STEP_LABELS[e.step] ?? e.step}</span>
        {e.retry_no > 0 && <span className="text-xs text-muted-foreground">retry {e.retry_no}</span>}
        {e.error_number != null && <span className="text-xs text-muted-foreground">error {e.error_number}</span>}
        {e.duration_ms != null && <span className="text-xs text-muted-foreground">{e.duration_ms} ms</span>}
      </div>
      {e.message && <p className="pl-[5.5rem] text-xs text-muted-foreground">{e.message}</p>}
    </li>
  );
}

function ActivityContent() {
  const params = useSearchParams();
  const [filters, setFilters] = useState<ActivityFilters>({ requestId: params.get("request_id") ?? "", operation: "", outcome: "" });
  const [auto, setAuto] = useState(false);
  const [selected, setSelected] = useState<string | null>(params.get("request_id"));
  const list = useActivityRequests(filters, auto);
  const timeline = useRequestTimeline(selected, auto);
  const filtered = filters.requestId !== "" || filters.operation !== "" || filters.outcome !== "";
  const t0 = timeline.events.length ? new Date(timeline.events[0].created_at).getTime() : 0;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-semibold text-olive">
          <Activity className="h-6 w-6" /> Activity
        </h1>
        <p className="text-sm text-muted-foreground">
          Every sale, expense, void and amount change is logged while it runs: transaction start, retries after a deadlock, commit, rollback.
          The log is written on a separate connection after the transaction ended, so a rolled-back request is still listed.
          &quot;Lock wait suspected&quot; is inferred from how long a call took; the app cannot observe lock waits directly.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div>
          <Label htmlFor="act-request">Request id</Label>
          <Input
            id="act-request"
            value={filters.requestId}
            onChange={(e) => setFilters({ ...filters, requestId: e.target.value })}
            placeholder="paste a request id"
            className="w-72"
          />
        </div>
        <div>
          <Label htmlFor="act-op">Operation</Label>
          <select id="act-op" value={filters.operation} onChange={(e) => setFilters({ ...filters, operation: e.target.value })} className={SELECT_CLASS}>
            <option value="">All operations</option>
            {OPERATIONS.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </div>
        <div>
          <Label htmlFor="act-outcome">Outcome</Label>
          <select
            id="act-outcome"
            value={filters.outcome}
            onChange={(e) => setFilters({ ...filters, outcome: e.target.value as TxnOutcome | "" })}
            className={SELECT_CLASS}
          >
            <option value="">All outcomes</option>
            {(Object.keys(OUTCOMES) as TxnOutcome[]).map((o) => (
              <option key={o} value={o}>
                {OUTCOMES[o].label}
              </option>
            ))}
          </select>
        </div>
        {filtered && (
          <Button variant="ghost" onClick={() => setFilters({ requestId: "", operation: "", outcome: "" })}>
            Clear filters
          </Button>
        )}
        <Button variant="outline" onClick={() => list.refresh()}>
          <RefreshCw className="h-4 w-4" /> Refresh
        </Button>
        <label className="flex h-10 items-center gap-2 text-sm">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
          Auto-refresh (3 s)
        </label>
      </div>
      {list.error && <p className="text-sm text-danger">{list.error}</p>}

      <div className="overflow-x-auto rounded-lg border border-border bg-surface">
        <table className="w-full text-sm">
          <thead className="bg-base-2 text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Started</th>
              <th className="px-4 py-3">Request id</th>
              <th className="px-4 py-3">Operation</th>
              <th className="px-4 py-3">Outcome</th>
              <th className="px-4 py-3 text-right">Retries</th>
              <th className="px-4 py-3 text-right">Duration</th>
              <th className="px-4 py-3">Isolation</th>
            </tr>
          </thead>
          <tbody>
            {list.loading && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                  Loading…
                </td>
              </tr>
            )}
            {!list.loading && list.requests.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                  {filtered ? "No requests match these filters." : "Nothing logged yet. Record a sale or an expense."}
                </td>
              </tr>
            )}
            {list.requests.map((r) => {
              const o = OUTCOMES[r.outcome] ?? OUTCOMES.in_progress;
              return (
                <tr key={r.request_id} className={`border-t border-border ${selected === r.request_id ? "bg-base-2" : ""}`}>
                  <td className="px-4 py-3 whitespace-nowrap tabular-nums">{formatTime(r.first_at)}</td>
                  <td className="px-4 py-3">
                    <button className="font-mono text-xs underline decoration-dotted" onClick={() => setSelected(r.request_id)}>
                      {r.request_id.length > 18 ? `${r.request_id.slice(0, 18)}…` : r.request_id}
                    </button>
                  </td>
                  <td className="px-4 py-3">{r.operation}</td>
                  <td className="px-4 py-3">
                    <Badge variant={o.variant}>{o.label}</Badge>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">{r.retries}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{r.duration_ms} ms</td>
                  <td className="px-4 py-3 text-muted-foreground">{r.isolation_level ?? "-"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {selected && (
        <Card>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-base font-semibold text-olive">
              <span>
                Timeline of <span className="font-mono text-sm">{selected}</span>
              </span>
              <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>
                Close
              </Button>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {timeline.error && <p className="text-sm text-danger">{timeline.error}</p>}
            {timeline.loading && <p className="text-sm text-muted-foreground">Loading…</p>}
            {!timeline.loading && !timeline.error && timeline.events.length === 0 && (
              <p className="text-sm text-muted-foreground">No events for this request id in your workspace.</p>
            )}
            <ol className="flex flex-col gap-2">
              {timeline.events.map((e) => (
                <TimelineEvent key={e.id} e={e} t0={t0} />
              ))}
            </ol>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function ActivityPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
      <ActivityContent />
    </Suspense>
  );
}
