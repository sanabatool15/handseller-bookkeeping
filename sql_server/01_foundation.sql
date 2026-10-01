/* =============================================================================
   01_foundation.sql  --  Handseller Bookkeeping, SQL Server (T-SQL)
   Adds: database HandsellerDB, tables orgs + users, idx_users_org_id,
         AFTER UPDATE triggers that maintain updated_at.
   Port of api/sql/schema.sql (Supabase/Postgres). Re-runnable: run it as often as
   you like in SSMS; nothing is dropped.

   Design notes
   * Circular FK: orgs.owner_id -> users.id and users.org_id -> orgs.id. Postgres used
     a DEFERRABLE FK; SQL Server has none, so BOTH columns are NULLable and the app
     registers in one transaction: INSERT user (org_id NULL) -> INSERT org (owner_id)
     -> UPDATE users SET org_id. (Rolled back as a whole on any failure.)
   * users.email is UNIQUE (the real guard against duplicate registration races).
     Default collation is case-insensitive, so Bob@x.com == bob@x.com (the old
     Postgres column was case-sensitive; see api/specs/17-open-questions.md).
   * NO Row Level Security here. SQL Server RLS needs SESSION_CONTEXT plumbing and
     the Postgres RLS policies were never the real control anyway (api/specs/10 #5):
     the application layer (id AND org_id in every statement, enforced by
     tests/unit/test_repository_sql_rules.py) is the primary tenancy control.
   * Because the tables have AFTER UPDATE triggers, repository code uses
     `OUTPUT ... INTO @table` + SELECT instead of bare `OUTPUT INSERTED.*`
     (SQL Server error 334 otherwise).
   ============================================================================= */

IF DB_ID(N'HandsellerDB') IS NULL
BEGIN
    CREATE DATABASE HandsellerDB;
END
GO

USE HandsellerDB;
GO

/* ---------------------------------------------------------------- orgs ---- */
IF OBJECT_ID(N'dbo.orgs', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.orgs (
        id         uniqueidentifier NOT NULL CONSTRAINT DF_orgs_id DEFAULT NEWID() CONSTRAINT PK_orgs PRIMARY KEY,
        name       nvarchar(200)    NOT NULL,
        owner_id   uniqueidentifier NULL,      -- FK to users added below (circular)
        created_at datetimeoffset   NOT NULL CONSTRAINT DF_orgs_created_at DEFAULT SYSUTCDATETIME(),
        updated_at datetimeoffset   NOT NULL CONSTRAINT DF_orgs_updated_at DEFAULT SYSUTCDATETIME()
    );
END
GO

/* --------------------------------------------------------------- users ---- */
IF OBJECT_ID(N'dbo.users', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.users (
        id              uniqueidentifier NOT NULL CONSTRAINT DF_users_id DEFAULT NEWID() CONSTRAINT PK_users PRIMARY KEY,
        org_id          uniqueidentifier NULL CONSTRAINT FK_users_org REFERENCES dbo.orgs(id),
        email           nvarchar(320)    NOT NULL CONSTRAINT UQ_users_email UNIQUE,
        full_name       nvarchar(200)    NULL,
        hashed_password nvarchar(255)    NOT NULL,
        role            nvarchar(20)     NOT NULL CONSTRAINT DF_users_role DEFAULT N'member', -- owner | admin | member
        created_at      datetimeoffset   NOT NULL CONSTRAINT DF_users_created_at DEFAULT SYSUTCDATETIME(),
        updated_at      datetimeoffset   NOT NULL CONSTRAINT DF_users_updated_at DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_orgs_owner')
BEGIN
    ALTER TABLE dbo.orgs ADD CONSTRAINT FK_orgs_owner FOREIGN KEY (owner_id) REFERENCES dbo.users(id);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_users_org_id' AND object_id = OBJECT_ID(N'dbo.users'))
BEGIN
    CREATE INDEX idx_users_org_id ON dbo.users(org_id);
END
GO

/* ------------------------------------------------- updated_at triggers ---- */
CREATE OR ALTER TRIGGER dbo.trg_orgs_updated_at ON dbo.orgs AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    IF TRIGGER_NESTLEVEL(OBJECT_ID(N'dbo.trg_orgs_updated_at')) > 1 RETURN; -- don't recurse
    UPDATE o SET updated_at = SYSUTCDATETIME()
    FROM dbo.orgs AS o INNER JOIN inserted AS i ON i.id = o.id;
END
GO

CREATE OR ALTER TRIGGER dbo.trg_users_updated_at ON dbo.users AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    IF TRIGGER_NESTLEVEL(OBJECT_ID(N'dbo.trg_users_updated_at')) > 1 RETURN;
    UPDATE u SET updated_at = SYSUTCDATETIME()
    FROM dbo.users AS u INNER JOIN inserted AS i ON i.id = u.id;
END
GO
