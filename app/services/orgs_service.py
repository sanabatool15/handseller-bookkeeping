"""Business logic for orgs."""
from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.orgs import OrgCreate, OrgOut
from app.repository import orgs_repo


def create_org(user_id: str, payload: OrgCreate) -> OrgOut:
    """Creates an org owned by the authenticated user.

    No ownership check needed here: the user always "owns" the act of
    creating their own org; owner_id is set from the authenticated user,
    never trusted from the request body.
    """
    row = orgs_repo.create_org(name=payload.name, owner_id=user_id)
    return OrgOut(**row)


def get_org(user_id: str, org_id: str) -> OrgOut:
    row = orgs_repo.get_org_by_id(org_id)
    if row is None:
        raise NotFoundError(f"Org [{org_id}] was not found.")
    if row["owner_id"] != user_id:
        raise ForbiddenError(f"User [{user_id}] does not own org_id [{org_id}].")
    return OrgOut(**row)


def list_my_orgs(user_id: str) -> list[OrgOut]:
    rows = orgs_repo.list_orgs_for_owner(user_id)
    return [OrgOut(**row) for row in rows]
