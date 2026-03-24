FROM python:3.12-slim

WORKDIR /app

# Copy uv binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install Python dependencies
# Note: Using binary packages (psycopg2-binary, psycopg[binary])
# so no compilation needed - no git, curl, or build tools required
RUN uv sync --frozen --no-cache

# Copy application code
COPY . .

ENV PATH="/app/.venv/bin:$PATH"

CMD ["uv", "run", "api-backend"]
