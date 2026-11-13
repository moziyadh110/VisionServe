# VisionServe – instructions for Claude Code

## Purpose
This is a learning project. I am preparing for SDE-ML / ML systems roles.
Optimize for my understanding, not just working code.

## How to work with me
- Work one milestone step at a time. Never implement future milestones.
- Before writing code, explain the plan and the backend concept involved.
- Keep code simple and readable; no clever abstractions.
- After writing code, explain each new file in 3–5 lines.
- Point out one thing I should try breaking to learn how it works.
- Add a short docstring explaining *why* to each non-obvious function.

## Git
- Never commit or push. Give me the git commands; I run them.
- Commit messages must not include Co-Authored-By lines or mention Claude.

## Environment
- Windows 11 + WSL2 Ubuntu 24.04, Python 3.12 with uv, RTX 3050 Laptop GPU (6 GB VRAM)
- Model: microsoft/Florence-2-base in FP16, loaded once at startup
- Local services via docker-compose: Postgres 16, Redis 7, MinIO

## Conventions
- FastAPI + async SQLAlchemy 2 + Alembic; Pydantic v2 schemas in app/schemas
- Config only via app/config.py (pydantic-settings); never hard-code secrets
- JSON logs with structlog, including request_id
- Every new endpoint gets a pytest API test; mock the model in tests
- Run `ruff check` and `pytest` before saying a step is done
