"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "./api-client";
import { LedgerEntry, LedgerEntryInput } from "./types";

export type LedgerKind = "sales" | "expenses";

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

  async function create(input: LedgerEntryInput) {
    await api.post(`/${kind}`, input);
    await refresh();
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
