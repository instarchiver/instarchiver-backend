from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("instagram", "0035_story_remove_thumbnail_insight"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="historicalpost",
            name="thumbnail_insight",
        ),
        migrations.RemoveField(
            model_name="historicalpost",
            name="thumbnail_insight_token_usage",
        ),
        migrations.RemoveField(
            model_name="post",
            name="thumbnail_insight",
        ),
        migrations.RemoveField(
            model_name="post",
            name="thumbnail_insight_token_usage",
        ),
    ]
