from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from instagram.models import Post
from instagram.tasks import download_post_thumbnail_from_url
from instagram.tasks import increment_post_view_count
from instagram.tasks import periodic_download_post_thumbnails
from instagram.tasks import periodic_process_post_thumbnails
from instagram.tasks import process_post_thumbnail
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


class TestDownloadPostThumbnailFromUrl(TestCase):
    @patch("instagram.models.Post.download_thumbnail", return_value="posts/x/a.jpg")
    def test_downloads_thumbnail(self, mock_download):
        post = PostFactory()

        result = download_post_thumbnail_from_url(post.id)

        assert result == {"success": True, "post_id": post.id, "downloaded": True}
        mock_download.assert_called_once()

    def test_missing_post(self):
        result = download_post_thumbnail_from_url("does-not-exist")

        assert result == {"success": False, "error": "Post not found"}


class TestPeriodicDownloadPostThumbnails(TestCase):
    @patch("instagram.tasks.post.download_post_thumbnail_from_url.delay")
    def test_queues_only_recent_posts_without_thumbnail(self, mock_delay):
        recent = PostFactory()
        with_thumbnail = PostFactory()
        Post.objects.filter(pk=with_thumbnail.pk).update(thumbnail="posts/x/a.jpg")
        PostFactory(thumbnail_url="")
        old = PostFactory()
        Post.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=8),
        )

        result = periodic_download_post_thumbnails()

        mock_delay.assert_called_once_with(recent.pk)
        assert result["queued"] == 1


def _unprocessed_post(**kwargs):
    """Return a post with a stored thumbnail name and no blur or size."""
    post = PostFactory(blur_data_url="", **kwargs)
    Post.objects.filter(pk=post.pk).update(thumbnail="posts/x/a.jpg")
    return post


class TestProcessPostThumbnail(TestCase):
    @patch("instagram.models.Post.process_thumbnail")
    def test_processes_post_that_needs_it(self, mock_process):
        post = _unprocessed_post()

        result = process_post_thumbnail(post.id)

        assert result == {"success": True, "post_id": post.id, "processed": True}
        mock_process.assert_called_once()

    @patch("instagram.models.Post.process_thumbnail")
    def test_skips_missing_done_or_thumbnailless_posts(self, mock_process):
        done = _unprocessed_post(width=10, height=10)
        Post.objects.filter(pk=done.pk).update(blur_data_url="abc")
        no_thumbnail = PostFactory(blur_data_url="")

        for post_id in ("does-not-exist", done.id, no_thumbnail.id):
            result = process_post_thumbnail(post_id)
            assert result["processed"] is False
        mock_process.assert_not_called()


class TestPeriodicProcessPostThumbnails(TestCase):
    @patch("instagram.tasks.post.process_post_thumbnail.delay")
    def test_queues_posts_missing_blur_or_size(self, mock_delay):
        no_blur = _unprocessed_post(width=10, height=10)
        no_size = _unprocessed_post()
        Post.objects.filter(pk=no_size.pk).update(blur_data_url="abc")
        done = _unprocessed_post(width=10, height=10)
        Post.objects.filter(pk=done.pk).update(blur_data_url="abc")
        PostFactory(blur_data_url="")  # no thumbnail

        result = periodic_process_post_thumbnails()

        queued = {call.args[0] for call in mock_delay.call_args_list}
        assert queued == {no_blur.pk, no_size.pk}
        assert result["queued"] == 2  # noqa: PLR2004
