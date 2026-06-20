# Pinned base. For full reproducibility pin by digest:
#   FROM python:3.13.5-slim-bookworm@sha256:<digest>
FROM python:3.13.5-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies/package first (build context is small, so a single copy
# is fine and keeps the layer simple).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

EXPOSE 8000

# Run as an unprivileged user.
USER nobody

# Liveness: confirm the streamable-HTTP listener is accepting connections.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket,os,sys; s=socket.create_connection(('127.0.0.1', int(os.getenv('SIYUAN_MCP_PORT','8000'))), 3); s.close()" || exit 1

CMD ["siyuan-mcp"]
