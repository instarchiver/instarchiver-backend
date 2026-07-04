# Preview Deployments

Preview deployments automatically create an isolated environment for every Pull Request. Each PR gets its own URL at `https://pr-{N}.preview.instarchiver.net`, stays live while the PR is open, and is torn down automatically when the PR is closed.

## How It Works

```
Open / push to PR
        │
        ▼
┌───────────────────┐    fails → deploy is skipped
│  linter + pytest  │──────────────────────────────►  (no deploy)
└───────────────────┘
        │ passes
        ▼
┌───────────────────┐
│  build-and-push   │  → ghcr.io/.../django:pr-{N}
│  (Django + PG)    │  → ghcr.io/.../postgres:pr-{N}
└───────────────────┘
        │
        ▼
┌───────────────────┐
│     deploy        │  → SSH to VPS, docker compose up
└───────────────────┘
        │
        ▼
PR comment: https://pr-{N}.preview.instarchiver.net


PR closed / merged
        │
        ▼
┌───────────────────┐
│     cleanup       │  → docker compose down -v
└───────────────────┘     delete GHCR images, delete directory
```

### Per-PR Stack

Each PR gets an independent Docker Compose stack:

| Service | Image | Notes |
|---|---|---|
| `django` | `ghcr.io/.../django:pr-{N}` | Django + uvicorn, port 8000 |
| `postgres` | `ghcr.io/.../postgres:pr-{N}` | Isolated database per PR |
| `redis` | `redis:6` | Cache + Celery broker |
| `mailpit` | `axllent/mailpit` | Email testing |
| `celeryworker` | same as django | Background tasks |
| `celerybeat` | same as django | Periodic tasks |

Each stack runs on two Docker networks:

- `preview-internal` — container-to-container communication (django ↔ postgres ↔ redis)
- `traefik` — exposes django to the shared Traefik reverse proxy

### Routing

Traefik (one shared instance on the VPS) handles routing and TLS:

```
Browser
  │
  ▼
Traefik :443  ──► pr-{N}.preview.instarchiver.net
  │                    (wildcard TLS via Cloudflare DNS challenge)
  ▼
Django container :8000
```

HTTP (port 80) is automatically redirected to HTTPS by the Traefik entrypoint redirect — no per-container middleware needed.

---

## Prerequisites

### VPS

- Docker + Docker Compose v2
- Ports 80 and 443 open in the firewall
- SSH access (password or key)

### Cloudflare

- Wildcard DNS A record: `*.preview.instarchiver.net` → VPS public IP
- API Token with permission: `Zone > DNS > Edit` for the `instarchiver.net` zone

### VPS — Environment Files

Preview environments use existing env files on the VPS as a base. Ensure the following files exist at the path referenced by the `PREVIEW_SHARED_ENV_DIR` secret:

```
/opt/instarchiver/.envs/.local/
├── .django    ← DJANGO_SETTINGS_MODULE, REDIS_URL, credentials, etc.
└── .postgres  ← POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, etc.
```

These are the same files used for local development.

---

## One-Time VPS Setup

### 1. Run Traefik

```bash
# Copy the folder to the VPS
scp -r compose/preview/traefik/ user@vps:/opt/instarchiver/traefik/

# SSH into the VPS
ssh user@vps

# Create a .env file with your Cloudflare token
echo "CF_DNS_API_TOKEN=<token>" > /opt/instarchiver/traefik/.env

# Start Traefik (runs once, restart: unless-stopped)
cd /opt/instarchiver/traefik
docker compose up -d
```

Traefik will automatically request a wildcard certificate for `*.preview.instarchiver.net` via Cloudflare DNS challenge. The certificate is stored in a Docker volume (`acme`) and renewed automatically before expiry.

### 2. Create the Deploy Directory

```bash
mkdir -p /opt/instarchiver/previews
```

### 3. Add GitHub Secrets

In the repository: **Settings → Secrets and variables → Actions**

| Secret | Example value | Description |
|---|---|---|
| `PREVIEW_SSH_HOST` | `123.45.67.89` | VPS IP or hostname |
| `PREVIEW_SSH_USERNAME` | `ubuntu` | SSH user on the VPS |
| `PREVIEW_SSH_PASSWORD` | `...` | SSH password |
| `PREVIEW_DEPLOY_PATH` | `/opt/instarchiver/previews` | Root deploy directory on VPS |
| `PREVIEW_SHARED_ENV_DIR` | `/opt/instarchiver/.envs/.local` | Path to the shared env files |

> `GITHUB_TOKEN` is provided automatically — no manual secret needed.

---

## Day-to-Day Usage

### Opening a PR

Open a PR targeting `master`. The `Preview` workflow runs automatically:

1. Linter + tests run (mirrors the main CI workflow)
2. If they pass → images are built and pushed to GHCR
3. The stack is deployed to the VPS
4. A comment is posted on the PR with the preview URL

```
Preview deployed → https://pr-42.preview.instarchiver.net

Built from `abc1234`
```

### Pushing Updates

Every push to the PR branch triggers a full rebuild and redeploy. The old containers are replaced via `--remove-orphans`.

### Closing a PR

When a PR is merged or closed, the cleanup job automatically:

- Stops and removes all containers and volumes (`docker compose down -v`)
- Deletes the deploy directory on the VPS
- Deletes the `django:pr-{N}` and `postgres:pr-{N}` images from GHCR
- Posts a confirmation comment on the PR

---

## Files

```
instarchiver-backend/
├── .github/workflows/preview.yml       ← GHA workflow (trigger, build, deploy, cleanup)
├── docker-compose.preview.yml          ← Per-preview stack definition
└── compose/preview/traefik/
    ├── docker-compose.yml              ← Traefik (run once on VPS)
    └── traefik.yml                     ← Traefik static config
```

### `.github/workflows/preview.yml`

| Job | Trigger | Description |
| --- | --- | --- |
| `linter` | PR opened/sync/reopened | Runs pre-commit hooks |
| `pytest` | PR opened/sync/reopened | Runs the full test suite |
| `build-and-push` | After linter + pytest pass | Builds django + postgres images, pushes to GHCR tagged `pr-{N}` |
| `deploy` | After build-and-push | SSHes to VPS, writes `.env`, copies compose file, runs `docker compose up` |
| `cleanup` | PR closed | `docker compose down -v`, deletes GHCR images, deletes deploy directory |

### `docker-compose.preview.yml`

Mirrors `docker-compose.local.yml` with the following differences:

- Images pulled from GHCR instead of built locally
- Traefik labels for automatic routing
- No port mappings (Traefik handles exposure)
- No `flower` service

### `compose/preview/traefik/`

One-time setup. Traefik runs as a permanent container on the VPS, listening on ports 80 and 443. Its Docker provider reads labels from other containers on the `traefik` network to configure routing automatically.

---

## Django Settings

Preview environments use `config.settings.local` (identical to local development). Two additions in `config/settings/local.py` support the preview proxy setup:

```python
# Always show the debug toolbar — don't rely on REMOTE_ADDR check.
# In preview, REMOTE_ADDR is the Traefik container IP, not the Docker gateway,
# so the default INTERNAL_IPS check fails.
DEBUG_TOOLBAR_CONFIG = {
    ...
    "SHOW_TOOLBAR_CALLBACK": lambda request: True,
}

# Allow form submissions over HTTPS.
# Traefik terminates TLS and forwards plain HTTP to Django, so request.scheme
# is "http" while the browser sends Origin: https://... — CSRF check fails
# without this setting.
CSRF_TRUSTED_ORIGINS = ["https://*.preview.instarchiver.net"]
```

---

## Environment Variables

Three env files are loaded in order (later files override earlier ones):

```yaml
env_file:
  - ${SHARED_ENV_DIR}/.django    # Base Django config (from VPS)
  - ${SHARED_ENV_DIR}/.postgres  # POSTGRES_* vars (from VPS)
  - .env                         # Per-PR routing vars
```

The per-PR `.env` written by the workflow contains only three variables:

```env
SHARED_ENV_DIR=/opt/instarchiver/.envs/.local
PR_NUMBER=42
IMAGE_REPO=instarchiver/instarchiver-backend
```

All credentials (database, Redis, API keys, etc.) come from the shared files already on the VPS.

---

## Troubleshooting

### Preview is not triggered

Make sure the PR targets `master`. The workflow only fires on `pull_request` events against `master`.

Check the **Actions** tab on GitHub — if `linter` or `pytest` fails, the `deploy` job will not run.

### Containers cannot pull the image

GHCR packages inherit repository visibility. If the repository is private, ensure the packages are also set to private and the workflow has `packages: write` permission.

### `POSTGRES_USER: unbound variable`

The `.postgres` file is not loaded by the `django` container. Verify that `${SHARED_ENV_DIR}/.postgres` is listed in the `env_file` section of the `django` service in `docker-compose.preview.yml`.

### ERR_TOO_MANY_REDIRECTS

Do not add an HTTP→HTTPS redirect middleware on container labels. Traefik already handles the redirect at the entrypoint level (`web` → `websecure`). A per-container redirect middleware conflicts with this and creates a redirect loop.

### CSRF Forbidden on HTTPS form submissions

Ensure `CSRF_TRUSTED_ORIGINS = ["https://*.preview.instarchiver.net"]` is set in `config/settings/local.py`. Without it, Django rejects form submissions from HTTPS because it receives the request as plain HTTP from Traefik, causing an origin mismatch.

### Debug toolbar not showing

Ensure `"SHOW_TOOLBAR_CALLBACK": lambda request: True` is set in `DEBUG_TOOLBAR_CONFIG`. The default toolbar check compares `REMOTE_ADDR` against `INTERNAL_IPS`, but in preview `REMOTE_ADDR` is the Traefik container IP — not the Docker gateway — so the check fails.

### Manually tearing down a preview

```bash
# SSH into the VPS
ssh user@vps

# List active previews
docker ps --filter "name=preview-"

# Tear down a specific preview
docker compose -p "preview-pr42" \
  -f /opt/instarchiver/previews/pr-42/docker-compose.preview.yml \
  down -v --remove-orphans

# Remove the deploy directory
rm -rf /opt/instarchiver/previews/pr-42
```
