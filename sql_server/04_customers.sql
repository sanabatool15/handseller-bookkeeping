/* =============================================================================
   04_customers.sql  --  Handseller Bookkeeping, SQL Server (T-SQL)
   Adds: table customers, idx_customers_org_id, UQ_customers_org_phone (FILTERED unique index),
         UQ_customers_id_org, trg_customers_updated_at (AFTER UPDATE trigger maintaining updated_at);
         column sales.customer_id (nullable) + FK_sales_customer + idx_sales_org_customer.
   Requires 01_foundation.sql, 02_sales_expenses_agents.sql. Re-runnable: nothing is dropped.

   Design notes
   * UNIQUE (org_id, phone) must ignore customers WITHOUT a phone. A plain UNIQUE constraint/index
     treats NULLs as equal in SQL Server, so only ONE phone-less customer per org would be allowed.
     Hence a FILTERED unique index `... WHERE phone IS NOT NULL`: phones are unique per org, any number
     of customers may have no phone, and the same phone may exist in another org. The service stores
     blank phones as NULL (never ''), otherwise '' would count as a value. A filtered index needs the usual
     SET options (QUOTED_IDENTIFIER ON etc.) on every writing connection; pyodbc/SSMS default to them.
     A violation raises error 2601 (unique INDEX; a constraint would be 2627) => HTTP 409.
   * sales.customer_id is NULLable and optional: the free-text sales.customer_name keeps working.
     The FK is COMPOSITE (customer_id, org_id) -> customers(id, org_id) (needs UQ_customers_id_org),
     so the database itself refuses a sale that points at another org's customer. With a NULL
     customer_id the FK is not checked.
   * No ON DELETE action: deleting a customer that still has sales is refused (the API checks
     in the same DELETE statement and answers 409; the FK is the backstop, error 547). See api/specs/14.
   * No Row Level Security (same decision as 01..03): the application layer (id AND org_id) is the control.
   * Because the table has an AFTER UPDATE trigger, repository code uses `OUTPUT ... INTO @table` (error 334).
   ============================================================================= */

USE HandsellerDB;
GO

IF OBJECT_ID(N'dbo.customers', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.customers (
        id          uniqueidentifier NOT NULL CONSTRAINT DF_customers_id DEFAULT NEWID() CONSTRAINT PK_customers PRIMARY KEY,
        org_id      uniqueidentifier NOT NULL CONSTRAINT FK_customers_org REFERENCES dbo.orgs(id),
        created_by  uniqueidentifier NULL     CONSTRAINT FK_customers_created_by REFERENCES dbo.users(id),
        name        nvarchar(200)    NOT NULL,
        phone       nvarchar(32)     NULL,
        email       nvarchar(320)    NULL,
        address     nvarchar(500)    NULL,
        notes       nvarchar(1000)   NULL,
        created_at  datetimeoffset   NOT NULL CONSTRAINT DF_customers_created_at DEFAULT SYSUTCDATETIME(),
        updated_at  datetimeoffset   NOT NULL CONSTRAINT DF_customers_updated_at DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_customers_id_org UNIQUE (id, org_id)   -- target of the composite FK from sales
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_customers_org_id' AND object_id = OBJECT_ID(N'dbo.customers'))
BEGIN
    CREATE INDEX idx_customers_org_id ON dbo.customers(org_id);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'UQ_customers_org_phone' AND object_id = OBJECT_ID(N'dbo.customers'))
BEGIN
    CREATE UNIQUE INDEX UQ_customers_org_phone ON dbo.customers(org_id, phone) WHERE phone IS NOT NULL;
END
GO

CREATE OR ALTER TRIGGER dbo.trg_customers_updated_at ON dbo.customers AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    IF TRIGGER_NESTLEVEL(OBJECT_ID(N'dbo.trg_customers_updated_at')) > 1 RETURN; -- don't recurse
    UPDATE t SET updated_at = SYSUTCDATETIME()
    FROM dbo.customers AS t INNER JOIN inserted AS i ON i.id = t.id;
END
GO

/* ---- sales.customer_id (optional link to customers) ---------------------- */
IF COL_LENGTH(N'dbo.sales', N'customer_id') IS NULL
BEGIN
    ALTER TABLE dbo.sales ADD customer_id uniqueidentifier NULL;
END
GO

-- Separate batch: the column must exist when this batch is compiled.
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_sales_customer' AND parent_object_id = OBJECT_ID(N'dbo.sales'))
BEGIN
    ALTER TABLE dbo.sales ADD CONSTRAINT FK_sales_customer
        FOREIGN KEY (customer_id, org_id) REFERENCES dbo.customers (id, org_id);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_sales_org_customer' AND object_id = OBJECT_ID(N'dbo.sales'))
BEGIN
    CREATE INDEX idx_sales_org_customer ON dbo.sales(org_id, customer_id);
END
GO
