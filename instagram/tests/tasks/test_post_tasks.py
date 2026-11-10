from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from instagram.models import Post
from instagram.models import PostMedia
from instagram.tasks import create_post_media
from instagram.tasks import download_post_media_from_url
from instagram.tasks import download_post_thumbnail_from_url
from instagram.tasks import generate_post_embedding
from instagram.tasks import increment_post_view_count
from instagram.tasks import periodic_create_post_media
from instagram.tasks import periodic_download_post_media
from instagram.tasks import periodic_download_post_thumbnails
from instagram.tasks import periodic_generate_post_embeddings
from instagram.tasks import periodic_process_post_thumbnails
from instagram.tasks import process_post_thumbnail
from instagram.tests.factories import PostFactory
from instagram.tests.factories import PostMediaFactory


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


def _post_with_thumbnail(thumbnail="posts/x/a.jpg", **kwargs):
    """Return a post with a stored thumbnail name and no embedding."""
    post = PostFactory(**kwargs)
    Post.objects.filter(pk=post.pk).update(thumbnail=thumbnail)
    return post


class TestGeneratePostEmbedding(TestCase):
    @patch("instagram.models.Post.generate_embedding", return_value=[0.1] * 1536)
    def test_generates_for_post_that_needs_it(self, mock_generate):
        post = _post_with_thumbnail()

        result = generate_post_embedding(post.id)

        assert result["generated"] is True
        assert result["dimensions"] == 1536  # noqa: PLR2004
        mock_generate.assert_called_once()

    @patch("instagram.models.Post.generate_embedding")
    def test_skips_posts_that_cannot_or_need_not_be_embedded(self, mock_generate):
        done = _post_with_thumbnail()
        Post.objects.filter(pk=done.pk).update(embedding=[0.1] * 1536)
        no_thumbnail = PostFactory()
        video_file = _post_with_thumbnail(thumbnail="posts/x/old.MP4")

        for post_id in ("does-not-exist", done.id, no_thumbnail.id, video_file.id):
            assert generate_post_embedding(post_id)["generated"] is False
        mock_generate.assert_not_called()


class TestPeriodicGeneratePostEmbeddings(TestCase):
    @patch("instagram.tasks.post.generate_post_embedding.delay")
    def test_queues_only_posts_needing_an_embedding(self, mock_delay):
        needs = _post_with_thumbnail()
        done = _post_with_thumbnail()
        Post.objects.filter(pk=done.pk).update(embedding=[0.1] * 1536)
        PostFactory()  # no thumbnail
        _post_with_thumbnail(thumbnail="posts/x/old.mp4")

        result = periodic_generate_post_embeddings()

        mock_delay.assert_called_once_with(needs.pk)
        assert result["queued"] == 1

    @patch("instagram.tasks.post.EMBEDDING_BATCH_SIZE", 2)
    @patch("instagram.tasks.post.generate_post_embedding.delay")
    def test_queues_newest_posts_up_to_the_batch_size(self, mock_delay):
        posts = [_post_with_thumbnail() for _ in range(3)]
        for days, post in enumerate(posts):
            Post.objects.filter(pk=post.pk).update(
                created_at=timezone.now() - timedelta(days=days),
            )

        periodic_generate_post_embeddings()

        queued = {call.args[0] for call in mock_delay.call_args_list}
        assert queued == {posts[0].pk, posts[1].pk}


MEDIAS = {"medias": [{"type": "image", "url": "https://cdn.example.com/a.jpg"}]}


class TestCreatePostMedia(TestCase):
    def test_creates_rows_for_post_that_needs_them(self):
        post = PostFactory(raw_data=MEDIAS)

        result = create_post_media(post.id)

        assert result["created"] is True
        assert result["media_count"] == 1
        assert PostMedia.objects.filter(post=post).count() == 1

    @patch("instagram.models.Post.create_media")
    def test_skips_posts_without_usable_media_or_with_rows(self, mock_create):
        has_rows = PostFactory(raw_data=MEDIAS)
        PostMediaFactory(post=has_rows)
        empty = PostFactory(raw_data={"medias": []})
        no_url = PostFactory(raw_data={"medias": [{"type": "image", "url": ""}]})

        for post_id in ("does-not-exist", has_rows.id, empty.id, no_url.id):
            assert create_post_media(post_id)["created"] is False
        mock_create.assert_not_called()


class TestDownloadPostMediaFromUrl(TestCase):
    @patch("instagram.models.PostMedia.download_media", return_value="posts/x/a.mp4")
    def test_downloads_media(self, mock_download):
        post_media = PostMediaFactory()

        result = download_post_media_from_url(post_media.id)

        assert result == {
            "success": True,
            "post_media_id": post_media.id,
            "downloaded": True,
        }
        mock_download.assert_called_once()

    def test_missing_post_media(self):
        result = download_post_media_from_url(999999)

        assert result == {"success": False, "error": "PostMedia not found"}


class TestPeriodicCreatePostMedia(TestCase):
    @patch("instagram.tasks.post.create_post_media.delay")
    def test_queues_only_posts_with_usable_media_and_no_rows(self, mock_delay):
        needs = PostFactory(raw_data=MEDIAS)
        has_rows = PostFactory(raw_data=MEDIAS)
        PostMediaFactory(post=has_rows)
        PostFactory(raw_data={"medias": []})
        PostFactory(raw_data={"medias": None})
        PostFactory(raw_data={"medias": [{"type": "image", "url": ""}]})
        PostFactory(raw_data=None)

        periodic_create_post_media()

        mock_delay.assert_called_once_with(needs.pk)


class TestPeriodicDownloadPostMedia(TestCase):
    @patch("instagram.tasks.post.download_post_media_from_url.delay")
    def test_queues_only_recent_media_without_file(self, mock_delay):
        recent = PostMediaFactory()
        with_file = PostMediaFactory()
        PostMedia.objects.filter(pk=with_file.pk).update(media="posts/x/a.mp4")
        PostMediaFactory(media_url="")
        old = PostMediaFactory()
        Post.objects.filter(pk=old.post.pk).update(
            created_at=timezone.now() - timedelta(days=8),
        )

        periodic_download_post_media()

        mock_delay.assert_called_once_with(recent.pk)
