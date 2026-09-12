"""Org endpoints. Delegates all logic to app.services.orgs_service."""
from fastapi import APIRouter, Depends, status

from app.core.security import CurrentUser, get_current_user
from app.models.orgs import OrgCreate, OrgOut
from app.services import orgs_service

router = APIRouter(prefix="/orgs", tags=["orgs"])


@router.post("", response_model=OrgOut, status_code=status.HTTP_201_CREATED)
def create_org(payload: OrgCreate, current_user: CurrentUser = Depends(get_current_user)):
    return orgs_service.create_org(current_user.user_id, payload)


@router.get("", response_model=list[OrgOut])
def list_my_orgs(current_user: CurrentUser = Depends(get_current_user)):
    return orgs_service.list_my_orgs(current_user.user_id)


@router.get("/{org_id}", response_model=OrgOut)
def get_org(org_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return orgs_service.get_org(current_user.user_id, org_id)
