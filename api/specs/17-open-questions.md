# Open questions (SQL Server migration)

1. **OUTPUT INSERTED.* vs triggers.** Why unsure: the brief says `OUTPUT INSERTED.*`, but tables with
   enabled triggers reject OUTPUT without INTO (error 334) and every table gets an updated_at trigger.
   Assumed: use `OUTPUT ... INTO @table` + SELECT everywhere (see spec 13). Alternative: drop triggers
   and set `updated_at` in UPDATE statements. Later slices need to know.
2. **Email case sensitivity.** Postgres `users.email` was case-sensitive; SQL Server's default collation is
   case-insensitive, so `A@x.com` and `a@x.com` now collide. Assumed this is desirable; emails are not lower-cased by the app.
3. **Register is one transaction, owned by the service via `repository.base.transaction`.** The `get_sql_db`
   dependency would also commit at request end; assumed explicit transaction in the service is clearer and
   keeps atomicity independent of how the Db was obtained.
4. **`updated_at` returned from `set_user_org` is pre-trigger** (OUTPUT INTO captures INSERTED before the AFTER trigger fires). Assumed harmless.
5. **Unrun T-SQL / datetimeoffset converter.** The pyodbc output converter for type -155 (`datetimeoffset`) is from
   known pyodbc recipes but untested here.
6. **`pyodbc` in `requirements.txt` / Vercel.** Added to requirements and pyproject; the Vercel deployment (spec 12) has
   no Microsoft ODBC driver, so the API cannot reach SQL Server from there. Assumed local `uvicorn` is the target now.
7. **`get_ownership` in `repository/base.py`** is still the Supabase version for the unmigrated repos; a SQL variant
   `get_ownership_sql` (whitelisted tables) was added. Assumed later slices rename it when Supabase goes away.
8. **mcp_gateway/server.py** still reads `agent_logs` through Supabase directly (pre-existing layering breach, out of F0a scope).
