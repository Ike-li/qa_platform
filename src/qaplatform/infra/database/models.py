"""SQLAlchemy 2.0 ORM models for QA Platform."""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import (
    BIGINT,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Float,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import BYTEA, INET, JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _gen_uuid() -> str:
    return "gen_random_uuid()"


# ---------- Enums ----------


class RunStatusEnum(str, enum.Enum):
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    COLLECTING = "collecting"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TestResultStatusEnum(str, enum.Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"
    XFAIL = "xfail"


class NotificationStatusEnum(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


# ---------- Base ----------


class Base(DeclarativeBase):
    __soft_deletable__ = True

    @declared_attr
    def deleted_at(cls):
        if cls.__dict__.get("__soft_deletable__", True):
            return mapped_column(DateTime(timezone=True), nullable=True, default=None)
        return None


class AuditBase(DeclarativeBase):
    """Separate base for the audit schema."""
    pass


# ---------- Default-schema tables ----------


class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text(_gen_uuid())
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), onupdate=_utcnow
    )


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_app_user_tenant_id"),
        UniqueConstraint("tenant_id", "username", name="uq_app_user_tenant_username"),
        UniqueConstraint("tenant_id", "email", name="uq_app_user_tenant_email"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text(_gen_uuid())
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False
    )
    username: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'member'"))
    is_platform_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    tenant: Mapped[Tenant] = relationship("Tenant", lazy="joined")
    api_tokens: Mapped[list[ApiToken]] = relationship("ApiToken", back_populates="user", lazy="selectin")


class ApiToken(Base):
    __tablename__ = "api_token"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text(_gen_uuid())
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    token_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    secret_hash: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[\"*\"]'"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    is_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped[AppUser] = relationship("AppUser", back_populates="api_tokens", lazy="joined")


class Project(Base):
    __tablename__ = "project"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_project_tenant_id"),
        UniqueConstraint("tenant_id", "slug", name="uq_project_tenant_slug"),
        ForeignKeyConstraint(
            ["tenant_id", "created_by"],
            ["app_user.tenant_id", "app_user.id"],
            name="fk_project_created_by",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text(_gen_uuid())
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    git_url: Mapped[str] = mapped_column(Text, nullable=False)
    git_auth_method: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'none'"))
    credential_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    default_branch: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'main'"))
    root_path: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'.'"))
    shallow_clone: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    default_env_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), onupdate=_utcnow
    )

    tenant: Mapped[Tenant] = relationship("Tenant", lazy="joined")
    environments: Mapped[list[Environment]] = relationship("Environment", back_populates="project", lazy="selectin")
    pipelines: Mapped[list[Pipeline]] = relationship("Pipeline", back_populates="project", lazy="selectin")
    credentials: Mapped[list[Credential]] = relationship("Credential", back_populates="project", lazy="selectin")
    members: Mapped[list[ProjectMember]] = relationship("ProjectMember", back_populates="project", lazy="selectin")


class Environment(Base):
    __tablename__ = "environment"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_environment_project_name"),
        UniqueConstraint("project_id", "id", name="uq_environment_project_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text(_gen_uuid())
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    base_image: Mapped[str] = mapped_column(Text, nullable=False)
    setup_script: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_mb: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("512"))
    cpu_cores: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("1.0"))
    resource_limits: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
        server_default=text("'{}'"),
    )
    network_policy: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'deny'"))
    env_vars: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    cache_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    project: Mapped[Project] = relationship("Project", back_populates="environments")


class Pipeline(Base):
    __tablename__ = "pipeline"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_pipeline_project_name"),
        UniqueConstraint("project_id", "id", name="uq_pipeline_project_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text(_gen_uuid())
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    stages: Mapped[list] = mapped_column(JSONB, nullable=False)
    selector: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    trigger_config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1800"))
    retry_policy: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), onupdate=_utcnow
    )

    project: Mapped[Project] = relationship("Project", back_populates="pipelines")
    runs: Mapped[list[Run]] = relationship("Run", back_populates="pipeline", lazy="noload")
    schedules: Mapped[list[Schedule]] = relationship("Schedule", back_populates="pipeline", lazy="selectin")


class Credential(Base):
    __tablename__ = "credential"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_credential_project_name"),
        UniqueConstraint("project_id", "id", name="uq_credential_project_id"),
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["project.tenant_id", "project.id"],
            name="fk_credential_project",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by"],
            ["app_user.tenant_id", "app_user.id"],
            name="fk_credential_created_by",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text(_gen_uuid())
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_value: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    project: Mapped[Project] = relationship("Project", back_populates="credentials", lazy="joined")


class Run(Base):
    __tablename__ = "run"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_run_project_id"),
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["project.tenant_id", "project.id"],
            name="fk_run_tenant_project",
        ),
        ForeignKeyConstraint(
            ["project_id", "pipeline_id"],
            ["pipeline.project_id", "pipeline.id"],
            name="fk_run_pipeline",
        ),
        ForeignKeyConstraint(
            ["project_id", "environment_id"],
            ["environment.project_id", "environment.id"],
            name="fk_run_environment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "triggered_by"],
            ["app_user.tenant_id", "app_user.id"],
            name="fk_run_triggered_by",
        ),
        Index("idx_run_project_status", "project_id", "status", "created_at"),
        Index("idx_run_project_created", "project_id", "created_at"),
        Index(
            "idx_run_status_created",
            "status",
            "created_at",
            postgresql_where=text("status IN ('queued', 'preparing', 'running')"),
        ),
        Index(
            "idx_run_active_dedup",
            "project_id",
            "pipeline_id",
            "dedup_key",
            unique=True,
            postgresql_where=text(
                "dedup_key IS NOT NULL AND status IN ('queued', 'preparing', 'running', 'collecting')"
            ),
        ),
        Index(
            "idx_run_dedup_lookup",
            "project_id",
            "pipeline_id",
            "dedup_key",
            "dedup_expires_at",
            postgresql_where=text("dedup_key IS NOT NULL"),
        ),
        Index(
            "idx_run_stale",
            "status",
            "status_updated_at",
            postgresql_where=text("status IN ('preparing', 'collecting')"),
        ),
        Index(
            "idx_run_waiting",
            "priority",
            "created_at",
            postgresql_where=text("status = 'queued' AND enqueued_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text(_gen_uuid())
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    pipeline_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    environment_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    status: Mapped[RunStatusEnum] = mapped_column(
        Enum(RunStatusEnum, name="run_status_enum", native_enum=False, create_constraint=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default=text("'queued'"),
    )
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    triggered_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    git_ref: Mapped[str] = mapped_column(Text, nullable=False)
    git_sha: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Retry tracking
    retry_group_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    # Event chain
    source_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    chain_depth: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Control plane
    dedup_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedup_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    queue_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    arq_job_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    execution_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'"))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), onupdate=_utcnow
    )

    tenant: Mapped[Tenant] = relationship("Tenant", lazy="joined")
    project: Mapped[Project] = relationship(
        "Project",
        primaryjoin="and_(Run.project_id == Project.id, Run.tenant_id == Project.tenant_id)",
        foreign_keys=[project_id, tenant_id],
        lazy="joined",
    )
    pipeline: Mapped[Pipeline] = relationship(
        "Pipeline",
        primaryjoin="and_(Run.pipeline_id == Pipeline.id, Run.project_id == Pipeline.project_id)",
        foreign_keys=[pipeline_id, project_id],
        back_populates="runs",
        lazy="joined",
        overlaps="project",
    )
    environment: Mapped[Environment] = relationship(
        "Environment",
        primaryjoin="Run.environment_id == Environment.id",
        foreign_keys="[Run.environment_id]",
        lazy="joined",
    )
    test_results: Mapped[list[TestResult]] = relationship("TestResult", back_populates="run", lazy="noload")
    artifacts: Mapped[list[Artifact]] = relationship("Artifact", back_populates="run", lazy="noload")
    run_events: Mapped[list[RunEvent]] = relationship("RunEvent", back_populates="run", lazy="noload")


class TestResult(Base):
    __tablename__ = "test_result"
    __soft_deletable__ = False
    __table_args__ = (
        UniqueConstraint("run_id", "suite", "name", name="uq_test_result_run_suite_name"),
        Index("idx_test_result_run", "run_id"),
        Index("idx_test_result_status", "run_id", "status"),
        Index("idx_test_result_flaky", "suite", "name", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text(_gen_uuid())
    )
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("run.id", ondelete="CASCADE"), nullable=False
    )
    suite: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TestResultStatusEnum] = mapped_column(
        Enum(TestResultStatusEnum, name="test_result_status_enum", native_enum=False, create_constraint=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    stack_trace: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    run: Mapped[Run] = relationship("Run", back_populates="test_results")


class Artifact(Base):
    __tablename__ = "artifact"
    __table_args__ = (Index("idx_artifact_run", "run_id"),)

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text(_gen_uuid())
    )
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("run.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BIGINT, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    run: Mapped[Run] = relationship("Run", back_populates="artifacts")


class RunEvent(Base):
    __tablename__ = "run_event"
    __soft_deletable__ = False
    __table_args__ = (Index("idx_run_event_run_created", "run_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text(_gen_uuid())
    )
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("run.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    run: Mapped[Run] = relationship("Run", back_populates="run_events")


class Schedule(Base):
    __tablename__ = "schedule"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_schedule_project_id"),
        ForeignKeyConstraint(
            ["project_id", "pipeline_id"],
            ["pipeline.project_id", "pipeline.id"],
            name="fk_schedule_pipeline",
            ondelete="CASCADE",
        ),
        Index("idx_schedule_next", "next_run_at", postgresql_where=text("enabled = true")),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text(_gen_uuid())
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    pipeline_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    cron_expr: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'Asia/Shanghai'"))
    missed_fire_policy: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'skip'"))
    quiet_windows: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    pipeline: Mapped[Pipeline] = relationship("Pipeline", back_populates="schedules")


class NotificationRule(Base):
    __tablename__ = "notification_rule"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_notification_rule_project_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text(_gen_uuid())
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    conditions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    channels: Mapped[list] = mapped_column(JSONB, nullable=False)
    template: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    notifications: Mapped[list[NotificationLog]] = relationship("NotificationLog", back_populates="rule", lazy="noload")


class NotificationLog(Base):
    __tablename__ = "notification_log"
    __soft_deletable__ = False
    __table_args__ = (
        UniqueConstraint("run_id", "rule_id", "channel_type", name="uq_notification_log_run_rule_channel"),
        ForeignKeyConstraint(
            ["project_id", "run_id"],
            ["run.project_id", "run.id"],
            name="fk_notification_log_run",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["project_id", "rule_id"],
            ["notification_rule.project_id", "notification_rule.id"],
            name="fk_notification_log_rule",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text(_gen_uuid())
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    rule_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    channel_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[NotificationStatusEnum] = mapped_column(
        Enum(NotificationStatusEnum, name="notification_status_enum", create_constraint=False),
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    rule: Mapped[NotificationRule] = relationship("NotificationRule", back_populates="notifications")


class ProjectMember(Base):
    __tablename__ = "project_member"
    __table_args__ = (
        PrimaryKeyConstraint("project_id", "user_id", name="pk_project_member"),
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["project.tenant_id", "project.id"],
            name="fk_project_member_project",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["app_user.tenant_id", "app_user.id"],
            name="fk_project_member_user",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'developer'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    project: Mapped[Project] = relationship("Project", back_populates="members", overlaps="user")
    user: Mapped[AppUser] = relationship("AppUser", lazy="joined", overlaps="members,project")


# ---------- Audit schema table ----------


class AuditEvent(AuditBase):
    __tablename__ = "event"
    __table_args__ = (
        Index("idx_audit_resource", "resource_type", "resource_id", "created_at"),
        Index("idx_audit_user", "user_id", "created_at"),
        {"schema": "audit"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text(_gen_uuid())
    )
    tenant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    before_state: Mapped[dict | None] = mapped_column("before_state", JSONB, nullable=True)
    after_state: Mapped[dict | None] = mapped_column("after_state", JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
