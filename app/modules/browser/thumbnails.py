"""Lazy image thumbnails for the browser icon view.

The icon provider is also used by the list view for every file, so loading a
thumbnail eagerly for every image makes large folders (especially network
shares) much slower than Windows Explorer.  Thumbnails are therefore only
generated while the icon view is active, and images are decoded at thumbnail
size instead of full resolution.
"""

import os

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QImageReader, QPixmap
from PyQt6.QtWidgets import QFileIconProvider

from app.modules.browser.preview import IMAGE_EXTENSIONS

MAX_THUMBNAIL_BYTES = 10 * 1024 * 1024
CACHE_LIMIT = 300
FAILED_LIMIT = 1000
THUMBNAIL_SIZE = QSize(112, 112)


class ThumbnailIconProvider(QFileIconProvider):
    """Provide real thumbnails for common image files, system icons otherwise."""

    def __init__(self):
        super().__init__()
        self._cache = {}
        self._failed = set()
        self._thumbnails_enabled = False

    def set_thumbnails_enabled(self, enabled):
        """Enable image decoding only for the icon/thumbnail view."""
        self._thumbnails_enabled = bool(enabled)
        if not self._thumbnails_enabled:
            # Cached thumbnails are still cheap, but drop them so the list
            # view always uses the lightweight system icons.
            self._cache.clear()

    def icon(self, info):
        if not self._thumbnails_enabled:
            return super().icon(info)
        try:
            path = info.filePath() if hasattr(info, "filePath") else str(info)
            if not path or not info.isFile():
                return super().icon(info)
        except Exception:
            return super().icon(info)

        extension = os.path.splitext(path)[1].lower().lstrip(".")
        if extension not in IMAGE_EXTENSIONS:
            return super().icon(info)

        cached = self._cache.get(path)
        if cached is not None:
            return cached
        if path in self._failed:
            return super().icon(info)

        try:
            size = info.size()
            if size is not None and size > MAX_THUMBNAIL_BYTES:
                self._remember_failure(path)
                return super().icon(info)
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            source_size = reader.size()
            if source_size.isValid() and not source_size.isEmpty():
                reader.setScaledSize(
                    source_size.scaled(
                        THUMBNAIL_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatio,
                    )
                )
            else:
                reader.setScaledSize(THUMBNAIL_SIZE)
            image = reader.read()
            if image.isNull():
                self._remember_failure(path)
                return super().icon(info)
            pixmap = QPixmap.fromImage(image)
            icon = QIcon(pixmap)
        except Exception:
            self._remember_failure(path)
            return super().icon(info)

        if len(self._cache) > CACHE_LIMIT:
            self._cache.clear()
        self._cache[path] = icon
        return icon

    def _remember_failure(self, path):
        if len(self._failed) > FAILED_LIMIT:
            self._failed.clear()
        self._failed.add(path)
