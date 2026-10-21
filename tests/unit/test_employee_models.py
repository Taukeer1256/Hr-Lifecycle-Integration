"""Unit tests for employee models and validation."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.models.employee import EmployeeCreate, EmployeeTerminate, EmployeeUpdate


class TestEmployeeCreate:
    def test_valid_create(self):
        emp = EmployeeCreate(
            employee_id="EMP001",
            name="Alice Smith",
            email="alice@example.com",
            department="Engineering",
            job_title="Engineer",
            location="London",
            start_date=date.today(),
        )
        assert emp.employee_id == "EMP001"

    def test_invalid_email(self):
        with pytest.raises(ValidationError):
            EmployeeCreate(
                employee_id="EMP001",
                name="Alice",
                email="not-an-email",
                department="Engineering",
                job_title="Engineer",
                location="London",
                start_date=date.today(),
            )

    def test_empty_employee_id_fails(self):
        with pytest.raises(ValidationError):
            EmployeeCreate(
                employee_id="",
                name="Alice",
                email="alice@example.com",
                department="Engineering",
                job_title="Engineer",
                location="London",
                start_date=date.today(),
            )


class TestEmployeeUpdate:
    def test_valid_update(self):
        upd = EmployeeUpdate(department="HR", job_title="Manager")
        assert upd.department == "HR"

    def test_empty_update_fails(self):
        with pytest.raises(ValidationError, match="At least one field"):
            EmployeeUpdate()

    def test_partial_update_valid(self):
        upd = EmployeeUpdate(location="Berlin")
        assert upd.location == "Berlin"
        assert upd.department is None

    def test_invalid_email_in_update(self):
        with pytest.raises(ValidationError):
            EmployeeUpdate(email="not-valid")


class TestEmployeeTerminate:
    def test_valid_terminate(self):
        term = EmployeeTerminate(end_date=date.today())
        assert term.end_date == date.today()

    def test_missing_end_date_fails(self):
        with pytest.raises(ValidationError):
            EmployeeTerminate()
