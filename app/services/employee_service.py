"""Employee CRUD service."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.employee import (
    EmployeeCreate,
    EmployeeDocument,
    EmployeeListResponse,
    EmployeeResponse,
    EmploymentStatus,
    validate_status_transition,
)

logger = logging.getLogger(__name__)

SENSITIVE_FIELDS = {"hashed_password"}


def _doc_to_response(doc: dict[str, Any]) -> EmployeeResponse:
    return EmployeeResponse(
        employee_id=doc["employee_id"],
        name=doc["name"],
        email=doc["email"],
        department=doc["department"],
        job_title=doc["job_title"],
        manager_id=doc.get("manager_id"),
        location=doc["location"],
        employment_status=doc["employment_status"],
        start_date=doc["start_date"],
        end_date=doc.get("end_date"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def _clean_for_audit(doc: dict[str, Any]) -> dict[str, Any]:
    """Strip internal fields not relevant for auditing."""
    return {
        k: v
        for k, v in doc.items()
        if k not in ("_id",) and k not in SENSITIVE_FIELDS
    }


async def get_employee_by_id(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    employee_id: str,
) -> dict[str, Any]:
    doc = await db.employees.find_one({"employee_id": employee_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee '{employee_id}' not found.",
        )
    return doc


async def create_employee(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    data: EmployeeCreate,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Insert new employee. Returns (after_doc, None).
    Raises 409 if employee_id or email already exists.
    """
    existing_id = await db.employees.find_one({"employee_id": data.employee_id})
    if existing_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Employee with employee_id '{data.employee_id}' already exists.",
        )
    existing_email = await db.employees.find_one({"email": data.email})
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Employee with email '{data.email}' already exists.",
        )

    doc = EmployeeDocument(
        employee_id=data.employee_id,
        name=data.name,
        email=str(data.email),
        department=data.department,
        job_title=data.job_title,
        manager_id=data.manager_id,
        location=data.location,
        start_date=data.start_date,
    )
    insert_dict = doc.model_dump(by_alias=True)
    insert_dict["_id"] = str(insert_dict["_id"])
    # Convert date to datetime for Mongo
    insert_dict["start_date"] = datetime.combine(data.start_date, datetime.min.time())
    await db.employees.insert_one(insert_dict)
    inserted = await db.employees.find_one({"employee_id": data.employee_id})
    return inserted, None  # type: ignore[return-value]


async def update_employee(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    employee_id: str,
    updates: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Apply partial update to an employee. Returns (after_doc, before_doc).
    Raises 409 if resulting state is invalid.
    """
    before = await get_employee_by_id(db, employee_id)

    current_status = EmploymentStatus(before["employment_status"])
    if current_status == EmploymentStatus.terminated:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot modify a terminated employee.",
        )

    # Email uniqueness check
    if "email" in updates and updates["email"] != before["email"]:
        conflict = await db.employees.find_one(
            {"email": updates["email"], "employee_id": {"$ne": employee_id}}
        )
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{updates['email']}' is already in use.",
            )

    updates["updated_at"] = datetime.utcnow()
    await db.employees.update_one({"employee_id": employee_id}, {"$set": updates})
    after = await db.employees.find_one({"employee_id": employee_id})
    return after, before  # type: ignore[return-value]


async def change_status(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    employee_id: str,
    new_status: EmploymentStatus,
    extra_updates: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Validate and apply a status transition. Returns (after_doc, before_doc).
    Raises 409 on invalid transition.
    """
    before = await get_employee_by_id(db, employee_id)
    current = EmploymentStatus(before["employment_status"])

    try:
        validate_status_transition(current, new_status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    update_fields: dict[str, Any] = {
        "employment_status": new_status,
        "updated_at": datetime.utcnow(),
    }
    if extra_updates:
        update_fields.update(extra_updates)

    await db.employees.update_one({"employee_id": employee_id}, {"$set": update_fields})
    after = await db.employees.find_one({"employee_id": employee_id})
    return after, before  # type: ignore[return-value]


async def list_employees(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    *,
    department: Optional[str] = None,
    employment_status: Optional[EmploymentStatus] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> EmployeeListResponse:
    query: dict[str, Any] = {}
    if department:
        query["department"] = department
    if employment_status:
        query["employment_status"] = employment_status
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"employee_id": {"$regex": search, "$options": "i"}},
        ]

    skip = (page - 1) * page_size
    total = await db.employees.count_documents(query)
    cursor = (
        db.employees.find(query).sort("created_at", -1).skip(skip).limit(page_size)
    )
    docs = await cursor.to_list(length=page_size)
    items = [_doc_to_response(d) for d in docs]
    return EmployeeListResponse(total=total, page=page, page_size=page_size, items=items)
