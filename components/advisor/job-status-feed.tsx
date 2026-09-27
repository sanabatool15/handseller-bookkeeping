"use client";

import { Check, Loader2, CircleAlert } from "lucide-react";
import { AgentJob } from "@/lib/types";
import { cn } from "@/lib/utils";

const STEPS = ["gather_data", "run_agent", "finalize"];

const STEP_LABELS: Record<string, string> = {
  gather_data: "Gathering data",
  run_agent: "Running agent",
  finalize: "Finalizing",
};

export function JobStatusFeed({ job }: { job: AgentJob }) {
  const currentIndex = STEPS.indexOf(job.current_step ?? "");
  const failed = job.status === "failed";
  const completed = job.status === "completed";

  return (
    <div className="flex flex-col gap-2 rounded-md border border-border bg-base-2 p-4">
      {STEPS.map((step, i) => {
        const done = completed || i < currentIndex || (i === currentIndex && completed);
        const active = !completed && !failed && i === currentIndex;
        const isFailedHere = failed && i === currentIndex;

        return (
          <div key={step} className="flex items-center gap-3 text-sm">
            <span
              className={cn(
                "flex h-5 w-5 items-center justify-center rounded-full",
                done && "bg-success text-white",
                active && "bg-olive text-white",
                isFailedHere && "bg-danger text-white",
                !done && !active && !isFailedHere && "bg-border text-muted-foreground"
              )}
            >
              {done && <Check className="h-3 w-3" />}
              {active && <Loader2 className="h-3 w-3 animate-spin" />}
              {isFailedHere && <CircleAlert className="h-3 w-3" />}
            </span>
            <span
              className={cn(
                "font-medium",
                active ? "text-olive" : "text-muted-foreground",
                done && "text-foreground"
              )}
            >
              {STEP_LABELS[step]}
            </span>
          </div>
        );
      })}
    </div>
  );
}
