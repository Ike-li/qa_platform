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
    expected_response = {
        "id": env_id,
        "project_id": project_id,
        "name": "encrypted-env",
        "base_image": "python:3.12.1",
        "setup_script": None,
        "memory_mb": 512,
        "cpu_cores": 1.0,
        "disk_mb": None,
        "max_artifact_size_mb": 100,
        "max_artifacts_count": 50,
        "network_policy": "deny",
        "env_vars": first_env,
        "cache_key": None,
        "created_at": body["created_at"],
    }
    assert body == expected_response

    stored = await _db_env_vars(integration_db_session, env_id)
    assert "API_TOKEN" not in repr(stored)
    assert "secret-value" not in repr(stored)

    get_resp = await integration_client.get(
        f"/api/v1/projects/{project_id}/environments/{env_id}"
    )
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json() == expected_response

    next_env = {"NEW_TOKEN": "rotated-secret"}
    update_resp = await integration_client.put(
        f"/api/v1/projects/{project_id}/environments/{env_id}",
        json={"env_vars": next_env},
    )
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json() == {
        **expected_response,
        "env_vars": next_env,
    }

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
    assert mismatch_resp.json() == {"detail": "Environment env vars decrypt failed"}
    assert "TOKEN" not in mismatch_resp.text
    assert "bound-to-source" not in mismatch_resp.text

    audit_result = await integration_db_session.execute(
        sa.text(
            """
            SELECT
                tenant_id::text AS tenant_id,
                user_id::text AS user_id,
                action,
                resource_type,
                resource_id::text AS resource_id,
                before_state,
                after_state
            FROM audit.event
            WHERE resource_id = :resource_id
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"resource_id": target_id},
    )
    audit = audit_result.mappings().one()
    assert audit["tenant_id"] == str(seed_run["tenant"].id)
    assert audit["user_id"] == str(seed_run["user"].id)
    assert audit["action"] == "environment.env_vars_decrypt_failed"
    assert audit["resource_type"] == "environment"
    assert audit["resource_id"] == target_id
    assert audit["before_state"] is None
    assert audit["after_state"] == {
        "operation": "decrypt",
        "project_id": project_id,
        "environment_id": target_id,
        "error_type": "ValueError",
    }
    serialized_failure = repr(
        [mismatch_resp.text, audit["before_state"], audit["after_state"]]
    )
    for forbidden in ["TOKEN", "bound-to-source", source_id]:
        assert forbidden not in serialized_failure
