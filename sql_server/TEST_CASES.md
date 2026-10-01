# SQL Server test cases (manual, SSMS)

Run scripts in order. Replace nothing unless noted. All T-SQL is untested at authoring time.

## Slice F0a: foundation + auth

### F0a-01 Script runs and is re-runnable
Steps: open `01_foundation.sql` in SSMS, Execute. Execute it a second time.
Expected: both runs finish without errors; database `HandsellerDB` exists with tables `orgs`, `users`.
Pass: no error messages; `SELECT name FROM sys.tables` lists both.

### F0a-02 Constraints and index
Steps: `SELECT name FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.users');` and
`SELECT name FROM sys.foreign_keys;`
Expected: `UQ_users_email`, `idx_users_org_id`, `FK_users_org`, `FK_orgs_owner` present.
Pass: all four listed.

### F0a-03 Unique email
Steps: `INSERT users(email,hashed_password) VALUES(N'a@x.com',N'h'); INSERT users(email,hashed_password) VALUES(N'A@X.COM',N'h');`
Expected: second insert fails with error 2627 (case-insensitive collation).
Pass: error 2627; one row. Cleanup: `DELETE users WHERE email=N'a@x.com'`.

### F0a-04 updated_at trigger
Steps: insert a user; `WAITFOR DELAY '00:00:01'`; `UPDATE users SET full_name=N'B' WHERE email=N'a@x.com'`; select `created_at, updated_at`.
Expected: `updated_at` > `created_at`.
Pass: yes. Same check for `orgs` (update `name`).

### F0a-05 Register via API
Steps: start `uvicorn core.fastapi_app:app`; `POST /auth/register` with `Idempotency-Key` header and
`{"email":"o@x.com","password":"hunter2pass","org_name":"Acme"}`.
Expected: 201 with `access_token`, `user.org_id == org.id`, `org.owner_id == user.id`.
Pass: and `SELECT * FROM users/orgs` shows the linked rows.

### F0a-06 Duplicate email
Steps: repeat F0a-05 with a new Idempotency-Key.
Expected: 409 `Email already registered`; still exactly one user and one org for that email.

### F0a-07 Atomic rollback
Steps: in SSMS, `ALTER TABLE orgs ADD CONSTRAINT CK_tmp CHECK (name <> N'FAIL');` then register with `org_name` = `FAIL`.
Expected: 500; `SELECT * FROM users WHERE email=...` returns no row (no orphan user). Cleanup: `ALTER TABLE orgs DROP CONSTRAINT CK_tmp;`.

### F0a-08 Automated DB tests
Steps: `RUN_MSSQL=1 pytest tests/sqlserver -v` from `api/`. Pass: 3 passed.

## Slice F0b: sales, expenses, agent jobs/logs (script `02_sales_expenses_agents.sql`)

Prerequisite: `01_foundation.sql` applied. Below, `<ORG>` / `<USER>` are the ids from `POST /auth/register`
(or `SELECT id, org_id FROM users WHERE email = ...`). Send an `Idempotency-Key` header on every POST/PUT.

### F0b-01 Script runs and is re-runnable
Steps: execute `02_sales_expenses_agents.sql` in SSMS, then execute it again.
Expected: no errors either time; tables `sales`, `expenses`, `agent_jobs`, `agent_logs` exist.
Pass: `SELECT name FROM sys.tables ORDER BY name` lists all six tables (with `orgs`, `users`).

### F0b-02 Indexes, constraints, triggers
Steps: `SELECT name FROM sys.indexes WHERE name LIKE 'idx[_]%' ORDER BY name;`
`SELECT name FROM sys.check_constraints ORDER BY name;` `SELECT name FROM sys.triggers ORDER BY name;`
Expected: `idx_sales_org_id, idx_expenses_org_id, idx_agent_jobs_org_id, idx_agent_logs_job_id, idx_agent_logs_org_id, idx_users_org_id`;
checks `CK_agent_jobs_status, CK_agent_jobs_input_json, CK_agent_jobs_result_json, CK_agent_jobs_error_json, CK_agent_logs_insights_json`;
triggers `trg_sales_updated_at, trg_expenses_updated_at, trg_agent_jobs_updated_at, trg_agent_logs_updated_at` (+ the two from F0a).
Pass: all listed.

### F0b-03 updated_at triggers
Steps: insert a sale (`INSERT sales(org_id, amount) VALUES (<ORG>, 10)`), `WAITFOR DELAY '00:00:01'`,
`UPDATE sales SET category = N'x' WHERE org_id = <ORG>`; compare `created_at`, `updated_at`. Repeat for `expenses`, `agent_jobs`
(`job_name`), `agent_logs` (`step_name`).
Expected: `updated_at` > `created_at` in every case. Pass: yes.

### F0b-04 JSON and status checks
Steps: `INSERT agent_jobs(job_name, org_id, input_payload) VALUES (N'x', <ORG>, N'not json');`
and `INSERT agent_jobs(job_name, org_id, status) VALUES (N'x', <ORG>, N'bogus');`
Expected: both fail (check constraint violation, error 547). `input_payload = NULL` and `N'{}'` insert fine.
Pass: two errors; no rows inserted by the failing statements.

### F0b-05 agent_logs cannot disagree with its job's org
Steps: create two orgs A, B and a job of A; `INSERT agent_logs(job_id, org_id, step_name) VALUES (<jobA>, <ORG_B>, N's');`
Expected: FK violation (error 547, composite FK `FK_agent_logs_job`). Same insert with `<ORG_A>` succeeds. Deleting the job deletes its logs (cascade).
Pass: as described.

### F0b-06 Create sale/expense via API (JSON shape)
Steps: `POST /sales {"amount": 19.99, "category": "retail", "customer_name": "Zed"}`; `POST /expenses {"amount": 5.25, "category": "rent", "voucher_reference": "V-1"}`.
Expected: 201; `id`, `org_id`, `created_by` strings; `amount` a JSON number (19.99); `sale_date`/`expense_date` = today (UTC) as `YYYY-MM-DD`;
`created_at`/`updated_at` ISO strings. `GET /sales`, `/sales/{id}`, `/expenses` return the same shapes (compare with `lib/types.ts` `LedgerEntry`).
Pass: yes, and `SELECT * FROM sales` shows the row with `org_id = <ORG>`, `created_by = <USER>`.

### F0b-07 Update, delete, validation
Steps: `PUT /sales/{id} {"amount": 20.5}`; `DELETE /sales/{id}`; `POST /sales {"amount": 0}`; `POST /sales` without `amount`.
Expected: 200 with the new amount (other fields unchanged; note `updated_at` in the PUT response is the pre-trigger value, a later GET shows the new one);
204 then 404 on GET; 422; 422.
Pass: yes.

### F0b-08 Tenant isolation => 404
Steps: register a second org B (token B). With token B call `GET/PUT/DELETE /sales/{id of A's sale}` and the same for `/expenses/{id}` and `GET /agent-jobs/{A's job}`.
Expected: always 404 (never 403/200); A's rows unchanged; `GET /sales` with token B returns `[]`.
Pass: yes.

### F0b-09 Month sums and breakdown are computed in SQL
Steps: insert sales for org `<ORG>` with `sale_date` 2026-01-31, 2026-02-01, 2026-02-28, 2026-03-01 (amounts 7, 100.10, 50.20, 9; category retail) and one 2026-02-10 gift sale of 1.0;
then `SELECT COALESCE(SUM(amount),0) FROM sales WHERE org_id=<ORG> AND sale_date >= '2026-02-01' AND sale_date < '2026-03-01';` (expect 151.30).
In Python (from `api/`): `python -c "from core.clients import db_session; from services.financial_report_service import monthly_summary, sales_breakdown_by_category as b; \
s=db_session().__enter__(); print(monthly_summary(s, org_id='<ORG>', year=2026, month=2), b(s, org_id='<ORG>', year=2026, month=2))"`.
Expected: `total_sales` 151.3 and `{'retail': 150.3, 'gifts': 1.0}`; month 4 gives 0.0; `year=2026, month=12` works (range ends 2027-01-01).
Pass: matches the SQL result; boundary days (Jan 31, Mar 1) excluded.

### F0b-10 Agent job lifecycle through the API
Steps: with Inngest dev server running (or without it: the job just stays pending), `POST /agent-jobs/financial-advice {"question": "How are we doing?"}`; then poll `GET /agent-jobs/{job_id}`.
Expected: 202 with `job_id`, `status: "pending"`; the row is already committed when the response returns; `input_payload` is the dict `{"question": ...}`;
with the worker running: `status` becomes `processing` then `completed`, `result` is a dict with `advice` and `source`, and `SELECT step_name FROM agent_logs WHERE job_id = ...` shows `gather_data, run_agent, finalize`.
Pass: yes (without OpenAI keys `source` is `rule_based_fallback`).

### F0b-11 MCP server
Steps: from `api/`, `python mcp_gateway/server.py` and connect a client (or call the tools from a unit harness): `log_sale`, `log_expense`, `trigger_financial_agent_job`, `stream_job_logs`, read `ledger://<ORG>/monthly.csv`.
Expected: rows appear in `sales`/`expenses`; logs of a job of another org come back empty with an error log ("not found"); CSV lists only the current month.
Pass: yes.

### F0b-12 Health
Steps: `GET /health` with SQL Server up, then stop the SQL Server service (or break `MSSQL_*`) and call again.
Expected: first `{"status":"ok","checks":{"redis":"ok","database":"ok"}}`; second `database` = `error: ...` (status field stays "ok"); startup log shows "SQL Server connection OK" / a warning.
Pass: yes.

### F0b-13 Automated DB tests
Steps: `RUN_MSSQL=1 pytest tests/sqlserver -v` from `api/`.
Expected: 3 tests from F0a + 8 from F0b (`test_ledger_sqlserver.py`) pass (11 total).
Pass: all green; tests clean up their own orgs/users (`mssql-test-*`).
