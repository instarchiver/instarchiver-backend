from django.test import TestCase

from instagram.tasks import increment_post_view_count
from instagram.tests.factories import PostFactory


class TestIncrementPostViewCount(TestCase):
    def test_increments_view_count(self):
        post = PostFactory()
        assert post.view_count == 0

        increment_post_view_count(post.id)

        post.refresh_from_db()
        assert post.view_count == 1

    def test_does_not_create_historical_record(self):
        """Incrementing view_count must use .update(), not .save(), to avoid
        triggering simple_history's post_save signal on every view."""
        post = PostFactory()
        history_count_before = post.history.count()

        increment_post_view_count(post.id)

        assert post.history.count() == history_count_before

    def test_missing_post_is_a_no_op(self):
        increment_post_view_count("does-not-exist")
