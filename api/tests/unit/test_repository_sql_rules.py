"""Static guard over repository/*.py SQL (no DB needed).

Rules (see api/CLAUDE.md, specs/03):
 1. No f-string / .format / % / "+ var" built SQL: SQL strings are literals.
 2. A statement touching a tenant table BY id must also mention org_id (same statement).
 3. Every statement touching a tenant table must mention org_id, unless it carries an explicit
    `/* allow-no-org: <reason> */` marker (e.g. login lookup by email, when no org is known yet).
 4. orgs (the tenant root) by-id statements must also filter by owner_id.
Extend `TENANT_TABLES` as slices add tables; never weaken the rules.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

REPO_DIR = pathlib.Path(__file__).resolve().parents[2] / "repository"
TENANT_TABLES = {"users", "sales", "expenses", "agent_jobs", "agent_logs", "products", "customers", "sale_items", "cash_accounts", "cash_ledger"}
ROOT_TABLES = {"orgs"}
SQL_START = re.compile(r"^\s*(/\*.*?\*/\s*)?(SET\s+NOCOUNT|DECLARE|SELECT|INSERT|UPDATE|DELETE|WITH|MERGE)\b", re.I | re.S)
TABLE_REF = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO|DELETE\s+FROM)\s+(?:dbo\.)?([A-Za-z_][A-Za-z0-9_]*)", re.I)


def _py_files():
    return sorted(p for p in REPO_DIR.glob("*.py") if p.name not in ("__init__.py",))


def _sql_nodes(path):
    """Yield (lineno, resolved_sql_or_None, node) for each SQL-looking string/constant expr."""
    tree = ast.parse(path.read_text())
    consts: dict[str, str] = {}

    def resolve(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            return n.value
        if isinstance(n, ast.Name) and n.id in consts:
            return consts[n.id]
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            l, r = resolve(n.left), resolve(n.right)
            return l + r if l is not None and r is not None else None
        return None

    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            val = resolve(node.value)
            if val is not None:
                consts[node.targets[0].id] = val
                if SQL_START.match(val):
                    yield node.lineno, val, node
    # SQL that is not a plain module-level constant: string literals inside dicts/functions, and
    # "a" + "b" concatenations built inside functions. (Pieces of a concatenation are not checked on
    # their own, only the joined statement; docstrings/bare expression statements are skipped.)
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr):
            skip.add(id(node.value))
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            for child in (node.left, node.right):
                skip.add(id(child))
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, (ast.Constant, ast.BinOp)):
            val = resolve(node)
            if isinstance(val, str) and SQL_START.match(val):
                yield node.lineno, val, node
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            yield node.lineno, None, node  # f-string
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            if isinstance(node.func.value, ast.Constant) and isinstance(node.func.value.value, str) and SQL_START.match(node.func.value.value):
                yield node.lineno, None, node


def _statements(sql: str):
    return [s for s in sql.split(";") if s.strip()]


def _tables(stmt: str) -> set[str]:
    return {m.lower() for m in TABLE_REF.findall(stmt)}


def _all():
    out = []
    for p in _py_files():
        for lineno, sql, node in _sql_nodes(p):
            out.append((p, lineno, sql, node))
    return out


def test_repository_files_found_and_have_sql():
    assert any(sql for _, _, sql, _ in _all()), "guard found no SQL; parser is broken"


def test_no_fstring_or_format_sql():
    bad = []
    for p, lineno, sql, node in _all():
        if isinstance(node, ast.JoinedStr):
            text = "".join(v.value for v in node.values if isinstance(v, ast.Constant))
            if SQL_START.match(text):
                bad.append(f"{p.name}:{lineno}")
        elif sql is None:
            bad.append(f"{p.name}:{lineno}")
    assert not bad, f"SQL must be literal + parameterised (?): {bad}"


def test_tenant_statements_scoped_by_org_id():
    bad = []
    for p, lineno, sql, _ in _all():
        if not sql:
            continue
        for stmt in _statements(sql):
            tabs = _tables(stmt)
            if tabs & TENANT_TABLES:
                if "allow-no-org:" in stmt:
                    continue
                if not re.search(r"\borg_id\b", stmt, re.I):
                    bad.append(f"{p.name}:{lineno}: {stmt.strip()[:80]}")
            if tabs & ROOT_TABLES and re.search(r"\bWHERE\b.*\bid\s*=\s*\?", stmt, re.I | re.S):
                if not re.search(r"\bowner_id\b", stmt, re.I):
                    bad.append(f"{p.name}:{lineno}: orgs by id without owner_id")
    assert not bad, f"statements missing org_id scoping: {bad}"


def test_by_id_statements_include_org_id():
    bad = []
    for p, lineno, sql, _ in _all():
        if not sql:
            continue
        for stmt in _statements(sql):
            if _tables(stmt) & TENANT_TABLES and re.search(r"\bWHERE\b.*\bid\s*=\s*\?", stmt, re.I | re.S):
                if not re.search(r"\borg_id\b", stmt, re.I):
                    bad.append(f"{p.name}:{lineno}")
    assert not bad, bad


def test_guard_sees_sql_in_dicts_and_new_repositories():
    """The guard must cover the F0b repositories and dict-held SQL (base._OWNERSHIP_SQL)."""
    seen = {p.name for p, _, sql, _ in _all() if sql}
    assert {"sales_repository.py", "expenses_repository.py", "agent_jobs_repository.py", "products_repository.py", "customers_repository.py", "cash_repository.py", "base.py"} <= seen
    base_sql = [sql for p, _, sql, _ in _all() if p.name == "base.py" and sql]
    assert any("FROM sales WHERE id = ? AND org_id = ?" in q for q in base_sql)


def test_every_tenant_table_has_a_repository_statement_with_org_id():
    text = " ".join(sql for _, _, sql, _ in _all() if sql)
    for table in ("sales", "expenses", "agent_jobs", "agent_logs", "products", "customers", "sale_items", "cash_accounts", "cash_ledger"):
        assert re.search(rf"\b{table}\b[^;]*\borg_id\b", text, re.I), table


def test_guard_detects_violations():
    """The guard itself must not be vacuous."""
    stmt = "SELECT * FROM users WHERE id = ?"
    assert _tables(stmt) & TENANT_TABLES and not re.search(r"\borg_id\b", stmt)
    assert "allow-no-org:" not in stmt


def test_no_sql_outside_repository():
    """Layering: only repository/ (and core/db.py) may issue SQL."""
    root = REPO_DIR.parent
    offenders = []
    for sub in ("services", "routers", "jobs", "mcp_gateway", "middleware", "ai_agents"):
        for p in (root / sub).rglob("*.py"):
            if re.search(r"\bdb\.(query|query_one|execute)\(", p.read_text()):
                offenders.append(str(p.relative_to(root)))
    assert not offenders, offenders


def test_products_adjust_stock_is_one_guarded_statement():
    """The race-safe adjust: one UPDATE with id, org_id AND the non-negative guard in the same statement."""
    sql = {s for p, _, s, _ in _all() if p.name == "products_repository.py" and s and "stock_qty = stock_qty + ?" in s}
    assert len(sql) == 1
    stmt = next(iter(sql))
    assert re.search(r"WHERE id = \? AND org_id = \? AND stock_qty \+ \? >= 0", stmt)
    assert "INTO @o" in stmt


def _customers_sql():
    return {s for p, _, s, _ in _all() if p.name == "customers_repository.py" and s}


def test_customers_summary_scopes_org_id_on_both_tables():
    stmt = next(s for s in _customers_sql() if "AS sale_count" in s)
    assert re.search(r"JOIN sales s ON .*\bs\.org_id = \?", stmt) and re.search(r"WHERE c\.id = \? AND c\.org_id = \?", stmt)
    assert "GROUP BY" in stmt and "LEFT JOIN" in stmt


def test_customers_delete_has_not_exists_guard_in_same_statement():
    stmt = next(s for s in _customers_sql() if s.startswith("DELETE FROM customers"))
    assert "WHERE id = ? AND org_id = ?" in stmt and re.search(r"NOT EXISTS \(SELECT 1 FROM sales WHERE .*sales\.org_id = \?\)", stmt)


def test_customers_search_is_parameterised_like_with_escape():
    stmt = next(s for s in _customers_sql() if "LIKE" in s)
    assert stmt.count("LIKE ? ESCAPE") == 2 and "org_id = ?" in stmt


def test_sales_customer_id_checked_via_get_ownership_allow_list():
    base_sql = [sql for p, _, sql, _ in _all() if p.name == "base.py" and sql]
    assert any("FROM customers WHERE id = ? AND org_id = ?" in q for q in base_sql)


def _sales_sql():
    return {s for p, _, s, _ in _all() if p.name == "sales_repository.py" and s}


def test_sale_procedures_are_executed_with_parameters_only():
    """record/void go through EXEC with ? placeholders: org_id is a procedure parameter, nothing is interpolated."""
    execs = [s for s in _sales_sql() if "EXEC dbo.usp_" in s]
    assert {"usp_RecordSale", "usp_VoidSale"} == {m for s in execs for m in re.findall(r"usp_\w+", s)}
    for stmt in execs:
        assert "@org_id = ?" in stmt and "%" not in stmt


def test_sale_items_reads_are_scoped_by_org_id_on_both_joined_tables():
    stmt = next(s for s in _sales_sql() if "FROM sale_items si JOIN products p" in s and "si.sale_id = ?" in s)
    assert "p.org_id = si.org_id" in stmt and "si.org_id = ?" in stmt


def test_sales_and_expenses_updates_never_touch_amount():
    """Retired bypass: amount is part of the cash ledger and changes only through usp_AdjustEntryAmount."""
    for name, table in (("sales_repository.py", "sales"), ("expenses_repository.py", "expenses")):
        stmts = sorted({s for p, _, s, _ in _all() if p.name == name and s and f"UPDATE {table} SET" in s})
        assert len(stmts) == 1, name
        assert "amount" not in stmts[0][stmts[0].index("UPDATE "):].split("OUTPUT")[0] and "WHERE id = ? AND org_id = ?" in stmts[0]


def test_no_repository_function_writes_sales_or_expenses_without_the_ledger():
    """No plain INSERT/DELETE on sales/expenses/cash tables in repository code: those happen only inside the procedures."""
    bad = []
    for p, lineno, sql, _ in _all():
        if not sql:
            continue
        for stmt in _statements(sql):
            if re.search(r"\b(INSERT\s+INTO|DELETE\s+FROM)\s+(sales|expenses|cash_accounts|cash_ledger|sale_items)\b", stmt, re.I):
                bad.append(f"{p.name}:{lineno}: {stmt.strip()[:70]}")
    assert not bad, bad


def test_sale_procedure_sql_scopes_every_tenant_statement_by_org_id():
    """Static check of sql_server/05: every statement in the procedures that touches a tenant table mentions org_id."""
    sql = (REPO_DIR.parents[1] / "sql_server" / "05_sale_items_cash_recordsale.sql").read_text()
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)  # block comments first (they may contain "--")
    sql = re.sub(r"--[^\n]*", "", sql)
    body = sql[sql.index("CREATE OR ALTER PROCEDURE dbo.usp_RecordSale"):]
    tenant = r"(?:dbo\.)?(sales|sale_items|products|customers|cash_accounts|cash_ledger)\b"
    bad = []
    for stmt in re.split(r";", body):
        if re.search(r"\b(FROM|JOIN|UPDATE|INTO|DELETE\s+FROM)\s+" + tenant, stmt, re.I) and not re.search(r"\borg_id\b", stmt, re.I):
            bad.append(" ".join(stmt.split())[:90])
    assert not bad, bad
    assert "SET XACT_ABORT ON" in body and body.count("SET XACT_ABORT ON") == 2
    assert "stock_qty >= @qty" in body and "SAVE TRANSACTION sp_item" in body and "XACT_STATE()" in body


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)  # block comments first (they may contain "--")
    return re.sub(r"--[^\n]*", "", sql)


def test_expense_and_adjust_procedure_sql_scopes_every_tenant_statement_by_org_id():
    """Static check of sql_server/06: every statement in the three procedures that touches a tenant table mentions org_id."""
    sql = _strip_sql_comments((REPO_DIR.parents[1] / "sql_server" / "06_expenses_cash.sql").read_text())
    body = sql[sql.index("CREATE OR ALTER PROCEDURE dbo.usp_RecordExpense"):]
    tenant = r"(?:dbo\.)?(sales|sale_items|expenses|products|customers|cash_accounts|cash_ledger)\b"
    bad = []
    for stmt in re.split(r";", body):
        if re.search(r"\b(FROM|JOIN|UPDATE|INTO|DELETE\s+FROM)\s+" + tenant, stmt, re.I) and not re.search(r"\borg_id\b", stmt, re.I):
            bad.append(" ".join(stmt.split())[:90])
    assert not bad, bad
    assert {"usp_RecordExpense", "usp_VoidExpense", "usp_AdjustEntryAmount"} <= set(re.findall(r"CREATE OR ALTER PROCEDURE dbo\.(usp_\w+)", body))
    assert body.count("SET XACT_ABORT ON") == 3 and body.count("XACT_STATE()") >= 6
    assert body.count("DECLARE @own_tran") == 3 and body.count("SAVE TRANSACTION") == 3


def test_expense_procedures_follow_the_documented_rules():
    sql = _strip_sql_comments((REPO_DIR.parents[1] / "sql_server" / "06_expenses_cash.sql").read_text())
    # the ledger CHECK is widened with a guarded drop/re-create (re-runnable) and allows 'expense_void'
    assert "DROP CONSTRAINT CK_cash_ledger_entry_type" in sql and "N'expense_void'" in sql
    assert "definition NOT LIKE N'%expense_void%'" in sql
    # a negative cash balance is ALLOWED: the decrement has no "balance >= amount" guard
    assert "SET balance = balance - @amount" in sql and not re.search(r"balance\s*>=", sql)
    # the ledger delta of an adjustment: sale +delta, expense -delta
    assert "SET @signed = @delta" in sql and "SET @signed = -@delta" in sql
    # a sale with line items is refused (not_allowed) inside the procedure
    assert "FROM dbo.sale_items WHERE sale_id = @ref_id AND org_id = @org_id" in sql and "N'not_allowed'" in sql
    # business failures are OUTPUT values: no THROW / RAISERROR in the procedures
    assert not re.search(r"\b(THROW|RAISERROR)\b", sql, re.I)


def test_void_sale_reverses_adjustments_too():
    """usp_VoidSale (05, F4 version) reverses the 'sale' entry AND its 'adjustment' entries, or the balance would drift."""
    sql = _strip_sql_comments((REPO_DIR.parents[1] / "sql_server" / "05_sale_items_cash_recordsale.sql").read_text())
    assert "ref_id = @sale_id AND entry_type IN (N'sale', N'adjustment')" in sql


def test_cash_repository_filters_are_static_parameterised_statements():
    stmts = {s for p, _, s, _ in _all() if p.name == "cash_repository.py" and s}
    ledger = next(s for s in stmts if "FROM cash_ledger WHERE org_id = ?" in s and "OFFSET" in s)
    assert ledger.count("?") == 9 and "entry_type = ?" in ledger and "entry_date >= CAST(? AS date)" in ledger
    summary = next(s for s in stmts if "GROUP BY entry_type" in s)
    assert "SUM(amount)" in summary and "org_id = ?" in summary
    opening = next(s for s in stmts if "AS opening" in s)
    assert "SUM(amount)" in opening and "org_id = ?" in opening and "entry_date < ?" in opening
    adjust = next(s for s in stmts if "usp_AdjustEntryAmount" in s)
    assert "@org_id = ?" in adjust and "%" not in adjust
