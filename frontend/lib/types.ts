export interface User {
  id: string;
  email: string;
  full_name?: string | null;
  org_id: string;
  role?: string;
}

export interface Org {
  id: string;
  name: string;
}

export interface AuthResponse {
  access_token: string;
  user: User;
  org?: Org;
}

export interface LedgerEntry {
  id: string;
  org_id: string;
  created_by: string;
  amount: number;
  category: string;
  description?: string | null;
  customer_name?: string | null;
  voucher_reference?: string | null;
  sale_date?: string;
  expense_date?: string;
  created_at: string;
  updated_at: string;
}

export interface LedgerEntryInput {
  amount: number;
  category?: string;
  description?: string | null;
  customer_name?: string | null;
  voucher_reference?: string | null;
}

export type AgentJobStatus = "pending" | "processing" | "completed" | "failed";

export interface AgentJobResult {
  // jobs/financial_agent_job.py always produces a plain string here (both
  // the live agent path in run_financial_advisor() and the offline
  // rule_based_financial_advice() fallback return str, not a structured
  // BookkeepingResult object) -- never assume this is an object.
  advice: string;
  source: "openai_agent" | "rule_based_fallback" | string;
}

export interface AgentJob {
  id: string;
  job_name: string;
  org_id: string;
  requested_by: string;
  status: AgentJobStatus;
  current_step?: string | null;
  input_payload?: Record<string, unknown>;
  result?: AgentJobResult | null;
  error_details?: string | null;
  created_at: string;
  updated_at: string;
}
