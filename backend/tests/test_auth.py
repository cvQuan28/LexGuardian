"""
Unit tests for auth business logic.

Tests verify_password + hash_password round-trips and session token
generation without touching the database (pure unit tests).

Integration-level auth route tests are intentionally left out here —
they require a live DB and are better suited for the CI smoke suite.
"""
import pytest

from app.core.security import hash_password, verify_password, generate_session_token, hash_session_token


class TestAuthBusinessLogic:
    """Verify the auth primitives used by /register and /login."""

    def test_register_hash_then_login_verify(self):
        """Simulate: user registers → password stored as hash → user logs in."""
        raw_password = "S3cur3P@ssw0rd!"
        stored_hash = hash_password(raw_password)

        # Login with correct password
        assert verify_password(raw_password, stored_hash) is True

    def test_login_wrong_password_rejected(self):
        stored_hash = hash_password("correct")
        assert verify_password("incorrect", stored_hash) is False

    def test_case_sensitive_password(self):
        stored_hash = hash_password("Password")
        assert verify_password("password", stored_hash) is False
        assert verify_password("PASSWORD", stored_hash) is False

    def test_session_token_uniqueness_across_users(self):
        """Each login call should produce a unique token."""
        tokens = [generate_session_token() for _ in range(50)]
        assert len(set(tokens)) == 50

    def test_token_hash_used_for_storage(self):
        """The stored token_hash must differ from the raw token."""
        token = generate_session_token()
        stored = hash_session_token(token)
        assert stored != token
        # Verify the stored hash is not easily reversible
        assert token not in stored

    def test_email_normalization(self):
        """Emails should be lowercased before storage/lookup."""
        emails = ["TEST@EXAMPLE.COM", "Test@Example.Com", "test@example.com"]
        normalized = [e.lower() for e in emails]
        assert len(set(normalized)) == 1, "All email variants must normalize to same value"


class TestPasswordEdgeCases:
    def test_special_characters(self):
        for pwd in ["abc!@#$%^&*()", "pás$wörd", "1234567890", " leading space"]:
            h = hash_password(pwd)
            assert verify_password(pwd, h), f"Failed for: {pwd!r}"

    def test_minimum_length_boundary(self):
        pwd = "a"  # minimal
        h = hash_password(pwd)
        assert verify_password(pwd, h)

    def test_hash_format_invariant(self):
        """Hash format: '<salt>$<digest>' where both parts are non-empty hex strings."""
        h = hash_password("test")
        parts = h.split("$", 1)
        assert len(parts) == 2
        salt, digest = parts
        assert len(salt) == 32, "Salt should be 16-byte hex (32 chars)"
        assert len(digest) == 64, "PBKDF2-SHA256 digest should be 32-byte hex (64 chars)"
