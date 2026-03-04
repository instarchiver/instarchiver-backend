# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Instarchiver Backend is a Django 5.2 REST API service for archiving Instagram content. Built on the cookiecutter-django template, it uses PostgreSQL, Redis, and Celery for background processing.

## Development Commands

All development is done through Docker using justfile commands or docker-compose directly.

### Running the Server

**Start all services:**
```bash
just up
# or
docker-compose -f docker-compose.local.yml up
```

**Build containers:**
```bash
just build
# or
docker-compose -f docker-compose.local.yml build
```

**Stop containers:**
```bash
just down
# or
docker-compose -f docker-compose.local.yml down
```

**View logs:**
```bash
just logs
# or for specific service
just logs django
```

**Remove containers and volumes:**
```bash
just prune
```

### Django Management Commands

**Run any manage.py command:**
```bash
just manage <command>
# Examples:
just manage migrate
just manage makemigrations
just manage createsuperuser
just manage shell
```

**Run custom Django command:**
```bash
just django <command>
# Example:
just django python manage.py showmigrations
```

### Testing

**Run all tests:**
```bash
just manage test
# or with pytest
just django pytest
```

**Run specific test file:**
```bash
just django pytest path/to/test_file.py
```

**Run with coverage:**
```bash
just django coverage run -m pytest
just django coverage html
```

**Test settings:** Tests use `config.settings.test` (configured in [pyproject.toml:4](pyproject.toml#L4))

### Code Quality

**Format code:**
```bash
just django ruff format
```

**Lint and auto-fix:**
```bash
just django ruff check --fix
```

**Type checking:**
```bash
just django mypy core
```

**Pre-commit hooks (run in container):**
```bash
just django pre-commit run --all-files
```

The project uses Ruff for linting/formatting with strict rules (see [pyproject.toml:56-138](pyproject.toml#L56-L138)), django-upgrade targeting Django 5.0, and djLint for template formatting.

## Architecture

### Settings Structure

Django settings are split by environment in `config/settings/`:
- `base.py` - Shared configuration
- `local.py` - Development settings
- `production.py` - Production settings
- `test.py` - Test settings
- `unfold_admin.py` - Admin UI configuration

Settings are selected via `DJANGO_SETTINGS_MODULE` environment variable (default: `config.settings.local`).

### App Structure

**Core Apps:**
- `core/` - Main application with users module and utilities
- `instagram/` - Instagram data models and archiving logic
- `authentication/` - Firebase authentication integration
- `settings/` - Database-backed configuration (singleton models)
- `api_logs/` - API request logging for external calls

**Configuration:**
- `config/` - Django project configuration (URLs, ASGI, WSGI, Celery)

### URL Routing

Main URL configuration in [config/urls.py](config/urls.py):
- Root (`/`) redirects to API docs
- `/admin/` - Django admin interface
- `/authentication/` - Firebase auth endpoints
- `/instagram/` - Instagram archiving endpoints
- `/health/` - Health check endpoints
- `/docs/` - Swagger/OpenAPI documentation (drf-spectacular)
- `/schema/` - OpenAPI schema

API routers in [config/api_router.py](config/api_router.py) use DRF's DefaultRouter (debug mode) or SimpleRouter (production).

### Models Architecture

**Two User Models:**
1. `core.users.models.User` - Django authentication user (extends AbstractUser)
2. `instagram.models.User` - Instagram profile data with UUID primary key

**Instagram Models** ([instagram/models.py](instagram/models.py)):
- `User` - Instagram user profiles with auto-update flags
- Tracks profile pictures, biography, follower counts, verification status
- Uses `simple_history` for change tracking

**Settings Models** ([settings/models.py](settings/models.py)):
- `OpenAISetting` - OpenAI API configuration
- `CoreAPISetting` - External Core API credentials
- `FirebaseAdminSetting` - Firebase service account JSON
- All use `SingletonModel` for single-instance configuration

### External API Integration

**Core API Client** ([core/utils/core_api.py](core/utils/core_api.py)):
- Centralized API client for external Instagram data service
- Automatically logs all requests to `APIRequestLog` model
- Retrieves configuration from `CoreAPISetting` singleton
- All requests include timing, status, headers, and error tracking

**Instagram API Utilities** ([core/utils/instagram_api.py](core/utils/instagram_api.py)):
- `fetch_user_info_by_username_v2()` - Get user data by username
- `fetch_user_info_by_user_id()` - Get user data by ID
- `fetch_user_stories_by_username()` - Retrieve user stories
- All functions use the Core API client under the hood

### Background Tasks

**Celery Configuration** ([config/celery_app.py](config/celery_app.py)):
- App name: `"core"`
- Auto-discovers tasks from all installed apps
- Uses Django settings with `CELERY_` prefix

**Task Examples** ([instagram/tasks.py](instagram/tasks.py)):
- `update_profile_picture_from_url()` - Downloads and updates profile pictures
- Uses hash comparison to detect actual content changes
- Configured with retries (max 3, 60s delay)

### Authentication

**Firebase Integration** ([authentication/firebase.py](authentication/firebase.py)):
- Loads service account JSON from `FirebaseAdminSetting` database model
- Dynamically reloads credentials when changed
- Handles app re-initialization for configuration updates

### Testing Strategy

**Coverage Configuration** ([pyproject.toml:11-14](pyproject.toml#L11-L14)):
- Includes: `core/**`, `settings/**`, `api_logs/**`
- Excludes: `*/migrations/*`, `*/tests/*`
- Uses `django_coverage_plugin`

**MyPy Configuration** ([pyproject.toml:16-35](pyproject.toml#L16-L35)):
- Uses `mypy_django_plugin` and `mypy_drf_plugin`
- Ignores errors in migrations
- Test settings: `config.settings.test`

### Docker Services

**Local development** (`docker-compose.local.yml`):
- Django app (port 8000)
- PostgreSQL database
- Redis cache
- Mailpit (email testing, port 8025)
- Celery worker + beat
- Flower (Celery monitoring, port 5555)

**Production** (`docker-compose.production.yml`):
- Optimized builds with Gunicorn
- No debug tools or Mailpit

## Important Patterns

### Database-Backed Configuration

Configuration values (API keys, URLs, Firebase credentials) are stored in database models, not environment variables. This allows runtime configuration changes without redeployment. Access via:

```python
from settings.models import CoreAPISetting, OpenAISetting, FirebaseAdminSetting

# Get singleton instance
settings = CoreAPISetting.get_solo()
api_url = settings.api_url
```

### API Request Logging

All external API calls automatically log to `APIRequestLog` via `core.utils.core_api.make_request()`. The log captures:
- Request method, URL, headers, params, body
- Response status, headers, body
- Duration in milliseconds
- Status (pending, success, error, timeout)

### Image Upload Patterns

Models use callable upload paths (e.g., `get_user_profile_picture_upload_location`) for organized media storage. The `instagram/misc.py` module defines these path generators.

### Auto-Update Flags

Instagram user models have boolean flags like `allow_auto_update_stories` and `allow_auto_update_profile` to control automated background updates.

## Environment Setup

**Local development requires:**
- Docker and Docker Compose
- Just command runner (optional, for convenience)

**Environment files:**
- `.envs/.local/.django` - Django configuration
- `.envs/.local/.postgres` - Database credentials

Docker Compose handles PostgreSQL, Redis, Celery, and all other services automatically.

**Production:**
- Configure environment variables or use `.envs/.production/`
- Set `DJANGO_DEBUG=False`, configure `ALLOWED_HOSTS`, `SECRET_KEY`, `SENTRY_DSN`

## API Documentation

With server running, access:
- **Swagger UI:** http://localhost:8000/docs/
- **OpenAPI Schema:** http://localhost:8000/schema/
- **Admin:** http://localhost:8000/admin/
