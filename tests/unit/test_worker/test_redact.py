"""Unit tests for worker._redact.redact_url_userinfo (P1-F)."""
from __future__ import annotations

from qaplatform.worker._redact import redact_url_userinfo


class TestRedactUrlUserinfo:
    def test_strips_user_password_userinfo(self):
        text = "fatal: clone failed for https://user:secret@github.com/org/repo.git"
        out = redact_url_userinfo(text)
        assert "secret" not in out
        assert "user" not in out
        assert "https://***@github.com/org/repo.git" in out

    def test_strips_x_access_token_pattern(self):
        text = (
            "RuntimeError: git clone aborted: "
            "https://x-access-token:ghp_supersecrettoken@github.com/org/repo.git"
        )
        out = redact_url_userinfo(text)
        assert "ghp_supersecrettoken" not in out
        assert "x-access-token" not in out
        assert "https://***@github.com/org/repo.git" in out

    def test_strips_user_only_userinfo(self):
        text = "https://oauth2@gitlab.com/group/repo.git denied"
        out = redact_url_userinfo(text)
        assert "oauth2" not in out
        assert "https://***@gitlab.com/group/repo.git" in out

    def test_no_userinfo_unchanged(self):
        text = "git clone https://github.com/org/repo.git failed: 404"
        assert redact_url_userinfo(text) == text

    def test_multiple_urls_all_redacted(self):
        text = (
            "tried https://a:1@host1/r and then "
            "https://x-access-token:tok@host2/r both failed"
        )
        out = redact_url_userinfo(text)
        assert "1" not in out.split("host1")[0]
        assert "tok" not in out
        assert out.count("***@") == 2

    def test_empty_and_none_safe(self):
        assert redact_url_userinfo("") == ""
        assert redact_url_userinfo(None) is None  # type: ignore[arg-type]

    def test_non_url_at_sign_unchanged(self):
        # Email-like text without scheme://userinfo@host pattern stays untouched.
        text = "contact admin@example.com about this failure"
        assert redact_url_userinfo(text) == text

    def test_ssh_style_url_unchanged(self):
        # git@github.com:org/repo.git has no scheme://, must not match.
        text = "fatal: ssh access denied for git@github.com:org/repo.git"
        assert redact_url_userinfo(text) == text
