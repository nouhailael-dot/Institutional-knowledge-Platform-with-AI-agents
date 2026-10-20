.PHONY: install db-up db-down migrate profile test lint format clean

install:
	pip install -e ".[dev]"

db-up:
	docker compose up -d

db-down:
	docker compose down

migrate:
	alembic upgrade head

profile:
	python -m src.etl.profile_all

test:
	pytest

lint:
	ruff check src tests

format:
	ruff format src tests

clean:
	rm -rf data/interim/* data/processed/*
	find . -type d -name __pycache__ -exec rm -rf {} +
