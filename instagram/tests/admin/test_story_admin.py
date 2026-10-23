from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from instagram.tests.factories import StoryFactory

DjangoUser = get_user_model()


class TestStoryAdminQueryset(TestCase):
    """The Story admin should not load the heavy columns on its list page."""

    def setUp(self):
        self.story = StoryFactory(embedding=[0.1] * 1536, raw_api_data={"a": 1})
        superuser = DjangoUser.objects.create_superuser(
            username="adminsuper",
            password="testpassword123",  # noqa: S106
            email="adminsuper@example.com",
        )
        self.client.force_login(superuser)

    def test_changelist_skips_heavy_columns(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse("admin:instagram_story_changelist"))
        assert response.status_code == 200  # noqa: PLR2004
        selects = [
            q["sql"].split(" FROM ")[0]
            for q in ctx.captured_queries
            if q["sql"].startswith("SELECT")
            and '"instagram_story"."story_id"' in q["sql"]
        ]
        assert selects
        for sql in selects:
            assert '"embedding"' not in sql
            assert '"raw_api_data"' not in sql
            assert '"moderation_result"' not in sql

    def test_change_page_still_renders(self):
        url = reverse("admin:instagram_story_change", args=[self.story.pk])
        response = self.client.get(url)
        assert response.status_code == 200  # noqa: PLR2004
