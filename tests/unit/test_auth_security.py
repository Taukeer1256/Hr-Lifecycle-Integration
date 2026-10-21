"""Unit tests for JWT auth and RBAC."""

from __future__ import annotations

from app.models.user import UserRole
from app.security.jwt_auth import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.security.rbac import sign_payload, verify_signature


class TestPasswordHashing:
    def test_hash_and_verify(self):
        password = "SecurePass123!"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("correct-password")
        assert not verify_password("wrong-password", hashed)

    def test_hash_is_unique(self):
        # Same password should produce different hashes (bcrypt uses salt)
        h1 = hash_password("same-password")
        h2 = hash_password("same-password")
        assert h1 != h2


class TestJWT:
    def test_create_and_decode_token(self):
        token, expires_in = create_access_token("testuser", UserRole.hr_admin)
        assert isinstance(token, str)
        assert expires_in > 0

        token_data = decode_token(token)
        assert token_data is not None
        assert token_data.sub == "testuser"
        assert token_data.role == UserRole.hr_admin

    def test_decode_invalid_token(self):
        result = decode_token("invalid.token.string")
        assert result is None

    def test_decode_empty_token(self):
        result = decode_token("")
        assert result is None

    def test_decode_tampered_token(self):
        token, _ = create_access_token("testuser", UserRole.hr_viewer)
        # Tamper with signature
        parts = token.split(".")
        parts[2] = "invalidsignature"
        tampered = ".".join(parts)
        result = decode_token(tampered)
        assert result is None

    def test_all_roles_round_trip(self):
        for role in UserRole:
            token, _ = create_access_token(f"user_{role.value}", role)
            token_data = decode_token(token)
            assert token_data is not None
            assert token_data.role == role

    def test_expires_in_is_positive(self):
        _, expires_in = create_access_token("user", UserRole.hr_admin)
        assert expires_in == 60 * 60  # 60 minutes in seconds


class TestHMACSigning:
    def test_sign_payload_returns_hex_string(self):
        payload = {"event": "test", "employee_id": "EMP001"}
        sig = sign_payload(payload)
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA256 hex digest length

    def test_signature_is_deterministic(self):
        payload = {"event": "test", "employee_id": "EMP001"}
        sig1 = sign_payload(payload)
        sig2 = sign_payload(payload)
        assert sig1 == sig2

    def test_different_payloads_different_signatures(self):
        sig1 = sign_payload({"key": "value1"})
        sig2 = sign_payload({"key": "value2"})
        assert sig1 != sig2

    def test_verify_valid_signature(self):
        payload = {"event": "employee.joined", "employee_id": "EMP001"}
        sig = sign_payload(payload)
        assert verify_signature(payload, sig)

    def test_verify_invalid_signature(self):
        payload = {"event": "employee.joined", "employee_id": "EMP001"}
        assert not verify_signature(payload, "invalidsignature")

    def test_verify_tampered_payload(self):
        payload = {"event": "employee.joined", "employee_id": "EMP001"}
        sig = sign_payload(payload)
        tampered = {"event": "employee.joined", "employee_id": "EMP002"}  # changed
        assert not verify_signature(tampered, sig)

    def test_key_order_does_not_matter(self):
        """sign_payload uses sort_keys=True so order doesn't matter."""
        p1 = {"b": 2, "a": 1}
        p2 = {"a": 1, "b": 2}
        assert sign_payload(p1) == sign_payload(p2)
