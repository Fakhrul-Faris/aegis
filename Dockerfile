FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Dependency layer first for build caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

# flyctl for one-shot post-M1 deploy from the running collector.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -L https://fly.io/install.sh | sh \
    && rm -rf /var/lib/apt/lists/*
ENV PATH="/root/.fly/bin:${PATH}"

ENV PATH="/app/.venv/bin:$PATH"
# Writable state lives on the mounted volume (see fly.toml).
ENV AEGIS_SQLITE_PATH=/data/aegis.sqlite
ENV AEGIS_LOG_DIR=/data/logs
# Forex demo paper uses the same SQLite file on Fly (event_spike_fade tables).
ENV AEGIS_FOREX_DEMO_SQLITE_PATH=/data/aegis.sqlite
ENV AEGIS_FOREX_ENABLED=1
ENV AEGIS_INTRADAY_ENABLED=1
ENV AEGIS_PORTFOLIO_ENABLED=1

CMD ["aegis-collect"]
