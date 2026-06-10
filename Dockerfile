FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Dependency layer first for build caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
# Writable state lives on the mounted volume (see fly.toml).
ENV AEGIS_SQLITE_PATH=/data/aegis.sqlite
ENV AEGIS_LOG_DIR=/data/logs

CMD ["aegis-collect"]
