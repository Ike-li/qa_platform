.PHONY: up down logs migrate migrate-create test lint format seed

# --- Docker Compose ---
up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

# --- Database migrations ---
migrate:
	alembic upgrade head

migrate-create:
	alembic revision --autogenerate -m "$(msg)"

# --- Quality ---
test:
	pytest

lint:
	ruff check src tests

format:
	ruff format src tests

# --- Seed data ---
seed:
	python -m qaplatform.seed
