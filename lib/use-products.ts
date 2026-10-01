"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api-client";
import { Product, ProductInput } from "./types";

/** Human-readable message for API failures (409 duplicate SKU / insufficient stock, 422 validation). */
export function productErrorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    // FastAPI body-validation errors arrive as an array, which api-client stringifies to "[object Object]".
    if (e.status === 422 && e.message.includes("[object Object]")) {
      return "Please check the values you entered.";
    }
    if (e.status === 409 || e.status === 422 || e.status === 404) return e.message;
  }
  return fallback;
}

export function useProducts() {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<Product[]>("/products?limit=200&offset=0");
      setProducts(data);
    } catch {
      setError("Could not load products");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- kicks off async fetch, setState happens after await
    refresh();
  }, [refresh]);

  async function create(input: ProductInput) {
    await api.post("/products", input);
    await refresh();
  }

  async function update(id: string, input: Partial<Omit<ProductInput, "stock_qty">>) {
    await api.put(`/products/${id}`, input);
    await refresh();
  }

  async function remove(id: string) {
    await api.delete(`/products/${id}`);
    await refresh();
  }

  async function adjustStock(id: string, delta: number, reason: string | null) {
    await api.post(`/products/${id}/adjust-stock`, { delta, reason });
    await refresh();
  }

  return { products, loading, error, refresh, create, update, remove, adjustStock };
}
