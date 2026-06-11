FROM ghcr.io/astral-sh/uv:python3.12-bookworm AS base

WORKDIR /app

# UV_COMPILE_BYTECODE for faster startup; UV_LINK_MODE=copy for cross-filesystem compat
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Install dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy source code
COPY src /app/src

FROM python:3.12.8-slim AS final

EXPOSE 8000

# PYTHONUNBUFFERED=1 to disable output buffering
ENV PYTHONUNBUFFERED=1
ARG VERSION=0.1.0
ENV APP_VERSION=$VERSION

# System deps required by docling (PDF parsing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the virtual environment from the base stage
COPY --from=base /app /app

# Add virtual environment to PATH
ENV PATH="/app/.venv/bin:$PATH"

# Run the application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"] 