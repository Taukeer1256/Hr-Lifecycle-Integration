"""Employees router – CRUD + JML workflow endpoints."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db import get_db
from app.models.employee import (
    EmployeeCreate,
    EmployeeListResponse,
    EmployeeResponse,
    EmployeeTerminate,
    EmployeeUpdate,
    EmploymentStatus,
)
from app.models.user import CurrentUser
from app.security.rbac import (
    require_hr_admin,
    require_hr_admin_or_viewer,
)
from app.services.employee_service import (
    _doc_to_response,
    get_employee_by_id,
    list_employees,
)
from app.services.jml_service import (
    activate_employee,
    joiner_workflow,
    leaver_workflow,
    mover_workflow,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/employees", tags=["Employees"])


def _correlation_id(request: Request) -> Optional[str]:
    return request.headers.get("X-Correlation-ID")


# ── List ────────────────────────────────────────────────────────────────────
@router.get(
    "",
    response_model=EmployeeListResponse,
    summary="List employees (with optional filters & pagination)",
)
async def list_employees_endpoint(
    request: Request,
    department: Optional[str] = None,
    employment_status: Optional[EmploymentStatus] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    _user: CurrentUser = Depends(require_hr_admin_or_viewer),
) -> EmployeeListResponse:
    return await list_employees(
        db,
        department=department,
        employment_status=employment_status,
        search=search,
        page=page,
        page_size=page_size,
    )


# ── Get single ──────────────────────────────────────────────────────────────
@router.get(
    "/{employee_id}",
    response_model=EmployeeResponse,
    summary="Get employee by ID",
)
async def get_employee(
    employee_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    _user: CurrentUser = Depends(require_hr_admin_or_viewer),
) -> EmployeeResponse:
    doc = await get_employee_by_id(db, employee_id)
    return _doc_to_response(doc)


# ── Joiner ──────────────────────────────────────────────────────────────────
@router.post(
    "",
    response_model=EmployeeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create employee (Joiner workflow)",
)
async def create_employee_endpoint(
    request: Request,
    data: EmployeeCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    current_user: CurrentUser = Depends(require_hr_admin),
) -> EmployeeResponse:
    after_doc = await joiner_workflow(
        db,
        data=data,
        actor=current_user.username,
        actor_role=current_user.role.value,
        correlation_id=_correlation_id(request),
    )
    return _doc_to_response(after_doc)


# ── Mover ───────────────────────────────────────────────────────────────────
@router.patch(
    "/{employee_id}",
    response_model=EmployeeResponse,
    summary="Update employee fields (Mover workflow)",
)
async def update_employee_endpoint(
    request: Request,
    employee_id: str,
    data: EmployeeUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    current_user: CurrentUser = Depends(require_hr_admin),
) -> EmployeeResponse:
    after_doc = await mover_workflow(
        db,
        employee_id=employee_id,
        data=data,
        actor=current_user.username,
        actor_role=current_user.role.value,
        correlation_id=_correlation_id(request),
    )
    return _doc_to_response(after_doc)


# ── Activate ─────────────────────────────────────────────────────────────────
@router.post(
    "/{employee_id}/activate",
    response_model=EmployeeResponse,
    summary="Activate a pending employee",
)
async def activate_employee_endpoint(
    request: Request,
    employee_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    current_user: CurrentUser = Depends(require_hr_admin),
) -> EmployeeResponse:
    after_doc = await activate_employee(
        db,
        employee_id=employee_id,
        actor=current_user.username,
        actor_role=current_user.role.value,
        correlation_id=_correlation_id(request),
    )
    return _doc_to_response(after_doc)


# ── Leaver ───────────────────────────────────────────────────────────────────
@router.post(
    "/{employee_id}/terminate",
    response_model=EmployeeResponse,
    summary="Terminate employee (Leaver workflow)",
)
async def terminate_employee(
    request: Request,
    employee_id: str,
    data: EmployeeTerminate,
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    current_user: CurrentUser = Depends(require_hr_admin),
) -> EmployeeResponse:
    after_doc = await leaver_workflow(
        db,
        employee_id=employee_id,
        data=data,
        actor=current_user.username,
        actor_role=current_user.role.value,
        correlation_id=_correlation_id(request),
    )
    return _doc_to_response(after_doc)
