"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api-client";
import { DbLabDeadlockResult, DbLabRaceResult, DbLabResult, DbLabStatus, IsolationLevel } from "./types";

/** Is the demo-only DB Lab switched on at the server (ENABLE_DB_LAB)? `null` while unknown. Never throws: errors mean "off". */
export function useDbLabStatus() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  useEffect(() => {
    let alive = true;
    api
      .get<DbLabStatus>("/db-lab/status")
      .then((s) => alive && setEnabled(Boolean(s.enabled)))
      .catch(() => alive && setEnabled(false));
    return () => {
      alive = false;
    };
  }, []);
  return enabled;
}

export interface RaceParams {
  productId: string;
  quantity: number;
  clients: number;
  mode: "safe" | "unsafe";
  isolationLevel: IsolationLevel;
  delaySeconds: number;
}

export interface DeadlockParams {
  productA: string;
  productB: string;
  delaySeconds: number;
}

export function dbLabErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 404) return "Not found (the product is not yours, or the DB Lab is switched off).";
    if (e.status === 422) return e.message.includes("[object Object]") ? "Please check the values you entered." : e.message;
  }
  return "The demo failed. Check the server log.";
}

/** Runs the demos. Each call blocks for several seconds (the server really runs the concurrent transactions). */
export function useDbLabRunner() {
  const [running, setRunning] = useState<string | null>(null);
  const [result, setResult] = useState<DbLabResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (label: string, call: () => Promise<DbLabResult>) => {
    setRunning(label);
    setError(null);
    try {
      setResult(await call());
    } catch (e) {
      setResult(null);
      setError(dbLabErrorMessage(e));
    } finally {
      setRunning(null);
    }
  }, []);

  const raceSale = (p: RaceParams) =>
    run("race", () =>
      api.post<DbLabRaceResult>("/db-lab/race-sale", {
        product_id: p.productId,
        quantity: p.quantity,
        clients: p.clients,
        mode: p.mode,
        isolation_level: p.isolationLevel,
        delay_seconds: p.delaySeconds,
      })
    );
  const deadlock = (p: DeadlockParams, fixed: boolean) =>
    run(fixed ? "fixed" : "deadlock", () =>
      api.post<DbLabDeadlockResult>(fixed ? "/db-lab/deadlock-fixed" : "/db-lab/deadlock", {
        product_a: p.productA,
        product_b: p.productB,
        delay_seconds: p.delaySeconds,
      })
    );

  return { running, result, error, raceSale, deadlock };
}
