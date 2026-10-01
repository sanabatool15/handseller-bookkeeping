"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "./api-client";
import { CashBalance, CashLedgerEntry } from "./types";

/** Cash balance (always) and, when `withLedger` is true, the newest ledger entries. Read-only: cash is written by sales. */
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
