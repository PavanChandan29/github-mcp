## Docker Run Guide

### Files included (must be at repo root)
1. `Dockerfile` — builds the container image  
2. `.dockerignore` — prevents local artifacts (DB, caches, IDE files) from being copied into the image  
3. `docker-compose.yml` — runs the container with env vars + mounted volumes

### Requirements
- Docker Engine (20.10+ recommended)
- Docker Compose v2 (`docker compose ...`)
- GitHub Personal Access Token (classic) exported as `GITHUB_TOKEN`

### Commands (run from project root)

#### 1) Export GitHub token
```bash

export GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxx"

docker compose build

docker compose run --rm github-mcp python -m github_mcp.ingest

docker compose up

docker compose down
```