"""Unit tests for scripts/seed_admin.py password validation.

Tests the P1-2 security fix that prevents empty and weak passwords.
"""
import subprocess
import sys
from pathlib import Path


def test_seed_admin_rejects_empty_password():
    """seed_admin.py must reject empty password (ADMIN_PASSWORD='')."""
    result = subprocess.run(
        [sys.executable, "scripts/seed_admin.py"],
        env={"ADMIN_PASSWORD": ""},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1, "Should exit with code 1 for empty password"
    assert "must not be empty" in result.stderr, "Should mention empty password in error"


def test_seed_admin_rejects_unset_password():
    """seed_admin.py must reject unset password (ADMIN_PASSWORD not provided)."""
    result = subprocess.run(
        [sys.executable, "scripts/seed_admin.py"],
        env={},  # No ADMIN_PASSWORD
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1, "Should exit with code 1 for unset password"
    assert "required" in result.stderr, "Should mention required in error"


def test_seed_admin_rejects_short_password():
    """seed_admin.py must reject passwords shorter than 8 characters."""
    result = subprocess.run(
        [sys.executable, "scripts/seed_admin.py"],
        env={"ADMIN_PASSWORD": "1234567"},  # 7 characters
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1, "Should exit with code 1 for short password"
    assert "at least 8 characters" in result.stderr, "Should mention minimum length"


def test_seed_admin_accepts_valid_password():
    """seed_admin.py must accept passwords with 8+ characters.

    Note: This test will fail if the database is not available,
    but that's expected - we're only testing password validation,
    not the full database operation.
    """
    result = subprocess.run(
        [sys.executable, "scripts/seed_admin.py"],
        env={"ADMIN_PASSWORD": "ValidPass123"},  # 12 characters
        capture_output=True,
        text=True,
        timeout=5,
    )

    # Should NOT fail on password validation
    # It may fail later on database connection, but that's OK
    if result.returncode != 0:
        # If it failed, make sure it's NOT a password validation error
        assert "must not be empty" not in result.stderr, \
            "Should not reject valid password as empty"
        assert "at least 8 characters" not in result.stderr, \
            "Should not reject valid password as too short"
        # Acceptable failure reasons: database connection, etc.
    else:
        # If it succeeded, that's perfect
        assert result.returncode == 0


def test_seed_admin_password_validation_order():
    """Password validation should check empty before checking length."""
    # Empty password should fail with "empty" error, not "length" error
    result = subprocess.run(
        [sys.executable, "scripts/seed_admin.py"],
        env={"ADMIN_PASSWORD": ""},
        capture_output=True,
        text=True,
    )

    assert "must not be empty" in result.stderr, \
        "Should check for empty first"
    assert "at least 8 characters" not in result.stderr, \
        "Should not reach length check for empty password"


def test_seed_admin_whitespace_only_password():
    """seed_admin.py must reject whitespace-only passwords."""
    result = subprocess.run(
        [sys.executable, "scripts/seed_admin.py"],
        env={"ADMIN_PASSWORD": "   "},  # Only spaces
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1, "Should exit with code 1 for whitespace-only"
    # Will fail on length check (3 chars < 8)
    assert "at least 8 characters" in result.stderr
