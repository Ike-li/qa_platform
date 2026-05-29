FROM python:3.12-slim AS base

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
COPY alembic.ini .
COPY alembic/ alembic/
COPY scripts/seed_admin.py scripts/seed_admin.py

RUN pip install --no-cache-dir .

RUN useradd -u 1000 -m app
USER app:app

EXPOSE 8000

CMD ["uvicorn", "qaplatform.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
