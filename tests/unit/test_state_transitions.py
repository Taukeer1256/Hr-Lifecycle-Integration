"""Unit tests for employee state transitions."""

from __future__ import annotations

import pytest

from app.models.employee import (
    ALLOWED_TRANSITIONS,
    EmploymentStatus,
    validate_status_transition,
)


class TestStateTransitions:
    """Test all valid and invalid status transitions."""

    def test_pending_to_active_is_valid(self):
        # Should not raise
        validate_status_transition(EmploymentStatus.pending, EmploymentStatus.active)

    def test_pending_to_terminated_is_valid(self):
        validate_status_transition(EmploymentStatus.pending, EmploymentStatus.terminated)

    def test_active_to_on_leave_is_valid(self):
        validate_status_transition(EmploymentStatus.active, EmploymentStatus.on_leave)

    def test_active_to_terminated_is_valid(self):
        validate_status_transition(EmploymentStatus.active, EmploymentStatus.terminated)

    def test_on_leave_to_active_is_valid(self):
        validate_status_transition(EmploymentStatus.on_leave, EmploymentStatus.active)

    def test_on_leave_to_terminated_is_valid(self):
        validate_status_transition(EmploymentStatus.on_leave, EmploymentStatus.terminated)

    def test_terminated_to_active_is_invalid(self):
        with pytest.raises(ValueError, match="terminated"):
            validate_status_transition(EmploymentStatus.terminated, EmploymentStatus.active)

    def test_terminated_to_pending_is_invalid(self):
        with pytest.raises(ValueError, match="terminated"):
            validate_status_transition(EmploymentStatus.terminated, EmploymentStatus.pending)

    def test_pending_to_on_leave_is_invalid(self):
        with pytest.raises(ValueError, match="Cannot transition"):
            validate_status_transition(EmploymentStatus.pending, EmploymentStatus.on_leave)

    def test_active_to_pending_is_invalid(self):
        with pytest.raises(ValueError, match="Cannot transition"):
            validate_status_transition(EmploymentStatus.active, EmploymentStatus.pending)

    def test_terminated_is_terminal_state(self):
        assert ALLOWED_TRANSITIONS[EmploymentStatus.terminated] == set()

    def test_error_message_includes_allowed_transitions(self):
        with pytest.raises(ValueError) as exc_info:
            validate_status_transition(EmploymentStatus.pending, EmploymentStatus.on_leave)
        assert "Allowed:" in str(exc_info.value)

    def test_same_status_not_allowed_pending(self):
        with pytest.raises(ValueError):
            validate_status_transition(EmploymentStatus.pending, EmploymentStatus.pending)

    def test_same_status_not_allowed_active(self):
        with pytest.raises(ValueError):
            validate_status_transition(EmploymentStatus.active, EmploymentStatus.active)
