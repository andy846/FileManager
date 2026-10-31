"""Preview pane for the file browser (images, text and metadata)."""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImageReader, QPixmap
from PyQt6.QtWidgets import (
    QLabel, QPlainTextEdit, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from app.core.i18n import tr
from app.core.utils import (
    CATEGORY_LABELS, file_category, file_extension, format_datetime,
    format_size,
)

IMAGE_EXTENSIONS = {
    "jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff", "ico", "svg",
}
TEXT_EXTENSIONS = {
    "txt", "md", "py", "js", "tsx", "jsx", "json", "xml", "yaml", "yml",
    "ini", "toml", "csv", "log", "html", "htm", "css", "scss", "c", "cpp",
    "h", "hpp", "cs", "java", "go", "rs", "rb", "php", "sql", "sh", "ps1",
    "bat", "vue", "svelte", "lua", "kt", "swift",
}
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
TEXT_PREVIEW_BYTES = 256 * 1024


class PreviewPanel(QWidget):
    """Show a preview and metadata for the current browser selection."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("previewPanel")
        self.setMinimumWidth(260)
        self.max_image_bytes = MAX_IMAGE_BYTES
        self._pixmap = None
        self._current_path = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.title = QLabel(tr("預覽"))
        self.title.setObjectName("previewDataLabel")
        self.title.setStyleSheet("font-weight: bold;")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)

        self.meta = QLabel(tr("選取檔案以顯示預覽"))
        self.meta.setProperty("role", "hint")
        self.meta.setWordWrap(True)
        layout.addWidget(self.meta)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_scroll.setWidget(self.image_label)
        self.stack.addWidget(self.image_scroll)

        self.text_view = QPlainTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text_view.setStyleSheet(
            'font-family: "Consolas", "Cascadia Mono", monospace;'
        )
        self.stack.addWidget(self.text_view)

        self.message = QLabel("")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setProperty("role", "hint")
        self.stack.addWidget(self.message)
        self.stack.setCurrentWidget(self.message)

    def clear(self):
        self._pixmap = None
        self._current_path = ""
        self.title.setText(tr("預覽"))
        self.meta.setText(tr("選取檔案以顯示預覽"))
        self.image_label.clear()
        self.text_view.clear()
        self.message.setText(tr("選取單一檔案以顯示預覽"))
        self.stack.setCurrentWidget(self.message)

    def show_paths(self, paths):
        if len(paths) != 1:
            self._pixmap = None
            self._current_path = ""
            self.title.setText(tr("預覽"))
            self.meta.setText("")
            self.message.setText(
                tr("已選取多個項目\n請選取單一檔案以顯示預覽")
                if paths else tr("選取檔案以顯示預覽")
            )
            self.stack.setCurrentWidget(self.message)
            return
        self.show_path(paths[0])

    def show_path(self, path):
        path = str(path)
        self._current_path = path
        self._pixmap = None
        name = os.path.basename(path.rstrip("\\/")) or path
        self.title.setText(name)
        if not os.path.exists(path):
            self._set_message(tr("找不到此項目"))
            return
        try:
            stat = os.stat(path)
        except OSError as exc:
            self._set_message(str(exc))
            return

        modified = format_datetime(stat.st_mtime)
        if os.path.isdir(path):
            self.meta.setText(
                f"{tr('資料夾')} · {tr('修改時間')} {modified}"
            )
            self.message.setText(tr("資料夾\n\n使用雙擊進入資料夾"))
            self.stack.setCurrentWidget(self.message)
            return

        category = tr(CATEGORY_LABELS.get(file_category(path), "其他"))
        self.meta.setText(
            f"{format_size(stat.st_size)} · {category} · {modified}"
        )
        ext = file_extension(path)

        if ext in IMAGE_EXTENSIONS and stat.st_size <= self.max_image_bytes:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            image = reader.read()
            if not image.isNull():
                self._pixmap = QPixmap.fromImage(image)
                self._update_image()
                self.stack.setCurrentWidget(self.image_scroll)
                return
            self._set_message(
                tr("無法讀取圖片：") + reader.errorString()
            )
            return

        if (ext in TEXT_EXTENSIONS or stat.st_size <= 64 * 1024) \
                and stat.st_size <= MAX_TEXT_BYTES:
            try:
                with open(path, "rb") as handle:
                    data = handle.read(TEXT_PREVIEW_BYTES)
            except OSError as exc:
                self._set_message(str(exc))
                return
            text = self._decode_text(data)
            if text is not None:
                self.text_view.setPlainText(text)
                if stat.st_size > TEXT_PREVIEW_BYTES:
                    self.meta.setText(
                        self.meta.text() + " · "
                        + tr("僅顯示前 256 KB")
                    )
                self.stack.setCurrentWidget(self.text_view)
                return

        self._set_message(tr("此檔案類型不支援預覽"))

    @staticmethod
    def _decode_text(data):
        if not data:
            return ""
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            try:
                return data.decode("utf-16")
            except UnicodeDecodeError:
                pass
        if b"\x00" in data:
            return None
        sample = data[:4096]
        control_chars = sum(
            1 for byte in sample if byte < 9 or 13 < byte < 32
        )
        if sample and control_chars / len(sample) > 0.05:
            return None
        for encoding in ("utf-8-sig", "utf-8", "big5", "cp950"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("latin-1", errors="replace")

    def _set_message(self, text):
        self._pixmap = None
        self.message.setText(text)
        self.stack.setCurrentWidget(self.message)

    def _update_image(self):
        if self._pixmap is None:
            return
        width = max(120, self.image_scroll.viewport().width() - 12)
        if self._pixmap.width() > width:
            scaled = self._pixmap.scaledToWidth(
                width, Qt.TransformationMode.SmoothTransformation
            )
        else:
            scaled = self._pixmap
        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event):  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._update_image()
