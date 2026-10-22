from instagram.models import User


def run():
    user = User.objects.get(username="dota_2")
    user.update_stories_from_saveapi()
