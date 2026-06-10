"""Tests for project repository."""

import pytest

from qaplatform.infra.database.repositories.project_repo import ProjectRepository


@pytest.mark.asyncio
async def test_project_repo_get_by_slug(integration_db_session, seed_run):
    """Test get project by slug."""
    repo = ProjectRepository(integration_db_session)
    project = seed_run["project"]
    tenant = seed_run["tenant"]

    result = await repo.get_by_slug(tenant.id, project.slug)

    assert result is not None
    assert result.id == project.id


@pytest.mark.asyncio
async def test_project_repo_get_by_slug_not_found(integration_db_session, seed_run):
    """Test get project by slug returns None when not found."""
    repo = ProjectRepository(integration_db_session)
    tenant = seed_run["tenant"]

    result = await repo.get_by_slug(tenant.id, "nonexistent-slug")

    assert result is None


@pytest.mark.asyncio
async def test_project_repo_list_by_tenant(integration_db_session, seed_run):
    """Test list projects by tenant."""
    repo = ProjectRepository(integration_db_session)
    tenant = seed_run["tenant"]

    projects, count = await repo.list_by_tenant(tenant.id, offset=0, limit=20)

    assert count >= 1
    assert len(projects) >= 1


@pytest.mark.asyncio
async def test_project_repo_list_filtered_by_status(integration_db_session, seed_run):
    """Test list projects filtered by status."""
    repo = ProjectRepository(integration_db_session)
    tenant = seed_run["tenant"]
    project = seed_run["project"]

    projects, count = await repo.list_filtered_by_tenant(
        tenant.id, offset=0, limit=20, status=project.status
    )

    assert count >= 1
    assert all(p.status == project.status for p in projects)


@pytest.mark.asyncio
async def test_project_repo_list_filtered_by_query(integration_db_session, seed_run):
    """Test list projects filtered by query."""
    repo = ProjectRepository(integration_db_session)
    tenant = seed_run["tenant"]
    project = seed_run["project"]

    # Search by name
    projects, count = await repo.list_filtered_by_tenant(
        tenant.id, offset=0, limit=20, query=project.name[:5]
    )

    assert count >= 1


@pytest.mark.asyncio
async def test_project_repo_list_by_git_urls(integration_db_session, seed_run):
    """Test list projects by git URLs."""
    repo = ProjectRepository(integration_db_session)
    project = seed_run["project"]

    projects = await repo.list_by_git_urls([project.git_url])

    assert len(projects) >= 1
    assert any(p.id == project.id for p in projects)


@pytest.mark.asyncio
async def test_project_repo_list_by_git_urls_empty(integration_db_session):
    """Test list projects by empty git URLs."""
    repo = ProjectRepository(integration_db_session)

    projects = await repo.list_by_git_urls([])

    assert len(projects) == 0
