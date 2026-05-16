"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import BYTEA, INET, JSONB, UUID as PG_UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extensions & schemas
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE SCHEMA IF NOT EXISTS audit")

    # --- tenant ---
    op.create_table(
        "tenant",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("settings", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # --- app_user ---
    op.create_table(
        "app_user",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", PG_UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("username", sa.Text, nullable=False),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False, server_default=sa.text("'user'")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_app_user_tenant_id"),
        sa.UniqueConstraint("tenant_id", "username", name="uq_app_user_tenant_username"),
        sa.UniqueConstraint("tenant_id", "email", name="uq_app_user_tenant_email"),
    )

    # --- api_token ---
    op.create_table(
        "api_token",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("token_id", sa.Text, nullable=False, unique=True),
        sa.Column("secret_hash", sa.Text, nullable=False),
        sa.Column("scopes", JSONB, nullable=False, server_default=sa.text("'[\"*\"]'")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_ip", INET, nullable=True),
        sa.Column("is_revoked", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # --- project ---
    op.create_table(
        "project",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", PG_UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("slug", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("git_url", sa.Text, nullable=False),
        sa.Column("git_auth_method", sa.Text, nullable=False, server_default=sa.text("'none'")),
        sa.Column("credential_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("default_branch", sa.Text, nullable=False, server_default=sa.text("'main'")),
        sa.Column("root_path", sa.Text, nullable=False, server_default=sa.text("'.'")),
        sa.Column("shallow_clone", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("default_env_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("settings", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_by", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_project_tenant_id"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_project_tenant_slug"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by"],
            ["app_user.tenant_id", "app_user.id"],
            name="fk_project_created_by",
        ),
    )

    # --- environment ---
    op.create_table(
        "environment",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", PG_UUID(as_uuid=True), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("base_image", sa.Text, nullable=False),
        sa.Column("setup_script", sa.Text, nullable=True),
        sa.Column("resource_limits", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("network_policy", sa.Text, nullable=False, server_default=sa.text("'deny'")),
        sa.Column("env_vars", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("cache_key", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "name", name="uq_environment_project_name"),
        sa.UniqueConstraint("project_id", "id", name="uq_environment_project_id"),
    )

    # Deferred FKs on project for default_env_id and credential_id
    op.execute(
        """ALTER TABLE project ADD CONSTRAINT fk_project_default_env
           FOREIGN KEY (id, default_env_id) REFERENCES environment(project_id, id)
           DEFERRABLE INITIALLY DEFERRED"""
    )

    # --- pipeline ---
    op.create_table(
        "pipeline",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", PG_UUID(as_uuid=True), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("stages", JSONB, nullable=False),
        sa.Column("selector", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("trigger_config", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("timeout_seconds", sa.Integer, nullable=False, server_default=sa.text("1800")),
        sa.Column("retry_policy", JSONB, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "name", name="uq_pipeline_project_name"),
        sa.UniqueConstraint("project_id", "id", name="uq_pipeline_project_id"),
    )

    # --- credential ---
    op.create_table(
        "credential",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", PG_UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("project_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("encrypted_value", BYTEA, nullable=False),
        sa.Column("created_by", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "name", name="uq_credential_project_name"),
        sa.UniqueConstraint("project_id", "id", name="uq_credential_project_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["project.tenant_id", "project.id"],
            name="fk_credential_project",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by"],
            ["app_user.tenant_id", "app_user.id"],
            name="fk_credential_created_by",
        ),
    )

    # Deferred FK on project for credential_id
    op.execute(
        """ALTER TABLE project ADD CONSTRAINT fk_project_credential
           FOREIGN KEY (id, credential_id) REFERENCES credential(project_id, id)
           DEFERRABLE INITIALLY DEFERRED"""
    )

    # --- run ---
    op.create_table(
        "run",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", PG_UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("project_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("environment_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'queued'")),
        sa.Column("trigger_type", sa.Text, nullable=False),
        sa.Column("priority", sa.SmallInteger, nullable=False, server_default=sa.text("1")),
        sa.Column("triggered_by", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("git_ref", sa.Text, nullable=False),
        sa.Column("git_sha", sa.Text, nullable=True),
        sa.Column("retry_group_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("attempt", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("source_run_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("chain_depth", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("dedup_key", sa.Text, nullable=True),
        sa.Column("dedup_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queue_name", sa.Text, nullable=True),
        sa.Column("arq_job_id", sa.Text, nullable=True, unique=True),
        sa.Column("execution_id", sa.Text, nullable=True),
        sa.Column("worker_id", sa.Text, nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("summary", JSONB, nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "id", name="uq_run_project_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["project.tenant_id", "project.id"],
            name="fk_run_tenant_project",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "pipeline_id"],
            ["pipeline.project_id", "pipeline.id"],
            name="fk_run_pipeline",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "environment_id"],
            ["environment.project_id", "environment.id"],
            name="fk_run_environment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "triggered_by"],
            ["app_user.tenant_id", "app_user.id"],
            name="fk_run_triggered_by",
        ),
    )

    # Run indexes
    op.create_index("idx_run_project_status", "run", ["project_id", "status", sa.text("created_at DESC")])
    op.create_index("idx_run_project_created", "run", ["project_id", sa.text("created_at DESC")])
    op.create_index(
        "idx_run_status_created", "run", ["status", "created_at"],
        postgresql_where=sa.text("status IN ('queued', 'preparing', 'running')"),
    )
    op.create_index(
        "idx_run_active_dedup", "run", ["project_id", "pipeline_id", "dedup_key"],
        unique=True,
        postgresql_where=sa.text("dedup_key IS NOT NULL AND status IN ('queued', 'preparing', 'running', 'collecting')"),
    )
    op.create_index(
        "idx_run_dedup_lookup", "run", ["project_id", "pipeline_id", "dedup_key", "dedup_expires_at"],
        postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )
    op.create_index(
        "idx_run_stale", "run", ["status", "status_updated_at"],
        postgresql_where=sa.text("status IN ('preparing', 'collecting')"),
    )
    op.create_index(
        "idx_run_waiting", "run", ["priority", "created_at"],
        postgresql_where=sa.text("status = 'queued' AND enqueued_at IS NULL"),
    )

    # --- test_result ---
    op.create_table(
        "test_result",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", PG_UUID(as_uuid=True), sa.ForeignKey("run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("suite", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("stack_trace", sa.Text, nullable=True),
        sa.Column("tags", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("run_id", "suite", "name", name="uq_test_result_run_suite_name"),
    )
    op.create_index("idx_test_result_run", "test_result", ["run_id"])
    op.create_index("idx_test_result_status", "test_result", ["run_id", "status"])
    op.create_index("idx_test_result_flaky", "test_result", ["suite", "name", "status"])

    # --- artifact ---
    op.create_table(
        "artifact",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", PG_UUID(as_uuid=True), sa.ForeignKey("run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("storage_path", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("mime_type", sa.Text, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_artifact_run", "artifact", ["run_id"])

    # --- run_event ---
    op.create_table(
        "run_event",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", PG_UUID(as_uuid=True), sa.ForeignKey("run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_run_event_run_created", "run_event", ["run_id", "created_at"])

    # --- schedule ---
    op.create_table(
        "schedule",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("cron_expr", sa.Text, nullable=False),
        sa.Column("timezone", sa.Text, nullable=False, server_default=sa.text("'Asia/Shanghai'")),
        sa.Column("missed_fire_policy", sa.Text, nullable=False, server_default=sa.text("'skip'")),
        sa.Column("quiet_windows", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "id", name="uq_schedule_project_id"),
        sa.ForeignKeyConstraint(
            ["project_id", "pipeline_id"],
            ["pipeline.project_id", "pipeline.id"],
            name="fk_schedule_pipeline",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_schedule_next", "schedule", ["next_run_at"],
        postgresql_where=sa.text("enabled = true"),
    )

    # --- project_member ---
    op.create_table(
        "project_member",
        sa.Column("tenant_id", PG_UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("project_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.Text, nullable=False, server_default=sa.text("'developer'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("project_id", "user_id", name="pk_project_member"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["project.tenant_id", "project.id"],
            name="fk_project_member_project",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["app_user.tenant_id", "app_user.id"],
            name="fk_project_member_user",
            ondelete="CASCADE",
        ),
    )

    # --- notification_rule ---
    op.create_table(
        "notification_rule",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", PG_UUID(as_uuid=True), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("conditions", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("channels", JSONB, nullable=False),
        sa.Column("template", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "id", name="uq_notification_rule_project_id"),
    )

    # --- notification_log ---
    op.create_table(
        "notification_log",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("channel_type", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("run_id", "rule_id", "channel_type", name="uq_notification_log_run_rule_channel"),
        sa.ForeignKeyConstraint(
            ["project_id", "run_id"],
            ["run.project_id", "run.id"],
            name="fk_notification_log_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "rule_id"],
            ["notification_rule.project_id", "notification_rule.id"],
            name="fk_notification_log_rule",
            ondelete="CASCADE",
        ),
    )

    # --- audit.event (audit schema) ---
    op.create_table(
        "event",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("resource_type", sa.Text, nullable=False),
        sa.Column("resource_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("before_state", JSONB, nullable=True),
        sa.Column("after_state", JSONB, nullable=True),
        sa.Column("ip_address", INET, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="audit",
    )
    op.create_index(
        "idx_audit_resource", "event", ["resource_type", "resource_id", sa.text("created_at DESC")],
        schema="audit",
    )
    op.create_index(
        "idx_audit_user", "event", ["user_id", sa.text("created_at DESC")],
        schema="audit",
    )


def downgrade() -> None:
    op.drop_table("event", schema="audit")
    op.drop_table("notification_log")
    op.drop_table("notification_rule")
    op.drop_table("project_member")
    op.drop_table("schedule")
    op.drop_table("run_event")
    op.drop_table("artifact")
    op.drop_table("test_result")
    op.drop_table("run")
    op.drop_table("credential")
    op.drop_table("pipeline")
    op.execute("ALTER TABLE project DROP CONSTRAINT IF EXISTS fk_project_default_env")
    op.execute("ALTER TABLE project DROP CONSTRAINT IF EXISTS fk_project_credential")
    op.drop_table("environment")
    op.drop_table("project")
    op.drop_table("api_token")
    op.drop_table("app_user")
    op.drop_table("tenant")
    op.execute("DROP SCHEMA IF EXISTS audit CASCADE")
