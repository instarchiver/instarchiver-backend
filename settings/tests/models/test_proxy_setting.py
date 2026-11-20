import pytest
from django.core.exceptions import ValidationError
from django.test import TestCase

from settings.models import ProxySetting


class ProxySettingModelTest(TestCase):
    def test_singleton_behavior(self):
        ProxySetting.objects.all().delete()
        setting1 = ProxySetting.get_solo()
        setting2 = ProxySetting.get_solo()

        assert setting1.pk == setting2.pk
        assert ProxySetting.objects.count() == 1
        assert str(setting1) == "Proxy Settings"
        assert setting1.proxy_url == ""
        assert setting1.verify_ssl is True

    def test_valid_proxy_urls_pass_clean_including_docker_hostnames(self):
        valid_urls = [
            "",
            "   ",
            "http://squid:3128",
            "socks5h://gluetun:1080",
            " https://user:pass@proxy.example.com:8443 ",
            "socks5://[::1]:1080",
        ]
        for raw_url in valid_urls:
            setting = ProxySetting.get_solo()
            setting.proxy_url = raw_url
            setting.full_clean()
            setting.save()
            assert setting.proxy_url == raw_url.strip()

    @pytest.mark.usefixtures("db")
    def test_invalid_proxy_urls_rejected(self):
        invalid_urls = [
            "ftp://proxy.example.com:21",
            "squid:3128",
            "http://",
            "http://proxy.example.com:99999",
        ]
        for raw_url in invalid_urls:
            setting = ProxySetting.get_solo()
            setting.proxy_url = raw_url
            with pytest.raises(ValidationError):
                setting.full_clean()
