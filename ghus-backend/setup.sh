#!/usr/bin/env bash
# setup.sh — Global Hubs platform project skeleton
set -e

mkdir -p \
  config \
  prompts/extraction \
  prompts/querying \
  prompts/adjudication \
  docs/adr \
  docs/architecture \
  docs/interviews \
  data/raw \
  data/interim \
  data/processed \
  data/exports \
  notebooks \
  src/etl \
  src/enrichment/apis \
  src/enrichment/scrapers \
  src/enrichment/extraction \
  src/db \
  src/agent \
  src/common \
  migrations/versions \
  evals \
  scripts \
  tests/etl \
  tests/enrichment \
  tests/db \
  tests/agent

touch \
  src/__init__.py \
  src/etl/__init__.py \
  src/enrichment/__init__.py \
  src/enrichment/apis/__init__.py \
  src/enrichment/scrapers/__init__.py \
  src/enrichment/extraction/__init__.py \
  src/db/__init__.py \
  src/agent/__init__.py \
  src/common/__init__.py \
  tests/__init__.py \
  tests/etl/__init__.py \
  tests/enrichment/__init__.py \
  tests/db/__init__.py \
  tests/agent/__init__.py

cat > README.md <<'EOF'
# Global Hubs U.S. — Digital Intelligence Platform

AI-enabled platform consolidating internal ecosystem data with
external enrichment across executive education, R&D, and
entrepreneurship & innovation.

## Quick start

## Repository layout
See `docs/architecture/system-overview.md` for the full layout.
EOF

cat > LICENSE <<'EOF'
Internal — All rights reserved.
Property of Global Hubs U.S.
EOF

cat > CHANGELOG.md <<'EOF'
# Changelog

## [Unreleased]
- Initial project skeleton
EOF

cat > .gitignore <<'EOF'
# Secrets
.env
.env.local
*.pem
*.key

# Data — never committed
data/raw/
data/interim/
data/processed/
data/exports/

# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Notebooks
.ipynb_checkpoints/

# OS
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/

# Build
dist/
build/

# Node
node_modules/
.next/

# Local DB
*.db
*.sqlite
EOF

cat > .env.example <<'EOF'
# ---- Database ----
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/globalhubs

# ---- Anthropic ----
ANTHROPIC_API_KEY=sk-ant-...

# ---- Supabase ----
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=

# ---- External data APIs ----
GITHUB_TOKEN=
NSF_API_KEY=

# ---- Observability ----
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
EOF

cat > .python-version <<'EOF'
3.12
EOF

cat > pyproject.toml <<'EOF'
[project]
name = "global-hubs-platform"
version = "0.1.0"
description = "AI-enabled digital intelligence platform for Global Hubs U.S."
requires-python = ">=3.12"
dependencies = [
  "pandas>=2.2",
  "openpyxl>=3.1",
  "ydata-profiling>=4.10",
  "sqlalchemy>=2.0",
  "alembic>=1.13",
  "pydantic>=2.6",
  "python-dotenv>=1.0",
  "httpx>=0.27",
  "anthropic>=0.40",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "ruff>=0.6",
  "ipykernel>=6.29",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.pytest.ini_options]
testpaths = ["tests"]
EOF

cat > Makefile <<'EOF'
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
EOF

cat > docker-compose.yml <<'EOF'
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: globalhubs
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
EOF

cat > docs/learning-log.md <<'EOF'
# Learning log

Two minutes per day. Don't skip.

## Template
### Day N — YYYY-MM-DD
- What I did:
- What I learned:
- What confused me:
- Open questions:
EOF

cat > docs/data-dictionary.md <<'EOF'
# Data dictionary

For every entity: its meaning, its fields, source(s), update cadence,
and validation rules. To be filled in during Phase 1.
EOF

cat > docs/runbook.md <<'EOF'
# Runbook

Operational procedures. To be filled in continuously.

## How to add a new data source
## How to investigate a failed enrichment job
## How to restore from backup
## How to rotate API keys
EOF

cat > docs/use-case-charter.md <<'EOF'
# V1 use case charter

The five concrete questions the platform must answer at Week 16.
To be drafted from stakeholder interviews and signed off by supervisor.

## Use case 1
## Use case 2
## Use case 3
## Use case 4
## Use case 5

---
Signed off by: ____________________  Date: __________
EOF

cat > docs/adr/001-data-storage-format.md <<EOF
# ADR 001: Raw data is preserved unmodified in data/raw/

## Status
Accepted

## Date
$(date +%Y-%m-%d)

## Context
The original spreadsheets are the canonical source of truth.

## Decision
- data/raw/ is read-only and never modified.
- Transformations produce outputs in data/interim/ or data/processed/.

## Consequences
- Re-running the pipeline always produces the same result.
- We can always recover the truth.
EOF

cat > docs/architecture/system-overview.md <<'EOF'
# System overview

To be filled in. See ADRs in docs/adr/ for individual decisions.
EOF

cat > prompts/extraction/organization.md <<'EOF'
# Organization extraction prompt

Version: 0.1
Model: claude-sonnet-4-6

System: [to be drafted]
EOF

cat > evals/golden_dataset.jsonl <<'EOF'
EOF

cat > evals/README.md <<'EOF'
# Evaluation harness

Hand-labeled examples used to test every prompt change.
Build target: 100-150 examples by end of Phase 1.
EOF

git init -q -b main
git add .
git commit -q -m "chore: initial project skeleton"

echo ""
echo "✓ Project skeleton created and committed."
echo ""
echo "Next steps:"
echo "  1. Copy your spreadsheets into data/raw/"
echo "  2. cp .env.example .env  (then fill in values)"
echo "  3. Create a private GitHub repo and push"