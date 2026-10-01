"""In-memory fakes of the SQL Server repository functions.

Same function names/signatures as `repository/<mod>.py`; installed by the autouse
fixture in tests/conftest.py via `monkeypatch.setattr(repository.<mod>, name, fake)`.
Services must therefore call `module.func(...)` (never `from x import func`).

`FakeSqlDb` mimics `core.db.Db` transactionality for the fakes: it snapshots the
store when created and `rollback()` restores it, so atomicity tests are meaningful.
"""
from __future__ import annotations

import copy
import itertools
import uuid
from typing import Any, Optional

from repository import base as repo_base
from repository.base import DuplicateRecordError

# The REAL get_ownership, captured before install_fake_repos() patches the module attribute
# (lets a unit test exercise the real function's allow-list/SQL shape with a recording Db).
REAL_GET_OWNERSHIP = repo_base.get_ownership


class FakeSqlStore:
    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.orgs: dict[str, dict[str, Any]] = {}
        self.sales: dict[str, dict[str, Any]] = {}
        self.expenses: dict[str, dict[str, Any]] = {}
        self.agent_jobs: dict[str, dict[str, Any]] = {}
        self.agent_logs: dict[str, dict[str, Any]] = {}
        self.products: dict[str, dict[str, Any]] = {}
        self.customers: dict[str, dict[str, Any]] = {}
        self.sale_items: dict[str, dict[str, Any]] = {}
        self.cash_accounts: dict[str, dict[str, Any]] = {}   # keyed by org_id
        self.cash_ledger: dict[str, dict[str, Any]] = {}

    _TABLES = ("users", "orgs", "sales", "expenses", "agent_jobs", "agent_logs", "products", "customers",
               "sale_items", "cash_accounts", "cash_ledger")

    def snapshot(self):
        return copy.deepcopy({t: getattr(self, t) for t in self._TABLES})

    def restore(self, snap) -> None:
        for t, rows in copy.deepcopy(snap).items():
            setattr(self, t, rows)


class FakeSqlDb:
    """Stand-in for core.db.Db handed to services/routers in tests."""

    def __init__(self, store: FakeSqlStore) -> None:
        self.store = store
        self._snap = store.snapshot()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1
        self._snap = self.store.snapshot()

    def rollback(self) -> None:
        self.rollbacks += 1
        self.store.restore(self._snap)

    def close(self) -> None:
        self.closed = True

    def query(self, *a, **k):  # pragma: no cover - guard: fakes never run SQL
        raise AssertionError("FakeSqlDb does not execute SQL; repositories must be faked")

    query_one = execute = query


_tick = itertools.count(1)


def _now() -> str:
    """Strictly increasing fake timestamps, so "newest first" orderings are deterministic."""
    return f"2026-01-01T00:00:00.{next(_tick):06d}+00:00"


def build_users_fakes(store: FakeSqlStore) -> dict[str, Any]:
    def get_user_by_email(db, email: str) -> Optional[dict]:
        for u in store.users.values():
            if u["email"].lower() == email.lower():  # SQL Server default collation is CI
                return dict(u)
        return None

    def get_user_by_id_scoped(db, *, user_id: str, org_id: str) -> Optional[dict]:
        u = store.users.get(user_id)
        return dict(u) if u and u["org_id"] == org_id else None

    def create_user(db, *, email, hashed_password, full_name, org_id, role="member") -> dict:
        if get_user_by_email(db, email):
            raise DuplicateRecordError("duplicate email (2627)")
        row = {"id": str(uuid.uuid4()), "org_id": org_id, "email": email, "full_name": full_name,
               "hashed_password": hashed_password, "role": role, "created_at": _now(), "updated_at": _now()}
        store.users[row["id"]] = row
        return dict(row)

    def set_user_org(db, *, user_id: str, org_id: str) -> dict:
        u = store.users.get(user_id)
        if u is None or u["org_id"] is not None:
            raise RuntimeError("Failed to link user to org")
        u["org_id"] = org_id
        return dict(u)

    return {k: v for k, v in locals().items() if callable(v) and k != "store"}


def build_orgs_fakes(store: FakeSqlStore) -> dict[str, Any]:
    def create_org(db, *, name: str, owner_id: str) -> dict:
        row = {"id": str(uuid.uuid4()), "name": name, "owner_id": owner_id, "created_at": _now(), "updated_at": _now()}
        store.orgs[row["id"]] = row
        return dict(row)

    def get_org_scoped(db, *, org_id: str, owner_id: str) -> Optional[dict]:
        o = store.orgs.get(org_id)
        return dict(o) if o and o["owner_id"] == owner_id else None

    return {k: v for k, v in locals().items() if callable(v) and k != "store"}


def _ledger_fakes(store: FakeSqlStore, *, table: str, singular: str, date_col: str, extra_col: str,
                  link_cols: tuple[str, ...] = ()) -> dict[str, Any]:
    """Read/metadata fakes for sales/expenses. They scope by id AND org_id exactly like the SQL does, so a
    cross-tenant id simply "does not exist" (=> 404 at the router), and they sum per date range. There is deliberately
    NO create/delete here (those go through the procedure fakes, which post to the cash ledger) and `amount` is not
    updatable (usp_AdjustEntryAmount)."""
    def tbl() -> dict[str, dict[str, Any]]:
        return getattr(store, table)

    def _ordered(org_id: str) -> list[dict]:
        mine = [r for r in tbl().values() if r["org_id"] == org_id]
        return sorted(mine, key=lambda r: (r[date_col], r["created_at"]), reverse=True)

    def list_(db, *, org_id, limit=100, offset=0) -> list[dict]:
        limit, offset = repo_base.clamp_page(limit, offset)
        return [dict(r) for r in _ordered(org_id)[offset:offset + limit]]

    def _in_month(r: dict, year: int, month: int) -> bool:
        start, end = repo_base.month_range(year, month)
        return start.isoformat() <= r[date_col] < end.isoformat()

    def list_for_month(db, *, org_id, year, month) -> list[dict]:
        return [dict(r) for r in _ordered(org_id) if _in_month(r, year, month)]

    def get_scoped(db, *, org_id, **ids) -> Optional[dict]:
        r = tbl().get(ids[f"{singular}_id"])
        return dict(r) if r and r["org_id"] == org_id else None

    def update_scoped(db, *, org_id, updates, **ids) -> Optional[dict]:
        allowed = {"category", extra_col, "description", *link_cols}  # amount only via adjust_entry_amount (ledger)
        if set(updates) - allowed:
            raise ValueError(f"cannot update columns: {sorted(set(updates) - allowed)}")
        r = tbl().get(ids[f"{singular}_id"])
        if not r or r["org_id"] != org_id:
            return None
        # link columns (customer_id): a PRESENT key is written even when None (unlink); others skip None
        r.update({k: v for k, v in updates.items() if v is not None or k in link_cols})
        r["updated_at"] = _now()
        return dict(r)

    def sum_month(db, *, org_id, year, month) -> float:
        return float(sum(r["amount"] for r in _ordered(org_id) if _in_month(r, year, month)))

    def by_category(db, *, org_id, year, month) -> dict[str, float]:
        out: dict[str, float] = {}
        for r in _ordered(org_id):
            if _in_month(r, year, month):
                out[r["category"] or "uncategorized"] = out.get(r["category"] or "uncategorized", 0.0) + r["amount"]
        return out

    plural = table
    return {
        f"list_{plural}": list_, f"list_{plural}_for_month": list_for_month,
        f"get_{singular}_scoped": get_scoped, f"update_{singular}_scoped": update_scoped,
        f"sum_{plural}_for_month": sum_month,
        f"sum_{plural}_by_category_for_month": by_category,
    }


def _round2(x: float) -> float:
    return round(float(x) + 0.0, 2)


def post_cash(store: FakeSqlStore, org_id, entry_type, amount, ref_type, ref_id, created_by, entry_date=None) -> None:
    """What every procedure does at its end: balance += amount (account created lazily) and one ledger row with balance_after."""
    acct = store.cash_accounts.setdefault(org_id, {"org_id": org_id, "balance": 0.0, "created_at": _now(), "updated_at": _now()})
    acct["balance"] = _round2(acct["balance"] + amount)
    acct["updated_at"] = _now()
    row = {"id": str(uuid.uuid4()), "org_id": org_id, "entry_type": entry_type, "amount": _round2(amount),
           "ref_type": ref_type, "ref_id": ref_id, "balance_after": acct["balance"],
           "entry_date": entry_date or repo_base.today_utc().isoformat(), "created_by": created_by,
           "created_at": _now(), "updated_at": _now()}
    store.cash_ledger[row["id"]] = row


def build_sales_fakes(store: FakeSqlStore) -> dict[str, Any]:
    """Fakes for sales + the two stored procedures. record_sale/void_sale mirror usp_RecordSale/usp_VoidSale:
    all-or-nothing unless skip_invalid_items, stock never negative (the guarded decrement), cash balance +
    ledger posted in the same step, everything scoped by org_id. They work on copies and apply the result at the
    end, which is how a rollback looks from the outside (and FakeSqlDb.rollback() restores the store anyway)."""
    fakes = _ledger_fakes(store, table="sales", singular="sale", date_col="sale_date", extra_col="customer_name",
                          link_cols=("customer_id",))
    base_get, base_list, base_update = fakes["get_sale_scoped"], fakes["list_sales"], fakes["update_sale_scoped"]

    def _items_of(sale_id: str, org_id: str) -> list[dict]:
        rows = [dict(i) for i in store.sale_items.values() if i["sale_id"] == sale_id and i["org_id"] == org_id]
        return sorted(rows, key=lambda r: r["created_at"])

    def _with_items(sale: Optional[dict]) -> Optional[dict]:
        if sale is not None:
            sale["items"] = _items_of(sale["id"], sale["org_id"])
        return sale

    def get_sale_scoped(db, *, sale_id, org_id):
        return _with_items(base_get(db, sale_id=sale_id, org_id=org_id))

    def list_sales(db, *, org_id, limit=100, offset=0):
        return [_with_items(s) for s in base_list(db, org_id=org_id, limit=limit, offset=offset)]

    def update_sale_scoped(db, *, sale_id, org_id, updates):
        return _with_items(base_update(db, sale_id=sale_id, org_id=org_id, updates=updates))

    def _post_cash(org_id, entry_type, amount, ref_id, created_by, entry_date=None) -> None:
        post_cash(store, org_id, entry_type, amount, "sale", ref_id, created_by, entry_date)

    def record_sale(db, *, org_id, created_by, customer_id, customer_name, category, description, amount, items,
                    skip_invalid_items) -> dict:
        def rolled_back(number: int, message: str) -> dict:
            return {"status": "rolled_back", "message": message, "error_number": number, "skipped_items": [], "sale": None}

        if items is None and (amount is None or amount <= 0):
            return rolled_back(50003, "amount must be positive when no items are given")
        if customer_id is not None:
            c = store.customers.get(customer_id)
            if not c or c["org_id"] != org_id:
                return rolled_back(50004, "Customer not found")
        sale_id = str(uuid.uuid4())
        stock = {pid: p["stock_qty"] for pid, p in store.products.items() if p["org_id"] == org_id}
        lines: list[dict] = []
        skipped: list[dict] = []
        ordered = sorted(enumerate(items or []), key=lambda t: (t[1]["product_id"], t[0]))  # same order as the proc
        for _, it in ordered:
            pid, qty = it["product_id"], it["quantity"]
            err = None
            if qty is None or qty <= 0:
                err = (50003, "Each item needs a product_id and a quantity greater than 0")
            elif it.get("unit_price") is not None and it["unit_price"] < 0:
                err = (50003, "unit_price must not be negative")
            elif pid not in stock:
                err = (50002, "Product not found")
            elif stock[pid] < qty:  # UPDATE ... WHERE stock_qty >= qty touched 0 rows
                err = (50001, f"Not enough stock for {store.products[pid]['name']}")
            if err is None:
                stock[pid] -= qty
                price = it["unit_price"] if it.get("unit_price") is not None else store.products[pid]["price"]
                lines.append({"id": str(uuid.uuid4()), "org_id": org_id, "sale_id": sale_id, "product_id": pid,
                              "product_name": store.products[pid]["name"], "quantity": qty, "unit_price": float(price),
                              "line_total": _round2(qty * price), "created_at": _now(), "updated_at": _now()})
            elif skip_invalid_items:
                skipped.append({"product_id": pid, "quantity": qty, "error_number": err[0], "reason": err[1]})
            else:
                return rolled_back(*err)
        if items and not lines:  # nothing usable => whole sale rolled back with the first reason
            return rolled_back(skipped[0]["error_number"], skipped[0]["reason"]) if skipped else rolled_back(50003, "No valid items")
        total = _round2(sum(l["line_total"] for l in lines)) if items else _round2(amount)
        # ---- "commit": apply everything ----
        for pid, qty in stock.items():
            store.products[pid]["stock_qty"] = qty
            store.products[pid]["updated_at"] = _now()
        sale = {"id": sale_id, "org_id": org_id, "created_by": created_by, "amount": total, "category": category,
                "customer_name": customer_name, "description": description, "sale_date": repo_base.today_utc().isoformat(),
                "customer_id": customer_id, "created_at": _now(), "updated_at": _now()}
        store.sales[sale_id] = sale
        for l in lines:
            store.sale_items[l["id"]] = l
        _post_cash(org_id, "sale", total, sale_id, created_by)
        return {"status": "partial" if skipped else "committed", "message": "Sale recorded", "error_number": None,
                "skipped_items": skipped, "sale": get_sale_scoped(db, sale_id=sale_id, org_id=org_id)}

    def void_sale(db, *, org_id, sale_id, voided_by) -> dict:
        sale = store.sales.get(sale_id)
        if not sale or sale["org_id"] != org_id:
            return {"status": "not_found", "message": "Sale not found"}
        for it in _items_of(sale_id, org_id):
            store.products[it["product_id"]]["stock_qty"] += it["quantity"]
            del store.sale_items[it["id"]]
        posted = sum(e["amount"] for e in store.cash_ledger.values()   # the 'sale' entry + its 'adjustment' entries
                     if e["org_id"] == org_id and e["ref_id"] == sale_id and e["entry_type"] in ("sale", "adjustment"))
        if posted:
            _post_cash(org_id, "sale_void", -posted, sale_id, voided_by)
        del store.sales[sale_id]
        return {"status": "voided", "message": "Sale voided"}

    fakes.update(get_sale_scoped=get_sale_scoped, list_sales=list_sales, update_sale_scoped=update_sale_scoped,
                 record_sale=record_sale, void_sale=void_sale)
    return fakes


def build_cash_fakes(store: FakeSqlStore) -> dict[str, Any]:
    def get_balance(db, *, org_id) -> dict:
        acct = store.cash_accounts.get(org_id)
        return {"balance": acct["balance"], "updated_at": acct["updated_at"]} if acct else {"balance": 0.0, "updated_at": None}

    def list_ledger(db, *, org_id, limit=100, offset=0, entry_type=None, date_from=None, date_to=None) -> list[dict]:
        limit, offset = repo_base.clamp_page(limit, offset)
        rows = [dict(e) for e in store.cash_ledger.values() if e["org_id"] == org_id
                and (entry_type is None or e["entry_type"] == entry_type)
                and (date_from is None or e["entry_date"] >= date_from.isoformat())
                and (date_to is None or e["entry_date"] <= date_to.isoformat())]
        rows.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
        return rows[offset:offset + limit]

    def get_month_summary(db, *, org_id, year, month) -> dict:
        start, end = repo_base.month_range(year, month)
        mine = [e for e in store.cash_ledger.values() if e["org_id"] == org_id]
        opening = sum(e["amount"] for e in mine if e["entry_date"] < start.isoformat())
        inside = [e for e in mine if start.isoformat() <= e["entry_date"] < end.isoformat()]
        by_type: dict[str, float] = {}
        for e in inside:
            by_type[e["entry_type"]] = _round2(by_type.get(e["entry_type"], 0.0) + e["amount"])
        return {"opening_balance": _round2(opening),
                "total_in": _round2(sum(e["amount"] for e in inside if e["amount"] > 0)),
                "total_out": _round2(sum(-e["amount"] for e in inside if e["amount"] < 0)),
                "closing_balance": _round2(opening + sum(e["amount"] for e in inside)), "by_type": by_type}

    def adjust_entry_amount(db, *, org_id, ref_type, ref_id, new_amount, adjusted_by) -> dict:
        """Mirror of usp_AdjustEntryAmount: scoped by id AND org_id, refuses sales with items, posts +delta (sale) / -delta (expense)."""
        def out(status, number, message):
            return {"status": status, "message": message, "error_number": number}

        if ref_type not in ("sale", "expense"):
            return out("rolled_back", 50003, "ref_type must be sale or expense")
        if new_amount is None or new_amount <= 0:
            return out("rolled_back", 50003, "amount must be positive")
        row = (store.sales if ref_type == "sale" else store.expenses).get(ref_id)
        if not row or row["org_id"] != org_id:
            return out("not_found", 50006 if ref_type == "sale" else 50007, "Sale not found" if ref_type == "sale" else "Expense not found")
        if ref_type == "sale" and any(i["sale_id"] == ref_id and i["org_id"] == org_id for i in store.sale_items.values()):
            return out("not_allowed", 50008, "The amount of a sale with line items cannot be changed (it is the sum of its items)")
        delta = _round2(float(new_amount) - row["amount"])
        if delta == 0:
            return out("unchanged", None, "Amount unchanged")
        row["amount"] = _round2(new_amount)
        row["updated_at"] = _now()
        post_cash(store, org_id, "adjustment", delta if ref_type == "sale" else -delta, ref_type, ref_id, adjusted_by)
        return out("adjusted", None, "Amount adjusted")

    return {"get_balance": get_balance, "list_ledger": list_ledger, "get_month_summary": get_month_summary,
            "adjust_entry_amount": adjust_entry_amount}


def build_expenses_fakes(store: FakeSqlStore) -> dict[str, Any]:
    """Fakes for expenses + usp_RecordExpense / usp_VoidExpense: the expense row, the cash balance and the ledger entry
    change together (negative balance allowed), everything scoped by org_id."""
    fakes = _ledger_fakes(store, table="expenses", singular="expense", date_col="expense_date", extra_col="voucher_reference")
    get_scoped = fakes["get_expense_scoped"]

    def record_expense(db, *, org_id, created_by, amount, category, voucher_reference, description, expense_date=None) -> dict:
        if amount is None or amount <= 0:
            return {"status": "rolled_back", "message": "amount must be positive", "error_number": 50003, "expense": None}
        day = (expense_date or repo_base.today_utc()).isoformat()
        row = {"id": str(uuid.uuid4()), "org_id": org_id, "created_by": created_by, "amount": _round2(amount),
               "category": category or "general", "voucher_reference": voucher_reference, "description": description,
               "expense_date": day, "created_at": _now(), "updated_at": _now()}
        store.expenses[row["id"]] = row
        post_cash(store, org_id, "expense", -_round2(amount), "expense", row["id"], created_by, day)
        return {"status": "committed", "message": "Expense recorded", "error_number": None,
                "expense": get_scoped(db, expense_id=row["id"], org_id=org_id)}

    def void_expense(db, *, org_id, expense_id, voided_by) -> dict:
        row = store.expenses.get(expense_id)
        if not row or row["org_id"] != org_id:
            return {"status": "not_found", "message": "Expense not found"}
        posted = sum(e["amount"] for e in store.cash_ledger.values()
                     if e["org_id"] == org_id and e["ref_id"] == expense_id and e["entry_type"] in ("expense", "adjustment"))
        if posted:
            post_cash(store, org_id, "expense_void", -posted, "expense", expense_id, voided_by)
        del store.expenses[expense_id]
        return {"status": "voided", "message": "Expense voided"}

    fakes.update(record_expense=record_expense, void_expense=void_expense)
    return fakes


def build_products_fakes(store: FakeSqlStore) -> dict[str, Any]:
    """Fakes for products. Like the DB: id AND org_id scoping, UNIQUE (org_id, sku) (=> DuplicateRecordError),
    CHECK stock_qty >= 0 / price >= 0 / reorder_level >= 0 (=> IntegrityError-like AssertionError), and an
    adjust that only applies when stock + delta >= 0 (the WHERE guard of the real statement)."""
    def _check(row: dict) -> None:
        if row["stock_qty"] < 0 or row["price"] < 0 or row["reorder_level"] < 0:
            raise AssertionError("CHECK constraint violated (547)")

    def _sku_taken(org_id: str, sku: str, except_id: str | None = None) -> bool:
        return any(r["org_id"] == org_id and r["sku"].lower() == sku.lower() and r["id"] != except_id  # CI collation
                   for r in store.products.values())

    def create_product(db, *, org_id, created_by, name, sku, price, stock_qty, reorder_level) -> dict:
        if _sku_taken(org_id, sku):
            raise DuplicateRecordError("duplicate (org_id, sku) (2627)")
        row = {"id": str(uuid.uuid4()), "org_id": org_id, "created_by": created_by, "name": name, "sku": sku,
               "price": float(price), "stock_qty": int(stock_qty), "reorder_level": int(reorder_level),
               "is_active": True, "created_at": _now(), "updated_at": _now()}
        _check(row)
        store.products[row["id"]] = row
        return dict(row)

    def list_products(db, *, org_id, limit=100, offset=0, low_stock=False) -> list[dict]:
        limit, offset = repo_base.clamp_page(limit, offset)
        mine = [r for r in store.products.values() if r["org_id"] == org_id
                and (not low_stock or r["stock_qty"] <= r["reorder_level"])]
        mine.sort(key=lambda r: (r["name"], r["id"]))
        return [dict(r) for r in mine[offset:offset + limit]]

    def get_product_scoped(db, *, product_id, org_id) -> Optional[dict]:
        r = store.products.get(product_id)
        return dict(r) if r and r["org_id"] == org_id else None

    def update_product_scoped(db, *, product_id, org_id, updates) -> Optional[dict]:
        allowed = {"name", "sku", "price", "reorder_level", "is_active"}
        if set(updates) - allowed:
            raise ValueError(f"cannot update columns: {sorted(set(updates) - allowed)}")
        r = store.products.get(product_id)
        if not r or r["org_id"] != org_id:
            return None
        if updates.get("sku") is not None and _sku_taken(org_id, updates["sku"], except_id=product_id):
            raise DuplicateRecordError("duplicate (org_id, sku) (2627)")
        candidate = {**r, **{k: v for k, v in updates.items() if v is not None}}
        candidate["price"] = float(candidate["price"])
        _check(candidate)
        r.update(candidate)
        r["updated_at"] = _now()
        return dict(r)

    def delete_product_scoped(db, *, product_id, org_id) -> bool:
        r = store.products.get(product_id)
        if not r or r["org_id"] != org_id:
            return False
        if any(i["product_id"] == product_id for i in store.sale_items.values()):  # FK_sale_items_product (547)
            raise repo_base.RecordInUseError("DELETE conflicted with the REFERENCE constraint FK_sale_items_product (547)")
        del store.products[product_id]
        return True

    def adjust_stock_scoped(db, *, product_id, org_id, delta) -> Optional[dict]:
        r = store.products.get(product_id)
        if not r or r["org_id"] != org_id or r["stock_qty"] + int(delta) < 0:
            return None
        r["stock_qty"] += int(delta)
        r["updated_at"] = _now()
        return dict(r)

    return {k: v for k, v in locals().items() if callable(v) and k not in ("store", "_check", "_sku_taken")}


def build_customers_fakes(store: FakeSqlStore) -> dict[str, Any]:
    """Fakes for customers. Like the DB: id AND org_id scoping, filtered UNIQUE (org_id, phone) WHERE phone IS NOT NULL
    (=> DuplicateRecordError), prefix search where LIKE wildcards in the term are literal (the repo escapes them),
    delete refused while sales reference the customer, summary aggregated over sales scoped on both tables."""
    def _phone_taken(org_id: str, phone, except_id: str | None = None) -> bool:
        return phone is not None and any(
            r["org_id"] == org_id and r["phone"] is not None and r["phone"].lower() == phone.lower() and r["id"] != except_id
            for r in store.customers.values())

    def create_customer(db, *, org_id, created_by, name, phone, email, address, notes) -> dict:
        if _phone_taken(org_id, phone):
            raise DuplicateRecordError("duplicate (org_id, phone) (2601)")
        row = {"id": str(uuid.uuid4()), "org_id": org_id, "created_by": created_by, "name": name, "phone": phone,
               "email": email, "address": address, "notes": notes, "created_at": _now(), "updated_at": _now()}
        store.customers[row["id"]] = row
        return dict(row)

    def list_customers(db, *, org_id, limit=100, offset=0, q=None) -> list[dict]:
        limit, offset = repo_base.clamp_page(limit, offset)
        mine = [r for r in store.customers.values() if r["org_id"] == org_id]
        if q:
            ql = q.lower()
            mine = [r for r in mine if r["name"].lower().startswith(ql) or (r["phone"] or "").lower().startswith(ql)]
        mine.sort(key=lambda r: (r["name"].lower(), r["id"]))
        return [dict(r) for r in mine[offset:offset + limit]]

    def get_customer_scoped(db, *, customer_id, org_id) -> Optional[dict]:
        r = store.customers.get(customer_id)
        return dict(r) if r and r["org_id"] == org_id else None

    def update_customer_scoped(db, *, customer_id, org_id, updates) -> Optional[dict]:
        allowed = {"name", "phone", "email", "address", "notes"}
        if set(updates) - allowed:
            raise ValueError(f"cannot update columns: {sorted(set(updates) - allowed)}")
        r = store.customers.get(customer_id)
        if not r or r["org_id"] != org_id:
            return None
        if "phone" in updates and _phone_taken(org_id, updates["phone"], except_id=customer_id):
            raise DuplicateRecordError("duplicate (org_id, phone) (2601)")
        if updates.get("name") is not None:
            r["name"] = updates["name"]
        for col in ("phone", "email", "address", "notes"):
            if col in updates:
                r[col] = updates[col]  # present key written, even None (clears)
        r["updated_at"] = _now()
        return dict(r)

    def delete_customer_scoped(db, *, customer_id, org_id) -> bool:
        r = store.customers.get(customer_id)
        if not r or r["org_id"] != org_id:
            return False
        if any(s.get("customer_id") == customer_id and s["org_id"] == org_id for s in store.sales.values()):
            return False  # NOT EXISTS (sales ...) guard
        del store.customers[customer_id]
        return True

    def get_customer_summary_scoped(db, *, customer_id, org_id) -> Optional[dict]:
        r = store.customers.get(customer_id)
        if not r or r["org_id"] != org_id:
            return None
        sales = [s for s in store.sales.values() if s.get("customer_id") == customer_id and s["org_id"] == org_id]
        return {"customer": dict(r), "total_sales": float(sum(s["amount"] for s in sales)), "sale_count": len(sales),
                "last_sale_date": max((s["sale_date"] for s in sales), default=None)}

    return {k: v for k, v in locals().items() if callable(v) and k not in ("store", "_phone_taken")}


def build_agent_jobs_fakes(store: FakeSqlStore) -> dict[str, Any]:
    def create_job(db, *, job_name, org_id, requested_by, input_payload=None) -> dict:
        row = {"id": str(uuid.uuid4()), "job_name": job_name, "org_id": org_id, "requested_by": requested_by,
               "status": "pending", "current_step": None, "input_payload": input_payload or {}, "result": None,
               "error_details": None, "created_at": _now(), "updated_at": _now()}
        store.agent_jobs[row["id"]] = row
        return copy.deepcopy(row)

    def get_job_scoped(db, *, job_id, org_id) -> Optional[dict]:
        j = store.agent_jobs.get(job_id)
        return copy.deepcopy(j) if j and j["org_id"] == org_id else None

    def update_job_status(db, *, job_id, org_id, status, current_step=None, result=None, error_details=None) -> Optional[dict]:
        j = store.agent_jobs.get(job_id)
        if not j or j["org_id"] != org_id:
            return None
        j["status"] = status
        for k, v in (("current_step", current_step), ("result", result), ("error_details", error_details)):
            if v is not None:
                j[k] = copy.deepcopy(v)
        j["updated_at"] = _now()
        return copy.deepcopy(j)

    def add_log(db, *, job_id, org_id, step_name, action_summary, insights_generated=None) -> dict:
        j = store.agent_jobs.get(job_id)
        if not j or j["org_id"] != org_id:  # INSERT ... SELECT FROM agent_jobs WHERE id AND org_id => no row
            raise RuntimeError("Failed to write agent log (job not found for this org)")
        row = {"id": str(uuid.uuid4()), "job_id": job_id, "org_id": org_id, "step_name": step_name,
               "action_summary": action_summary, "insights_generated": copy.deepcopy(insights_generated or {}),
               "executed_at": _now(), "created_at": _now(), "updated_at": _now()}
        store.agent_logs[row["id"]] = row
        return copy.deepcopy(row)

    def list_logs_for_job(db, *, job_id, org_id) -> list[dict]:
        logs = [l for l in store.agent_logs.values() if l["job_id"] == job_id and l["org_id"] == org_id]
        return [copy.deepcopy(l) for l in sorted(logs, key=lambda l: l["executed_at"])]

    def get_completed_steps(db, *, job_id, org_id) -> set[str]:
        return {l["step_name"] for l in list_logs_for_job(db, job_id=job_id, org_id=org_id)}

    return {k: v for k, v in locals().items() if callable(v) and k != "store"}


def build_ownership_fake(store: FakeSqlStore):
    def get_ownership(db, *, table: str, record_id: str, org_id: str) -> bool:
        if table not in ("users", "sales", "expenses", "agent_jobs", "products", "customers"):
            raise repo_base.RepositoryError(f"ownership check not supported for table {table!r}")
        r = getattr(store, table).get(record_id)
        return bool(r and r.get("org_id") == org_id)

    return get_ownership


def install_fake_repos(monkeypatch, store: FakeSqlStore) -> None:
    from repository import (agent_jobs_repository, cash_repository, customers_repository, expenses_repository, health_repository, orgs_repository,
                            products_repository, sales_repository, users_repository)

    for name, fn in build_sales_fakes(store).items():
        monkeypatch.setattr(sales_repository, name, fn)
    for name, fn in build_cash_fakes(store).items():
        monkeypatch.setattr(cash_repository, name, fn)
    for name, fn in build_expenses_fakes(store).items():
        monkeypatch.setattr(expenses_repository, name, fn)
    for name, fn in build_products_fakes(store).items():
        monkeypatch.setattr(products_repository, name, fn)
    for name, fn in build_customers_fakes(store).items():
        monkeypatch.setattr(customers_repository, name, fn)
    for name, fn in build_agent_jobs_fakes(store).items():
        monkeypatch.setattr(agent_jobs_repository, name, fn)
    monkeypatch.setattr(repo_base, "get_ownership", build_ownership_fake(store))
    monkeypatch.setattr(health_repository, "ping", lambda db: True)

    for name, fn in build_users_fakes(store).items():
        monkeypatch.setattr(users_repository, name, fn)
    for name, fn in build_orgs_fakes(store).items():
        monkeypatch.setattr(orgs_repository, name, fn)
