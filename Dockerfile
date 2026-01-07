FROM python:3.11-slim

# Basic runtime hygiene
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# App directory
WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code
COPY github_mcp ./github_mcp
COPY github_mcp_server.py .
COPY config ./config

# Data directory (mounted at runtime)
ENV GITHUB_MCP_DATA_DIR=/data
RUN mkdir -p /data

# Start MCP server by default
CMD ["python", "github_mcp_server.py"]