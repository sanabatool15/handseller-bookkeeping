"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api-client";
import { Customer, CustomerInput, CustomerSummary } from "./types";

/** Human-readable message for API failures (409 duplicate phone / customer has sales, 422 validation). */
export function customerErrorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    // FastAPI body-validation errors arrive as an array, which api-client stringifies to "[object Object]".
    if (e.status === 422 && e.message.includes("[object Object]")) {
      return "Please check the values you entered.";
    }
    if (e.status === 409 || e.status === 422 || e.status === 404) return e.message;
  }
  return fallback;
}

/** `q` = optional server-side prefix search on name/phone. */
export function useCustomers(q: string = "") {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ limit: "200", offset: "0" });
      if (q.trim()) params.set("q", q.trim());
      const data = await api.get<Customer[]>(`/customers?${params.toString()}`);
      setCustomers(data);
    } catch {
      setError("Could not load customers");
    } finally {
      setLoading(false);
    }
  }, [q]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- kicks off async fetch, setState happens after await
    refresh();
  }, [refresh]);

  async function create(input: CustomerInput) {
    await api.post("/customers", input);
    await refresh();
  }

  async function update(id: string, input: Partial<CustomerInput>) {
    await api.put(`/customers/${id}`, input);
    await refresh();
  }

  async function remove(id: string) {
    await api.delete(`/customers/${id}`);
    await refresh();
  }

  async function fetchSummary(id: string) {
    return api.get<CustomerSummary>(`/customers/${id}/summary`);
  }

  return { customers, loading, error, refresh, create, update, remove, fetchSummary };
}
