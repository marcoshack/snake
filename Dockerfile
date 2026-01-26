# syntax=docker/dockerfile:1

FROM python:3.14-rc-slim

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files first for better layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies using uv (frozen to match lock file)
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY main.py tools.py ./

# Create output directory for reports
RUN mkdir -p /app/build/output

# Run the agent
CMD ["uv", "run", "python", "main.py"]
