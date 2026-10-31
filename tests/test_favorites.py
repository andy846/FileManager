"""Tests for shared favourites storage and groups."""

import os

from app.core.favorites import (
    DEFAULT_GROUP, MAX_FAVORITES, add_favorite, clear_favorites,
    favorite_group, grouped_favorites, list_favorites, remove_favorite,
    set_favorite_group,
)


class FakeSettings:
    def __init__(self):
        self.data = {}

    def value(self, name, default=None):
        return self.data.get(name, default)

    def set_value(self, name, value):
        self.data[name] = value


def test_add_list_and_deduplicate(tmp_path):
    settings = FakeSettings()
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()

    assert add_favorite(settings, first) is True
    assert add_favorite(settings, str(first) + os.sep) is False
    assert add_favorite(settings, second) is True
    assert list_favorites(settings) == [str(first), str(second)]


def test_remove_and_clear(tmp_path):
    settings = FakeSettings()
    folder = tmp_path / "folder"
    folder.mkdir()
    add_favorite(settings, folder)
    assert remove_favorite(settings, folder) is True
    assert remove_favorite(settings, folder) is False
    add_favorite(settings, folder)
    clear_favorites(settings)
    assert list_favorites(settings) == []


def test_favourites_are_capped(tmp_path):
    settings = FakeSettings()
    for index in range(MAX_FAVORITES + 5):
        add_favorite(settings, tmp_path / f"folder-{index}")
    favorites = list_favorites(settings)
    assert len(favorites) == MAX_FAVORITES
    assert favorites[-1].endswith(f"folder-{MAX_FAVORITES + 4}")


def test_favourite_groups(tmp_path):
    settings = FakeSettings()
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    add_favorite(settings, first)
    add_favorite(settings, second)
    assert favorite_group(settings, first) == DEFAULT_GROUP
    set_favorite_group(settings, first, "專案 A")
    assert favorite_group(settings, first) == "專案 A"
    groups = grouped_favorites(settings)
    assert groups[0][0] == DEFAULT_GROUP
    assert any(name == "專案 A" and paths for name, paths in groups)
    remove_favorite(settings, first)
    assert favorite_group(settings, first) == DEFAULT_GROUP
