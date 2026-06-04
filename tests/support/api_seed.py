"""Test-environment seed helpers for API black-box tests.

These helpers are an explicit exception to the public-API-only setup rule. They
may create prerequisite state that the public API cannot currently create, but
the tests must still exercise and assert behavior through HTTP APIs.
"""
from __future__ import annotations

import ipaddress
import ssl
import subprocess
import tempfile
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker


@dataclass(frozen=True)
class SeededUser:
    id: str
    tenant_id: str
    username: str
    email: str


class ApiSeedStateFactory:
    """Seed test-only state that has no public setup API."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.session_factory = session_factory
        self._cleanups: list[tuple[str, dict[str, Any]]] = []

    async def promote_platform_admin(self, user_id: str) -> None:
        from qaplatform.infra.database.models import AppUser

        parsed_user_id = UUID(user_id)
        async with self.session_factory() as session:
            result = await session.execute(
                update(AppUser)
                .where(AppUser.id == parsed_user_id)
                .values(is_platform_admin=True)
            )
            if result.rowcount != 1:
                raise AssertionError(f"seed user not found: {user_id}")
            await session.commit()
        self._cleanups.append(("demote_platform_admin", {"user_id": parsed_user_id}))

    async def create_same_tenant_user(
        self,
        *,
        tenant_id: str,
        prefix: str = "seed-member",
    ) -> SeededUser:
        from qaplatform.infra.database.models import AppUser

        suffix = uuid4().hex[:10]
        username = f"{prefix}-{suffix}".replace("-", "_")[:32]
        user = AppUser(
            tenant_id=UUID(tenant_id),
            username=username,
            email=f"{username}@qaplatform.seed",
            password_hash="seeded-test-user-not-for-login",
            role="member",
            is_platform_admin=False,
            is_active=True,
        )
        async with self.session_factory() as session:
            session.add(user)
            await session.commit()
            await session.refresh(user)
        self._cleanups.append(("delete_user", {"user_id": user.id}))
        return SeededUser(
            id=str(user.id),
            tenant_id=str(user.tenant_id),
            username=user.username,
            email=user.email,
        )

    async def cleanup(self) -> list[str]:
        errors: list[str] = []
        while self._cleanups:
            action, payload = self._cleanups.pop()
            try:
                if action == "demote_platform_admin":
                    await self._demote_platform_admin(payload["user_id"])
                elif action == "delete_user":
                    await self._delete_user(payload["user_id"])
                else:
                    errors.append(f"unknown seed cleanup action: {action}")
            except Exception as exc:  # pragma: no cover - cleanup diagnostics
                errors.append(f"{action}: {exc!r}")
        return errors

    async def _demote_platform_admin(self, user_id: UUID) -> None:
        from qaplatform.infra.database.models import AppUser

        async with self.session_factory() as session:
            await session.execute(
                update(AppUser)
                .where(AppUser.id == user_id)
                .values(is_platform_admin=False)
            )
            await session.commit()

    async def _delete_user(self, user_id: UUID) -> None:
        from qaplatform.infra.database.models import AppUser

        async with self.session_factory() as session:
            await session.execute(delete(AppUser).where(AppUser.id == user_id))
            await session.commit()


@asynccontextmanager
async def api_seed_state_factory(app) -> AsyncIterator[ApiSeedStateFactory]:
    session_factory = app.state.container.db_session_factory
    if session_factory is None:
        raise AssertionError("test app container has no db_session_factory")
    factory = ApiSeedStateFactory(session_factory)
    cleanup_should_raise = True
    try:
        yield factory
    except BaseException:
        cleanup_should_raise = False
        raise
    finally:
        errors = await factory.cleanup()
        if errors and cleanup_should_raise:
            raise AssertionError("API seed state cleanup failed: " + "; ".join(errors))


class _QuietHttpHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


class LocalHttpsGitRepo:
    """Serve a deterministic bare Git repository over local HTTPS."""

    def __init__(self) -> None:
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.url = ""

    def __enter__(self) -> LocalHttpsGitRepo:
        self._tmp = tempfile.TemporaryDirectory(prefix="qap-git-seed-")
        root = Path(self._tmp.name)
        self._create_bare_repo(root)
        cert_path, key_path = self._write_localhost_certificate(root)
        handler = partial(_QuietHttpHandler, directory=str(root))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=cert_path, keyfile=key_path)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        self._server = server
        self.url = f"https://127.0.0.1:{server.server_port}/repo.git"
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._tmp is not None:
            self._tmp.cleanup()

    def _create_bare_repo(self, root: Path) -> None:
        bare = root / "repo.git"
        work = root / "work"
        self._run(["git", "init", "--bare", str(bare)])
        self._run(["git", "init", str(work)])
        self._run(["git", "config", "user.email", "seed@example.test"], cwd=work)
        self._run(["git", "config", "user.name", "QA Seed"], cwd=work)
        self._run(["git", "checkout", "-b", "main"], cwd=work)
        (work / "README.md").write_text("seed repository\n", encoding="utf-8")
        self._run(["git", "add", "README.md"], cwd=work)
        self._run(["git", "commit", "-m", "seed"], cwd=work)
        self._run(["git", "branch", "feature/seed"], cwd=work)
        self._run(["git", "branch", "release/api"], cwd=work)
        self._run(["git", "remote", "add", "origin", str(bare)], cwd=work)
        self._run(["git", "push", "origin", "main", "feature/seed", "release/api"], cwd=work)
        self._run(["git", "--git-dir", str(bare), "symbolic-ref", "HEAD", "refs/heads/main"])
        self._run(["git", "--git-dir", str(bare), "update-server-info"])

    def _write_localhost_certificate(self, root: Path) -> tuple[str, str]:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]
        )
        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName("localhost"),
                        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    ]
                ),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        cert_path = root / "localhost.pem"
        key_path = root / "localhost-key.pem"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
        return str(cert_path), str(key_path)

    def _run(self, args: list[str], *, cwd: Path | None = None) -> None:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"{' '.join(args)} failed with {result.returncode}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
