/* =============================================================================
   03_products.sql  --  Handseller Bookkeeping, SQL Server (T-SQL)
   Adds: table products (stock-keeping), UQ_products_org_sku, idx_products_org_id,
         trg_products_updated_at (AFTER UPDATE trigger that maintains updated_at).
   Requires 01_foundation.sql. Re-runnable: nothing is dropped.

   Design notes
   * CHECK (stock_qty >= 0) is the DB-LEVEL CONSISTENCY GUARD for inventory. The later sale
     procedure (which decrements stock while recording a sale) relies on it: even if two
     sessions race or application code is buggy, SQL Server itself refuses to let stock go
     negative (error 547) and the surrounding transaction rolls back. The application's
     adjust-stock statement additionally adds `AND stock_qty + ? >= 0` to its WHERE clause so
     the normal "insufficient stock" case is a clean zero-row result instead of a 547 error.
   * UNIQUE (org_id, sku): a SKU is unique per organisation, the same SKU may exist in
     another organisation (a UNIQUE violation surfaces as error 2627 => HTTP 409).
   * No Row Level Security (same decision as 01/02): the application layer (id AND org_id in
     every statement) is the tenancy control.
   * Because the table has an AFTER UPDATE trigger, repository code uses
     `OUTPUT ... INTO @table` + SELECT instead of bare `OUTPUT INSERTED.*` (error 334).
   * No ON DELETE CASCADE; products are hard-deleted by the API today (see api/specs/17).
   ============================================================================= */

USE HandsellerDB;
GO

IF OBJECT_ID(N'dbo.products', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.products (
        id            uniqueidentifier NOT NULL CONSTRAINT DF_products_id DEFAULT NEWID() CONSTRAINT PK_products PRIMARY KEY,
        org_id        uniqueidentifier NOT NULL CONSTRAINT FK_products_org REFERENCES dbo.orgs(id),
        created_by    uniqueidentifier NULL     CONSTRAINT FK_products_created_by REFERENCES dbo.users(id),
        name          nvarchar(200)    NOT NULL,
        sku           nvarchar(64)     NOT NULL,
        price         decimal(14,2)    NOT NULL CONSTRAINT CK_products_price CHECK (price >= 0),
        stock_qty     int              NOT NULL CONSTRAINT DF_products_stock_qty DEFAULT 0
                      CONSTRAINT CK_products_stock_qty CHECK (stock_qty >= 0),
        reorder_level int              NOT NULL CONSTRAINT DF_products_reorder_level DEFAULT 0
                      CONSTRAINT CK_products_reorder_level CHECK (reorder_level >= 0),
        is_active     bit              NOT NULL CONSTRAINT DF_products_is_active DEFAULT 1,
        created_at    datetimeoffset   NOT NULL CONSTRAINT DF_products_created_at DEFAULT SYSUTCDATETIME(),
        updated_at    datetimeoffset   NOT NULL CONSTRAINT DF_products_updated_at DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_products_org_sku UNIQUE (org_id, sku)
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_products_org_id' AND object_id = OBJECT_ID(N'dbo.products'))
BEGIN
    CREATE INDEX idx_products_org_id ON dbo.products(org_id);
END
GO

CREATE OR ALTER TRIGGER dbo.trg_products_updated_at ON dbo.products AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    IF TRIGGER_NESTLEVEL(OBJECT_ID(N'dbo.trg_products_updated_at')) > 1 RETURN; -- don't recurse
    UPDATE t SET updated_at = SYSUTCDATETIME()
    FROM dbo.products AS t INNER JOIN inserted AS i ON i.id = t.id;
END
GO
