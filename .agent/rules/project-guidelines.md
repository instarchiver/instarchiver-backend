---
trigger: always_on
---

# Antigravity Rules for Instarchiver Backend

## Project Context

This is a Django 5.2 REST API service for archiving Instagram content, built on cookiecutter-django template. The project uses PostgreSQL, Redis, Celery for background processing, and Firebase for authentication.

### Framework & Documentation Reference (Context7)

**CRITICAL**: Before creating plans (`/plan`), optimizing, refactoring, or implementing features, always check the frameworks/libraries and versions used in this project (`pyproject.toml` / `requirements.txt`) and query **Context7 MCP** (`resolve-library-id` -> `query-docs`) as the primary implementation reference.

### Writing, Coding & Planning Guidelines

- **Writing (`humanizer`)**: Always use the `humanizer` skill (`.agent/skills/humanizer/SKILL.md`) when writing or editing prose (documentation, docstrings, comments, commit messages, PR descriptions, changelogs, drf-spectacular `help_text`/`summary`/`description`, and user-facing messages). Write the text first, then run it through the humanizer before saving. Do not wrap names in double backticks in docstrings and comments.
- **Coding (`ponytail`)**: Always use the `ponytail` skill (`.agent/skills/ponytail/SKILL.md`, level `full` by default) for coding work: writing, fixing, refactoring, reviewing, or designing code, and choosing dependencies. Keep it on unless the user says "stop ponytail" or "normal mode".
- **Planning (`planning-and-task-breakdown` & `doubt-driven-development`)**:
  - Write every plan in Indonesian (specs, task breakdowns, and revised plans). Everything committed to the repo stays in English.
  - Run an evil reviewer pass before presenting or executing any plan using a fresh-context subagent with the `doubt-driven-development` skill (`.agent/skills/doubt-driven-development/SKILL.md`).
  - The reviewer must verify every library or API claim against Context7 (`resolve-library-id` -> `query-docs`) and check concrete failure scenarios (empty/malformed inputs, duplicates/races, Celery retry idempotency, existing production rows/migrations, external API failures, permissions, and timezones/pagination).
  - Fix valid findings, state 1-line reasons for rejected findings, and show the revised plan with a short summary of what the reviewer found.

## Development Environment

### Docker-First Development

**CRITICAL**: All development must be done through Docker containers. Never suggest running commands directly on the host machine.

**Correct command patterns:**
```bash
# Use justfile commands (preferred)
just up
just manage migrate
just django pytest

# Or docker-compose directly
docker-compose -f docker-compose.local.yml up
docker-compose -f docker-compose.local.yml run --rm django python manage.py migrate
```

**Never suggest:**
```bash
# ❌ WRONG - Don't run directly on host
python manage.py migrate
pip install package
pytest
```

### Available Services

When the development environment is running (`just up`), these services are available:
- **Django app**: http://localhost:8000
- **API Documentation**: http://localhost:8000/api/docs/
- **Admin Interface**: http://localhost:8000/admin/
- **Mailpit** (email testing): http://localhost:8025
- **Flower** (Celery monitoring): http://localhost:5555

## Code Quality Standards

### Linting and Formatting

**Always run code quality checks before completing tasks:**

```bash
# Format code with Ruff
just django ruff format

# Check and auto-fix linting issues
just django ruff check --fix

# Type checking with MyPy
just django mypy core
```

**Important Ruff rules to follow:**
- Use `force-single-line` imports (configured in pyproject.toml)
- Follow Django best practices (DJ rules enabled)
- Avoid bare `except:` clauses - use specific exceptions
- Use modern Python syntax (UP rules for Python 3.12+)
- Avoid mutable class attributes without `typing.ClassVar`

### Testing Requirements

**All new features must include tests:**

```bash
# Run tests with coverage
just django pytest --cov --cov-branch

# Run specific test file
just django pytest path/to/test_file.py
```

**Coverage targets:**
- Minimum 80% coverage for new code
- Tests should cover: `core/**`, `settings/**`, `api_logs/**`, `instagram/**`, `authentication/**`
- Exclude: `*/migrations/*`, `*/tests/*`

## Architecture Patterns

### Settings Management

**When to use environment variables:**
- Only for deployment-time configuration (DEBUG, SECRET_KEY, DATABASE_URL, REDIS_URL)
- Never for values that might change at runtime

### Django Settings Structure

Settings are split by environment in `config/settings/`:
- `base.py` - Shared configuration
- `local.py` - Development settings (default)
- `production.py` - Production settings
- `test.py` - Test settings
- `unfold_admin.py` - Admin UI configuration

**When modifying settings:**
1. Add to `base.py` if it applies to all environments
2. Override in `local.py`, `production.py`, or `test.py` as needed
3. Use `DJANGO_SETTINGS_MODULE` env var to switch environments

### Model Architecture

**Two separate User models exist:**
1. `core.users.models.User` - Django authentication user (extends AbstractUser)
2. `instagram.models.User` - Instagram profile data (UUID primary key)

**When creating new models:**
- Use UUID primary keys for non-auth models
- Add `simple_history` for models that need change tracking
- Use callable upload paths for file fields (see `instagram/misc.py`)
- Add `created_at` and `updated_at` timestamps
- Use `SingletonModel` for configuration models (see `settings/models.py`)

### Admin Interface

**Use Unfold admin theme:**

```python
from unfold.admin import ModelAdmin
from unfold.decorators import action
from simple_history.admin import SimpleHistoryAdmin

@admin.register(MyModel)
class MyModelAdmin(SimpleHistoryAdmin, ModelAdmin):
    # Use fieldsets with "tab" classes for organization
    fieldsets = (
        (
            "General",
            {
                "fields": ("field1", "field2"),
                "classes": ["tab"],
            },
        ),
    )

    # Use @action decorator for custom actions
    @action(
        description=_("Custom Action"),
        url_path="custom-action",
        permissions=["change"],
    )
    def custom_action(self, request: HttpRequest, object_id: str):
        # Implementation
        pass
```

**Admin organization:**
- Split admin into separate files in `app/admin/` directory
- Import all admin classes in `app/admin/__init__.py`
- Use tabs for complex fieldsets
- Add custom actions for common operations

### API Development

**Use Django REST Framework with drf-spectacular:**

```python
from rest_framework import viewsets
from drf_spectacular.utils import extend_schema, OpenApiParameter

class MyViewSet(viewsets.ModelViewSet):
    @extend_schema(
        summary="Brief description",
        description="Detailed description",
        parameters=[
            OpenApiParameter(name="param", description="Param description"),
        ],
    )
    def list(self, request):
        # Implementation
        pass
```

**API patterns:**
- Use ViewSets for CRUD operations
- Add OpenAPI documentation with `@extend_schema`
- Implement pagination (see `instagram/paginations.py`)
- Add filtering, searching, and ordering
- Cache frequently accessed endpoints (30s default for detail views)

### External API Integration

**Always use the centralized API clients (`core/utils/saveapi.py` or `core/utils/core_api.py`) for external requests:**

```python
from core.utils.saveapi import fetch_user_profile

# ✅ CORRECT - Uses centralized client with automatic logging
user_data = fetch_user_profile(username)

# ❌ WRONG - Don't make direct requests
import requests
response = requests.get(f"https://api.example.com/users/{username}")
```

**SaveAPI client rules (`core/utils/saveapi.py`):**
- Keep `core/utils/saveapi.py` dumb: it makes the request, logs to `APIRequestLog` (with `Authorization` masked), and raises a classified `SaveAPIError` (`code`, `status_code`, `retryable`, `retry_after`).
- Never put cache writes, shared cooldown state (Redis/Django cache), or retry decisions inside `core/utils/saveapi.py`.
- All retry, backoff, and rate-limit rescheduling logic belongs in the Celery task layer (`instagram/tasks/`). When SaveAPI returns a rate limit with `Retry-After`, the task reschedules itself with `apply_async(countdown=retry_after)` rather than using a shared cache cooldown.
- For Telegram HTTP calls, always use `call_telegram_api()` in `telegram_bot/utils.py`, which masks the bot token in logs.

### Background Tasks with Celery

**Task patterns:**

```python
from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def my_task(self, param):
    try:
        # Task implementation
        logger.info(f"Processing {param}")
    except Exception as exc:
        logger.error(f"Task failed: {exc}")
        raise self.retry(exc=exc)
```

**When to use Celery tasks:**
- Long-running operations (API calls, file processing)
- Scheduled/periodic tasks
- Operations that can fail and need retries
- Background updates (profile pictures, stories)

**Task naming and priorities:**
- Use descriptive names: `update_profile_picture_from_url`, not `update_pic`
- Place in `app/tasks.py` or `app/tasks/`
- Auto-discovered by Celery from all installed apps
- All tasks run on one worker with Redis message priorities enabled (0 is highest, default is 5). `telegram_bot` tasks must pass `priority=0` to `@shared_task` so bot replies skip ahead of the Instagram backlog.

## File Organization

### App Structure

```
app_name/
├── __init__.py
├── admin/              # Split admin files
│   ├── __init__.py
│   ├── model1.py
│   └── model2.py
├── migrations/
├── serializers/        # Split serializers if many
│   ├── __init__.py
│   └── model.py
├── tests/              # Split tests by feature
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_views.py
│   └── test_tasks.py
├── views/              # Split views if many
│   ├── __init__.py
│   └── viewsets.py
├── apps.py
├── models.py
├── signals.py
├── tasks.py
├── urls.py
└── utils.py
```

### Import Organization

**Follow Ruff's force-single-line imports:**

```python
# ✅ CORRECT
from django.contrib import admin
from django.contrib import messages
from django.http import HttpRequest

# ❌ WRONG
from django.contrib import admin, messages
from django.http import HttpRequest
```

**Import order:**
1. Standard library
2. Third-party packages
3. Django imports
4. Local app imports

## Database Migrations

**Migration workflow:**

```bash
# Create migrations
just manage makemigrations

# Review migration file before applying
# Check for:
# - Data migrations that might timeout
# - Indexes on large tables
# - Non-nullable fields without defaults

# Apply migrations
just manage migrate

# For production, test migrations on staging first
```

**Migration best practices:**
- Always review auto-generated migrations
- Add indexes for frequently queried fields
- Use `db_index=True` in model fields
- Avoid removing fields in same migration as adding (split into separate migrations)
- Test data migrations with realistic data volumes

## Security Considerations

### Sensitive Data

**Never commit:**
- API keys, tokens, passwords
- Firebase service account JSON
- Production database credentials
- SECRET_KEY values

**Use:**
- Database-backed settings for runtime configuration
- Environment variables for deployment-time secrets
- `.envs/.local/` for local development (gitignored)

## Common Workflows

### Adding a New Model

1. Define model in `app/models.py`
2. Add to admin in `app/admin/model_name.py`
3. Create serializer in `app/serializers/`
4. Create viewset in `app/views/`
5. Add URL route in `app/urls.py`
6. Create migrations: `just manage makemigrations`
7. Apply migrations: `just manage migrate`
8. Write tests in `app/tests/test_models.py`
9. Run tests: `just django pytest`
10. Format and lint: `just django ruff format && just django ruff check --fix`

### Adding a Background Task

1. Define task in `app/tasks.py`
2. Add retry logic and logging
3. Create model method to trigger task (if applicable)
4. Write tests in `app/tests/test_tasks.py`
5. Test task execution in development
6. Monitor with Flower: http://localhost:5555

### Debugging

**View logs:**
```bash
# All services
just logs

# Specific service
just logs django
just logs celeryworker
just logs postgres
```

**Django shell:**
```bash
just manage shell
# or
just django python manage.py shell_plus
```

**Database access:**
```bash
just django python manage.py dbshell
```

## Documentation

### Code Documentation

**Docstrings required for:**
- All public functions and methods
- All classes
- Complex algorithms or business logic

**Use Google-style docstrings:**

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
    pass
```

### API Documentation

**Use drf-spectacular for OpenAPI docs:**
- Add `@extend_schema` decorators to all viewset methods
- Provide clear summaries and descriptions
- Document all parameters and response codes
- Include example requests/responses

## Performance Optimization

### Caching

**Use Redis caching for:**
- Frequently accessed API endpoints (30s default)
- Expensive database queries
- External API responses

```python
from django.core.cache import cache

# Cache for 30 seconds
cache.set('key', value, 30)
value = cache.get('key')
```

### Database Optimization

**Query optimization:**
- Use `select_related()` for foreign keys
- Use `prefetch_related()` for many-to-many and reverse foreign keys
- Add database indexes for frequently filtered/ordered fields
- Use `only()` and `defer()` to limit fields retrieved
- Monitor query counts with Django Debug Toolbar (local only)

### Task Optimization

**Celery best practices:**
- Keep tasks idempotent (safe to run multiple times)
- Use task retries for transient failures
- Batch operations when possible
- Monitor task queue length and worker capacity

## Error Handling

### Logging

**Use Django's logging framework:**

```python
import logging

logger = logging.getLogger(__name__)

logger.debug("Debug message")
logger.info("Info message")
logger.warning("Warning message")
logger.error("Error message", exc_info=True)
```
