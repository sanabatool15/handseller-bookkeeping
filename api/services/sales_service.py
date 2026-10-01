"""Sales business logic + validation. No direct DB access here — only via repository."""
from __future__ import annotations

import uuid
from typing import Any, Callable

from core.db import Db, run_with_deadlock_retry

from repository import base as repo_base
from repository import cash_repository, sales_repository


class ValidationError(Exception):
    pass


class NotFoundError(Exception):
    pass


class InsufficientStockError(Exception):
    """A requested item has less stock than the quantity (HTTP 409); the message names the product."""


def _require_customer(db: Db, org_id: str, customer_id: str) -> None:
    """A customer of another org is indistinguishable from a missing one: both 404 (id AND org_id check)."""
    if not repo_base.get_ownership(db, table="customers", record_id=customer_id, org_id=org_id):
        raise NotFoundError("Customer not found")


MAX_ITEMS = 200
MAX_AMOUNT = 999_999_999_999.99  # decimal(14,2) maximum
MAX_QTY = 1_000_000


def _normalise_items(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Validate/clean line items: product_id must be a UUID, quantity 1..MAX_QTY, unit_price (optional) >= 0."""
    clean: list[dict[str, Any]] = []
    for raw in items or []:
        try:
            product_id = str(uuid.UUID(str(raw.get("product_id"))))
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValidationError("Each item needs a valid product_id") from exc
        quantity = raw.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 0 < quantity <= MAX_QTY:
            raise ValidationError(f"Item quantity must be a whole number between 1 and {MAX_QTY}")
        item: dict[str, Any] = {"product_id": product_id, "quantity": quantity}
        price = raw.get("unit_price")
        if price is not None:
            if price < 0:
                raise ValidationError("Item unit_price must not be negative")
            item["unit_price"] = round(float(price), 2)
        clean.append(item)
    if len(clean) > MAX_ITEMS:
        raise ValidationError(f"A sale can have at most {MAX_ITEMS} items")
    return clean


def create_sale(
    db: Db, *, org_id: str, user_id: str, amount: float | None = None, category: str = "general",
    description: str | None = None, customer_name: str | None = None, customer_id: str | None = None,
    items: list[dict[str, Any]] | None = None, skip_invalid_items: bool = False,
    on_event: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Record a sale ATOMICALLY (stock, cash balance and ledger move together; see specs/15).

    With `items` the total is the sum of the lines (`amount` is ignored); without items `amount` is required
    (old behaviour). Raises ValidationError (422), NotFoundError (404: customer/product), InsufficientStockError (409).
    The unit of work is re-run when SQL Server picks it as a deadlock victim (`on_event` is told about retries)."""
    clean_items = _normalise_items(items)
    if not clean_items:
        if amount is None:
            raise ValidationError("amount is required when no items are given")
        if amount <= 0:
            raise ValidationError("Sale amount must be positive")
    if customer_id is not None:
        _require_customer(db, org_id, customer_id)
    outcome = run_with_deadlock_retry(
        lambda: sales_repository.record_sale(
            db, org_id=org_id, created_by=user_id, customer_id=customer_id, customer_name=customer_name,
            category=category or "general", description=description, amount=None if clean_items else amount,
            items=clean_items or None, skip_invalid_items=skip_invalid_items,
        ),
        on_event=on_event,
    )
    if outcome["status"] == "rolled_back":
        number, message = outcome["error_number"], outcome["message"]
        if number == 50001:
            raise InsufficientStockError(message)
        if number == 50002:
            raise NotFoundError("Product not found")
        if number == 50004:
            raise NotFoundError("Customer not found")
        if number == 50005:
            raise NotFoundError("Organisation not found")
        raise ValidationError(message or "Sale rejected")
    sale = outcome["sale"]
    if outcome["status"] == "partial":
        sale["skipped_items"] = outcome["skipped_items"]
    return sale


def list_sales(db: Db, *, org_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    return sales_repository.list_sales(db, org_id=org_id, limit=limit, offset=offset)


def get_sale(db: Db, *, org_id: str, sale_id: str) -> dict[str, Any]:
    sale = sales_repository.get_sale_scoped(db, sale_id=sale_id, org_id=org_id)
    if sale is None:
        raise NotFoundError("Sale not found")
    return sale


def update_sale(
    db: Db, *, org_id: str, sale_id: str, updates: dict[str, Any], user_id: str | None = None,
    on_event: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Update a sale. A changed `amount` goes through usp_AdjustEntryAmount, which posts the delta to the cash ledger in
    the same transaction (a sale WITH line items is refused: 422). The other fields are updated in the same request."""
    if "amount" in updates and updates["amount"] is not None:
        if updates["amount"] <= 0:
            raise ValidationError("Sale amount must be positive")
        if updates["amount"] > MAX_AMOUNT:
            raise ValidationError("Sale amount is too large")
    # customer_id is the one field where a PRESENT null is meaningful (unlink the sale); everything else drops None.
    clean_updates = {k: v for k, v in updates.items() if v is not None or k == "customer_id"}
    if clean_updates.get("customer_id") is not None:
        _require_customer(db, org_id, clean_updates["customer_id"])
    new_amount = clean_updates.pop("amount", None)
    if new_amount is not None:
        result = run_with_deadlock_retry(
            lambda: cash_repository.adjust_entry_amount(
                db, org_id=org_id, ref_type="sale", ref_id=sale_id, new_amount=new_amount, adjusted_by=user_id,
            ),
            on_event=on_event,
        )
        if result["status"] == "not_found":
            raise NotFoundError("Sale not found")
        if result["status"] == "not_allowed":
            raise ValidationError(result["message"] or "The amount of a sale with line items cannot be changed")
        if result["status"] not in ("adjusted", "unchanged"):
            raise ValidationError(result["message"] or "Amount change rejected")
    updated = sales_repository.update_sale_scoped(db, sale_id=sale_id, org_id=org_id, updates=clean_updates)
    if updated is None:
        raise NotFoundError("Sale not found")
    return updated


def delete_sale(db: Db, *, org_id: str, sale_id: str, user_id: str | None = None, on_event: Callable[..., None] | None = None) -> None:
    """Void the sale (usp_VoidSale): stock back, reversing cash entry, sale deleted - all in one transaction."""
    result = run_with_deadlock_retry(
        lambda: sales_repository.void_sale(db, org_id=org_id, sale_id=sale_id, voided_by=user_id), on_event=on_event,
    )
    if result["status"] == "not_found":
        raise NotFoundError("Sale not found")
