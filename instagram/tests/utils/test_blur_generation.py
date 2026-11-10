import base64
from io import BytesIO

from django.test import TestCase
from PIL import Image as PILImage

from instagram.utils import generate_blur_data_url_from_image


def _decode(result):
    return PILImage.open(BytesIO(base64.b64decode(result)))


class TestGenerateBlurDataUrlFromImage(TestCase):
    """Tests for the generate_blur_data_url_from_image utility function."""

    def test_shrinks_to_two_percent(self):
        """The default output is 2% of the original size."""
        result = generate_blur_data_url_from_image(PILImage.new("RGB", (200, 200)))

        assert _decode(result).size == (4, 4)

    def test_custom_resize_percentage(self):
        """resize_percentage controls the output size."""
        result = generate_blur_data_url_from_image(
            PILImage.new("RGB", (100, 100)),
            resize_percentage=0.05,
        )

        assert _decode(result).size == (5, 5)

    def test_small_image_keeps_at_least_one_pixel(self):
        """A 10x10 image shrinks to 1x1 instead of failing on a zero size."""
        result = generate_blur_data_url_from_image(PILImage.new("RGB", (10, 10)))

        assert _decode(result).size == (1, 1)

    def test_rgba_png_becomes_jpeg(self):
        """Images with alpha are flattened and always encoded as JPEG."""
        img = PILImage.new("RGBA", (200, 100), color=(0, 0, 255, 128))

        decoded = _decode(generate_blur_data_url_from_image(img))

        assert decoded.format == "JPEG"
        assert decoded.size == (4, 2)

    def test_every_input_format_becomes_jpeg(self):
        """JPEG, PNG and GIF files all produce a JPEG blur."""
        for img_format in ["JPEG", "PNG", "GIF"]:
            buffer = BytesIO()
            PILImage.new("RGB", (100, 100), color="yellow").save(
                buffer,
                format=img_format,
            )
            buffer.seek(0)

            result = generate_blur_data_url_from_image(PILImage.open(buffer))

            assert _decode(result).format == "JPEG"
