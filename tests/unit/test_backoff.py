"""Unit tests for outbox backoff and retry logic."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.workers.outbox_worker import compute_next_attempt


class TestBackoffLogic:
    """Tests for exponential backoff computation."""

    def test_first_retry_backoff(self):
        """First retry: base^1 = 2 seconds."""
        result = compute_next_attempt(retry_count=1, base=2, max_wait=60)
        expected_min = datetime.utcnow() + timedelta(seconds=1)
        expected_max = datetime.utcnow() + timedelta(seconds=4)  # Some tolerance
        assert expected_min <= result <= expected_max

    def test_second_retry_backoff(self):
        """Second retry: base^2 = 4 seconds."""
        result = compute_next_attempt(retry_count=2, base=2, max_wait=60)
        expected_min = datetime.utcnow() + timedelta(seconds=3)
        expected_max = datetime.utcnow() + timedelta(seconds=6)
        assert expected_min <= result <= expected_max

    def test_third_retry_backoff(self):
        """Third retry: base^3 = 8 seconds."""
        result = compute_next_attempt(retry_count=3, base=2, max_wait=60)
        expected_min = datetime.utcnow() + timedelta(seconds=7)
        expected_max = datetime.utcnow() + timedelta(seconds=10)
        assert expected_min <= result <= expected_max

    def test_max_wait_cap(self):
        """High retry count should be capped at max_wait."""
        result = compute_next_attempt(retry_count=10, base=2, max_wait=60)
        # 2^10 = 1024, but should be capped at 60
        expected_min = datetime.utcnow() + timedelta(seconds=58)
        expected_max = datetime.utcnow() + timedelta(seconds=62)
        assert expected_min <= result <= expected_max

    def test_zero_retry_backoff(self):
        """Retry count 0: base^0 = 1 second."""
        result = compute_next_attempt(retry_count=0, base=2, max_wait=60)
        expected_min = datetime.utcnow() + timedelta(seconds=0)
        expected_max = datetime.utcnow() + timedelta(seconds=2)
        assert expected_min <= result <= expected_max

    def test_backoff_increases_with_retry(self):
        """Each retry should schedule further into the future."""
        t1 = compute_next_attempt(retry_count=1, base=2, max_wait=3600)
        t2 = compute_next_attempt(retry_count=2, base=2, max_wait=3600)
        t3 = compute_next_attempt(retry_count=3, base=2, max_wait=3600)
        assert t1 < t2 < t3

    def test_custom_base_and_max(self):
        """Custom base and max_wait values."""
        result = compute_next_attempt(retry_count=2, base=3, max_wait=100)
        # 3^2 = 9 seconds
        expected_min = datetime.utcnow() + timedelta(seconds=7)
        expected_max = datetime.utcnow() + timedelta(seconds=12)
        assert expected_min <= result <= expected_max
