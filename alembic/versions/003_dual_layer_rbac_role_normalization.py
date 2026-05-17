"""Dual-layer RBAC: normalise legacy app_user.role values, add is_platform_admin

Revision ID: 003
Revises: 002
Create Date: 2026-05-17

Background
----------
PRD §F-AU-03 mandates a dual-layer RBAC: tenant-level (Owner/Admin/Member/Viewer)
intersected with project-level (Admin/Developer/Viewer). The historical
``app_user.role`` column carried tenant-level strings ``platform_admin`` /
``developer`` / ``user``; the new canonical names are ``admin`` / ``member``.

Note: ``project_member.role`` already uses the canonical project-level names
(``admin``/``developer``/``viewer``) and must not be touched here. The literal
``'developer'`` means *tenant Member* in ``app_user.role`` but *project
Developer* in ``project_member.role`` — same string, different scope.

A new ``is_platform_admin`` boolean flag is introduced so the cross-tenant
super-user concept can survive without overloading the role string.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column(
            "is_platform_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Pre-existing 'platform_admin' rows become tenant Admin + platform-admin flag.
    op.execute(
        """
        UPDATE app_user
        SET is_platform_admin = true,
            role = 'admin'
        WHERE role = 'platform_admin'
        """
    )

    op.execute(
        """
        UPDATE app_user
        SET role = 'member'
        WHERE role IN ('developer', 'user')
        """
    )

    # Refresh the column default so newly created rows land on the canonical
    # tenant role name.
    op.alter_column("app_user", "role", server_default=sa.text("'member'"))


def downgrade() -> None:
    op.execute(
        """
        UPDATE app_user
        SET role = 'platform_admin'
        WHERE is_platform_admin = true
        """
    )
    op.execute(
        """
        UPDATE app_user
        SET role = 'developer'
        WHERE role = 'member'
        """
    )
    op.alter_column("app_user", "role", server_default=sa.text("'user'"))
    op.drop_column("app_user", "is_platform_admin")
