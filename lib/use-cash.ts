"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api-client";
import { CashBalance, CashLedgerEntry, CashLedgerFilters, CashSummary } from "./types";

/** Cash balance (always) and, when `withLedger` is true, the newest ledger entries. Read-only: cash is written by sales and expenses. */
export function useCash(withLedger = false) {
  const [balance, setBalance] = useState<CashBalance>({ balance: 0, updated_at: null });
  const [ledger, setLedger] = useState<CashLedgerEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setBalance(await api.get<CashBalance>("/cash/balance"));
      if (withLedger) setLedger(await api.get<CashLedgerEntry[]>("/cash/ledger?limit=100&offset=0"));
    } catch {
      setError("Could not load cash balance");
    } finally {
      setLoading(false);
    }
  }, [withLedger]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- kicks off async fetch, setState happens after await
    refresh();
  }, [refresh]);

  return { balance: balance.balance, updatedAt: balance.updated_at, ledger, loading, error, refresh };
}

/** Ledger entries (newest first) filtered by type and/or entry date, server-side. Re-fetches when the filters change. */
export function useCashLedger(filters: CashLedgerFilters) {
  const [entries, setEntries] = useState<CashLedgerEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { entryType, from, to } = filters;

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    const q = new URLSearchParams({ limit: "200", offset: "0" });
    if (entryType) q.set("entry_type", entryType);
    if (from) q.set("from", from);
    if (to) q.set("to", to);
    try {
      setEntries(await api.get<CashLedgerEntry[]>(`/cash/ledger?${q.toString()}`));
    } catch (e) {
      setEntries([]);
      setError(e instanceof ApiError && e.status === 422 ? e.message : "Could not load the cash ledger");
    } finally {
      setLoading(false);
    }
  }, [entryType, from, to]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- kicks off async fetch, setState happens after await
    refresh();
  }, [refresh]);

  return { entries, loading, error, refresh };
}

/** Monthly summary (opening / in / out / closing / by type) for `year` + `month` (1-12), computed by the API. */
export function useCashSummary(year: number, month: number) {
  const [summary, setSummary] = useState<CashSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSummary(await api.get<CashSummary>(`/cash/summary?year=${year}&month=${month}`));
    } catch {
      setSummary(null);
      setError("Could not load the monthly summary");
    } finally {
      setLoading(false);
    }
  }, [year, month]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- kicks off async fetch, setState happens after await
    refresh();
  }, [refresh]);

  return { summary, loading, error, refresh };
}
