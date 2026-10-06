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
import { LedgerEntry, LedgerEntryInput } from "@/lib/types";
import { LedgerKind } from "@/lib/use-ledger";

interface LedgerFormModalProps {
  kind: LedgerKind;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initial?: LedgerEntry | null;
  onSubmit: (input: LedgerEntryInput) => Promise<void>;
}

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
}: LedgerFormModalProps) {
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("general");
  const [description, setDescription] = useState("");
  const [extra, setExtra] = useState(""); // customer_name or voucher_reference
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resets form fields when the dialog is (re)opened
    setAmount(initial ? String(initial.amount) : "");
    setCategory(initial?.category ?? "general");
    setDescription(initial?.description ?? "");
    setExtra(
      (kind === "sales" ? initial?.customer_name : initial?.voucher_reference) ?? ""
    );
    setError(null);
  }, [open, initial, kind]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const parsed = parseFloat(amount);
    if (Number.isNaN(parsed) || parsed <= 0) {
      setError("Enter a valid amount");
      return;
    }
    setSubmitting(true);
    try {
      const input: LedgerEntryInput = {
        amount: parsed,
        category,
        description: description || null,
        ...(kind === "sales"
          ? { customer_name: extra || null }
          : { voucher_reference: extra || null }),
      };
      await onSubmit(input);
      onOpenChange(false);
    } catch {
      setError("Could not save entry");
    } finally {
      setSubmitting(false);
    }
  }

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
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="amount">Amount</Label>
            <Input
              id="amount"
              type="number"
              step="0.01"
              min="0"
              required
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="category">Category</Label>
            <select
              id="category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="h-10 rounded-md border border-border bg-surface px-3 text-sm focus:outline-none focus:ring-2 focus:ring-olive-soft"
            >
              {defaultCategories[kind].map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
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
          <div className="mt-2 flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Saving…" : "Save"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
