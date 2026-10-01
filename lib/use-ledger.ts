"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api-client";
import { LedgerEntry, LedgerEntryInput } from "./types";

export type LedgerKind = "sales" | "expenses";

/** Human-readable message for API failures (404 unknown product, 409 not enough stock, 422 validation). */
export function ledgerErrorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    // FastAPI body-validation errors arrive as an array, which api-client stringifies to "[object Object]".
    if (e.status === 422 && e.message.includes("[object Object]")) {
      return "Please check the values you entered.";
    }
    if (e.status === 409 || e.status === 422 || e.status === 404) return e.message;
  }
  return fallback;
}

export function useLedger(kind: LedgerKind) {
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<LedgerEntry[]>(`/${kind}?limit=200&offset=0`);
      setEntries(data);
    } catch {
      setError("Could not load data");
    } finally {
      setLoading(false);
    }
  }, [kind]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- kicks off async fetch, setState happens after await
    refresh();
  }, [refresh]);

  async function create(input: LedgerEntryInput): Promise<LedgerEntry> {
    const created = await api.post<LedgerEntry>(`/${kind}`, input);
    await refresh();
    return created;
  }

  async function update(id: string, input: Partial<LedgerEntryInput>) {
    await api.put(`/${kind}/${id}`, input);
    await refresh();
  }

  async function remove(id: string) {
    await api.delete(`/${kind}/${id}`);
    await refresh();
  }

  return { entries, loading, error, refresh, create, update, remove };
}
