"""Populate caption field from raw_data for existing Post records."""

from instagram.models import Post


def run():
    """Populate caption field from raw_data for posts with empty captions."""
    # Query posts with empty captions but valid raw_data
    posts = Post.objects.filter(
        caption="",
        raw_data__isnull=False,
    )

    total_posts = posts.count()
    print(f"Found {total_posts} posts with empty captions and raw_data...")  # noqa: T201

    if total_posts == 0:
        print("No posts to process. Exiting.")  # noqa: T201
        return

    updated_count = 0
    skipped_count = 0
    error_count = 0

    for post in posts:
        try:
            # Extract caption from raw_data
            raw_data = post.raw_data
            caption_data = raw_data.get("caption")

            # Handle different caption formats
            if caption_data:
                if isinstance(caption_data, dict):
                    caption_text = caption_data.get("text", "")
                elif isinstance(caption_data, str):
                    caption_text = caption_data
                else:
                    caption_text = ""
            else:
                caption_text = ""

            # Only update if we found a non-empty caption
            if caption_text:
                Post.objects.filter(id=post.id).update(caption=caption_text)
                updated_count += 1
                # Truncate caption for display if too long
                display_caption = (
                    caption_text[:50] + "..."
                    if len(caption_text) > 50  # noqa: PLR2004
                    else caption_text
                )
                print(f"✓ Post {post.id}: '{display_caption}'")  # noqa: T201
            else:
                skipped_count += 1
                print(f"⊘ Post {post.id}: No caption in raw_data")  # noqa: T201

        except Exception as e:  # noqa: BLE001
            error_count += 1
            print(f"✗ Post {post.id}: {e}")  # noqa: T201

    # Print summary
    print("\n" + "=" * 50)  # noqa: T201
    print("Summary:")  # noqa: T201
    print(f"  Total posts processed: {total_posts}")  # noqa: T201
    print(f"  ✓ Updated: {updated_count}")  # noqa: T201
    print(f"  ⊘ Skipped (no caption): {skipped_count}")  # noqa: T201
    print(f"  ✗ Errors: {error_count}")  # noqa: T201
    print("=" * 50)  # noqa: T201
    print("\nDone!")  # noqa: T201
