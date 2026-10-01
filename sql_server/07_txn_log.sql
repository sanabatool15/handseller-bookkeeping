/* =============================================================================
   07_txn_log.sql  --  Handseller Bookkeeping, SQL Server (T-SQL)
   Adds: table dbo.txn_log (transaction event log) + idx_txn_log_org_id (org_id, created_at DESC)
         + idx_txn_log_org_request (org_id, request_id).
   Requires 01_foundation.sql. Re-runnable: nothing is dropped, the table/indexes are created only if missing.

   What it is for (the demo layer of the course project, see api/specs/15 and api/specs/16)
   * The API appends one row per transaction EVENT of an instrumented request (record/void sale, record/void expense,
     amount adjustment, and the DB Lab demos): txn_started, lock_wait_suspected, deadlock_1205_caught,
     lock_timeout_caught, retry_triggered, rolled_back, committed, business_rejected.
   * The Activity page groups the rows by request_id (one row per request, GROUP BY) and shows the timeline of one request.

   Design notes / deliberate deviations from the other tables (also in api/specs/17)
   * APPEND-ONLY: rows are only ever inserted, never updated, so there is NO updated_at column and NO trigger
     (the convention of 01..06 exists to track edits). There is no created_by either: the log describes technical
     events of a request, not user-authored data; the org is what scopes it.
   * org_id is NOT NULL with a FK to orgs and is part of both indexes; every statement in the repository carries
     org_id (a tenant never sees another tenant's events).
   * IDENTITY bigint key: gives a cheap, strictly increasing tiebreaker for events with the same timestamp.
   * The rows are written by the API on a SEPARATE autocommit connection AFTER the business transaction ended, so a
     rolled-back request still leaves its log. If they were written inside the business transaction they would be
     rolled back together with it - exactly the rows we want to keep.
   * created_at is supplied by the application (the moment the event happened, UTC); the default only covers manual
     inserts from SSMS.
   * step is restricted by a CHECK. 'lock_wait_suspected' is INFERRED by the application from the elapsed time of a call
     (it is not read from SQL Server's lock manager); the column values never claim more than that.
   * Rows are never deleted by the application. Prune old rows by hand if the table grows (see api/specs/17).
   * OPTIONAL, for the DB Lab 'SNAPSHOT' isolation choice only (not run by this script, it changes the database):
         ALTER DATABASE HandsellerDB SET ALLOW_SNAPSHOT_ISOLATION ON;
     Without it, choosing SNAPSHOT in the lab fails with error 3952 and the lab reports a rolled_back client.
   * No Row Level Security (same decision as 01..06): the application layer (org_id in every statement) is the control.
   ============================================================================= */

USE HandsellerDB;
GO

IF OBJECT_ID(N'dbo.txn_log', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.txn_log (
        id              bigint           IDENTITY(1,1) NOT NULL CONSTRAINT PK_txn_log PRIMARY KEY,
        request_id      nvarchar(64)     NOT NULL,
        org_id          uniqueidentifier NOT NULL CONSTRAINT FK_txn_log_org REFERENCES dbo.orgs(id),
        operation       nvarchar(60)     NOT NULL,   -- e.g. 'record_sale', 'void_sale', 'lab_deadlock'
        step            nvarchar(40)     NOT NULL
                        CONSTRAINT CK_txn_log_step CHECK (step IN (
                            N'txn_started', N'lock_wait_suspected', N'deadlock_1205_caught', N'lock_timeout_caught',
                            N'retry_triggered', N'rolled_back', N'committed', N'business_rejected')),
        isolation_level nvarchar(24)     NULL,       -- effective level of the business connection, e.g. 'READ COMMITTED'
        status          nvarchar(20)     NULL,       -- step-level label: started, committed, rolled_back, rejected, error, retrying, suspected
        error_number    int              NULL,       -- SQL Server error (1205, 1222, ...) or procedure business number (50001, ...)
        message         nvarchar(400)    NULL,
        duration_ms     int              NULL,       -- of the attempt (error/suspect events) or of the whole request (committed/rolled_back)
        retry_no        int              NOT NULL CONSTRAINT DF_txn_log_retry_no DEFAULT 0 CONSTRAINT CK_txn_log_retry_no CHECK (retry_no >= 0),
        created_at      datetimeoffset   NOT NULL CONSTRAINT DF_txn_log_created_at DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_txn_log_org_id' AND object_id = OBJECT_ID(N'dbo.txn_log'))
BEGIN
    CREATE INDEX idx_txn_log_org_id ON dbo.txn_log (org_id, created_at DESC);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_txn_log_org_request' AND object_id = OBJECT_ID(N'dbo.txn_log'))
BEGIN
    CREATE INDEX idx_txn_log_org_request ON dbo.txn_log (org_id, request_id);
END
GO
