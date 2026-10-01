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
TENANT_TABLES = {"users", "sales", "expenses", "agent_jobs", "agent_logs"}
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
    assert {"sales_repository.py", "expenses_repository.py", "agent_jobs_repository.py", "base.py"} <= seen
    base_sql = [sql for p, _, sql, _ in _all() if p.name == "base.py" and sql]
    assert any("FROM sales WHERE id = ? AND org_id = ?" in q for q in base_sql)


def test_every_tenant_table_has_a_repository_statement_with_org_id():
    text = " ".join(sql for _, _, sql, _ in _all() if sql)
    for table in ("sales", "expenses", "agent_jobs", "agent_logs"):
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
