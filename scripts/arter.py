from instagram.models import Story  # noqa: INP001


def run():
    story = Story.objects.get(story_id="3864373243738778145")
    story.generate_embedding()
