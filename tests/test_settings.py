"""Tests for settings migration and history pruning."""

from app.core.settings import AppSettings


class FakeQ:
    def __init__(self):
        self.data = {}

    def contains(self, key):
        return key in self.data

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):
        self.data[key] = value

    def sync(self):
        pass


def test_settings_migration_is_additive():
    settings = object.__new__(AppSettings)
    settings.q = FakeQ()
    settings.q.data["options/theme"] = "light"
    assert settings.migrate() == 2
    assert settings.option("theme", "dark") == "light"
    assert settings.option("start_page", "") == "dashboard"
    assert settings.option("copy_verify_mode", "") == "quick"
    assert settings.option("copy_retries", 0) == 1
    assert settings.option("settings_version", 0) == 2
    # Running again must not overwrite a user choice.
    settings.set_option("start_page", "browser")
    settings.migrate()
    assert settings.option("start_page", "dashboard") == "browser"
