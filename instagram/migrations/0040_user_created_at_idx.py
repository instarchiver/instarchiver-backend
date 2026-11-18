from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY can't run inside a transaction. If the build
    # is interrupted, the INVALID index blocks a rerun: drop it with
    # DROP INDEX CONCURRENTLY user_created_at_idx;
    # and run migrate again.
    atomic = False

    dependencies = [
        ("instagram", "0039_post_post_created_at_idx"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="user",
            index=models.Index(fields=["created_at"], name="user_created_at_idx"),
        ),
    ]
