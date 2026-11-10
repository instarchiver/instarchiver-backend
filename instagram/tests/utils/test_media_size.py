from io import BytesIO

from django.test import TestCase
from PIL import Image

from instagram.tests.tasks.test_story_thumbnail import _make_video_bytes
from instagram.utils import get_media_size


def _jpeg(size, orientation=None):
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    buffer = BytesIO()
    Image.new("RGB", size).save(buffer, "JPEG", exif=exif.tobytes())
    return buffer.getvalue()


class TestGetMediaSize(TestCase):
    def test_image_size(self):
        assert get_media_size(_jpeg((200, 100))) == (200, 100)

    def test_image_turned_by_exif_reports_shown_size(self):
        assert get_media_size(_jpeg((200, 100), orientation=6)) == (100, 200)

    def test_video_size_from_stream(self):
        assert get_media_size(_make_video_bytes()) == (32, 32)

    def test_unreadable_bytes(self):
        assert get_media_size(b"not media") == (None, None)
