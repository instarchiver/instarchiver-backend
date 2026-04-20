from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('instagram', '0034_historicalpost_is_flagged_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='story',
            name='thumbnail_insight',
        ),
        migrations.RemoveField(
            model_name='story',
            name='thumbnail_insight_token_usage',
        ),
    ]
