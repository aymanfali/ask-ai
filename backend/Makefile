.PHONY: infra-up infra-down api test lint typecheck migrate

infra-up:
	docker compose up -d postgres redis

infra-down:
	docker compose down

api:
	cd backend && uv run uvicorn ask_ai.main:app --reload --host 127.0.0.1 --port 8000

migrate:
	cd backend && uv run alembic upgrade head

test:
	cd backend && uv run pytest --cov=ask_ai --cov-report=term-missing

lint:
	cd backend && uv run ruff check .

typecheck:
	cd backend && uv run mypy src
