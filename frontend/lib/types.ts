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

export interface BookkeepingResult {
  mode: "investigation" | "record_entry";
  summary: string;
  root_cause?: string | null;
  recommendation?: string | null;
  used_web_search: boolean;
  record_reference?: string | null;
}

export interface AgentJob {
  id: string;
  job_name: string;
  org_id: string;
  requested_by: string;
  status: AgentJobStatus;
  current_step?: string | null;
  input_payload?: Record<string, unknown>;
  result?: { advice: BookkeepingResult; source: string } | null;
  error_details?: string | null;
  created_at: string;
  updated_at: string;
}
