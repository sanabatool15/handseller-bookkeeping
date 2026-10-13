/* =============================================================================
   08_idempotency.sql  --  Handseller Bookkeeping, SQL Server (T-SQL)
   Adds: table dbo.idempotency_keys (replaces Redis).

   What it is for
   * Every POST/PUT/PATCH from the app carries an "Idempotency-Key" header. The API stores the answer under that key,
     so if the same request is sent twice (double click, retry) the second call gets the saved answer and nothing
     is done twice.
   * state 'processing' = a request with this key is running right now. 'done' = the answer is saved.
   * Old rows are ignored once they are older than IDEMPOTENCY_TTL_SECONDS (default 24 hours).
   Re-runnable: the table is created only if it is missing.
   ============================================================================= */

USE HandsellerDB;
GO

IF OBJECT_ID(N'dbo.idempotency_keys', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.idempotency_keys (
        org_scope     nvarchar(64)   NOT NULL,   -- the business (org id) the key belongs to
        idem_key      nvarchar(200)  NOT NULL,   -- the Idempotency-Key header value
        state         nvarchar(12)   NOT NULL CONSTRAINT CK_idempotency_state CHECK (state IN (N'processing', N'done')),
        status_code   int            NULL,
        response_body nvarchar(max)  NULL,
        created_at    datetimeoffset NOT NULL CONSTRAINT DF_idempotency_created_at DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_idempotency_keys PRIMARY KEY (org_scope, idem_key)
    );
END
GO
