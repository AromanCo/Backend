.PHONY: up down migrate seed test lint typecheck run

up:
	docker compose up -d db
	docker compose --profile tools run --build --rm migrate
	docker compose up -d --build api

down:
	docker compose down

migrate:
	docker compose --profile tools run --build --rm migrate

seed:
	docker compose --profile tools run --rm migrate aroman-seed

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check aroman tests alembic

typecheck:
	.venv/bin/mypy aroman

run:
	.venv/bin/uvicorn aroman.main:app --reload --no-access-log --no-proxy-headers
