"""Apply ../sql_server/*.sql (in numeric order) to SQL Server. Used by the `db-init` service in compose.yaml.

Splits each script on lines containing only `GO` (the SSMS/sqlcmd batch separator, which is not T-SQL) and runs every
batch on an autocommit connection to `master`; the scripts switch to HandsellerDB themselves (`USE HandsellerDB`).
The scripts are re-runnable, so running this repeatedly is safe.

    python scripts/apply_sql.py [sql_dir]        # default sql_dir: $SQL_DIR or ../sql_server
Connection settings come from the same MSSQL_* environment variables as the API.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyodbc  # noqa: E402

from core.config import Settings, build_mssql_connection_string  # noqa: E402

GO = re.compile(r"^\s*GO\s*(?:--.*)?$", re.IGNORECASE | re.MULTILINE)


def connect(timeout_s: int = 120) -> "pyodbc.Connection":
    conn_str = build_mssql_connection_string(Settings(mssql_database="master"))
    deadline = time.time() + timeout_s
    while True:
        try:
            return pyodbc.connect(conn_str, autocommit=True, timeout=5)
        except pyodbc.Error as exc:
            if time.time() > deadline:
                raise SystemExit(f"SQL Server not reachable after {timeout_s}s: {exc}")
            print("waiting for SQL Server ...", flush=True)
            time.sleep(3)


def main() -> None:
    sql_dir = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SQL_DIR", "../sql_server"))
    scripts = sorted(sql_dir.glob("[0-9][0-9]_*.sql"))
    if not scripts:
        raise SystemExit(f"no NN_*.sql scripts found in {sql_dir.resolve()}")
    conn = connect()
    cur = conn.cursor()
    for script in scripts:
        batches = [b.strip() for b in GO.split(script.read_text(encoding="utf-8-sig")) if b.strip()]
        print(f"{script.name}: {len(batches)} batches", flush=True)
        for i, batch in enumerate(batches, 1):
            try:
                cur.execute(batch)
                while cur.nextset():
                    pass
            except pyodbc.Error as exc:
                raise SystemExit(f"FAILED {script.name} batch {i}: {exc}\n--- batch ---\n{batch[:600]}")
    print("all scripts applied", flush=True)


if __name__ == "__main__":
    main()
