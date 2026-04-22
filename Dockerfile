FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libpq5 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies — mount uv temporarily so it doesn't become a layer in the final image
RUN --mount=from=ghcr.io/astral-sh/uv:0.7,source=/uv,target=/uv \
    /uv pip install --system -r pyproject.toml

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 app && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import socket; s = socket.create_connection(('localhost', 8000), timeout=4); s.close()"

CMD ["python", "-m", "uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
