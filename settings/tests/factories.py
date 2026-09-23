from factory import Faker
from factory.django import DjangoModelFactory

from settings.models import CoreAPISetting
from settings.models import OpenAISetting


class OpenAISettingFactory(DjangoModelFactory):
    api_key = Faker(
        "password",
        length=51,
        special_chars=False,
        digits=True,
        upper_case=True,
        lower_case=True,
    )
    model_name = Faker(
        "random_element",
        elements=("gpt-4", "gpt-4-turbo", "gpt-3.5-turbo", "gpt-4o", "gpt-4o-mini"),
    )

    class Meta:
        model = OpenAISetting


class CoreAPISettingFactory(DjangoModelFactory):
    api_url = Faker("url")
    api_token = Faker(
        "password",
        length=64,
        special_chars=False,
        digits=True,
        upper_case=True,
        lower_case=True,
    )
    saveapi_url = Faker("url")
    saveapi_api_key = Faker(
        "password",
        length=64,
        special_chars=False,
        digits=True,
        upper_case=True,
        lower_case=True,
    )

    class Meta:
        model = CoreAPISetting
