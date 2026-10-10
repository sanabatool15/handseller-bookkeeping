# syntax=docker/dockerfile:1

# ---- Stage 1: build a wheel/venv with all dependencies ----
FROM python:3.11-slim-bookworm AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
COPY core ./core
COPY routers ./routers
COPY services ./services
COPY repository ./repository
COPY middleware ./middleware
COPY jobs ./jobs
COPY mcp_gateway ./mcp_gateway
COPY ai_agents ./ai_agents
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ---- Stage 2: slim runtime image ----
FROM python:3.11-slim-bookworm AS runtime

# Microsoft ODBC Driver 18 for SQL Server (pyodbc needs it to talk to SQL Server)
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg ca-certificates unixodbc \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY . .

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status==200 else 1)"

# Default: run the FastAPI app (which itself mounts the Inngest handler).
# Override CMD to `python mcp_gateway/server.py` to run the MCP stdio server instead.
CMD ["uvicorn", "core.fastapi_app:app", "--host", "0.0.0.0", "--port", "8000"]
