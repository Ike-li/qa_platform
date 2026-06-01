"""Integration tests for soft-delete (deleted_at) behavior.

These tests verify that:
- BaseRepository.delete() sets deleted_at instead of physical delete
- get_by_id, get_for_tenant, list all filter out soft-deleted records
- __soft_deletable__=False models (RunEvent, TestResult, NotificationLog) retain hard-delete
- Soft-deleted records are recoverable by clearing deleted_at
"""
from __future__ import annotations


import pytest
from sqlalchemy import select

from qaplatform.infra.database.models import (
    Pipeline,
    Project,
    RunEvent,
)
from qaplatform.infra.database.repositories.base import BaseRepository
from qaplatform.infra.database.repositories.project_repo import ProjectRepository


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class RunEventRepository(BaseRepository[RunEvent]):
    model = RunEvent


# --------------------------------------------------------------------------- #
# Tests: soft-delete on Project (via ProjectRepository)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_delete_sets_deleted_at(integration_db_session, seed_run):
    """delete() sets deleted_at, record still exists in DB."""
    session = integration_db_session
    project = seed_run["project"]
    repo = ProjectRepository(session)

    assert project.deleted_at is None
    await repo.delete(project)
    await session.commit()

    # deleted_at is set
    assert project.deleted_at is not None

    # Record still exists via raw query (bypasses repo filter)
    raw = await session.execute(
        select(Project).where(Project.id == project.id)
    )
    assert raw.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_get_by_id_excludes_soft_deleted(integration_db_session, seed_run):
    """get_by_id returns None for soft-deleted records."""
    session = integration_db_session
    project = seed_run["project"]
    repo = ProjectRepository(session)

    await repo.delete(project)
    await session.commit()

    result = await repo.get_by_id(project.id)
    assert result is None


@pytest.mark.asyncio
async def test_get_for_tenant_excludes_soft_deleted(integration_db_session, seed_run):
    """get_for_tenant returns None for soft-deleted records."""
    session = integration_db_session
    project = seed_run["project"]
    repo = ProjectRepository(session)

    await repo.delete(project)
    await session.commit()

    result = await repo.get_for_tenant(project.id, project.tenant_id)
    assert result is None


@pytest.mark.asyncio
async def test_list_excludes_soft_deleted(integration_db_session, seed_run):
    """list() returns empty when all records are soft-deleted."""
    session = integration_db_session
    project = seed_run["project"]
    repo = ProjectRepository(session)

    await repo.delete(project)
    await session.commit()

    items, total = await repo.list(
        filters=[Project.tenant_id == project.tenant_id],
        offset=0,
        limit=10,
    )
    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_soft_deleted_record_recoverable(integration_db_session, seed_run):
    """Clearing deleted_at makes the record visible again."""
    session = integration_db_session
    project = seed_run["project"]
    repo = ProjectRepository(session)

    await repo.delete(project)
    await session.commit()

    # Verify deleted
    assert await repo.get_by_id(project.id) is None

    # Recover
    project.deleted_at = None
    await session.commit()

    # Verify visible again
    result = await repo.get_by_id(project.id)
    assert result is not None
    assert result.id == project.id


@pytest.mark.asyncio
async def test_soft_delete_works_for_pipeline(integration_db_session, seed_run):
    """Base-level soft-delete works for non-Project entities (Pipeline)."""
    session = integration_db_session
    pipeline = seed_run["pipeline"]
    repo = BaseRepository[Pipeline](session)
    repo.model = Pipeline

    await repo.delete(pipeline)
    await session.commit()

    result = await repo.get_by_id(pipeline.id)
    assert result is None

    # Raw query still finds it
    raw = await session.execute(
        select(Pipeline).where(Pipeline.id == pipeline.id)
    )
    assert raw.scalar_one_or_none() is not None


# --------------------------------------------------------------------------- #
# Tests: __soft_deletable__ = False (RunEvent)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_run_event_hard_delete(integration_db_session, seed_run):
    """RunEvent (__soft_deletable__=False) is physically deleted."""
    session = integration_db_session
    run = seed_run["run"]

    event = RunEvent(
        run_id=run.id,
        type="status_change",
        payload={"from": "queued", "to": "preparing"},
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)

    repo = RunEventRepository(session)
    await repo.delete(event)
    await session.commit()

    # Physically gone — raw query returns None
    raw = await session.execute(
        select(RunEvent).where(RunEvent.id == event.id)
    )
    assert raw.scalar_one_or_none() is None
