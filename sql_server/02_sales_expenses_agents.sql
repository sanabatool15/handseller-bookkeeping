/* =============================================================================
   02_sales_expenses_agents.sql  --  Handseller Bookkeeping, SQL Server (T-SQL)
   Adds: tables sales, expenses, agent_jobs, agent_logs; idx_sales_org_id,
         idx_expenses_org_id, idx_agent_jobs_org_id, idx_agent_logs_job_id,
         idx_agent_logs_org_id; AFTER UPDATE triggers that maintain updated_at.
   Port of api/sql/schema.sql (Supabase/Postgres). Requires 01_foundation.sql.
   Re-runnable: run it as often as you like in SSMS; nothing is dropped.

   Design notes
   * NO Row Level Security (same decision as 01_foundation.sql): the application layer
     (id AND org_id in every statement) is the tenancy control.
   * Foreign keys carry NO "ON DELETE CASCADE" except agent_logs -> agent_jobs, because SQL
     Server rejects tables reachable by several cascade paths. The app never deletes orgs/users.
   * json columns are nvarchar(max) with CHECK (ISJSON(col) = 1). ISJSON(NULL) is NULL, which a
     CHECK accepts, so NULL stays allowed where the column is nullable.
   * agent_logs got an org_id column (the Postgres table only had job_id). Reason: every
     tenant-table statement in this codebase must mention org_id (static guard test), and
     it lets logs be read as WHERE job_id = ? AND org_id = ?. A composite FK
     (job_id, org_id) -> agent_jobs(id, org_id) guarantees a log can never carry a
     different org than its job.
   * agent_logs has NO UNIQUE (job_id, step_name): a retried Inngest step would re-insert its
     log row and a UNIQUE index would turn that retry into a permanent failure
     (see api/specs/17-open-questions.md).
   * sales.sale_date / expenses.expense_date are business dates (date), separate from
     created_at. The API sets them explicitly (UTC today); the DEFAULT is only a fallback.
   * Because the tables have AFTER UPDATE triggers, repository code uses
     `OUTPUT ... INTO @table` + SELECT instead of bare `OUTPUT INSERTED.*` (error 334).
   ============================================================================= */

USE HandsellerDB;
GO

/* --------------------------------------------------------------- sales ---- */
IF OBJECT_ID(N'dbo.sales', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.sales (
        id            uniqueidentifier NOT NULL CONSTRAINT DF_sales_id DEFAULT NEWID() CONSTRAINT PK_sales PRIMARY KEY,
        org_id        uniqueidentifier NOT NULL CONSTRAINT FK_sales_org REFERENCES dbo.orgs(id),
        created_by    uniqueidentifier NULL     CONSTRAINT FK_sales_created_by REFERENCES dbo.users(id),
        amount        decimal(14,2)    NOT NULL,
        category      nvarchar(100)    NOT NULL CONSTRAINT DF_sales_category DEFAULT N'general',
        description   nvarchar(max)    NULL,
        customer_name nvarchar(200)    NULL,
        sale_date     date             NOT NULL CONSTRAINT DF_sales_sale_date DEFAULT CONVERT(date, SYSUTCDATETIME()),
        created_at    datetimeoffset   NOT NULL CONSTRAINT DF_sales_created_at DEFAULT SYSUTCDATETIME(),
        updated_at    datetimeoffset   NOT NULL CONSTRAINT DF_sales_updated_at DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_sales_org_id' AND object_id = OBJECT_ID(N'dbo.sales'))
BEGIN
    CREATE INDEX idx_sales_org_id ON dbo.sales(org_id);
END
GO

/* ------------------------------------------------------------ expenses ---- */
IF OBJECT_ID(N'dbo.expenses', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.expenses (
        id                uniqueidentifier NOT NULL CONSTRAINT DF_expenses_id DEFAULT NEWID() CONSTRAINT PK_expenses PRIMARY KEY,
        org_id            uniqueidentifier NOT NULL CONSTRAINT FK_expenses_org REFERENCES dbo.orgs(id),
        created_by        uniqueidentifier NULL     CONSTRAINT FK_expenses_created_by REFERENCES dbo.users(id),
        amount            decimal(14,2)    NOT NULL,
        category          nvarchar(100)    NOT NULL CONSTRAINT DF_expenses_category DEFAULT N'general',
        voucher_reference nvarchar(200)    NULL,
        description       nvarchar(max)    NULL,
        expense_date      date             NOT NULL CONSTRAINT DF_expenses_expense_date DEFAULT CONVERT(date, SYSUTCDATETIME()),
        created_at        datetimeoffset   NOT NULL CONSTRAINT DF_expenses_created_at DEFAULT SYSUTCDATETIME(),
        updated_at        datetimeoffset   NOT NULL CONSTRAINT DF_expenses_updated_at DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_expenses_org_id' AND object_id = OBJECT_ID(N'dbo.expenses'))
BEGIN
    CREATE INDEX idx_expenses_org_id ON dbo.expenses(org_id);
END
GO

/* ---------------------------------------------------------- agent_jobs ---- */
IF OBJECT_ID(N'dbo.agent_jobs', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.agent_jobs (
        id            uniqueidentifier NOT NULL CONSTRAINT DF_agent_jobs_id DEFAULT NEWID() CONSTRAINT PK_agent_jobs PRIMARY KEY,
        job_name      nvarchar(100)    NOT NULL,
        org_id        uniqueidentifier NOT NULL CONSTRAINT FK_agent_jobs_org REFERENCES dbo.orgs(id),
        requested_by  uniqueidentifier NULL     CONSTRAINT FK_agent_jobs_requested_by REFERENCES dbo.users(id),
        status        nvarchar(20)     NOT NULL CONSTRAINT DF_agent_jobs_status DEFAULT N'pending'
                      CONSTRAINT CK_agent_jobs_status CHECK (status IN (N'pending', N'processing', N'completed', N'failed')),
        current_step  nvarchar(100)    NULL,
        input_payload nvarchar(max)    NULL CONSTRAINT CK_agent_jobs_input_json CHECK (ISJSON(input_payload) = 1),
        result        nvarchar(max)    NULL CONSTRAINT CK_agent_jobs_result_json CHECK (ISJSON(result) = 1),
        error_details nvarchar(max)    NULL CONSTRAINT CK_agent_jobs_error_json CHECK (ISJSON(error_details) = 1),
        created_at    datetimeoffset   NOT NULL CONSTRAINT DF_agent_jobs_created_at DEFAULT SYSUTCDATETIME(),
        updated_at    datetimeoffset   NOT NULL CONSTRAINT DF_agent_jobs_updated_at DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_agent_jobs_id_org UNIQUE (id, org_id)   -- target of the composite FK from agent_logs
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_agent_jobs_org_id' AND object_id = OBJECT_ID(N'dbo.agent_jobs'))
BEGIN
    CREATE INDEX idx_agent_jobs_org_id ON dbo.agent_jobs(org_id);
END
GO

/* ---------------------------------------------------------- agent_logs ---- */
IF OBJECT_ID(N'dbo.agent_logs', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.agent_logs (
        id                 uniqueidentifier NOT NULL CONSTRAINT DF_agent_logs_id DEFAULT NEWID() CONSTRAINT PK_agent_logs PRIMARY KEY,
        job_id             uniqueidentifier NOT NULL,
        org_id             uniqueidentifier NOT NULL CONSTRAINT FK_agent_logs_org REFERENCES dbo.orgs(id),
        step_name          nvarchar(100)    NOT NULL,
        action_summary     nvarchar(max)    NULL,
        insights_generated nvarchar(max)    NULL CONSTRAINT CK_agent_logs_insights_json CHECK (ISJSON(insights_generated) = 1),
        executed_at        datetimeoffset   NOT NULL CONSTRAINT DF_agent_logs_executed_at DEFAULT SYSUTCDATETIME(),
        created_at         datetimeoffset   NOT NULL CONSTRAINT DF_agent_logs_created_at DEFAULT SYSUTCDATETIME(),
        updated_at         datetimeoffset   NOT NULL CONSTRAINT DF_agent_logs_updated_at DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_agent_logs_job FOREIGN KEY (job_id, org_id)
            REFERENCES dbo.agent_jobs(id, org_id) ON DELETE CASCADE
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_agent_logs_job_id' AND object_id = OBJECT_ID(N'dbo.agent_logs'))
BEGIN
    CREATE INDEX idx_agent_logs_job_id ON dbo.agent_logs(job_id);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_agent_logs_org_id' AND object_id = OBJECT_ID(N'dbo.agent_logs'))
BEGIN
    CREATE INDEX idx_agent_logs_org_id ON dbo.agent_logs(org_id);
END
GO

/* ------------------------------------------------- updated_at triggers ---- */
CREATE OR ALTER TRIGGER dbo.trg_sales_updated_at ON dbo.sales AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    IF TRIGGER_NESTLEVEL(OBJECT_ID(N'dbo.trg_sales_updated_at')) > 1 RETURN; -- don't recurse
    UPDATE t SET updated_at = SYSUTCDATETIME()
    FROM dbo.sales AS t INNER JOIN inserted AS i ON i.id = t.id;
END
GO

CREATE OR ALTER TRIGGER dbo.trg_expenses_updated_at ON dbo.expenses AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    IF TRIGGER_NESTLEVEL(OBJECT_ID(N'dbo.trg_expenses_updated_at')) > 1 RETURN;
    UPDATE t SET updated_at = SYSUTCDATETIME()
    FROM dbo.expenses AS t INNER JOIN inserted AS i ON i.id = t.id;
END
GO

CREATE OR ALTER TRIGGER dbo.trg_agent_jobs_updated_at ON dbo.agent_jobs AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    IF TRIGGER_NESTLEVEL(OBJECT_ID(N'dbo.trg_agent_jobs_updated_at')) > 1 RETURN;
    UPDATE t SET updated_at = SYSUTCDATETIME()
    FROM dbo.agent_jobs AS t INNER JOIN inserted AS i ON i.id = t.id;
END
GO

CREATE OR ALTER TRIGGER dbo.trg_agent_logs_updated_at ON dbo.agent_logs AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    IF TRIGGER_NESTLEVEL(OBJECT_ID(N'dbo.trg_agent_logs_updated_at')) > 1 RETURN;
    UPDATE t SET updated_at = SYSUTCDATETIME()
    FROM dbo.agent_logs AS t INNER JOIN inserted AS i ON i.id = t.id;
END
GO
