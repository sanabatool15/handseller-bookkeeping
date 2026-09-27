"use client";

import { useRef, useState, FormEvent } from "react";
import { Send, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { VoiceButton } from "@/components/advisor/voice-button";
import { JobStatusFeed } from "@/components/advisor/job-status-feed";
import { api, ApiError } from "@/lib/api-client";
import { AgentJob } from "@/lib/types";

interface ChatTurn {
  id: string;
  question: string;
  job: AgentJob | null;
  error?: string;
}

export default function AdvisorPage() {
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const pollers = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  function pollJob(turnId: string, jobId: string) {
    // Clear any previous poller for this turn before starting a new one, so
    // a re-invocation (e.g. React Strict Mode / Fast Refresh in dev) can
    // never leave two intervals racing for the same turnId.
    if (pollers.current[turnId]) {
      clearInterval(pollers.current[turnId]);
    }

    const interval = setInterval(async () => {
      try {
        const job = await api.get<AgentJob>(`/agent-jobs/${jobId}`);
        setTurns((prev) =>
          prev.map((t) => (t.id === turnId ? { ...t, job } : t))
        );
        if (job.status === "completed" || job.status === "failed") {
          // Clear the interval this callback actually belongs to, not
          // whatever the ref currently points at -- a second pollJob call
          // for the same turnId would otherwise overwrite the ref and this
          // stop-condition would clear the *new* interval instead of itself,
          // leaving the original one polling forever.
          clearInterval(interval);
          delete pollers.current[turnId];
        }
      } catch {
        clearInterval(interval);
        delete pollers.current[turnId];
      }
    }, 1500);
    pollers.current[turnId] = interval;
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || submitting) return;
    setSubmitting(true);
    setInput("");

    const turnId = crypto.randomUUID();
    setTurns((prev) => [...prev, { id: turnId, question, job: null }]);

    try {
      const res = await api.post<{ job_id: string; status: string }>(
        "/agent-jobs/financial-advice",
        { question }
      );
      setTurns((prev) =>
        prev.map((t) =>
          t.id === turnId
            ? {
                ...t,
                job: {
                  id: res.job_id,
                  job_name: "financial-advice",
                  org_id: "",
                  requested_by: "",
                  status: "pending",
                  created_at: new Date().toISOString(),
                  updated_at: new Date().toISOString(),
                } as AgentJob,
              }
            : t
        )
      );
      pollJob(turnId, res.job_id);
    } catch (err) {
      setTurns((prev) =>
        prev.map((t) =>
          t.id === turnId
            ? {
                ...t,
                error: err instanceof ApiError ? err.message : "Could not reach the advisor",
              }
            : t
        )
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col gap-6">
      <div className="flex items-center gap-2">
        <Sparkles className="h-5 w-5 text-olive" />
        <div>
          <h1 className="text-2xl font-semibold text-olive">AI Agent Advisor</h1>
          <p className="text-sm text-muted-foreground">
            Ask about your finances, or tell it to log a sale or expense — by typing or speaking.
          </p>
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-4">
        {turns.length === 0 && (
          <Card>
            <CardContent className="py-8 text-center text-sm text-muted-foreground">
              Try: “Why were expenses higher last month?” or “Log a $45 sale to Jane for
              a repair.”
            </CardContent>
          </Card>
        )}
        {turns.map((turn) => (
          <div key={turn.id} className="flex flex-col gap-2">
            <div className="ml-auto max-w-[85%] rounded-lg bg-olive px-4 py-2 text-sm text-white">
              {turn.question}
            </div>

            {turn.error && (
              <Card className="max-w-[85%] border-danger/30">
                <CardContent className="py-3 text-sm text-danger">{turn.error}</CardContent>
              </Card>
            )}

            {turn.job && turn.job.status !== "completed" && turn.job.status !== "failed" && (
              <div className="max-w-[85%]">
                <JobStatusFeed job={turn.job} />
              </div>
            )}

            {turn.job?.status === "failed" && (
              <Card className="max-w-[85%] border-danger/30">
                <CardContent className="py-3 text-sm text-danger">
                  {turn.job.error_details || "The advisor couldn't complete this request."}
                </CardContent>
              </Card>
            )}

            {turn.job?.status === "completed" && turn.job.result && (
              <Card className="max-w-[85%]">
                <CardContent className="flex flex-col gap-2 py-4 text-sm">
                  <p className="whitespace-pre-wrap text-foreground">
                    {turn.job.result.advice}
                  </p>
                  {turn.job.result.source === "rule_based_fallback" && (
                    <p className="text-xs text-muted-foreground">
                      Generated offline — the AI advisor was unavailable.
                    </p>
                  )}
                </CardContent>
              </Card>
            )}
          </div>
        ))}
      </div>

      <form onSubmit={onSubmit} className="flex items-end gap-2 border-t border-border pt-4">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSubmit(e);
            }
          }}
          placeholder="Ask the advisor or describe an entry to log…"
          className="min-h-12 flex-1 resize-none rounded-md border border-border bg-surface p-3 text-sm focus:outline-none focus:ring-2 focus:ring-olive-soft"
        />
        <VoiceButton onTranscript={(text) => setInput(text)} />
        <Button type="submit" disabled={submitting || !input.trim()}>
          <Send className="h-4 w-4" />
        </Button>
      </form>
    </div>
  );
}
