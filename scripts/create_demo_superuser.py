from django.contrib.auth.models import User  # noqa: INP001


def run():
    if User.objects.filter(username="admin").exists():
        print("Demo superuser already exists.")  # noqa: T201
        return
    User.objects.create_superuser(
        username="admin",
        email="admin@preview.local",
        password="password",  # noqa: S106
    )
    print("Created demo superuser: admin / password")  # noqa: T201
