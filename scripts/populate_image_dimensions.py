"""Populate width and height fields for existing Post and PostMedia thumbnails."""

from io import BytesIO

from django.db.models import Q
from PIL import Image

from instagram.models import Post
from instagram.models import PostMedia


def run():
    """Populate image dimensions for existing thumbnails."""
    # Process Posts
    posts = Post.objects.filter(
        thumbnail__isnull=False,
    ).filter(
        Q(width__isnull=True) | Q(height__isnull=True),
    )

    print(f"Processing {posts.count()} posts...")  # noqa: T201
    for post in posts:
        try:
            with post.thumbnail.open("rb") as f:
                image = Image.open(BytesIO(f.read()))
                width, height = image.size

            Post.objects.filter(id=post.id).update(width=width, height=height)
            print(f"✓ Post {post.id}: {width}x{height}")  # noqa: T201
        except Exception as e:  # noqa: BLE001
            print(f"✗ Post {post.id}: {e}")  # noqa: T201

    # Process PostMedia
    post_media_items = PostMedia.objects.filter(
        thumbnail__isnull=False,
    ).filter(
        Q(width__isnull=True) | Q(height__isnull=True),
    )

    print(f"\nProcessing {post_media_items.count()} post media items...")  # noqa: T201
    for post_media in post_media_items:
        try:
            with post_media.thumbnail.open("rb") as f:
                image = Image.open(BytesIO(f.read()))
                width, height = image.size

            PostMedia.objects.filter(id=post_media.id).update(
                width=width,
                height=height,
            )
            print(f"✓ PostMedia {post_media.id}: {width}x{height}")  # noqa: T201
        except Exception as e:  # noqa: BLE001
            print(f"✗ PostMedia {post_media.id}: {e}")  # noqa: T201

    print("\nDone!")  # noqa: T201
