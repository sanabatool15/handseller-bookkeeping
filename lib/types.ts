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

export interface SaleItem {
  id: string;
  org_id: string;
  sale_id: string;
  product_id: string;
  product_name: string;
  quantity: number;
  unit_price: number;
  line_total: number;
  created_at: string;
  updated_at: string;
}

export interface SaleItemInput {
  product_id: string;
  quantity: number;
  unit_price?: number | null; // omitted = the product's current price
}

export interface SkippedSaleItem {
  product_id: string | null;
  quantity: number | null;
  error_number: number;
  reason: string;
}

export interface CashBalance {
  balance: number;
  updated_at: string | null;
}

export interface CashLedgerEntry {
  id: string;
  org_id: string;
  entry_type: "sale" | "sale_void" | "expense" | "adjustment";
  amount: number; // signed
  ref_type: string | null;
  ref_id: string | null;
  balance_after: number;
  entry_date: string;
  created_by: string | null;
  created_at: string;
}

export interface LedgerEntry {
  id: string;
  org_id: string;
  created_by: string;
  amount: number;
  category: string;
  description?: string | null;
  customer_name?: string | null;
  customer_id?: string | null; // sales only: optional link to a customer
  voucher_reference?: string | null;
  sale_date?: string;
  expense_date?: string;
  items?: SaleItem[]; // sales only (empty for quick sales)
  skipped_items?: SkippedSaleItem[]; // only in the POST response of a partial sale
  created_at: string;
  updated_at: string;
}

export interface LedgerEntryInput {
  amount?: number; // required unless `items` is given (the total is then the sum of the lines)
  items?: SaleItemInput[]; // sales only, create only
  skip_invalid_items?: boolean; // sales only: keep valid lines when some are invalid
  category?: string;
  description?: string | null;
  customer_name?: string | null;
  customer_id?: string | null; // sales only; null unlinks on update
  voucher_reference?: string | null;
}

export type AgentJobStatus = "pending" | "processing" | "completed" | "failed";

export interface BookkeepingAdvice {
  // Matches ai_agents/api/financial_advisor_agent.py's BookkeepingResult.
  // The rule-based fallback (jobs/financial_agent_job.py) only ever sets
  // mode + summary, leaving the rest undefined -- treat them as optional.
  mode: "investigation" | "record_entry";
  summary: string;
  root_cause?: string | null;
  recommendation?: string | null;
  used_web_search?: boolean;
  record_reference?: string | null;
}

export interface AgentJobResult {
  advice: BookkeepingAdvice;
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

export interface Product {
  id: string;
  org_id: string;
  created_by: string | null;
  name: string;
  sku: string;
  price: number;
  stock_qty: number;
  reorder_level: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProductInput {
  name: string;
  sku: string;
  price: number;
  // Initial stock: only used on create. Later changes go through adjust-stock.
  stock_qty?: number;
  reorder_level?: number;
  is_active?: boolean;
}

export interface Customer {
  id: string;
  org_id: string;
  created_by: string | null;
  name: string;
  phone: string | null;
  email: string | null;
  address: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface CustomerInput {
  name: string;
  phone?: string | null;
  email?: string | null;
  address?: string | null;
  notes?: string | null;
}

export interface CustomerSummary {
  customer: Customer;
  total_sales: number;
  sale_count: number;
  last_sale_date: string | null;
}
