# Instarchiver Backend

Welcome to Instarchiver Backend, the Django REST API for archiving Instagram content. Yes, another backend project—because the world clearly needed one more.

[![codecov](https://codecov.io/github/instarchiver/instarchiver-backend/graph/badge.svg?token=qLvch7qoAF)](https://codecov.io/github/instarchiver/instarchiver-backend)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Uptime Robot status](https://img.shields.io/uptimerobot/status/m801829955-01095d331ccf91d3ab2297bc)](https://stats.uptimerobot.com/GKy6liBGw7/801829955)
[![Uptime Robot ratio (7 days)](https://img.shields.io/uptimerobot/ratio/7/m801829955-01095d331ccf91d3ab2297bc)](https://stats.uptimerobot.com/GKy6liBGw7/801829955)

License: MIT (because why not?)

## Local Setup (Docker Only)

So you want to run this locally? Great! But don’t even think about skipping Docker. If you’re allergic to containers, this probably isn’t the project for you.

### Prerequisites

- Docker & Docker Compose (seriously, just install them)

### Getting Started

Open your terminal (yes, the scary black window) and run:

```bash
docker-compose -f docker-compose.local.yml up
```

If you see errors, try turning it off and on again. Or, you know, read the error message.

Services will magically appear at:

- **Django app**: http://localhost:8000
- **API Documentation**: http://localhost:8000/api/docs/
- **Admin Interface**: http://localhost:8000/admin/

## Common Docker Compose Tasks

Because you’ll probably forget these commands, here they are (again):

### 1. Build Images (when you break something or update dependencies)

```bash
docker-compose -f docker-compose.local.yml build
```

### 2. Start All Services (in case you closed everything by accident)

```bash
docker-compose -f docker-compose.local.yml up
```

### 3. Run Database Migrations (Django loves migrations, trust us)

Open a new terminal (yes, another one):

```bash
docker-compose -f docker-compose.local.yml run --rm django python manage.py migrate
```

### 4. Create Admin User (so you can actually log in)

```bash
docker-compose -f docker-compose.local.yml run --rm django python manage.py createsuperuser
```

Now, go to http://localhost:8000/admin/ and pretend you’re in charge.
