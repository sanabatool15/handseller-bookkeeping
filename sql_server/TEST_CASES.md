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
