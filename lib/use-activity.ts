"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api-client";
import { ActivityFilters, TxnEvent, TxnRequestSummary } from "./types";

const REFRESH_MS = 3000;

/** One row per request from /db-logs/requests (server-side filters). `autoRefresh` polls every 3 s without flashing the table. */
export function useActivityRequests(filters: ActivityFilters, autoRefresh: boolean) {
  const [requests, setRequests] = useState<TxnRequestSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { requestId, operation, outcome } = filters;

  const refresh = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true);
      const q = new URLSearchParams({ limit: "100", offset: "0" });
      if (requestId.trim()) q.set("request_id", requestId.trim());
      if (operation) q.set("operation", operation);
      if (outcome) q.set("outcome", outcome);
      try {
        setRequests(await api.get<TxnRequestSummary[]>(`/db-logs/requests?${q.toString()}`));
        setError(null);
      } catch (e) {
        if (!quiet) setRequests([]);
        setError(e instanceof ApiError && e.status === 422 ? e.message : "Could not load the activity log");
      } finally {
        if (!quiet) setLoading(false);
      }
    },
    [requestId, operation, outcome]
  );

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- kicks off async fetch, setState happens after await
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(() => refresh(true), REFRESH_MS);
    return () => clearInterval(id);
  }, [autoRefresh, refresh]);

  return { requests, loading, error, refresh };
}

/** The events of ONE request, oldest first (a timeline). Pass null for "nothing selected". */
export function useRequestTimeline(requestId: string | null, autoRefresh: boolean) {
  const [events, setEvents] = useState<TxnEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(
    async (quiet = false) => {
      if (!requestId) return;
      if (!quiet) setLoading(true);
      try {
        const q = new URLSearchParams({ request_id: requestId, order: "asc", limit: "200", offset: "0" });
        setEvents(await api.get<TxnEvent[]>(`/db-logs?${q.toString()}`));
        setError(null);
      } catch {
        setError("Could not load the events of this request");
      } finally {
        if (!quiet) setLoading(false);
      }
    },
    [requestId]
  );

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resets and kicks off an async fetch when the selection changes
    setEvents([]);
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!autoRefresh || !requestId) return;
    const id = setInterval(() => refresh(true), REFRESH_MS);
    return () => clearInterval(id);
  }, [autoRefresh, requestId, refresh]);

  return { events, loading, error };
}
