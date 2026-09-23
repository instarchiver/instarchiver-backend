from django.test import TestCase

from settings.models import CoreAPISetting
from settings.tests.factories import CoreAPISettingFactory


class CoreAPISettingModelTest(TestCase):
    def test_factory_creates_instance(self):
        """Test that the factory creates a Core API setting instance."""
        setting = CoreAPISettingFactory()

        assert isinstance(setting, CoreAPISetting)
        assert setting.api_url
        assert setting.api_token
        assert setting.saveapi_url
        assert setting.saveapi_api_key
        assert setting.created_at is not None
        assert setting.updated_at is not None

    def test_singleton_behavior(self):
        """Test that Core API setting maintains singleton behavior."""
        # Clear any existing instances first
        CoreAPISetting.objects.all().delete()

        setting1 = CoreAPISettingFactory()
        # Since it's a singleton model, getting another instance should return the same one  # noqa: E501
        setting2 = CoreAPISetting.get_solo()

        # Both should reference the same instance
        assert setting1.id == setting2.id
        assert CoreAPISetting.objects.count() == 1

    def test_str_representation(self):
        """Test the string representation of Core API setting."""
        setting = CoreAPISettingFactory()

        assert str(setting) == "Core API Settings"

    def test_default_values(self):
        """Test default values for Core API setting fields."""
        setting = CoreAPISetting.objects.create()

        assert setting.api_url == ""
        assert setting.api_token == ""
        assert setting.saveapi_url == "https://api.saveapi.org/v1"
        assert setting.saveapi_api_key == ""
        assert setting.created_at is not None
        assert setting.updated_at is not None

    def test_field_lengths(self):
        """Test field length constraints."""
        setting = CoreAPISettingFactory()

        # Test api_url max length (from model definition)
        assert len(setting.api_url) <= 255  # noqa: PLR2004

        # Test api_token max length (from model definition)
        assert len(setting.api_token) <= 255  # noqa: PLR2004

        # Test SaveAPI field max lengths (from model definition)
        assert len(setting.saveapi_url) <= 255  # noqa: PLR2004
        assert len(setting.saveapi_api_key) <= 255  # noqa: PLR2004

    def test_factory_generates_realistic_data(self):
        """Test that factory generates realistic Core API data."""
        setting = CoreAPISettingFactory()

        # Check that api_url is a valid URL format
        assert setting.api_url.startswith(("http://", "https://"))

        # Check that api_token looks like a reasonable length for an API token
        assert len(setting.api_token) > 20  # noqa: PLR2004
