# syntax=docker/dockerfile:1

# ---------- Stage 1: build the virtualenv ----------
# The builder has uv and the build cache. None of that ships in the final image.
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
# Copy only the dependency files first: this layer (several GB with torch) is
# rebuilt only when dependencies change, not on every code edit.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra ml --no-install-project


# ---------- Stage 2: runtime ----------
# Why not an nvidia/cuda base image? The PyTorch wheels from PyPI already bundle the
# CUDA and cuDNN libraries they need; the NVIDIA Container Toolkit mounts the host's
# GPU driver into the container at run time. A CUDA base would duplicate gigabytes.
FROM python:3.12-slim-bookworm AS runtime

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

# Run as an unprivileged user: a compromised process can't modify the image or
# act as root on mounted volumes.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /models \
    && chown app:app /models

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

USER app
EXPOSE 8000

# Model weights download to /models (HF_HOME) on first start; mount a volume
# there so restarts don't download them again.
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
