from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations
from pgvector.django import HnswIndex


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    # If the build is interrupted, drop the INVALID index before rerunning:
    # DROP INDEX CONCURRENTLY story_embedding_hnsw_idx;
    # In production, bypass PgBouncer (override POSTGRES_HOST=postgres and
    # POSTGRES_PORT=5432, since the entrypoint overwrites DATABASE_URL) with
    # PGOPTIONS="-c maintenance_work_mem=512MB" so the graph builds in memory.
    atomic = False

    dependencies = [
        ("instagram", "0040_user_created_at_idx"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="story",
            index=HnswIndex(
                ef_construction=64,
                fields=["embedding"],
                m=16,
                name="story_embedding_hnsw_idx",
                opclasses=["vector_l2_ops"],
            ),
        ),
    ]
