"""Seed script: create default tenant and admin user."""

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from argon2 import PasswordHasher

DATABASE_URL = os.environ.get(
    "QAP_DATABASE_URL",
    "postgresql+asyncpg://qaplatform:qaplatform@localhost:5432/qaplatform",
)

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@qaplatform.local")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
TENANT_NAME = os.environ.get("TENANT_NAME", "default")


async def main():
    engine = create_async_engine(DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    ph = PasswordHasher()
    password_hash = ph.hash(ADMIN_PASSWORD)

    async with async_session() as session:
        # Create tenant if not exists
        result = await session.execute(
            text("SELECT id FROM tenant WHERE name = :name"), {"name": TENANT_NAME}
        )
        tenant_row = result.fetchone()

        if tenant_row:
            tenant_id = tenant_row[0]
            print(f"Tenant '{TENANT_NAME}' already exists: {tenant_id}")
        else:
            result = await session.execute(
                text(
                    "INSERT INTO tenant (name) VALUES (:name) RETURNING id"
                ),
                {"name": TENANT_NAME},
            )
            tenant_id = result.fetchone()[0]
            print(f"Created tenant '{TENANT_NAME}': {tenant_id}")

        # Create admin user if not exists
        result = await session.execute(
            text(
                "SELECT id FROM app_user WHERE tenant_id = :tid AND username = :username"
            ),
            {"tid": tenant_id, "username": ADMIN_USERNAME},
        )
        user_row = result.fetchone()

        if user_row:
            await session.execute(
                text(
                    """UPDATE app_user
                    SET email = :email,
                        password_hash = :password_hash,
                        role = 'admin',
                        is_active = true
                    WHERE id = :user_id"""
                ),
                {
                    "email": ADMIN_EMAIL,
                    "password_hash": password_hash,
                    "user_id": user_row[0],
                },
            )
            print(f"Updated admin user '{ADMIN_USERNAME}': {user_row[0]}")
        else:
            result = await session.execute(
                text(
                    """INSERT INTO app_user (tenant_id, username, email, password_hash, role)
                    VALUES (:tid, :username, :email, :password_hash, 'admin')
                    RETURNING id"""
                ),
                {
                    "tid": tenant_id,
                    "username": ADMIN_USERNAME,
                    "email": ADMIN_EMAIL,
                    "password_hash": password_hash,
                },
            )
            user_id = result.fetchone()[0]
            print(f"Created admin user '{ADMIN_USERNAME}': {user_id}")

        await session.commit()

    await engine.dispose()
    print(f"\nLogin credentials:\n  username: {ADMIN_USERNAME}\n  password: {ADMIN_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
