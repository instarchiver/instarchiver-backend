from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY can't run inside a transaction. If the build
    # is interrupted, the INVALID index blocks a rerun: drop it with
    # DROP INDEX CONCURRENTLY post_post_created_at_idx;
    # and run migrate again.
    atomic = False

    dependencies = [
        ("instagram", "0038_story_created_at_idx"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="post",
            index=models.Index(fields=["post_created_at"], name="post_post_created_at_idx"),
        ),
    ]
