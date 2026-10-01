"use client";

import { useState } from "react";
import { Pencil, Trash2, Eye, Plus, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { LedgerFormModal } from "@/components/ledger-form-modal";
import { Customer, LedgerEntry, LedgerEntryInput, Product } from "@/lib/types";
import { LedgerKind } from "@/lib/use-ledger";
import { formatCurrency, formatDate } from "@/lib/utils";

interface LedgerTableProps {
  kind: LedgerKind;
  entries: LedgerEntry[];
  loading: boolean;
  onCreate: (input: LedgerEntryInput) => Promise<LedgerEntry | void>;
  onUpdate: (id: string, input: Partial<LedgerEntryInput>) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  /** Sales only: customers for the optional customer dropdown / linked-name fallback. */
  customers?: Customer[];
  /** Sales only: products for the line-items editor. */
  products?: Product[];
}

export function LedgerTable({
  kind,
  entries,
  loading,
  onCreate,
  onUpdate,
  onDelete,
  customers,
  products,
}: LedgerTableProps) {
  const [query, setQuery] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<LedgerEntry | null>(null);
  const [viewing, setViewing] = useState<LedgerEntry | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const customerNames = new Map((customers ?? []).map((c) => [c.id, c.name]));
  const extraLabel = kind === "sales" ? "Customer" : "Voucher";
  const dateField = kind === "sales" ? "sale_date" : "expense_date";
  const colCount = kind === "sales" ? 6 : 5;

  const filtered = entries.filter((e) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      e.category?.toLowerCase().includes(q) ||
      e.description?.toLowerCase().includes(q) ||
      e.customer_name?.toLowerCase().includes(q) ||
      e.voucher_reference?.toLowerCase().includes(q)
    );
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={`Search ${kind}…`}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-9"
          />
        </div>
        <Button
          onClick={() => {
            setEditing(null);
            setFormOpen(true);
          }}
        >
          <Plus className="h-4 w-4" />
          Add {kind === "sales" ? "sale" : "expense"}
        </Button>
      </div>

      <div className="overflow-hidden rounded-lg border border-border bg-surface">
        <table className="w-full text-sm">
          <thead className="bg-base-2 text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Date</th>
              <th className="px-4 py-3">Category</th>
              <th className="px-4 py-3">{extraLabel}</th>
              {kind === "sales" && <th className="px-4 py-3 text-right">Items</th>}
              <th className="px-4 py-3 text-right">Amount</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={colCount} className="px-4 py-8 text-center text-muted-foreground">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && filtered.length === 0 && (
              <tr>
                <td colSpan={colCount} className="px-4 py-8 text-center text-muted-foreground">
                  No {kind} yet. Add your first entry above.
                </td>
              </tr>
            )}
            {filtered.map((entry) => (
              <tr
                key={entry.id}
                className="cursor-pointer border-t border-border hover:bg-base-2"
                onClick={() => setViewing(entry)}
              >
                <td className="px-4 py-3">
                  {formatDate(
                    (entry as unknown as Record<string, string>)[dateField] ??
                      entry.created_at
                  )}
                </td>
                <td className="px-4 py-3">
                  <Badge>{entry.category}</Badge>
                </td>
                <td className="px-4 py-3 text-muted-foreground">
                  {kind === "sales"
                    ? entry.customer_name || (entry.customer_id ? customerNames.get(entry.customer_id) : null)
                    : entry.voucher_reference}
                </td>
                {kind === "sales" && (
                  <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                    {entry.items?.length ?? 0}
                  </td>
                )}
                <td className="px-4 py-3 text-right font-medium tabular-nums">
                  {formatCurrency(entry.amount)}
                </td>
                <td className="px-4 py-3">
                  <div
                    className="flex items-center justify-end gap-1"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={() => setViewing(entry)}
                      title="View"
                    >
                      <Eye className="h-4 w-4" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={() => {
                        setEditing(entry);
                        setFormOpen(true);
                      }}
                      title="Edit"
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <div className="relative">
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => setConfirmDeleteId(entry.id)}
                        title="Delete"
                      >
                        <Trash2 className="h-4 w-4 text-danger" />
                      </Button>
                      {confirmDeleteId === entry.id && (
                        <div className="absolute right-0 top-9 z-10 w-48 rounded-md border border-border bg-surface p-3 shadow-lg">
                          <p className="text-xs text-foreground">Delete this entry?</p>
                          <div className="mt-2 flex justify-end gap-2">
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setConfirmDeleteId(null)}
                            >
                              Cancel
                            </Button>
                            <Button
                              size="sm"
                              variant="danger"
                              onClick={async () => {
                                await onDelete(entry.id);
                                setConfirmDeleteId(null);
                              }}
                            >
                              Delete
                            </Button>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <LedgerFormModal
        kind={kind}
        open={formOpen}
        onOpenChange={setFormOpen}
        initial={editing}
        customers={customers}
        products={products}
        onSubmit={(input) =>
          editing ? onUpdate(editing.id, input) : onCreate(input)
        }
      />

      {viewing && (
        <LedgerDetailDrawer entry={viewing} kind={kind} onClose={() => setViewing(null)} />
      )}
    </div>
  );
}

function LedgerDetailDrawer({
  entry,
  kind,
  onClose,
}: {
  entry: LedgerEntry;
  kind: LedgerKind;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-olive/20" onClick={onClose}>
      <div
        className="h-full w-full max-w-sm bg-surface p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-lg font-semibold text-olive">
          {kind === "sales" ? "Sale" : "Expense"} details
        </h3>
        <dl className="mt-4 flex flex-col gap-3 text-sm">
          <Row label="Amount" value={formatCurrency(entry.amount)} />
          <Row label="Category" value={entry.category} />
          <Row
            label={kind === "sales" ? "Customer" : "Voucher reference"}
            value={
              (kind === "sales" ? entry.customer_name : entry.voucher_reference) || "—"
            }
          />
          <Row label="Description" value={entry.description || "—"} />
          <Row label="Created" value={formatDate(entry.created_at)} />
        </dl>
        {kind === "sales" && (
          <div className="mt-5">
            <h4 className="text-sm font-semibold text-olive">Items</h4>
            {entry.items && entry.items.length > 0 ? (
              <ul className="mt-2 flex flex-col gap-2 text-sm">
                {entry.items.map((item) => (
                  <li key={item.id} className="flex justify-between gap-3 border-b border-border pb-2">
                    <span>
                      {item.product_name}
                      <span className="text-muted-foreground">
                        {" "}
                        × {item.quantity} @ {formatCurrency(item.unit_price)}
                      </span>
                    </span>
                    <span className="font-medium tabular-nums">{formatCurrency(item.line_total)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-sm text-muted-foreground">Quick sale (no line items).</p>
            )}
          </div>
        )}
        <Button variant="outline" className="mt-6 w-full" onClick={onClose}>
          Close
        </Button>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-border pb-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
