"""Shared ownership-enforcement helper used by every other service.

Every service operation that touches org-scoped data must call
`assert_owns_org` before performing any read/write. It raises ForbiddenError
(mapped to HTTP 403) with an explicit message when the check fails.
"""
from app.core.exceptions import ForbiddenError
from app.repository.ownership_repo import get_ownership


def assert_owns_org(user_id: str, org_id: str) -> None:
    if not get_ownership(user_id, org_id):
        raise ForbiddenError(
            f"User [{user_id}] does not own org_id [{org_id}]."
        )
