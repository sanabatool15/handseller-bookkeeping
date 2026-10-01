"use client";

import { useState } from "react";
import Link from "next/link";
import { FlaskConical } from "lucide-react";
import { useProducts } from "@/lib/use-products";
import { useDbLabRunner, useDbLabStatus } from "@/lib/use-db-lab";
import { DbLabClientResult, DbLabDeadlockResult, DbLabRaceResult, IsolationLevel } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const LEVELS: IsolationLevel[] = ["READ UNCOMMITTED", "READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE", "SNAPSHOT"];
const DELAYS = [0, 1, 2, 3, 4, 5];
const SELECT_CLASS =
  "flex h-10 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-olive-soft";
const STATUS_VARIANT = { committed: "success", rejected: "default", rolled_back: "danger" } as const;

function ResultsTable({ rows }: { rows: DbLabClientResult[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full text-sm">
        <thead className="bg-base-2 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-4 py-3">Client</th>
            <th className="px-4 py-3">Outcome</th>
            <th className="px-4 py-3 text-right">Retries</th>
            <th className="px-4 py-3 text-right">Duration</th>
            <th className="px-4 py-3">SQL Server error</th>
            <th className="px-4 py-3">Message</th>
            <th className="px-4 py-3">Log</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.client} className="border-t border-border align-top">
              <td className="px-4 py-3">#{r.client}</td>
              <td className="px-4 py-3">
                <Badge variant={STATUS_VARIANT[r.status]}>{r.status.replace("_", " ")}</Badge>
              </td>
              <td className="px-4 py-3 text-right tabular-nums">{r.retries}</td>
              <td className="px-4 py-3 text-right tabular-nums">{r.duration_ms} ms</td>
              <td className="px-4 py-3 tabular-nums">{r.error_number ?? "-"}</td>
              <td className="px-4 py-3 text-xs text-muted-foreground">{r.message ?? "-"}</td>
              <td className="px-4 py-3">
                {r.request_id ? (
                  <Link className="font-mono text-xs underline decoration-dotted" href={`/activity?request_id=${encodeURIComponent(r.request_id)}`}>
                    {r.request_id.slice(0, 14)}…
                  </Link>
                ) : (
                  "-"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function DbLabPage() {
  const enabled = useDbLabStatus();
  const { products, loading: productsLoading } = useProducts();
  const lab = useDbLabRunner();
  const [productId, setProductId] = useState("");
  const [productB, setProductB] = useState("");
  const [clients, setClients] = useState(3);
  const [quantity, setQuantity] = useState(1);
  const [mode, setMode] = useState<"safe" | "unsafe">("unsafe");
  const [level, setLevel] = useState<IsolationLevel>("READ COMMITTED");
  const [delay, setDelay] = useState(1);

  if (enabled === null) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (!enabled) {
    return (
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold text-olive">DB Lab</h1>
        <p className="text-sm text-muted-foreground">
          The DB Lab is switched off on this server. It is a classroom demo; set <code>ENABLE_DB_LAB=true</code> in the API environment and restart to use it.
        </p>
      </div>
    );
  }

  const first = productId || products[0]?.id || "";
  const second = productB || products.find((p) => p.id !== first)?.id || "";
  const busy = lab.running !== null;
  const race = lab.result?.kind === "race_sale" ? (lab.result as DbLabRaceResult) : null;
  const dead = lab.result && lab.result.kind !== "race_sale" ? (lab.result as DbLabDeadlockResult) : null;
  const nameOf = (id: string) => products.find((p) => p.id === id)?.name ?? id.slice(0, 8);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-semibold text-olive">
          <FlaskConical className="h-6 w-6" /> DB Lab <Badge variant="accent">demo only</Badge>
        </h1>
        <p className="text-sm text-muted-foreground">
          Real concurrent transactions on your own products, to watch locking, deadlocks (error 1205), retries, rollbacks and commits.
          Only product stock is touched, and it is put back afterwards (the deadlock demo nets to zero; the race restores the stock it started with).
          No sales or cash entries are created. Do not run it while you are really selling the same product.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base font-semibold text-olive">Setup</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <Label htmlFor="lab-product">Product (race, deadlock A)</Label>
            <select id="lab-product" className={SELECT_CLASS} value={first} onChange={(e) => setProductId(e.target.value)} disabled={productsLoading}>
              {products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} (stock {p.stock_qty})
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="lab-product-b">Second product (deadlock B)</Label>
            <select id="lab-product-b" className={SELECT_CLASS} value={second} onChange={(e) => setProductB(e.target.value)} disabled={productsLoading}>
              {products
                .filter((p) => p.id !== first)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} (stock {p.stock_qty})
                  </option>
                ))}
            </select>
          </div>
          <div>
            <Label htmlFor="lab-clients">Clients (2-10)</Label>
            <Input id="lab-clients" type="number" min={2} max={10} value={clients} onChange={(e) => setClients(Number(e.target.value))} />
          </div>
          <div>
            <Label htmlFor="lab-qty">Quantity per sale</Label>
            <Input id="lab-qty" type="number" min={1} max={10} value={quantity} onChange={(e) => setQuantity(Number(e.target.value))} />
          </div>
          <div>
            <Label htmlFor="lab-mode">Race mode</Label>
            <select id="lab-mode" className={SELECT_CLASS} value={mode} onChange={(e) => setMode(e.target.value as "safe" | "unsafe")}>
              <option value="unsafe">unsafe: read stock, wait, write (can oversell)</option>
              <option value="safe">safe: one guarded UPDATE (one winner)</option>
            </select>
          </div>
          <div>
            <Label htmlFor="lab-level">Isolation level</Label>
            <select id="lab-level" className={SELECT_CLASS} value={level} onChange={(e) => setLevel(e.target.value as IsolationLevel)}>
              {LEVELS.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="lab-delay">Delay (seconds)</Label>
            <select id="lab-delay" className={SELECT_CLASS} value={delay} onChange={(e) => setDelay(Number(e.target.value))}>
              {DELAYS.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-wrap gap-3">
        <Button
          disabled={busy || !first}
          onClick={() => lab.raceSale({ productId: first, quantity, clients, mode, isolationLevel: level, delaySeconds: delay })}
        >
          {lab.running === "race" ? "Running…" : "Race sale"}
        </Button>
        <Button variant="danger" disabled={busy || !first || !second} onClick={() => lab.deadlock({ productA: first, productB: second, delaySeconds: delay }, false)}>
          {lab.running === "deadlock" ? "Running…" : "Force deadlock"}
        </Button>
        <Button variant="accent" disabled={busy || !first || !second} onClick={() => lab.deadlock({ productA: first, productB: second, delaySeconds: delay }, true)}>
          {lab.running === "fixed" ? "Running…" : "Deadlock fixed (same lock order)"}
        </Button>
        <Button variant="outline" asChild>
          <Link href="/activity">Open Activity</Link>
        </Button>
      </div>
      {busy && <p className="text-sm text-muted-foreground">Running real transactions on the server. A deadlock can take up to about 5 seconds to be detected by SQL Server.</p>}
      {lab.error && <p className="text-sm text-danger">{lab.error}</p>}
      {first && products.length < 2 && <p className="text-xs text-muted-foreground">The deadlock demos need two products.</p>}

      {lab.result && (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold text-olive">Result</h2>
          <p className="text-sm font-medium">{lab.result.verdict}</p>
          {race && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
              <Card><CardContent className="pt-4"><p className="text-xs text-muted-foreground">Stock before</p><p className="text-xl font-semibold tabular-nums">{race.stock_before}</p></CardContent></Card>
              <Card><CardContent className="pt-4"><p className="text-xs text-muted-foreground">Stock after the race</p><p className="text-xl font-semibold tabular-nums">{race.stock_after_race}</p></CardContent></Card>
              <Card><CardContent className="pt-4"><p className="text-xs text-muted-foreground">Units oversold</p><p className="text-xl font-semibold tabular-nums">{race.summary.oversold_units ?? 0}</p></CardContent></Card>
              <Card><CardContent className="pt-4"><p className="text-xs text-muted-foreground">Stock restored to</p><p className="text-xl font-semibold tabular-nums">{race.stock_after}</p></CardContent></Card>
            </div>
          )}
          {dead && (
            <p className="text-sm text-muted-foreground">
              Stock before / after (net zero): {nameOf(dead.product_a)} {dead.stock_before[dead.product_a]} / {dead.stock_after[dead.product_a]},{" "}
              {nameOf(dead.product_b)} {dead.stock_before[dead.product_b]} / {dead.stock_after[dead.product_b]}.
            </p>
          )}
          <ResultsTable rows={lab.result.results} />
          <p className="text-xs text-muted-foreground">
            Each client is a separate database connection and has its own entry on the Activity page (click its log id). &quot;Lock wait&quot; entries there are
            inferred from how long a call took: the application cannot observe lock waits directly. &quot;Error&quot; shows the SQL Server error the client met
            (1205 = chosen as deadlock victim, then retried).
          </p>
        </section>
      )}
    </div>
  );
}
