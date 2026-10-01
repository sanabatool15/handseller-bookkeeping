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
import { Product, ProductInput } from "@/lib/types";
import { productErrorMessage } from "@/lib/use-products";

interface ProductFormModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initial?: Product | null;
  onSubmit: (input: ProductInput) => Promise<void>;
}

export function ProductFormModal({
  open,
  onOpenChange,
  initial,
  onSubmit,
}: ProductFormModalProps) {
  const [name, setName] = useState("");
  const [sku, setSku] = useState("");
  const [price, setPrice] = useState("");
  const [stock, setStock] = useState("0");
  const [reorder, setReorder] = useState("0");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resets form fields when the dialog is (re)opened
    setName(initial?.name ?? "");
    setSku(initial?.sku ?? "");
    setPrice(initial ? String(initial.price) : "");
    setStock(initial ? String(initial.stock_qty) : "0");
    setReorder(initial ? String(initial.reorder_level) : "0");
    setError(null);
  }, [open, initial]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const parsedPrice = parseFloat(price);
    const parsedReorder = parseInt(reorder, 10);
    const parsedStock = parseInt(stock, 10);
    if (!name.trim() || !sku.trim()) {
      setError("Name and SKU are required");
      return;
    }
    if (Number.isNaN(parsedPrice) || parsedPrice < 0) {
      setError("Enter a valid price (0 or more)");
      return;
    }
    if (Number.isNaN(parsedReorder) || parsedReorder < 0) {
      setError("Reorder level must be 0 or more");
      return;
    }
    if (!initial && (Number.isNaN(parsedStock) || parsedStock < 0)) {
      setError("Initial stock must be 0 or more");
      return;
    }
    setSubmitting(true);
    try {
      const input: ProductInput = {
        name: name.trim(),
        sku: sku.trim(),
        price: parsedPrice,
        reorder_level: parsedReorder,
        ...(initial ? {} : { stock_qty: parsedStock }),
      };
      await onSubmit(input);
      onOpenChange(false);
    } catch (err) {
      setError(productErrorMessage(err, "Could not save product"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{initial ? "Edit" : "Add"} product</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="product-name">Name</Label>
            <Input
              id="product-name"
              required
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="product-sku">SKU</Label>
            <Input
              id="product-sku"
              required
              maxLength={64}
              value={sku}
              onChange={(e) => setSku(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="product-price">Price</Label>
              <Input
                id="product-price"
                type="number"
                step="0.01"
                min="0"
                required
                value={price}
                onChange={(e) => setPrice(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="product-stock">
                {initial ? "Stock (use Adjust)" : "Initial stock"}
              </Label>
              <Input
                id="product-stock"
                type="number"
                step="1"
                min="0"
                disabled={!!initial}
                value={stock}
                onChange={(e) => setStock(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="product-reorder">Reorder level</Label>
              <Input
                id="product-reorder"
                type="number"
                step="1"
                min="0"
                value={reorder}
                onChange={(e) => setReorder(e.target.value)}
              />
            </div>
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
