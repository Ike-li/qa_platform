from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


async def _db_env_vars(session, env_id: str):
    result = await session.execute(
        sa.text("SELECT env_vars FROM environment WHERE id = :id"),
        {"id": env_id},
    )
    return result.scalar_one()


async def _set_db_env_vars(session, env_id: str, env_vars: dict) -> None:
    stmt = sa.text(
        "UPDATE environment SET env_vars = :env_vars WHERE id = :id"
    ).bindparams(sa.bindparam("env_vars", type_=JSONB))
    await session.execute(stmt, {"id": env_id, "env_vars": env_vars})
    await session.commit()


async def test_environment_env_vars_create_fetch_update_are_encrypted_at_rest(
    integration_client,
    integration_db_session,
    seed_run,
):
    project_id = str(seed_run["project"].id)
    first_env = {"API_TOKEN": "secret-value"}

    create_resp = await integration_client.post(
        f"/api/v1/projects/{project_id}/environments",
        json={
            "name": "encrypted-env",
            "base_image": "python:3.12.1",
            "env_vars": first_env,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    body = create_resp.json()
    env_id = body["id"]
    assert body["env_vars"] == first_env

    stored = await _db_env_vars(integration_db_session, env_id)
    assert "API_TOKEN" not in repr(stored)
    assert "secret-value" not in repr(stored)

    get_resp = await integration_client.get(
        f"/api/v1/projects/{project_id}/environments/{env_id}"
    )
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["env_vars"] == first_env

    next_env = {"NEW_TOKEN": "rotated-secret"}
    update_resp = await integration_client.put(
        f"/api/v1/projects/{project_id}/environments/{env_id}",
        json={"env_vars": next_env},
    )
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["env_vars"] == next_env

    stored_after_update = await _db_env_vars(integration_db_session, env_id)
    assert "NEW_TOKEN" not in repr(stored_after_update)
    assert "rotated-secret" not in repr(stored_after_update)


async def test_environment_env_vars_aad_mismatch_returns_500_and_audits(
    integration_client,
    integration_db_session,
    seed_run,
):
    project_id = str(seed_run["project"].id)

    source_resp = await integration_client.post(
        f"/api/v1/projects/{project_id}/environments",
        json={
            "name": "aad-source",
            "base_image": "python:3.12.1",
            "env_vars": {"TOKEN": "bound-to-source"},
        },
    )
    assert source_resp.status_code == 201, source_resp.text
    source_id = source_resp.json()["id"]

    target_resp = await integration_client.post(
        f"/api/v1/projects/{project_id}/environments",
        json={
            "name": "aad-target",
            "base_image": "python:3.12.1",
            "env_vars": {},
        },
    )
    assert target_resp.status_code == 201, target_resp.text
    target_id = target_resp.json()["id"]

    await _set_db_env_vars(
        integration_db_session,
        target_id,
        await _db_env_vars(integration_db_session, source_id),
    )

    mismatch_resp = await integration_client.get(
        f"/api/v1/projects/{project_id}/environments/{target_id}"
    )
    assert mismatch_resp.status_code == 500, mismatch_resp.text

    audit_result = await integration_db_session.execute(
        sa.text(
            """
            SELECT action, after_state
            FROM audit.event
            WHERE resource_id = :resource_id
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"resource_id": target_id},
    )
    audit = audit_result.mappings().one()
    assert audit["action"] == "environment.env_vars_decrypt_failed"
    assert audit["after_state"]["operation"] == "decrypt"
    assert "bound-to-source" not in repr(audit["after_state"])
