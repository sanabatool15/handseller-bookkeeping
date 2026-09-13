"""In-memory fake Supabase client used across unit + integration tests.

Mimics the chained-builder query interface (`db.table(x).select(...).eq(...)
.execute()`) closely enough to exercise the repository layer's filtering
logic (including the critical id+org_id double-scoping) without needing a
real Postgres/Supabase instance.
"""
from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class _Response:
    data: list[dict[str, Any]]


class _QueryBuilder:
    def __init__(self, store: "FakeSupabase", table: str):
        self._store = store
        self._table = table
        self._filters: list[Callable[[dict[str, Any]], bool]] = []
        self._mode = "select"
        self._insert_rows: list[dict[str, Any]] | None = None
        self._update_values: dict[str, Any] | None = None
        self._order_field: str | None = None
        self._order_desc = False
        self._range: tuple[int, int] | None = None
        self._limit: int | None = None

    # --- filters ---
    def eq(self, field_name: str, value: Any) -> "_QueryBuilder":
        self._filters.append(lambda row: row.get(field_name) == value)
        return self

    def gte(self, field_name: str, value: Any) -> "_QueryBuilder":
        self._filters.append(lambda row: str(row.get(field_name, "")) >= str(value))
        return self

    def lt(self, field_name: str, value: Any) -> "_QueryBuilder":
        self._filters.append(lambda row: str(row.get(field_name, "")) < str(value))
        return self

    def limit(self, n: int) -> "_QueryBuilder":
        self._limit = n
        return self

    def order(self, field_name: str, desc: bool = False) -> "_QueryBuilder":
        self._order_field = field_name
        self._order_desc = desc
        return self

    def range(self, start: int, end: int) -> "_QueryBuilder":
        self._range = (start, end)
        return self

    # --- operations ---
    def select(self, *_args, **_kwargs) -> "_QueryBuilder":
        self._mode = "select"
        return self

    def insert(self, values: dict[str, Any] | list[dict[str, Any]]) -> "_QueryBuilder":
        self._mode = "insert"
        self._insert_rows = values if isinstance(values, list) else [values]
        return self

    def update(self, values: dict[str, Any]) -> "_QueryBuilder":
        self._mode = "update"
        self._update_values = values
        return self

    def delete(self) -> "_QueryBuilder":
        self._mode = "delete"
        return self

    def execute(self) -> _Response:
        table_rows = self._store.tables.setdefault(self._table, [])

        if self._mode == "insert":
            created = []
            for row in self._insert_rows or []:
                new_row = deepcopy(row)
                new_row.setdefault("id", str(uuid.uuid4()))
                now = self._store.now()
                new_row.setdefault("created_at", now)
                new_row.setdefault("updated_at", now)
                table_rows.append(new_row)
                created.append(deepcopy(new_row))
            return _Response(data=created)

        matched_idx = [i for i, row in enumerate(table_rows) if all(f(row) for f in self._filters)]

        if self._mode == "select":
            rows = [table_rows[i] for i in matched_idx]
            if self._order_field:
                rows.sort(key=lambda r: r.get(self._order_field), reverse=self._order_desc)
            if self._range:
                start, end = self._range
                rows = rows[start : end + 1]
            if self._limit is not None:
                rows = rows[: self._limit]
            return _Response(data=[deepcopy(r) for r in rows])

        if self._mode == "update":
            updated = []
            for i in matched_idx:
                table_rows[i].update(deepcopy(self._update_values or {}))
                table_rows[i]["updated_at"] = self._store.now()
                updated.append(deepcopy(table_rows[i]))
            return _Response(data=updated)

        if self._mode == "delete":
            deleted = [deepcopy(table_rows[i]) for i in matched_idx]
            for i in sorted(matched_idx, reverse=True):
                table_rows.pop(i)
            return _Response(data=deleted)

        raise RuntimeError(f"Unsupported query mode: {self._mode}")


class FakeSupabase:
    def __init__(self):
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self._counter = 0

    def now(self) -> str:
        import datetime as dt

        return dt.datetime.utcnow().isoformat()

    def table(self, name: str) -> _QueryBuilder:
        return _QueryBuilder(self, name)
