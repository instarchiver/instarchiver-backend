# Copilot Instructions for Instarchiver Backend

## Project Overview

Instarchiver Backend is a **Django 5.2 REST API** service for archiving Instagram content. Built on the cookiecutter-django template, it uses PostgreSQL, Redis, and Celery for background processing, and Firebase for authentication.

## Development Environment

### Docker-First Development

**CRITICAL**: All development is done through Docker containers. **Never run commands directly on the host machine.**

```bash
# Preferred: Use justfile commands
just up                    # Start all services
just down                  # Stop all services
just build                 # Build containers
just manage migrate        # Run Django management commands
just django pytest         # Run commands inside the Django container

# Alternative: docker-compose directly
docker-compose -f docker-compose.local.yml up
docker-compose -f docker-compose.local.yml run --rm django python manage.py migrate
```

**Never suggest:**
```bash
# ❌ WRONG - don't run directly on host
python manage.py migrate
pip install package
pytest
```

### Available Services (when running `just up`)

- **Django app**: http://localhost:8000
- **Swagger UI**: http://localhost:8000/docs/
- **Admin Interface**: http://localhost:8000/admin/
- **Mailpit** (email testing): http://localhost:8025
- **Flower** (Celery monitoring): http://localhost:5555

## Code Quality Standards

Always run these before completing any task:

```bash
just django ruff format          # Format code
just django ruff check --fix     # Lint and auto-fix
just django mypy core            # Type check
```

### Key Ruff Rules

- Use `force-single-line` imports (configured in `pyproject.toml`)
- Follow Django best practices (DJ rules enabled)
- Use modern Python 3.12+ syntax
- Avoid bare `except:` — use specific exceptions

### Import Style

```python
# ✅ CORRECT — one import per line
from django.contrib import admin
from django.contrib import messages

# ❌ WRONG
from django.contrib import admin, messages
```

**Import order:** standard library → third-party → Django → local apps

## Testing

```bash
just django pytest                                    # Run all tests
just django pytest path/to/test_file.py              # Run specific file
just django pytest --cov --cov-branch                # With coverage
```

- Tests use `config.settings.test` (set in `pyproject.toml`)
- Coverage targets: `core/**`, `settings/**`, `api_logs/**`, `instagram/**`, `authentication/**`
- Exclude: `*/migrations/*`, `*/tests/*`
- Minimum 80% coverage for new code

## Architecture Patterns

### Settings Structure

Settings are split by environment in `config/settings/`:
- `base.py` — shared configuration
- `local.py` — development (default)
- `production.py` — production
- `test.py` — tests
- `unfold_admin.py` — admin UI

When modifying settings:
1. Add to `base.py` if it applies to all environments
2. Override in environment-specific files as needed

### Database-Backed Configuration

API keys, URLs, and credentials are stored in **database models**, not environment variables. This allows runtime changes without redeployment.

```python
from settings.models import CoreAPISetting, OpenAISetting, FirebaseAdminSetting

settings = CoreAPISetting.get_solo()
api_url = settings.api_url
```

Available singleton models: `OpenAISetting`, `CoreAPISetting`, `FirebaseAdminSetting`.

### Two User Models

1. `core.users.models.User` — Django authentication user (extends `AbstractUser`)
2. `instagram.models.User` — Instagram profile data (UUID primary key)

### New Model Checklist

- Use UUID primary keys for non-auth models
- Add `simple_history` for change tracking
- Use callable upload paths for file fields (see `instagram/misc.py`)
- Add `created_at` and `updated_at` timestamps
- Use `SingletonModel` for configuration models

### External API Integration

Always use the centralized Core API client — never make direct HTTP requests:

```python
from core.utils.instagram_api import (
    fetch_user_info_by_username_v2,
    fetch_user_info_by_user_id,
)

# ✅ CORRECT — automatic logging, error handling, timing
user_data = fetch_user_info_by_username_v2(username)

# ❌ WRONG — bypasses logging and error handling
import requests
response = requests.get(f"https://api.example.com/users/{username}")
```

### Admin Interface

Use Unfold admin theme:

```python
from unfold.admin import ModelAdmin
from unfold.decorators import action
from simple_history.admin import SimpleHistoryAdmin

@admin.register(MyModel)
class MyModelAdmin(SimpleHistoryAdmin, ModelAdmin):
    fieldsets = (
        ("General", {"fields": ("field1", "field2"), "classes": ["tab"]}),
    )
```

- Split admin into `app/admin/` directory with `__init__.py`
- Use `tab` CSS class for complex fieldsets
- Add custom actions with `@action` decorator

### API Development

Use Django REST Framework with drf-spectacular:

```python
from rest_framework import viewsets
from drf_spectacular.utils import extend_schema, OpenApiParameter

class MyViewSet(viewsets.ModelViewSet):
    @extend_schema(summary="Brief description", description="Detailed description")
    def list(self, request):
        pass
```

- Use ViewSets for CRUD operations
- Add `@extend_schema` to all viewset methods
- Implement pagination (see `instagram/paginations.py`)
- Cache frequently accessed endpoints (30s default for detail views)

### Background Tasks (Celery)

```python
from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def my_task(self, param):
    try:
        logger.info(f"Processing {param}")
    except Exception as exc:
        logger.error(f"Task failed: {exc}")
        raise self.retry(exc=exc)
```

- Place tasks in `app/tasks.py` (auto-discovered by Celery)
- Use descriptive names: `update_profile_picture_from_url`, not `update_pic`
- Keep tasks idempotent and add retry logic

## File Organization

```
app_name/
├── admin/              # Split admin files
│   ├── __init__.py
│   └── model1.py
├── migrations/
├── serializers/
│   ├── __init__.py
│   └── model.py
├── tests/
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_views.py
│   └── test_tasks.py
├── views/
│   ├── __init__.py
│   └── viewsets.py
├── apps.py
├── models.py
├── tasks.py
└── urls.py
```

## Security

**Never commit:**
- API keys, tokens, passwords
- Firebase service account JSON
- Production database credentials
- `SECRET_KEY` values

**Use instead:**
- Database-backed settings for runtime configuration
- Environment variables for deployment-time secrets
- `.envs/.local/` for local development (gitignored)

## Common Workflows

### Adding a New Model

1. Define model in `app/models.py`
2. Add admin in `app/admin/model_name.py`
3. Create serializer in `app/serializers/`
4. Create viewset in `app/views/`
5. Add URL route in `app/urls.py`
6. `just manage makemigrations && just manage migrate`
7. Write tests in `app/tests/test_models.py`
8. `just django pytest && just django ruff format && just django ruff check --fix`

### Debugging

```bash
just logs                          # All services
just logs django                   # Django logs
just logs celeryworker             # Celery logs
just manage shell                  # Django shell
just django python manage.py shell_plus
just django python manage.py dbshell
```

## Documentation

Use Google-style docstrings for all public functions, methods, and classes:

```python
def fetch_user_info(username: str) -> dict:
    """Fetch Instagram user information from external API.

    Args:
        username: Instagram username to fetch

    Returns:
        Dictionary containing user profile data

    Raises:
        APIError: If the external API request fails
    """
```

Add `@extend_schema` decorators to all DRF viewset methods with clear summaries, descriptions, and parameter documentation.
