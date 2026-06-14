# syntax=docker/dockerfile:1

# ---- Builder: managed standalone Python + deps venv (both relocatable) ----
FROM ghcr.io/astral-sh/uv:0.7-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed

WORKDIR /app

# tini binary for the runtime (distroless has no package manager)
RUN apt-get update && \
    apt-get install -y --no-install-recommends tini && \
    rm -rf /var/lib/apt/lists/*

# Standalone CPython 3.12 (relocatable) + main deps pinned by uv.lock
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv python install 3.12 && \
    uv sync --frozen --no-dev --no-install-project

# Slim the artifacts that get copied into the runtime image.
# NOTE: no `strip` on vendored *.libs — manylinux wheels ship pre-stripped and
# binutils corrupts large-alignment libs (e.g. numpy's openblas → page-align error).
RUN set -eux; \
    PYLIB="$(echo /opt/python/cpython-*/lib/python3.12)"; \
    # botocore ships JSON for every AWS service; the app only uses SES v2
    find /app/.venv/lib/python3.12/site-packages/botocore/data -mindepth 1 -maxdepth 1 -type d ! -name sesv2 -exec rm -rf {} +; \
    # stdlib pieces a headless server never loads
    rm -rf "$PYLIB/test" "$PYLIB/idlelib" "$PYLIB/tkinter" "$PYLIB/turtledemo" \
           "$PYLIB/ensurepip" "$PYLIB/lib2to3" "$PYLIB/config-3.12"*; \
    # bundled test suites inside packages
    find /app/.venv -type d -name tests -prune -exec rm -rf {} + 2>/dev/null || true

# ---- Runtime: distroless, no shell, no package manager ----
FROM gcr.io/distroless/cc-debian12 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Standalone interpreter (venv symlinks point here, same absolute path) + venv + tini
COPY --from=builder /opt/python /opt/python
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /usr/bin/tini /usr/bin/tini

# libz: psycopg[binary]'s bundled libpq links it; not present in distroless/cc
COPY --from=builder /usr/lib/*-linux-gnu/libz.so.1 /usr/lib/libz.so.1

WORKDIR /app

# Application code, owned by the distroless nonroot user (uid 65532)
COPY --chown=65532:65532 . .

USER nonroot

EXPOSE 8000

# exec-form (no shell in distroless); hits the liveness endpoint, not just the socket
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["tini", "--"]

CMD ["python", "-m", "uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
