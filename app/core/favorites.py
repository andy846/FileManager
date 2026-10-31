"""Persistent favourite folders shared by the dashboard and browser."""

import os

from app.core.utils import normalize_path

MAX_FAVORITES = 30
_KEY = "favorites/folders"
_GROUPS_KEY = "favorites/groups"
DEFAULT_GROUP = "常用"


def _normalize(path):
    """Return a stable absolute path without changing drive/UNC semantics."""
    text = str(path).strip().strip('"')
    if not text:
        return ""
    return normalize_path(os.path.abspath(text))


def _key(path):
    return os.path.normcase(normalize_path(str(path)))


def list_favorites(settings):
    """Return the stored favourite folders in insertion order."""
    raw = settings.value(_KEY, [])
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    result = []
    seen = set()
    for item in raw:
        path = _normalize(item)
        if not path or _key(path) in seen:
            continue
        seen.add(_key(path))
        result.append(path)
    return result


def add_favorite(settings, path):
    """Add *path* to the favourites, returning True when the list changed."""
    path = _normalize(path)
    if not path:
        return False
    favorites = list_favorites(settings)
    if any(_key(p) == _key(path) for p in favorites):
        return False
    favorites.append(path)
    favorites = favorites[-MAX_FAVORITES:]
    settings.set_value(_KEY, favorites)
    return True


def remove_favorite(settings, path):
    """Remove *path* from favourites, returning True when it existed."""
    target = _key(_normalize(path))
    favorites = list_favorites(settings)
    kept = [p for p in favorites if _key(p) != target]
    if len(kept) == len(favorites):
        return False
    settings.set_value(_KEY, kept)
    groups = dict(settings.value(_GROUPS_KEY, {}) or {})
    for key in list(groups):
        if _key(key) == target:
            groups.pop(key, None)
    settings.set_value(_GROUPS_KEY, groups)
    return True


def clear_favorites(settings):
    settings.set_value(_KEY, [])
    settings.set_value(_GROUPS_KEY, {})


def favorite_groups(settings):
    """Return ``{normalized path: group}`` for existing favourites."""
    raw = settings.value(_GROUPS_KEY, {}) or {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def favorite_group(settings, path):
    target = _key(_normalize(path))
    groups = favorite_groups(settings)
    for key, value in groups.items():
        if _key(key) == target:
            return value or DEFAULT_GROUP
    return DEFAULT_GROUP


def set_favorite_group(settings, path, group):
    path = _normalize(path)
    if not path:
        return
    groups = favorite_groups(settings)
    for key in list(groups):
        if _key(key) == _key(path):
            groups.pop(key, None)
            break
    groups[path] = str(group).strip() or DEFAULT_GROUP
    settings.set_value(_GROUPS_KEY, groups)


def grouped_favorites(settings):
    """Return ``[(group, [paths])]`` in a stable display order."""
    groups = {}
    for path in list_favorites(settings):
        group = favorite_group(settings, path)
        groups.setdefault(group, []).append(path)
    ordered = []
    if DEFAULT_GROUP in groups:
        ordered.append((DEFAULT_GROUP, groups.pop(DEFAULT_GROUP)))
    for name in sorted(groups):
        ordered.append((name, groups[name]))
    return ordered
