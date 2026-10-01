/* =============================================================================
   05_sale_items_cash_recordsale.sql  --  Handseller Bookkeeping, SQL Server (T-SQL)
   Adds: tables sale_items, cash_accounts, cash_ledger (+ idx_sale_items_org_id, idx_sale_items_sale_id,
         idx_cash_ledger_org_id, idx_cash_ledger_org_date, updated_at triggers),
         UNIQUE (id, org_id) on sales and products (targets of composite FKs),
         stored procedures dbo.usp_RecordSale and dbo.usp_VoidSale.
   Requires 01..04. Re-runnable: tables are created only if missing, procedures/triggers use CREATE OR ALTER.

   THE TRANSACTIONAL CORE OF THE COURSE PROJECT (ACID). Read the comments inside the procedures.

   Design notes
   * A sale with line items must change FOUR things together or not at all:
        sales (+ sale_items)  -> products.stock_qty (decrement)  -> cash_accounts.balance  -> cash_ledger.
     Atomicity: all of it happens inside ONE transaction.
     Consistency: CHECK constraints (stock_qty >= 0, quantity > 0, unit_price >= 0) and composite FKs
                  (org_id travels with every foreign key) stop bad data even if application code is wrong.
     Isolation: the stock decrement is ONE statement,
                   UPDATE products SET stock_qty = stock_qty - @q WHERE id = @p AND org_id = @o AND stock_qty >= @q
                and @@ROWCOUNT tells us whether it worked. Never "SELECT stock, check in the app, UPDATE":
                two buyers could both read "1 left" and both succeed (lost update / oversell).
     Durability: COMMIT.
   * Transaction ownership. The procedures work in two situations:
        (a) called with NO open transaction (@@TRANCOUNT = 0, e.g. from SSMS):
            the procedure does BEGIN TRANSACTION ... COMMIT itself.
        (b) called INSIDE a caller's transaction (@@TRANCOUNT > 0; this is what the API connection does,
            pyodbc runs with autocommit OFF = SET IMPLICIT_TRANSACTIONS ON): the procedure must NOT commit
            (the caller owns the transaction), so it sets a SAVEPOINT and, on failure, rolls back only to it.
     The procedure remembers which case it is in @own_tran. See api/specs/15-transactions-and-concurrency.md.
   * Business failures (not enough stock, unknown product, ...) are NOT raised as errors: they are reported through
     the OUTPUT parameters (@status/@error_number/@message). Reason: with SET XACT_ABORT ON every raised error
     "dooms" the transaction (XACT_STATE() = -1) and only a FULL rollback is allowed, which would also destroy a
     caller's transaction. Business error numbers: 50001 insufficient stock, 50002 product not found,
     50003 validation, 50004 customer not found, 50005 organisation not found, 50006 sale not found.
     Any other number came from the engine (e.g. 1205 deadlock victim, 547 constraint) and the API treats it as a
     technical error (deadlock => retried).
   * Table variables (@lines, @skipped) are NOT rolled back by ROLLBACK, which is what lets us remember
     skipped items after rolling back to the item savepoint.
   * No Row Level Security (same decision as 01..04): the application layer (org_id in every statement) is the control.
   ============================================================================= */

USE HandsellerDB;
GO

/* ---- UNIQUE (id, org_id) on sales and products: targets of the composite foreign keys ---------------------- */
IF NOT EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = N'UQ_sales_id_org' AND parent_object_id = OBJECT_ID(N'dbo.sales'))
BEGIN
    ALTER TABLE dbo.sales ADD CONSTRAINT UQ_sales_id_org UNIQUE (id, org_id);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = N'UQ_products_id_org' AND parent_object_id = OBJECT_ID(N'dbo.products'))
BEGIN
    ALTER TABLE dbo.products ADD CONSTRAINT UQ_products_id_org UNIQUE (id, org_id);
END
GO

/* --------------------------------------------------------------- sale_items ---- */
IF OBJECT_ID(N'dbo.sale_items', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.sale_items (
        id          uniqueidentifier NOT NULL CONSTRAINT DF_sale_items_id DEFAULT NEWID() CONSTRAINT PK_sale_items PRIMARY KEY,
        org_id      uniqueidentifier NOT NULL CONSTRAINT FK_sale_items_org REFERENCES dbo.orgs(id),
        sale_id     uniqueidentifier NOT NULL,
        product_id  uniqueidentifier NOT NULL,
        quantity    int              NOT NULL CONSTRAINT CK_sale_items_quantity CHECK (quantity > 0),
        unit_price  decimal(14,2)    NOT NULL CONSTRAINT CK_sale_items_unit_price CHECK (unit_price >= 0),
        line_total  AS (CONVERT(decimal(16,2), quantity) * unit_price) PERSISTED,   -- computed + stored: always consistent
        created_at  datetimeoffset   NOT NULL CONSTRAINT DF_sale_items_created_at DEFAULT SYSUTCDATETIME(),
        updated_at  datetimeoffset   NOT NULL CONSTRAINT DF_sale_items_updated_at DEFAULT SYSUTCDATETIME(),
        -- composite FKs: an item can only point at a sale / product of the SAME org
        CONSTRAINT FK_sale_items_sale    FOREIGN KEY (sale_id, org_id)    REFERENCES dbo.sales (id, org_id) ON DELETE CASCADE,
        CONSTRAINT FK_sale_items_product FOREIGN KEY (product_id, org_id) REFERENCES dbo.products (id, org_id)
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_sale_items_org_id' AND object_id = OBJECT_ID(N'dbo.sale_items'))
BEGIN
    CREATE INDEX idx_sale_items_org_id ON dbo.sale_items(org_id);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_sale_items_sale_id' AND object_id = OBJECT_ID(N'dbo.sale_items'))
BEGIN
    CREATE INDEX idx_sale_items_sale_id ON dbo.sale_items(sale_id);
END
GO

/* ------------------------------------------------------------ cash_accounts ---- */
-- One row per org, created lazily by usp_RecordSale / usp_VoidSale. balance == SUM(cash_ledger.amount) of the org.
IF OBJECT_ID(N'dbo.cash_accounts', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.cash_accounts (
        org_id     uniqueidentifier NOT NULL CONSTRAINT PK_cash_accounts PRIMARY KEY
                   CONSTRAINT FK_cash_accounts_org REFERENCES dbo.orgs(id),
        balance    decimal(16,2)    NOT NULL CONSTRAINT DF_cash_accounts_balance DEFAULT 0,
        created_at datetimeoffset   NOT NULL CONSTRAINT DF_cash_accounts_created_at DEFAULT SYSUTCDATETIME(),
        updated_at datetimeoffset   NOT NULL CONSTRAINT DF_cash_accounts_updated_at DEFAULT SYSUTCDATETIME()
    );
END
GO

/* -------------------------------------------------------------- cash_ledger ---- */
-- Append-only journal of every cash movement; amount is signed (+ money in, - money out).
IF OBJECT_ID(N'dbo.cash_ledger', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.cash_ledger (
        id            uniqueidentifier NOT NULL CONSTRAINT DF_cash_ledger_id DEFAULT NEWID() CONSTRAINT PK_cash_ledger PRIMARY KEY,
        org_id        uniqueidentifier NOT NULL CONSTRAINT FK_cash_ledger_org REFERENCES dbo.orgs(id),
        entry_type    nvarchar(20)     NOT NULL
                      CONSTRAINT CK_cash_ledger_entry_type CHECK (entry_type IN (N'sale', N'sale_void', N'expense', N'adjustment')),
        amount        decimal(14,2)    NOT NULL,
        ref_type      nvarchar(20)     NULL,
        ref_id        uniqueidentifier NULL,      -- id of the sale/expense it belongs to (no FK: a voided sale is deleted)
        balance_after decimal(16,2)    NOT NULL,
        entry_date    date             NOT NULL CONSTRAINT DF_cash_ledger_entry_date DEFAULT CONVERT(date, SYSUTCDATETIME()),
        created_by    uniqueidentifier NULL     CONSTRAINT FK_cash_ledger_created_by REFERENCES dbo.users(id),
        created_at    datetimeoffset   NOT NULL CONSTRAINT DF_cash_ledger_created_at DEFAULT SYSUTCDATETIME(),
        updated_at    datetimeoffset   NOT NULL CONSTRAINT DF_cash_ledger_updated_at DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_cash_ledger_org_id' AND object_id = OBJECT_ID(N'dbo.cash_ledger'))
BEGIN
    CREATE INDEX idx_cash_ledger_org_id ON dbo.cash_ledger(org_id);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_cash_ledger_org_date' AND object_id = OBJECT_ID(N'dbo.cash_ledger'))
BEGIN
    CREATE INDEX idx_cash_ledger_org_date ON dbo.cash_ledger(org_id, entry_date);
END
GO

/* ------------------------------------------------- updated_at triggers ---- */
CREATE OR ALTER TRIGGER dbo.trg_sale_items_updated_at ON dbo.sale_items AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    IF TRIGGER_NESTLEVEL(OBJECT_ID(N'dbo.trg_sale_items_updated_at')) > 1 RETURN; -- don't recurse
    UPDATE t SET updated_at = SYSUTCDATETIME()
    FROM dbo.sale_items AS t INNER JOIN inserted AS i ON i.id = t.id;
END
GO

CREATE OR ALTER TRIGGER dbo.trg_cash_accounts_updated_at ON dbo.cash_accounts AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    IF TRIGGER_NESTLEVEL(OBJECT_ID(N'dbo.trg_cash_accounts_updated_at')) > 1 RETURN;
    UPDATE t SET updated_at = SYSUTCDATETIME()
    FROM dbo.cash_accounts AS t INNER JOIN inserted AS i ON i.org_id = t.org_id;
END
GO

CREATE OR ALTER TRIGGER dbo.trg_cash_ledger_updated_at ON dbo.cash_ledger AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    IF TRIGGER_NESTLEVEL(OBJECT_ID(N'dbo.trg_cash_ledger_updated_at')) > 1 RETURN;
    UPDATE t SET updated_at = SYSUTCDATETIME()
    FROM dbo.cash_ledger AS t INNER JOIN inserted AS i ON i.id = t.id;
END
GO

/* =============================================================================
   dbo.usp_RecordSale
   Records one sale atomically: header + line items + stock decrement + cash balance + cash ledger entry.

   Input
     @org_id, @created_by       who/where (every statement below is scoped by @org_id)
     @customer_id (optional)    must belong to @org_id
     @customer_name, @category, @description   free text for the sale header
     @amount                    used ONLY when there are no items (a "quick sale", old API behaviour)
     @items                     JSON array: [{"product_id":"<guid>","quantity":2,"unit_price":9.99}, ...]
                                unit_price is optional (defaults to products.price)
     @skip_invalid_items        0 = any bad item rolls back the WHOLE sale (all-or-nothing)
                                1 = bad items are skipped (their own changes are undone with a savepoint),
                                    valid items are kept ('partial'); if NO item is valid, everything is rolled back
   Output
     @sale_id, @total, @status ('committed' | 'partial' | 'rolled_back'), @message, @error_number,
     @skipped_items (JSON array of {product_id, quantity, error_number, message}, NULL if none)
   ============================================================================= */
CREATE OR ALTER PROCEDURE dbo.usp_RecordSale
    @org_id             uniqueidentifier,
    @created_by         uniqueidentifier = NULL,
    @customer_id        uniqueidentifier = NULL,
    @customer_name      nvarchar(200)    = NULL,
    @category           nvarchar(100)    = N'general',
    @description        nvarchar(max)    = NULL,
    @amount             decimal(14,2)    = NULL,
    @items              nvarchar(max)    = NULL,
    @skip_invalid_items bit              = 0,
    @sale_id            uniqueidentifier = NULL OUTPUT,
    @total              decimal(14,2)    = NULL OUTPUT,
    @status             nvarchar(20)     = NULL OUTPUT,
    @message            nvarchar(400)    = NULL OUTPUT,
    @error_number       int              = NULL OUTPUT,
    @skipped_items      nvarchar(max)    = NULL OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    -- Any run-time error aborts the batch and dooms the transaction instead of leaving it half done.
    SET XACT_ABORT ON;

    -- Must be the FIRST thing we look at: do we own the transaction? (see header comment)
    DECLARE @own_tran     bit = CASE WHEN @@TRANCOUNT = 0 THEN 1 ELSE 0 END;
    DECLARE @tran_started bit = 0;
    DECLARE @sale_date    date = CONVERT(date, SYSUTCDATETIME());
    DECLARE @has_items    bit = 0;

    -- Result of the validation / business rules. NULL = everything fine so far.
    DECLARE @fail_number  int           = NULL;
    DECLARE @fail_message nvarchar(400) = NULL;

    -- The parsed items. seq = processing order; we sort by product_id so two concurrent sales lock
    -- products in the same order (prevents most deadlocks).
    DECLARE @lines TABLE (
        seq        int              NOT NULL PRIMARY KEY,
        product_id uniqueidentifier NULL,
        quantity   int              NULL,
        unit_price decimal(14,2)    NULL
    );
    -- Items that could not be applied (only filled when @skip_invalid_items = 1).
    DECLARE @skipped TABLE (
        seq          int              NOT NULL PRIMARY KEY,
        product_id   uniqueidentifier NULL,
        quantity     int              NULL,
        error_number int              NOT NULL,
        message      nvarchar(400)    NOT NULL
    );
    DECLARE @bal TABLE (balance decimal(16,2) NOT NULL);

    -- Loop variables
    DECLARE @i int, @n int, @ok_count int = 0;
    DECLARE @pid uniqueidentifier, @qty int, @price decimal(14,2);
    DECLARE @item_err int, @item_msg nvarchar(400), @pname nvarchar(200), @rc int;
    DECLARE @new_balance decimal(16,2);

    -- Outputs start in a defined state
    SET @sale_id = NULL; SET @total = NULL; SET @status = NULL; SET @message = NULL;
    SET @error_number = NULL; SET @skipped_items = NULL;

    BEGIN TRY
        /* ---- 1. Validate the input that needs no table access (nothing to undo yet) ------------- */
        IF @items IS NOT NULL AND ISJSON(@items) = 0
        BEGIN
            SET @fail_number = 50003; SET @fail_message = N'items must be a valid JSON array';
        END
        ELSE IF @items IS NOT NULL
        BEGIN
            -- Parse: OPENJSON(@items) yields one row per array element; the second OPENJSON reads its fields.
            INSERT INTO @lines (seq, product_id, quantity, unit_price)
            SELECT ROW_NUMBER() OVER (ORDER BY j.product_id, CAST(o.[key] AS int)),
                   j.product_id, j.quantity, j.unit_price
            FROM OPENJSON(@items) AS o
            CROSS APPLY OPENJSON(o.[value]) WITH (
                product_id uniqueidentifier '$.product_id',
                quantity   int              '$.quantity',
                unit_price decimal(14,2)    '$.unit_price'
            ) AS j;
            SET @n = (SELECT COUNT(*) FROM @lines);
            IF @n > 0 SET @has_items = 1;
        END

        IF @fail_number IS NULL AND @has_items = 0 AND (@amount IS NULL OR @amount <= 0)
        BEGIN
            SET @fail_number = 50003; SET @fail_message = N'amount must be positive when no items are given';
        END

        /* ---- 2. Open the transaction (or a savepoint when the caller already has one) ----------- */
        IF @fail_number IS NULL
        BEGIN
            IF @own_tran = 1
            BEGIN
                BEGIN TRANSACTION;
            END
            ELSE
            BEGIN
                SAVE TRANSACTION sp_record_sale;
            END
            SET @tran_started = 1;

            -- Validate against the database. Every lookup is scoped by org_id.
            IF NOT EXISTS (SELECT 1 FROM dbo.orgs WHERE id = @org_id)
            BEGIN
                SET @fail_number = 50005; SET @fail_message = N'Organisation not found';
            END
            ELSE IF @customer_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM dbo.customers WHERE id = @customer_id AND org_id = @org_id)
            BEGIN
                SET @fail_number = 50004; SET @fail_message = N'Customer not found';
            END
        END

        /* ---- 3. Sale header ---------------------------------------------------------------------- */
        IF @fail_number IS NULL
        BEGIN
            SET @sale_id = NEWID();
            -- Items sales start at 0 and are set to SUM(line_total) in step 5; quick sales use @amount.
            INSERT INTO dbo.sales (id, org_id, created_by, amount, category, customer_name, description, sale_date, customer_id)
            VALUES (@sale_id, @org_id, @created_by,
                    CASE WHEN @has_items = 1 THEN 0 ELSE @amount END,
                    COALESCE(@category, N'general'), @customer_name, @description, @sale_date, @customer_id);
        END

        /* ---- 4. Items: a cursor-less WHILE loop over @lines -------------------------------------- */
        SET @i = 1;
        WHILE @fail_number IS NULL AND @has_items = 1 AND @i <= @n
        BEGIN
            SELECT @pid = product_id, @qty = quantity, @price = unit_price FROM @lines WHERE seq = @i;
            SET @item_err = NULL; SET @item_msg = NULL; SET @pname = NULL;

            -- Savepoint for THIS item: "ROLLBACK TRANSACTION sp_item" undoes only this item's work.
            SAVE TRANSACTION sp_item;

            IF @pid IS NULL OR @qty IS NULL OR @qty <= 0
            BEGIN
                SET @item_err = 50003; SET @item_msg = N'Each item needs a product_id and a quantity greater than 0';
            END
            ELSE IF @price IS NOT NULL AND @price < 0
            BEGIN
                SET @item_err = 50003; SET @item_msg = N'unit_price must not be negative';
            END
            ELSE
            BEGIN
                -- THE race-safe stock decrement: ONE statement. The row lock is taken, the condition
                -- stock_qty >= @qty is evaluated on the committed value and the new value is written
                -- without any gap in between. Zero rows = unknown product (or other org) OR not enough stock.
                UPDATE dbo.products
                   SET stock_qty = stock_qty - @qty
                 WHERE id = @pid AND org_id = @org_id AND stock_qty >= @qty;
                SET @rc = @@ROWCOUNT;

                IF @rc = 0
                BEGIN
                    -- Only to choose the message: the decision above was already taken atomically.
                    SELECT @pname = name FROM dbo.products WHERE id = @pid AND org_id = @org_id;
                    IF @pname IS NULL
                    BEGIN
                        SET @item_err = 50002; SET @item_msg = N'Product not found';
                    END
                    ELSE
                    BEGIN
                        SET @item_err = 50001; SET @item_msg = LEFT(CONCAT(N'Not enough stock for ', @pname), 400);
                    END
                END
                ELSE
                BEGIN
                    -- Price defaults to the product's current price.
                    INSERT INTO dbo.sale_items (org_id, sale_id, product_id, quantity, unit_price)
                    SELECT @org_id, @sale_id, p.id, @qty, COALESCE(@price, p.price)
                    FROM dbo.products AS p
                    WHERE p.id = @pid AND p.org_id = @org_id;
                END
            END

            IF @item_err IS NULL
            BEGIN
                SET @ok_count += 1;
            END
            ELSE IF @skip_invalid_items = 1
            BEGIN
                -- Partial mode: undo just this item (nothing to undo for a failed UPDATE, but this is the
                -- pattern for any multi-statement item), remember it, carry on with the next one.
                ROLLBACK TRANSACTION sp_item;
                INSERT INTO @skipped (seq, product_id, quantity, error_number, message)
                VALUES (@i, @pid, @qty, @item_err, @item_msg);
            END
            ELSE
            BEGIN
                -- All-or-nothing mode: the first bad item fails the whole sale; the loop ends.
                SET @fail_number = @item_err; SET @fail_message = @item_msg;
            END

            SET @i += 1;
        END

        -- Partial mode with not a single usable item: nothing worth recording => fail with the first reason.
        IF @fail_number IS NULL AND @has_items = 1 AND @ok_count = 0
        BEGIN
            SELECT TOP (1) @fail_number = error_number, @fail_message = message FROM @skipped ORDER BY seq;
            IF @fail_number IS NULL
            BEGIN
                SET @fail_number = 50003; SET @fail_message = N'No valid items';
            END
        END

        /* ---- 5. Totals, cash balance, cash ledger ------------------------------------------------ */
        IF @fail_number IS NULL
        BEGIN
            IF @has_items = 1
            BEGIN
                SELECT @total = COALESCE(SUM(line_total), 0) FROM dbo.sale_items WHERE sale_id = @sale_id AND org_id = @org_id;
                UPDATE dbo.sales SET amount = @total WHERE id = @sale_id AND org_id = @org_id;
            END
            ELSE
                SET @total = @amount;

            -- Create the org's cash account the first time. UPDLOCK + HOLDLOCK lock the (empty) key range, so two
            -- concurrent first sales cannot both insert (second one waits, then sees the row).
            INSERT INTO dbo.cash_accounts (org_id, balance)
            SELECT @org_id, 0
            WHERE NOT EXISTS (SELECT 1 FROM dbo.cash_accounts WITH (UPDLOCK, HOLDLOCK) WHERE org_id = @org_id);

            -- Atomic read-modify-write of the balance in one statement; OUTPUT .. INTO because of the trigger (error 334).
            UPDATE dbo.cash_accounts
               SET balance = balance + @total
            OUTPUT INSERTED.balance INTO @bal (balance)
             WHERE org_id = @org_id;
            SELECT TOP (1) @new_balance = balance FROM @bal;

            INSERT INTO dbo.cash_ledger (org_id, entry_type, amount, ref_type, ref_id, balance_after, entry_date, created_by)
            VALUES (@org_id, N'sale', @total, N'sale', @sale_id, @new_balance, @sale_date, @created_by);
        END

        /* ---- 6. Decide: commit, or undo everything this procedure did --------------------------- */
        IF @fail_number IS NULL
        BEGIN
            IF @own_tran = 1 COMMIT TRANSACTION;   -- when nested, the caller commits (see header)
            SET @status = CASE WHEN EXISTS (SELECT 1 FROM @skipped) THEN N'partial' ELSE N'committed' END;
            IF @status = N'partial'
            BEGIN
                SET @message = CONCAT(N'Sale recorded; ', (SELECT COUNT(*) FROM @skipped), N' item(s) skipped');
                SET @skipped_items = (SELECT product_id, quantity, error_number, message AS reason
                                      FROM @skipped ORDER BY seq FOR JSON PATH);
            END
            ELSE
                SET @message = N'Sale recorded';
        END
        ELSE
        BEGIN
            IF @tran_started = 1
            BEGIN
                IF @own_tran = 1
                BEGIN
                    ROLLBACK TRANSACTION;
                END
                ELSE
                BEGIN
                    ROLLBACK TRANSACTION sp_record_sale;   -- caller's earlier work survives
                END
            END
            SET @status = N'rolled_back'; SET @error_number = @fail_number; SET @message = @fail_message;
            SET @sale_id = NULL; SET @total = NULL;
        END
    END TRY
    BEGIN CATCH
        -- Unexpected engine error (deadlock victim 1205, constraint 547, conversion error, ...).
        -- XACT_STATE(): 1 = active and committable, -1 = doomed (only a FULL rollback is allowed), 0 = none.
        SET @error_number = ERROR_NUMBER();
        SET @message = LEFT(ERROR_MESSAGE(), 400);
        IF XACT_STATE() = -1
            ROLLBACK TRANSACTION;                 -- full rollback, even if the caller had a transaction
        ELSE IF XACT_STATE() = 1 AND @tran_started = 1
        BEGIN
            IF @own_tran = 1
            BEGIN
                ROLLBACK TRANSACTION;
            END
            ELSE
            BEGIN
                ROLLBACK TRANSACTION sp_record_sale;
            END
        END
        SET @status = N'rolled_back';
        SET @sale_id = NULL; SET @total = NULL; SET @skipped_items = NULL;
    END CATCH
END
GO

/* =============================================================================
   dbo.usp_VoidSale
   Cancels (deletes) a sale atomically: stock goes back, a reversing 'sale_void' entry is posted, the cash
   balance is reduced by what the sale had posted, then the sale (and its items) is deleted.
   Scoped by id AND org_id: an unknown or foreign sale gives @status = 'not_found' (the API answers 404).
   Output @status: 'voided' | 'not_found' | 'rolled_back'.
   ============================================================================= */
CREATE OR ALTER PROCEDURE dbo.usp_VoidSale
    @org_id       uniqueidentifier,
    @sale_id      uniqueidentifier,
    @voided_by    uniqueidentifier = NULL,
    @status       nvarchar(20)     = NULL OUTPUT,
    @message      nvarchar(400)    = NULL OUTPUT,
    @error_number int              = NULL OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @own_tran bit = CASE WHEN @@TRANCOUNT = 0 THEN 1 ELSE 0 END;   -- see usp_RecordSale
    DECLARE @tran_started bit = 0;
    DECLARE @found uniqueidentifier = NULL;
    DECLARE @posted decimal(14,2);
    DECLARE @bal TABLE (balance decimal(16,2) NOT NULL);
    DECLARE @new_balance decimal(16,2);

    SET @status = NULL; SET @message = NULL; SET @error_number = NULL;

    BEGIN TRY
        IF @own_tran = 1
        BEGIN
            BEGIN TRANSACTION;
        END
        ELSE
        BEGIN
            SAVE TRANSACTION sp_void_sale;
        END
        SET @tran_started = 1;

        -- Lock the sale row first (UPDLOCK): a concurrent void of the same sale waits here and then finds nothing.
        SELECT @found = id FROM dbo.sales WITH (UPDLOCK, HOLDLOCK) WHERE id = @sale_id AND org_id = @org_id;

        IF @found IS NULL
        BEGIN
            IF @own_tran = 1
            BEGIN
                ROLLBACK TRANSACTION;
            END
            ELSE
            BEGIN
                ROLLBACK TRANSACTION sp_void_sale;
            END
            SET @status = N'not_found'; SET @error_number = 50006; SET @message = N'Sale not found';
        END
        ELSE
        BEGIN
            -- 1. Give the stock back: one set-based statement over this sale's items.
            UPDATE p
               SET p.stock_qty = p.stock_qty + s.qty
              FROM dbo.products AS p
              INNER JOIN (SELECT product_id, SUM(quantity) AS qty
                            FROM dbo.sale_items
                           WHERE sale_id = @sale_id AND org_id = @org_id
                           GROUP BY product_id) AS s ON s.product_id = p.id
             WHERE p.org_id = @org_id;

            -- 2. Reverse exactly what was posted to the cash ledger for this sale: the 'sale' entry PLUS any 'adjustment'
            --    entries (F4: usp_AdjustEntryAmount posts the delta of an amount edit). Sales created before the cash
            --    ledger existed are reversed by what was really posted (possibly nothing).
            SELECT @posted = SUM(amount) FROM dbo.cash_ledger
             WHERE org_id = @org_id AND ref_type = N'sale' AND ref_id = @sale_id AND entry_type IN (N'sale', N'adjustment');

            IF @posted IS NOT NULL AND @posted <> 0
            BEGIN
                INSERT INTO dbo.cash_accounts (org_id, balance)
                SELECT @org_id, 0
                WHERE NOT EXISTS (SELECT 1 FROM dbo.cash_accounts WITH (UPDLOCK, HOLDLOCK) WHERE org_id = @org_id);

                UPDATE dbo.cash_accounts
                   SET balance = balance - @posted
                OUTPUT INSERTED.balance INTO @bal (balance)
                 WHERE org_id = @org_id;
                SELECT TOP (1) @new_balance = balance FROM @bal;

                INSERT INTO dbo.cash_ledger (org_id, entry_type, amount, ref_type, ref_id, balance_after, created_by)
                VALUES (@org_id, N'sale_void', -@posted, N'sale', @sale_id, @new_balance, @voided_by);
            END

            -- 3. Delete the sale. Items are removed explicitly (the FK would also cascade).
            DELETE FROM dbo.sale_items WHERE sale_id = @sale_id AND org_id = @org_id;
            DELETE FROM dbo.sales WHERE id = @sale_id AND org_id = @org_id;

            IF @own_tran = 1 COMMIT TRANSACTION;
            SET @status = N'voided'; SET @message = N'Sale voided';
        END
    END TRY
    BEGIN CATCH
        SET @error_number = ERROR_NUMBER();
        SET @message = LEFT(ERROR_MESSAGE(), 400);
        IF XACT_STATE() = -1
            ROLLBACK TRANSACTION;
        ELSE IF XACT_STATE() = 1 AND @tran_started = 1
        BEGIN
            IF @own_tran = 1
            BEGIN
                ROLLBACK TRANSACTION;
            END
            ELSE
            BEGIN
                ROLLBACK TRANSACTION sp_void_sale;
            END
        END
        SET @status = N'rolled_back';
    END CATCH
END
GO
