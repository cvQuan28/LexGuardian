"""
Unit tests for app.core.security — no external dependencies required.

Covers:
  - password hashing (PBKDF2, salt uniqueness, wrong-password rejection)
  - timing-safe comparison (verify_password)
  - session token generation (entropy, uniqueness)
  - session token hashing (deterministic, non-reversible)
"""
import pytest

from app.core.security import (
    hash_password,
    hash_session_token,
    generate_session_token,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_has_salt_prefix(self):
        h = hash_password("secret")
        assert "$" in h, "Hash must contain salt separator '$'"

    def test_verify_correct_password(self):
        h = hash_password("my_password")
        assert verify_password("my_password", h)

    def test_reject_wrong_password(self):
        h = hash_password("correct_password")
        assert not verify_password("wrong_password", h)

    def test_unique_salts(self):
        """Same password → different hashes (random salt)."""
        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        assert h1 != h2, "Two hashes of same password must differ (different salts)"

    def test_deterministic_with_explicit_salt(self):
        h1 = hash_password("password", salt="fixedsalt")
        h2 = hash_password("password", salt="fixedsalt")
        assert h1 == h2

    def test_malformed_hash_returns_false(self):
        assert not verify_password("anything", "no-separator-hash")

    def test_empty_password_hashes_safely(self):
        h = hash_password("")
        assert verify_password("", h)
        assert not verify_password("nonempty", h)

    def test_unicode_password(self):
        pwd = "mật_khẩu_tiếng_việt_123"
        h = hash_password(pwd)
        assert verify_password(pwd, h)
        assert not verify_password("wrong", h)

    def test_long_password(self):
        pwd = "x" * 1000
        h = hash_password(pwd)
        assert verify_password(pwd, h)


class TestSessionTokens:
    def test_token_has_minimum_entropy(self):
        token = generate_session_token()
        # secrets.token_urlsafe(32) → 43 chars of base64url
        assert len(token) >= 40, f"Token too short: {len(token)}"

    def test_tokens_are_unique(self):
        tokens = {generate_session_token() for _ in range(100)}
        assert len(tokens) == 100, "Token collision detected"

    def test_hash_is_deterministic(self):
        token = generate_session_token()
        h1 = hash_session_token(token)
        h2 = hash_session_token(token)
        assert h1 == h2

    def test_hash_differs_per_token(self):
        t1 = generate_session_token()
        t2 = generate_session_token()
        assert hash_session_token(t1) != hash_session_token(t2)

    def test_hash_is_sha256_hex(self):
        h = hash_session_token("test-token")
        assert len(h) == 64, "SHA-256 hex digest must be 64 chars"
        assert all(c in "0123456789abcdef" for c in h)

    def test_raw_token_not_stored_in_hash(self):
        token = "my-secret-token"
        h = hash_session_token(token)
        assert token not in h, "Raw token must not appear in its hash"
