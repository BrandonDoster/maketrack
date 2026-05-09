# syntax=docker/dockerfile:1.7

# ── build stage ────────────────────────────────────────────────────────────
FROM python:3.12 AS build

ENV UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PYTHONDONTWRITEBYTECODE=1

# uv: pin a version we know works for reproducible builds.
COPY --from=ghcr.io/astral-sh/uv:0.9.10 /uv /usr/local/bin/uv

WORKDIR /build

COPY pyproject.toml uv.lock ./

# Export a hashed requirements.txt for the slim final image (no uv at runtime).
# --no-emit-project keeps the editable project line out of the file; the final
# stage pip-installs the project itself with --no-deps from the copied source.
RUN uv export --no-dev --frozen --no-emit-project --format requirements-txt -o requirements.txt

# Compile Tailwind. Standalone CLI keeps Node out of the build entirely.
ARG TAILWIND_VERSION=v3.4.16
ARG TARGETARCH
RUN set -eux; \
    case "${TARGETARCH}" in \
        amd64) TW_ARCH="x64" ;; \
        arm64) TW_ARCH="arm64" ;; \
        *) echo "unsupported arch: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/tailwindcss \
        "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-${TW_ARCH}"; \
    chmod +x /usr/local/bin/tailwindcss

COPY tailwind.config.js tailwind.input.css ./
COPY src ./src

RUN mkdir -p src/maketrack/static && \
    tailwindcss \
        -c tailwind.config.js \
        -i tailwind.input.css \
        -o src/maketrack/static/tailwind.css \
        --minify

# ── final stage ────────────────────────────────────────────────────────────
FROM python:3.12-slim AS final

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MAKETRACK_DB_PATH=/data/maketrack.db \
    MAKETRACK_UPLOADS_PATH=/uploads \
    MAKETRACK_BIND_HOST=0.0.0.0 \
    MAKETRACK_BIND_PORT=8000

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd -r maketrack && useradd -r -g maketrack -d /app -s /usr/sbin/nologin maketrack

WORKDIR /app

COPY --from=build /build/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=build /build/src ./src
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir --no-deps .

RUN mkdir -p /data /uploads && chown -R maketrack:maketrack /app /data /uploads

USER maketrack

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${MAKETRACK_BIND_PORT}/healthz" || exit 1

CMD ["sh", "-c", "uvicorn maketrack.main:app --host ${MAKETRACK_BIND_HOST} --port ${MAKETRACK_BIND_PORT}"]
