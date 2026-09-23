from io import BytesIO
from unittest.mock import patch

import av
from django.core.files.base import ContentFile
from django.test import TestCase
from django.test import override_settings
from PIL import Image

from instagram.models import Story
from instagram.tasks import download_story_media_from_url
from instagram.tasks import generate_story_thumbnail_from_media
from instagram.tests.factories import StoryFactory
from instagram.utils import extract_video_frame


def _make_video_bytes(seconds=2, fps=10):
    """Encode a tiny solid-red mp4 in memory."""
    buffer = BytesIO()
    with av.open(buffer, mode="w", format="mp4") as container:
        stream = container.add_stream("mpeg4", rate=fps)
        stream.width = 32
        stream.height = 32
        stream.pix_fmt = "yuv420p"
        image = Image.new("RGB", (32, 32), color="red")
        for _ in range(seconds * fps):
            frame = av.VideoFrame.from_image(image)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return buffer.getvalue()


class TestExtractVideoFrame(TestCase):
    def test_returns_jpeg_bytes(self):
        content = extract_video_frame(BytesIO(_make_video_bytes()))

        assert content is not None
        image = Image.open(BytesIO(content))
        assert image.format == "JPEG"
        assert image.size == (32, 32)

    def test_short_video_falls_back_to_last_frame(self):
        content = extract_video_frame(
            BytesIO(_make_video_bytes(seconds=1)),
            at_seconds=30,
        )

        assert content is not None

    def test_invalid_file_returns_none(self):
        assert extract_video_frame(BytesIO(b"not a video")) is None


class TestGenerateThumbnailFromMedia(TestCase):
    def _video_story(self):
        story = StoryFactory(thumbnail_url="", media_url="")
        story.media.save("clip.mp4", ContentFile(_make_video_bytes()), save=True)
        return story

    def test_generates_thumbnail_for_video(self):
        story = self._video_story()

        saved_name = story.generate_thumbnail_from_media()

        assert saved_name is not None
        assert saved_name.endswith(".jpg")

    def test_skips_when_thumbnail_exists(self):
        story = self._video_story()
        story.thumbnail.save("thumb.jpg", ContentFile(b"x"), save=True)

        assert story.generate_thumbnail_from_media() is None

    def test_skips_image_media(self):
        story = StoryFactory(thumbnail_url="", media_url="")
        story.media.save("photo.webp", ContentFile(b"x"), save=True)

        assert story.generate_thumbnail_from_media() is None

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_task_saves_thumbnail(self):
        story = self._video_story()

        result = generate_story_thumbnail_from_media.delay(story.story_id)

        assert result.result["generated"] is True
        story.refresh_from_db()
        assert story.thumbnail.name.endswith(".jpg")

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_task_story_not_found(self):
        result = generate_story_thumbnail_from_media.delay("missing")

        assert result.result["success"] is False


@patch("instagram.tasks.story.generate_story_thumbnail_from_media.delay")
class TestDownloadMediaTriggersThumbnail(TestCase):
    """The thumbnail task is queued only after the video is stored."""

    def _run(self, download_result, thumbnail_url=""):
        story = StoryFactory(
            thumbnail_url=thumbnail_url,
            media_url="https://cdn.example.com/clip.mp4",
        )
        with patch.object(Story, "download_media", return_value=download_result):
            download_story_media_from_url(story.story_id)
        return story

    def test_queues_after_video_saved(self, mock_delay):
        story = self._run("stories/clip.mp4")

        mock_delay.assert_called_once_with(story.story_id)
        story.refresh_from_db()
        assert story.media.name == "stories/clip.mp4"

    def test_not_queued_when_download_fails(self, mock_delay):
        self._run(None)

        mock_delay.assert_not_called()

    def test_not_queued_when_thumbnail_url_exists(self, mock_delay):
        self._run(
            "stories/clip.mp4",
            thumbnail_url="https://cdn.example.com/thumb.jpg",
        )

        mock_delay.assert_not_called()

    def test_not_queued_for_image_media(self, mock_delay):
        self._run("stories/photo.webp")

        mock_delay.assert_not_called()
