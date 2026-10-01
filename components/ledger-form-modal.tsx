"use client";

import { useEffect, useState, FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Plus, Trash2 } from "lucide-react";
import { Customer, LedgerEntry, LedgerEntryInput, Product, SkippedSaleItem } from "@/lib/types";
import { LedgerKind, ledgerErrorMessage } from "@/lib/use-ledger";
import { formatCurrency } from "@/lib/utils";

interface LedgerFormModalProps {
  kind: LedgerKind;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initial?: LedgerEntry | null;
  onSubmit: (input: LedgerEntryInput) => Promise<LedgerEntry | void>;
  /** Sales only: when given, an optional customer dropdown is shown. */
  customers?: Customer[];
  /** Sales only: when given (new sale), a line-items editor is offered next to the quick amount. */
  products?: Product[];
}

interface ItemRow {
  key: number;
  productId: string;
  quantity: string;
  price: string; // prefilled from the product, editable
}

const selectClass =
  "h-10 rounded-md border border-border bg-surface px-3 text-sm focus:outline-none focus:ring-2 focus:ring-olive-soft";

const defaultCategories = {
  sales: ["general", "product", "service", "commission"],
  expenses: ["general", "supplies", "rent", "utilities", "marketing", "payroll"],
};

export function LedgerFormModal({
  kind,
  open,
  onOpenChange,
  initial,
  onSubmit,
  customers,
  products,
}: LedgerFormModalProps) {
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("general");
  const [description, setDescription] = useState("");
  const [extra, setExtra] = useState(""); // customer_name or voucher_reference
  const [customerId, setCustomerId] = useState(""); // "" = no linked customer
  const [rows, setRows] = useState<ItemRow[]>([]);
  const [nextKey, setNextKey] = useState(1);
  const [skipInvalid, setSkipInvalid] = useState(false);
  const [skipped, setSkipped] = useState<SkippedSaleItem[] | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const itemsEnabled = kind === "sales" && !initial && !!products;
  // A sale that has line items keeps its total = sum of lines: the amount cannot be edited.
  const amountLocked = !!initial?.items?.length;
  const lineTotal = rows.reduce((sum, r) => {
    const q = parseInt(r.quantity, 10);
    const p = parseFloat(r.price);
    return sum + (Number.isNaN(q) || Number.isNaN(p) ? 0 : q * p);
  }, 0);

  useEffect(() => {
    if (!open) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resets form fields when the dialog is (re)opened
    setAmount(initial ? String(initial.amount) : "");
    setCategory(initial?.category ?? "general");
    setDescription(initial?.description ?? "");
    setExtra(
      (kind === "sales" ? initial?.customer_name : initial?.voucher_reference) ?? ""
    );
    setCustomerId(initial?.customer_id ?? "");
    setRows([]);
    setSkipInvalid(false);
    setSkipped(null);
    setError(null);
  }, [open, initial, kind]);

  function addRow() {
    setRows((r) => [...r, { key: nextKey, productId: "", quantity: "1", price: "" }]);
    setNextKey((k) => k + 1);
  }

  function updateRow(key: number, patch: Partial<ItemRow>) {
    setRows((all) => all.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  function pickProduct(key: number, productId: string) {
    const product = products?.find((p) => p.id === productId);
    updateRow(key, { productId, price: product ? String(product.price) : "" });
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    let amountField: { amount?: number } = {};
    let itemsField: Pick<LedgerEntryInput, "items" | "skip_invalid_items"> = {};
    if (rows.length > 0) {
      const items = [];
      for (const r of rows) {
        const quantity = Number(r.quantity);
        const price = parseFloat(r.price);
        if (!r.productId) return setError("Choose a product for every line");
        if (!Number.isInteger(quantity) || quantity <= 0) return setError("Quantity must be a whole number above 0");
        if (Number.isNaN(price) || price < 0) return setError("Enter a valid price for every line");
        items.push({ product_id: r.productId, quantity, unit_price: price });
      }
      itemsField = { items, skip_invalid_items: skipInvalid };
    } else if (!amountLocked) {
      const parsed = parseFloat(amount);
      if (Number.isNaN(parsed) || parsed <= 0) {
        setError("Enter a valid amount");
        return;
      }
      amountField = { amount: parsed };
    }
    setSubmitting(true);
    try {
      const input: LedgerEntryInput = {
        ...amountField,
        ...itemsField,
        category,
        description: description || null,
        ...(kind === "sales"
          ? { customer_name: extra || null, customer_id: customerId || null }
          : { voucher_reference: extra || null }),
      };
      const saved = await onSubmit(input);
      if (saved && saved.skipped_items?.length) {
        // Partial sale: keep the dialog open so the user can read which lines were left out.
        setSkipped(saved.skipped_items);
      } else {
        onOpenChange(false);
      }
    } catch (err) {
      setError(ledgerErrorMessage(err, "Could not save entry"));
    } finally {
      setSubmitting(false);
    }
  }

  const productName = (id: string | null) => products?.find((p) => p.id === id)?.name ?? "Unknown product";
  const label = kind === "sales" ? "Customer" : "Voucher reference";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {initial ? "Edit" : "Add"} {kind === "sales" ? "sale" : "expense"}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {rows.length === 0 && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="amount">Amount</Label>
              <Input
                id="amount"
                type="number"
                step="0.01"
                min="0"
                required={!amountLocked}
                disabled={amountLocked}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
              {amountLocked && (
                <p className="text-xs text-muted-foreground">
                  This sale has line items, so its amount is the sum of the lines and cannot be changed.
                </p>
              )}
            </div>
          )}
          {itemsEnabled && (
            <div className="flex flex-col gap-2 rounded-md border border-border p-3">
              <div className="flex items-center justify-between">
                <Label>Line items (optional)</Label>
                <Button type="button" size="sm" variant="outline" onClick={addRow}>
                  <Plus className="h-4 w-4" /> Add item
                </Button>
              </div>
              {rows.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  Add products to reduce their stock and record the sale per item, or just enter an amount above.
                </p>
              )}
              {rows.map((r) => (
                <div key={r.key} className="grid grid-cols-[1fr_4.5rem_5.5rem_auto] items-center gap-2">
                  <select
                    aria-label="Product"
                    value={r.productId}
                    onChange={(e) => pickProduct(r.key, e.target.value)}
                    className={selectClass}
                  >
                    <option value="">Choose product…</option>
                    {products?.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} ({p.sku}) · stock {p.stock_qty}
                      </option>
                    ))}
                  </select>
                  <Input
                    aria-label="Quantity"
                    type="number"
                    min="1"
                    step="1"
                    value={r.quantity}
                    onChange={(e) => updateRow(r.key, { quantity: e.target.value })}
                  />
                  <Input
                    aria-label="Unit price"
                    type="number"
                    min="0"
                    step="0.01"
                    value={r.price}
                    onChange={(e) => updateRow(r.key, { price: e.target.value })}
                  />
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    title="Remove item"
                    onClick={() => setRows((all) => all.filter((x) => x.key !== r.key))}
                  >
                    <Trash2 className="h-4 w-4 text-danger" />
                  </Button>
                </div>
              ))}
              {rows.length > 0 && (
                <>
                  <p className="text-right text-sm font-medium tabular-nums">
                    Total: {formatCurrency(lineTotal)}
                  </p>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={skipInvalid}
                      onChange={(e) => setSkipInvalid(e.target.checked)}
                    />
                    Skip invalid items (keep the valid ones if some lines cannot be sold)
                  </label>
                </>
              )}
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="category">Category</Label>
            <select
              id="category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className={selectClass}
            >
              {defaultCategories[kind].map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          {kind === "sales" && customers && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="customer-id">Customer (optional)</Label>
              <select
                id="customer-id"
                value={customerId}
                onChange={(e) => setCustomerId(e.target.value)}
                className={selectClass}
              >
                <option value="">No customer</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                    {c.phone ? ` (${c.phone})` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="extra">{label}</Label>
            <Input id="extra" value={extra} onChange={(e) => setExtra(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="description">Description</Label>
            <Input
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          {error && <p className="text-sm text-danger">{error}</p>}
          {skipped && (
            <div className="rounded-md border border-border bg-base-2 p-3 text-sm">
              <p className="font-medium">Sale saved. Some items were skipped:</p>
              <ul className="mt-1 list-disc pl-5">
                {skipped.map((s, i) => (
                  <li key={i}>
                    {productName(s.product_id)}: {s.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="mt-2 flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              {skipped ? "Close" : "Cancel"}
            </Button>
            {!skipped && (
              <Button type="submit" disabled={submitting}>
                {submitting ? "Saving…" : "Save"}
              </Button>
            )}
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
