/* =============================================================================
   02_sales_expenses.sql  --  Handseller Bookkeeping, SQL Server (T-SQL)
   Adds: tables sales, expenses; idx_sales_org_id, idx_expenses_org_id;
         AFTER UPDATE triggers that maintain updated_at.
   Requires 01_foundation.sql.
   Re-runnable: run it as often as you like in SSMS; nothing is dropped.
   (An older version of this script also created agent_jobs / agent_logs for the AI agent feature. That feature
   was removed. If your database already has those two tables they are harmless and can be dropped by hand.)

   Design notes
   * NO Row Level Security: the application layer (id AND org_id in every statement) is the tenancy control.
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
