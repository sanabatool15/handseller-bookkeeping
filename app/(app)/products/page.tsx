"use client";

import { useState, FormEvent } from "react";
import { Boxes, AlertTriangle, Package, Pencil, Plus, Search, SlidersHorizontal, Trash2 } from "lucide-react";
import { useProducts, productErrorMessage } from "@/lib/use-products";
import { Product } from "@/lib/types";
import { formatCurrency } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { KpiCard } from "@/components/kpi-card";
import { ProductFormModal } from "@/components/product-form-modal";

const isLow = (p: Product) => p.stock_qty <= p.reorder_level;

export default function ProductsPage() {
  const { products, loading, error, create, update, remove, adjustStock } = useProducts();
  const [query, setQuery] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);
  const [adjusting, setAdjusting] = useState<Product | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const filtered = products.filter((p) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return p.name.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q);
  });
  const lowCount = products.filter(isLow).length;
  const stockValue = products.reduce((sum, p) => sum + p.price * p.stock_qty, 0);

  async function handleDelete(id: string) {
    setActionError(null);
    try {
      await remove(id);
    } catch (e) {
      setActionError(productErrorMessage(e, "Could not delete product"));
    } finally {
      setConfirmDeleteId(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-olive">Products</h1>
        <p className="text-sm text-muted-foreground">
          Manage your catalogue and keep track of stock levels.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <KpiCard label="Products" value={products.length} icon={Package} format="number" />
        <KpiCard label="Low stock" value={lowCount} icon={AlertTriangle} format="number" />
        <KpiCard label="Stock value" value={stockValue} icon={Boxes} tone="olive" />
      </div>

      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between gap-3">
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search products…"
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
            Add product
          </Button>
        </div>

        {(error || actionError) && (
          <p className="text-sm text-danger">{actionError ?? error}</p>
        )}

        <div className="overflow-hidden rounded-lg border border-border bg-surface">
          <table className="w-full text-sm">
            <thead className="bg-base-2 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">SKU</th>
                <th className="px-4 py-3 text-right">Price</th>
                <th className="px-4 py-3 text-right">Stock</th>
                <th className="px-4 py-3 text-right">Reorder level</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                    Loading…
                  </td>
                </tr>
              )}
              {!loading && filtered.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                    No products yet. Add your first product above.
                  </td>
                </tr>
              )}
              {filtered.map((p) => (
                <tr key={p.id} className="border-t border-border hover:bg-base-2">
                  <td className="px-4 py-3 font-medium">
                    {p.name}
                    {!p.is_active && (
                      <Badge className="ml-2" variant="default">
                        Inactive
                      </Badge>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{p.sku}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{formatCurrency(p.price)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    <span className="mr-2 font-medium">{p.stock_qty}</span>
                    {isLow(p) && <Badge variant="danger">Low stock</Badge>}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                    {p.reorder_level}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        size="icon"
                        variant="ghost"
                        title="Adjust stock"
                        onClick={() => setAdjusting(p)}
                      >
                        <SlidersHorizontal className="h-4 w-4" />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        title="Edit"
                        onClick={() => {
                          setEditing(p);
                          setFormOpen(true);
                        }}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <div className="relative">
                        <Button
                          size="icon"
                          variant="ghost"
                          title="Delete"
                          onClick={() => setConfirmDeleteId(p.id)}
                        >
                          <Trash2 className="h-4 w-4 text-danger" />
                        </Button>
                        {confirmDeleteId === p.id && (
                          <div className="absolute right-0 top-9 z-10 w-48 rounded-md border border-border bg-surface p-3 shadow-lg">
                            <p className="text-xs text-foreground">Delete this product?</p>
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
                                onClick={() => handleDelete(p.id)}
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
      </div>

      <ProductFormModal
        open={formOpen}
        onOpenChange={setFormOpen}
        initial={editing}
        onSubmit={(input) => {
          if (!editing) return create(input);
          // Stock is only changed through "Adjust stock".
          const { stock_qty: _ignored, ...rest } = input;
          void _ignored;
          return update(editing.id, rest);
        }}
      />

      <AdjustStockDialog
        product={adjusting}
        onClose={() => setAdjusting(null)}
        onSubmit={adjustStock}
      />
    </div>
  );
}

function AdjustStockDialog({
  product,
  onClose,
  onSubmit,
}: {
  product: Product | null;
  onClose: () => void;
  onSubmit: (id: string, delta: number, reason: string | null) => Promise<void>;
}) {
  // Re-mounted per product (key) so the fields start empty each time.
  return (
    <Dialog open={!!product} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        {product && <AdjustStockForm key={product.id} product={product} onClose={onClose} onSubmit={onSubmit} />}
      </DialogContent>
    </Dialog>
  );
}

function AdjustStockForm({
  product,
  onClose,
  onSubmit,
}: {
  product: Product;
  onClose: () => void;
  onSubmit: (id: string, delta: number, reason: string | null) => Promise<void>;
}) {
  const [delta, setDelta] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const parsed = parseInt(delta, 10);
    if (Number.isNaN(parsed) || parsed === 0) {
      setError("Enter a non-zero whole number (use a minus sign to remove stock)");
      return;
    }
    setSubmitting(true);
    try {
      await onSubmit(product.id, parsed, reason.trim() || null);
      onClose();
    } catch (err) {
      setError(productErrorMessage(err, "Could not adjust stock"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Adjust stock: {product.name}</DialogTitle>
      </DialogHeader>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <p className="text-sm text-muted-foreground">
          Current stock: <span className="font-medium text-foreground">{product.stock_qty}</span>
        </p>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="adjust-delta">Change (+ add / - remove)</Label>
          <Input
            id="adjust-delta"
            type="number"
            step="1"
            required
            placeholder="e.g. 10 or -3"
            value={delta}
            onChange={(e) => setDelta(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="adjust-reason">Reason (optional)</Label>
          <Input
            id="adjust-reason"
            maxLength={500}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </div>
        {error && <p className="text-sm text-danger">{error}</p>}
        <div className="mt-2 flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={submitting}>
            {submitting ? "Saving…" : "Apply"}
          </Button>
        </div>
      </form>
    </>
  );
}
