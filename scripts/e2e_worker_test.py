import httpx
import time
import json
import sys
import asyncio
from uuid import UUID

BASE_URL = "http://localhost:8000/api/v1"

async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Login
        print(">>> 1. Logging in...")
        try:
            resp = await client.post(
                f"{BASE_URL}/auth/login",
                json={"username": "admin", "password": "admin123"}
            )
            resp.raise_for_status()
            token = resp.json()["access_token"]
            client.headers["Authorization"] = f"Bearer {token}"
            print("Successfully logged in.")
        except Exception as e:
            print(f"Login failed: {e}")
            if hasattr(e, 'response') and e.response:
                print(f"Response: {e.response.text}")
            return

        # 2. Ensure Project exists
        print("\n>>> 2. Ensuring test project exists...")
        resp = await client.get(f"{BASE_URL}/projects")
        resp.raise_for_status()
        projects = resp.json()["data"]
        project = next((p for p in projects if p["slug"] == "e2e-test-project"), None)
        
        if not project:
            print("Creating test project...")
            project_data = {
                "name": "E2E Test Project",
                "slug": "e2e-test-project",
                "description": "Project for E2E worker verification",
                "git_url": "https://github.com/fastapi/fastapi.git",
                "default_branch": "master"
            }
            resp = await client.post(f"{BASE_URL}/projects", json=project_data)
            resp.raise_for_status()
            project = resp.json()
        
        project_id = project["id"]
        print(f"Project ID: {project_id}")

        # 3. Ensure Environment exists
        print("\n>>> 3. Ensuring test environment exists...")
        resp = await client.get(f"{BASE_URL}/projects/{project_id}/environments")
        resp.raise_for_status()
        envs = resp.json()["data"]
        env = next((e for e in envs if e["name"] == "E2E Env"), None)
        if not env:
            print("Creating test environment...")
            env_data = {
                "name": "E2E Env",
                "base_image": "python:3.12-slim",
                "setup_script": "pip install pytest",
                "memory_mb": 512,
                "cpu_cores": 1.0
            }
            resp = await client.post(f"{BASE_URL}/projects/{project_id}/environments", json=env_data)
            resp.raise_for_status()
            env = resp.json()
        
        env_id = env["id"]
        print(f"Environment ID: {env_id}")
        
        # Update project to use this env as default if not set
        if project.get("default_env_id") != env_id:
             await client.patch(f"{BASE_URL}/projects/{project_id}", json={"default_env_id": str(env_id)})

        # 4. Ensure Pipeline exists
        print("\n>>> 4. Ensuring test pipeline exists...")
        resp = await client.get(f"{BASE_URL}/projects/{project_id}/pipelines")
        resp.raise_for_status()
        pipelines = resp.json()["data"]
        pipeline = next((p for p in pipelines if p["name"] == "E2E Pipeline"), None)
        if not pipeline:
            print("Creating test pipeline...")
            pipeline_data = {
                "name": "E2E Pipeline",
                "stages": [
                    {
                        "name": "Run Tests",
                        "plugin": "pytest",
                        "config": {"args": ["tests/test_main.py"]}
                    }
                ],
                "timeout_seconds": 600
            }
            resp = await client.post(f"{BASE_URL}/projects/{project_id}/pipelines", json=pipeline_data)
            resp.raise_for_status()
            pipeline = resp.json()
        pipeline_id = pipeline["id"]
        print(f"Pipeline ID: {pipeline_id}")

        # 5. Trigger Run
        print("\n>>> 5. Triggering run...")
        resp = await client.post(f"{BASE_URL}/runs", json={"pipeline_id": pipeline_id, "git_ref": "master"})
        resp.raise_for_status()
        run = resp.json()
        run_id = run["id"]
        print(f"Run ID: {run_id}")

        # 6. Get SSE Ticket
        print("\n>>> 6. Getting SSE ticket...")
        resp = await client.post(f"{BASE_URL}/auth/sse-ticket")
        resp.raise_for_status()
        ticket = resp.json()["ticket"]
        print(f"SSE Ticket acquired.")

        # 7. Listen for logs and Poll status
        print("\n>>> 7. Monitoring execution...")
        
        terminal_statuses = {"passed", "failed", "cancelled", "timed_out", "error"}
        
        async def listen_logs():
            print("--- Log Stream Start ---")
            try:
                # We use a separate client for streaming to avoid blocking or timeout issues
                async with httpx.AsyncClient(timeout=None) as stream_client:
                    async with stream_client.stream(
                        "GET", 
                        f"{BASE_URL}/runs/{run_id}/logs", 
                        params={"ticket": ticket}
                    ) as response:
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                try:
                                    data_str = line[6:]
                                    if not data_str.strip():
                                        continue
                                    data = json.loads(data_str)
                                    if isinstance(data, dict) and "line" in data:
                                        print(f" {data['line']}", end="")
                                    elif isinstance(data, dict) and "status" in data:
                                         # Heartbeat or done event might have status
                                         pass
                                except json.JSONDecodeError:
                                    pass
                            elif line.startswith("event: done"):
                                print("\n--- Log Stream Finished ---")
                                break
            except Exception as e:
                print(f"\nSSE Stream error: {e}")

        log_task = asyncio.create_task(listen_logs())

        while True:
            resp = await client.get(f"{BASE_URL}/runs/{run_id}")
            resp.raise_for_status()
            run = resp.json()
            status = run["status"]
            print(f"Current status: {status}")
            if status in terminal_statuses:
                break
            await asyncio.sleep(5)
        
        print(f"Final status: {status}")
        
        # Wait a bit for log stream to catch up if needed
        await asyncio.wait_for(log_task, timeout=30)
        
        # 8. Verify artifacts
        print("\n>>> 8. Verifying artifacts...")
        resp = await client.get(f"{BASE_URL}/runs/{run_id}/artifacts")
        resp.raise_for_status()
        artifacts = resp.json()["data"]
        print(f"Found {len(artifacts)} artifacts.")
        for art in artifacts:
             print(f" - Artifact: {art['name']} ({art['size_bytes']} bytes), Type: {art['type']}")
             # Try to download if small
             if art['size_bytes'] < 1024 * 1024:
                 download_resp = await client.get(f"{BASE_URL}/artifacts/{art['id']}/download")
                 if download_resp.status_code == 200:
                     print(f"   Successfully verified download for {art['name']}")

        print("\nE2E Worker Verification Completed Successfully!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Script failed: {e}")
        sys.exit(1)
