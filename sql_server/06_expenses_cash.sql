/* =============================================================================
   06_expenses_cash.sql  --  Handseller Bookkeeping, SQL Server (T-SQL)
   Adds: 'expense_void' to the cash_ledger.entry_type CHECK (CK_cash_ledger_entry_type),
         stored procedures dbo.usp_RecordExpense, dbo.usp_VoidExpense, dbo.usp_AdjustEntryAmount.
   Requires 01..05 (05 must be the F4 version: usp_VoidSale also reverses 'adjustment' entries - re-run 05 first).
   Re-runnable: the constraint is only replaced when it does not yet allow 'expense_void'; procedures use CREATE OR ALTER.

   WHAT THIS SLICE DOES
   Expenses now move cash exactly like sales do (see 05 for the full explanation of the transaction pattern):
        expenses  ->  cash_accounts.balance (decrement)  ->  cash_ledger ('expense', NEGATIVE amount).
   All in ONE transaction. The procedures follow the same textbook structure as usp_RecordSale:
     * @own_tran = 1 when called without an open transaction (SSMS): BEGIN TRANSACTION ... COMMIT.
       @own_tran = 0 when called inside the API connection's implicit transaction: SAVE TRANSACTION, no COMMIT,
       failure rolls back to the savepoint only (the caller's earlier work survives).
     * Business failures are OUTPUT values (@status / @error_number / @message), never raised errors
       (a raised error + XACT_ABORT ON would doom the caller's transaction). Business numbers:
         50003 validation, 50005 organisation not found, 50006 sale not found, 50007 expense not found,
         50008 not allowed (amount of a sale WITH line items cannot be edited).
       Any other number came from the engine (1205 deadlock victim, 547 constraint, ...): technical error.
     * Every statement on a tenant table is scoped by org_id.

   DESIGN DECISION: the cash balance MAY GO NEGATIVE.
   A handseller often pays for stock, a stall fee or packaging BEFORE cashing up, so an expense is never refused
   because "not enough cash". cash_accounts.balance has no CHECK (balance >= 0) on purpose; balance == SUM(ledger.amount).
   ============================================================================= */

USE HandsellerDB;
GO

/* ---- widen CK_cash_ledger_entry_type: allow 'expense_void' (the reversal of an expense) ------------------------ */
-- CHECK constraints cannot be altered: drop + re-create. Guarded so a second run changes nothing.
IF EXISTS (SELECT 1 FROM sys.check_constraints
            WHERE name = N'CK_cash_ledger_entry_type' AND parent_object_id = OBJECT_ID(N'dbo.cash_ledger')
              AND definition NOT LIKE N'%expense_void%')
BEGIN
    ALTER TABLE dbo.cash_ledger DROP CONSTRAINT CK_cash_ledger_entry_type;
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints
                WHERE name = N'CK_cash_ledger_entry_type' AND parent_object_id = OBJECT_ID(N'dbo.cash_ledger'))
BEGIN
    ALTER TABLE dbo.cash_ledger ADD CONSTRAINT CK_cash_ledger_entry_type
        CHECK (entry_type IN (N'sale', N'sale_void', N'expense', N'expense_void', N'adjustment'));
END
GO

/* =============================================================================
   dbo.usp_RecordExpense
   Records one expense atomically: expense row + cash balance decrement + 'expense' ledger entry (negative amount).
   Input   @org_id, @created_by, @amount (> 0), @category, @voucher_reference, @description,
           @expense_date (NULL = today, UTC)
   Output  @expense_id, @status ('committed' | 'rolled_back'), @message, @error_number
   ============================================================================= */
CREATE OR ALTER PROCEDURE dbo.usp_RecordExpense
    @org_id            uniqueidentifier,
    @created_by        uniqueidentifier = NULL,
    @amount            decimal(14,2),
    @category          nvarchar(100)    = N'general',
    @voucher_reference nvarchar(200)    = NULL,
    @description       nvarchar(max)    = NULL,
    @expense_date      date             = NULL,
    @expense_id        uniqueidentifier = NULL OUTPUT,
    @status            nvarchar(20)     = NULL OUTPUT,
    @message           nvarchar(400)    = NULL OUTPUT,
    @error_number      int              = NULL OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    -- Must be the FIRST thing we look at: do we own the transaction? (see 05 and specs/15)
    DECLARE @own_tran     bit = CASE WHEN @@TRANCOUNT = 0 THEN 1 ELSE 0 END;
    DECLARE @tran_started bit = 0;
    DECLARE @fail_number  int           = NULL;
    DECLARE @fail_message nvarchar(400) = NULL;
    DECLARE @bal TABLE (balance decimal(16,2) NOT NULL);
    DECLARE @new_balance decimal(16,2);
    DECLARE @date date = COALESCE(@expense_date, CONVERT(date, SYSUTCDATETIME()));

    SET @expense_id = NULL; SET @status = NULL; SET @message = NULL; SET @error_number = NULL;

    BEGIN TRY
        /* ---- 1. Validate what needs no table access ------------------------------------------------ */
        IF @amount IS NULL OR @amount <= 0
        BEGIN
            SET @fail_number = 50003; SET @fail_message = N'amount must be positive';
        END

        /* ---- 2. Open the transaction (or a savepoint inside the caller's transaction) ------------ */
        IF @fail_number IS NULL
        BEGIN
            IF @own_tran = 1
            BEGIN
                BEGIN TRANSACTION;
            END
            ELSE
            BEGIN
                SAVE TRANSACTION sp_record_expense;
            END
            SET @tran_started = 1;

            IF NOT EXISTS (SELECT 1 FROM dbo.orgs WHERE id = @org_id)
            BEGIN
                SET @fail_number = 50005; SET @fail_message = N'Organisation not found';
            END
        END

        /* ---- 3. Expense row, cash balance, cash ledger --------------------------------------------- */
        IF @fail_number IS NULL
        BEGIN
            SET @expense_id = NEWID();
            INSERT INTO dbo.expenses (id, org_id, created_by, amount, category, voucher_reference, description, expense_date)
            VALUES (@expense_id, @org_id, @created_by, @amount, COALESCE(@category, N'general'),
                    @voucher_reference, @description, @date);

            -- First expense/sale of an org creates its cash account. UPDLOCK + HOLDLOCK lock the (empty) key range so two
            -- concurrent first postings cannot both insert (see 05).
            INSERT INTO dbo.cash_accounts (org_id, balance)
            SELECT @org_id, 0
            WHERE NOT EXISTS (SELECT 1 FROM dbo.cash_accounts WITH (UPDLOCK, HOLDLOCK) WHERE org_id = @org_id);

            -- Atomic read-modify-write of the balance in ONE statement (no SELECT-then-UPDATE gap).
            -- OUTPUT .. INTO because the table has an AFTER UPDATE trigger (error 334 otherwise).
            -- No "balance >= amount" guard: a negative balance is allowed (see header).
            UPDATE dbo.cash_accounts
               SET balance = balance - @amount
            OUTPUT INSERTED.balance INTO @bal (balance)
             WHERE org_id = @org_id;
            SELECT TOP (1) @new_balance = balance FROM @bal;

            INSERT INTO dbo.cash_ledger (org_id, entry_type, amount, ref_type, ref_id, balance_after, entry_date, created_by)
            VALUES (@org_id, N'expense', -@amount, N'expense', @expense_id, @new_balance, @date, @created_by);
        END

        /* ---- 4. Commit, or undo everything this procedure did ------------------------------------- */
        IF @fail_number IS NULL
        BEGIN
            IF @own_tran = 1 COMMIT TRANSACTION;   -- when nested, the caller commits
            SET @status = N'committed'; SET @message = N'Expense recorded';
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
                    ROLLBACK TRANSACTION sp_record_expense;   -- caller's earlier work survives
                END
            END
            SET @status = N'rolled_back'; SET @error_number = @fail_number; SET @message = @fail_message;
            SET @expense_id = NULL;
        END
    END TRY
    BEGIN CATCH
        -- Engine error (deadlock victim 1205, constraint 547, conversion/overflow ...).
        -- XACT_STATE(): 1 = committable, -1 = doomed (full rollback only), 0 = no transaction.
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
                ROLLBACK TRANSACTION sp_record_expense;
            END
        END
        SET @status = N'rolled_back';
        SET @expense_id = NULL;
    END CATCH
END
GO

/* =============================================================================
   dbo.usp_VoidExpense
   Deletes an expense atomically and gives the money back: a reversing 'expense_void' entry (positive) is posted
   and the balance goes up by what the expense had taken (its 'expense' entry plus any 'adjustment' entries).
   Scoped by id AND org_id: an unknown or foreign expense gives @status = 'not_found' (the API answers 404).
   Output @status: 'voided' | 'not_found' | 'rolled_back'.
   ============================================================================= */
CREATE OR ALTER PROCEDURE dbo.usp_VoidExpense
    @org_id       uniqueidentifier,
    @expense_id   uniqueidentifier,
    @voided_by    uniqueidentifier = NULL,
    @status       nvarchar(20)     = NULL OUTPUT,
    @message      nvarchar(400)    = NULL OUTPUT,
    @error_number int              = NULL OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @own_tran bit = CASE WHEN @@TRANCOUNT = 0 THEN 1 ELSE 0 END;   -- see usp_RecordExpense
    DECLARE @tran_started bit = 0;
    DECLARE @found uniqueidentifier = NULL;
    DECLARE @posted decimal(14,2);          -- signed sum of what the ledger recorded for this expense (negative = money out)
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
            SAVE TRANSACTION sp_void_expense;
        END
        SET @tran_started = 1;

        -- Lock the expense row first (UPDLOCK, HOLDLOCK): a concurrent void of the same expense waits here, then finds nothing.
        SELECT @found = id FROM dbo.expenses WITH (UPDLOCK, HOLDLOCK) WHERE id = @expense_id AND org_id = @org_id;

        IF @found IS NULL
        BEGIN
            IF @own_tran = 1
            BEGIN
                ROLLBACK TRANSACTION;
            END
            ELSE
            BEGIN
                ROLLBACK TRANSACTION sp_void_expense;
            END
            SET @status = N'not_found'; SET @error_number = 50007; SET @message = N'Expense not found';
        END
        ELSE
        BEGIN
            -- Reverse exactly what was posted for this expense (expenses recorded before F4 posted nothing: no entry, no change).
            SELECT @posted = SUM(amount) FROM dbo.cash_ledger
             WHERE org_id = @org_id AND ref_type = N'expense' AND ref_id = @expense_id
               AND entry_type IN (N'expense', N'adjustment');

            IF @posted IS NOT NULL AND @posted <> 0
            BEGIN
                INSERT INTO dbo.cash_accounts (org_id, balance)
                SELECT @org_id, 0
                WHERE NOT EXISTS (SELECT 1 FROM dbo.cash_accounts WITH (UPDLOCK, HOLDLOCK) WHERE org_id = @org_id);

                UPDATE dbo.cash_accounts
                   SET balance = balance - @posted        -- @posted is negative, so the balance goes UP
                OUTPUT INSERTED.balance INTO @bal (balance)
                 WHERE org_id = @org_id;
                SELECT TOP (1) @new_balance = balance FROM @bal;

                INSERT INTO dbo.cash_ledger (org_id, entry_type, amount, ref_type, ref_id, balance_after, created_by)
                VALUES (@org_id, N'expense_void', -@posted, N'expense', @expense_id, @new_balance, @voided_by);
            END

            DELETE FROM dbo.expenses WHERE id = @expense_id AND org_id = @org_id;

            IF @own_tran = 1 COMMIT TRANSACTION;
            SET @status = N'voided'; SET @message = N'Expense voided';
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
                ROLLBACK TRANSACTION sp_void_expense;
            END
        END
        SET @status = N'rolled_back';
    END CATCH
END
GO

/* =============================================================================
   dbo.usp_AdjustEntryAmount
   Changes the amount of a sale or an expense and posts the DIFFERENCE to the cash ledger, in ONE transaction:
        sales.amount / expenses.amount := @new_amount
        cash_accounts.balance          += delta        (sale: +delta, expense: -delta; delta = new - old)
        cash_ledger  'adjustment' entry with the signed effect on cash and the new balance
   so balance == SUM(ledger.amount) keeps holding after an edit.
   A sale WITH line items is refused (@status = 'not_allowed'): its amount is the sum of its items.
   Input   @org_id, @ref_type ('sale' | 'expense'), @ref_id, @new_amount (> 0), @adjusted_by
   Output  @status: 'adjusted' | 'unchanged' (same amount, nothing posted) | 'not_found' | 'not_allowed' | 'rolled_back'
           @message, @error_number (extra OUTPUT; 50003 validation, 50006 sale / 50007 expense not found, 50008 not allowed)
   ============================================================================= */
CREATE OR ALTER PROCEDURE dbo.usp_AdjustEntryAmount
    @org_id       uniqueidentifier,
    @ref_type     nvarchar(20),
    @ref_id       uniqueidentifier,
    @new_amount   decimal(14,2),
    @adjusted_by  uniqueidentifier = NULL,
    @status       nvarchar(20)     = NULL OUTPUT,
    @message      nvarchar(400)    = NULL OUTPUT,
    @error_number int              = NULL OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @own_tran     bit = CASE WHEN @@TRANCOUNT = 0 THEN 1 ELSE 0 END;   -- see usp_RecordExpense
    DECLARE @tran_started bit = 0;
    DECLARE @fail_status  nvarchar(20)  = NULL;
    DECLARE @fail_number  int           = NULL;
    DECLARE @fail_message nvarchar(400) = NULL;
    DECLARE @old_amount   decimal(14,2) = NULL;
    DECLARE @delta        decimal(16,2) = 0;     -- new - old
    DECLARE @signed       decimal(16,2) = 0;     -- effect on cash: sale +delta, expense -delta
    DECLARE @bal TABLE (balance decimal(16,2) NOT NULL);
    DECLARE @new_balance  decimal(16,2);

    SET @status = NULL; SET @message = NULL; SET @error_number = NULL;

    BEGIN TRY
        /* ---- 1. Validate what needs no table access ------------------------------------------------ */
        IF @ref_type IS NULL OR @ref_type NOT IN (N'sale', N'expense')
        BEGIN
            SET @fail_status = N'rolled_back'; SET @fail_number = 50003; SET @fail_message = N'ref_type must be sale or expense';
        END
        ELSE IF @new_amount IS NULL OR @new_amount <= 0
        BEGIN
            SET @fail_status = N'rolled_back'; SET @fail_number = 50003; SET @fail_message = N'amount must be positive';
        END

        /* ---- 2. Transaction / savepoint ------------------------------------------------------------- */
        IF @fail_number IS NULL
        BEGIN
            IF @own_tran = 1
            BEGIN
                BEGIN TRANSACTION;
            END
            ELSE
            BEGIN
                SAVE TRANSACTION sp_adjust_entry;
            END
            SET @tran_started = 1;

            -- Read the CURRENT amount with an update lock (UPDLOCK, HOLDLOCK) so two concurrent adjustments of the same row
            -- queue here and each computes its delta from the committed value of the other. Scoped by id AND org_id.
            IF @ref_type = N'sale'
            BEGIN
                SELECT @old_amount = amount FROM dbo.sales WITH (UPDLOCK, HOLDLOCK) WHERE id = @ref_id AND org_id = @org_id;
                IF @old_amount IS NULL
                BEGIN
                    SET @fail_status = N'not_found'; SET @fail_number = 50006; SET @fail_message = N'Sale not found';
                END
                ELSE IF EXISTS (SELECT 1 FROM dbo.sale_items WHERE sale_id = @ref_id AND org_id = @org_id)
                BEGIN
                    SET @fail_status = N'not_allowed'; SET @fail_number = 50008;
                    SET @fail_message = N'The amount of a sale with line items cannot be changed (it is the sum of its items)';
                END
            END
            ELSE
            BEGIN
                SELECT @old_amount = amount FROM dbo.expenses WITH (UPDLOCK, HOLDLOCK) WHERE id = @ref_id AND org_id = @org_id;
                IF @old_amount IS NULL
                BEGIN
                    SET @fail_status = N'not_found'; SET @fail_number = 50007; SET @fail_message = N'Expense not found';
                END
            END
        END

        /* ---- 3. Amount, balance, ledger (only when the amount really changes) ----------------------- */
        IF @fail_number IS NULL
        BEGIN
            SET @delta = @new_amount - @old_amount;
            IF @delta <> 0
            BEGIN
                IF @ref_type = N'sale'
                BEGIN
                    UPDATE dbo.sales SET amount = @new_amount WHERE id = @ref_id AND org_id = @org_id;
                    SET @signed = @delta;
                END
                ELSE
                BEGIN
                    UPDATE dbo.expenses SET amount = @new_amount WHERE id = @ref_id AND org_id = @org_id;
                    SET @signed = -@delta;
                END

                INSERT INTO dbo.cash_accounts (org_id, balance)
                SELECT @org_id, 0
                WHERE NOT EXISTS (SELECT 1 FROM dbo.cash_accounts WITH (UPDLOCK, HOLDLOCK) WHERE org_id = @org_id);

                UPDATE dbo.cash_accounts
                   SET balance = balance + @signed
                OUTPUT INSERTED.balance INTO @bal (balance)
                 WHERE org_id = @org_id;
                SELECT TOP (1) @new_balance = balance FROM @bal;

                INSERT INTO dbo.cash_ledger (org_id, entry_type, amount, ref_type, ref_id, balance_after, created_by)
                VALUES (@org_id, N'adjustment', @signed, @ref_type, @ref_id, @new_balance, @adjusted_by);
            END
        END

        /* ---- 4. Commit, or undo ---------------------------------------------------------------------- */
        IF @fail_number IS NULL
        BEGIN
            IF @own_tran = 1 COMMIT TRANSACTION;
            IF @delta = 0
            BEGIN
                SET @status = N'unchanged'; SET @message = N'Amount unchanged';
            END
            ELSE
            BEGIN
                SET @status = N'adjusted'; SET @message = N'Amount adjusted';
            END
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
                    ROLLBACK TRANSACTION sp_adjust_entry;
                END
            END
            SET @status = @fail_status; SET @error_number = @fail_number; SET @message = @fail_message;
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
                ROLLBACK TRANSACTION sp_adjust_entry;
            END
        END
        SET @status = N'rolled_back';
    END CATCH
END
GO
