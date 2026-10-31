"""Application settings page."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QVBoxLayout, QWidget,
)

from app.core.constants import (
    MODULE_COPY, MODULE_MOVE, MODULE_NAV_LABELS, MODULE_SETTINGS, NAV_GROUPS,
)
from app.core.history import prune_history
from app.core.i18n import tr
from app.ui.base import ModulePage
from app.ui.components import PageHeader, make_button


class SettingsPage(ModulePage):
    title = "設定"
    module_id = MODULE_SETTINGS

    def __init__(self, settings, main_window=None):
        super().__init__(settings, main_window)
        self._build_ui()
        self._load()

    def _module_choices(self):
        ids = []
        for _heading, module_ids in NAV_GROUPS:
            for module_id in module_ids:
                if module_id != MODULE_SETTINGS:
                    ids.append(module_id)
        return ids

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        content = QWidget()
        content.setObjectName("scrollContent")
        content.setMaximumWidth(880)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        root = QVBoxLayout(content)
        root.setContentsMargins(16, 12, 16, 16)
        root.setSpacing(12)

        self.page_header = PageHeader(
            "設定",
            "外觀、檔案操作、瀏覽器與歷史紀錄偏好",
            icon="settings",
            theme=self.theme(),
        )
        root.addWidget(self.page_header)
        hint = QLabel("設定會立即套用到可即時更新的項目；部分選項於下次啟動生效。")
        hint.setProperty("role", "hint")
        root.addWidget(hint)

        appearance = QGroupBox("外觀與啟動")
        form = QFormLayout(appearance)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.addItem("淺色", "light")
        form.addRow("主題", self.theme_combo)
        self.language_combo = QComboBox()
        self.language_combo.addItem(tr("英文"), "en")
        self.language_combo.addItem(tr("繁體中文"), "zh_TW")
        form.addRow(tr("語言"), self.language_combo)
        self.start_page = QComboBox()
        for module_id in self._module_choices():
            self.start_page.addItem(
                MODULE_NAV_LABELS.get(module_id, module_id), module_id
            )
        form.addRow("啟動頁面", self.start_page)
        root.addWidget(appearance)

        operations = QGroupBox("檔案操作")
        form = QFormLayout(operations)
        self.conflict = QComboBox()
        self.conflict.addItem("跳過", "skip")
        self.conflict.addItem("覆寫", "overwrite")
        self.conflict.addItem("自動重新命名", "rename")
        form.addRow("預設衝突策略", self.conflict)
        self.verify_mode = QComboBox()
        self.verify_mode.addItem("快速驗證（大小＋首尾內容）", "quick")
        self.verify_mode.addItem("完整驗證（SHA-256）", "full")
        self.verify_mode.addItem("不驗證（最快）", "off")
        form.addRow("複製後驗證", self.verify_mode)
        self.retries = QSpinBox()
        self.retries.setRange(0, 5)
        self.retries.setSuffix(tr(" 次"))
        form.addRow("網路錯誤重試", self.retries)
        self.threads = QSpinBox()
        self.threads.setRange(1, 16)
        form.addRow("批量操作執行緒", self.threads)
        self.delete_note = QLabel("刪除一律送往資源回收筒，不提供永久刪除選項。")
        self.delete_note.setProperty("role", "hint")
        form.addRow("刪除", self.delete_note)
        root.addWidget(operations)

        browser = QGroupBox("瀏覽器與預覽")
        form = QFormLayout(browser)
        self.dual = QCheckBox("預設使用雙窗格")
        form.addRow("", self.dual)
        self.hidden = QCheckBox("預設顯示隱藏檔案")
        form.addRow("", self.hidden)
        self.preview_default = QCheckBox("首次開啟時顯示預覽窗格")
        form.addRow("", self.preview_default)
        self.icons_default = QCheckBox("預設使用縮圖檢視")
        form.addRow("", self.icons_default)
        self.preview_mb = QDoubleSpinBox()
        self.preview_mb.setRange(1, 200)
        self.preview_mb.setSuffix(" MB")
        form.addRow("圖片預覽大小上限", self.preview_mb)
        root.addWidget(browser)

        history = QGroupBox("歷史紀錄")
        form = QFormLayout(history)
        self.history_limit = QSpinBox()
        self.history_limit.setRange(20, 5000)
        form.addRow("保留筆數", self.history_limit)
        clear_row = QHBoxLayout()
        clear_btn = QPushButton("立即清除歷史")
        clear_btn.clicked.connect(self._clear_history)
        clear_row.addWidget(clear_btn)
        clear_row.addStretch(1)
        form.addRow("", clear_row)
        root.addWidget(history)

        buttons = QHBoxLayout()
        save_btn = make_button("儲存設定", "check", self.theme(), "primary")
        save_btn.clicked.connect(self._save)
        reset_btn = make_button("重設所有設定", "alert", self.theme(), "danger")
        reset_btn.clicked.connect(self._reset)
        buttons.addWidget(save_btn)
        buttons.addStretch(1)
        buttons.addWidget(reset_btn)
        root.addLayout(buttons)
        root.addStretch(1)

    def on_theme_changed(self):
        self.page_header.set_theme(self.theme())

    def _load(self):
        theme = self.settings.option("theme", "dark")
        index = self.theme_combo.findData(theme)
        self.theme_combo.setCurrentIndex(max(0, index))
        lang = self.settings.option("language", "en")
        index = self.language_combo.findData(lang)
        self.language_combo.setCurrentIndex(max(0, index))
        start = self.settings.option("start_page", "dashboard")
        if start == MODULE_MOVE:
            # Batch move is now part of the merged copy/move page.
            start = MODULE_COPY
        index = self.start_page.findData(start)
        self.start_page.setCurrentIndex(max(0, index))
        conflict = self.settings.option("default_conflict", "skip")
        index = self.conflict.findData(conflict)
        self.conflict.setCurrentIndex(max(0, index))
        mode = self.settings.option(
            "copy_verify_mode",
            "quick" if self.settings.option("verify_copy", True) else "off",
        )
        index = self.verify_mode.findData(mode)
        self.verify_mode.setCurrentIndex(max(0, index))
        self.retries.setValue(self.settings.option("copy_retries", 1))
        self.threads.setValue(self.settings.option("copy_threads", 4))
        self.dual.setChecked(self.settings.option("browser_dual", True))
        self.hidden.setChecked(self.settings.option("browser_show_hidden", False))
        self.preview_default.setChecked(
            self.settings.option("browser_preview_default", False)
        )
        self.icons_default.setChecked(
            self.settings.option("browser_icons", False)
        )
        self.preview_mb.setValue(self.settings.option("preview_max_mb", 20))
        self.history_limit.setValue(self.settings.option("history_limit", 500))

    def _save(self):
        old_language = self.settings.option("language", "en")
        new_language = self.language_combo.currentData()
        self.settings.set_options({
            "theme": self.theme_combo.currentData(),
            "language": new_language,
            "start_page": self.start_page.currentData(),
            "default_conflict": self.conflict.currentData(),
            "copy_conflict": self.conflict.currentData(),
            "verify_copy": self.verify_mode.currentData() != "off",
            "copy_verify": self.verify_mode.currentData() != "off",
            "copy_verify_mode": self.verify_mode.currentData(),
            "copy_retries": self.retries.value(),
            "copy_threads": self.threads.value(),
            "browser_dual": self.dual.isChecked(),
            "browser_show_hidden": self.hidden.isChecked(),
            "browser_preview_default": self.preview_default.isChecked(),
            "browser_icons": self.icons_default.isChecked(),
            "preview_max_mb": self.preview_mb.value(),
            "history_limit": self.history_limit.value(),
            "settings_version": 2,
        })
        prune_history(self.settings, self.history_limit.value())
        if self.main_window is not None:
            self.main_window.apply_settings()
        self.status("設定已儲存")
        QMessageBox.information(self, "設定", "設定已儲存。")
        if old_language != new_language:
            QMessageBox.information(
                self,
                tr("語言已變更"),
                tr("請重新啟動 FileManager 以套用新語言。"),
            )
        self._load()

    def _clear_history(self):
        answer = QMessageBox.question(
            self, "清除歷史", "確定要清除所有操作歷史嗎？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        from app.core.history import clear_history

        clear_history(self.settings)
        self.status("歷史紀錄已清除")

    def _reset(self):
        answer = QMessageBox.question(
            self, "重設設定",
            "這會清除所有偏好設定（不影響我的最愛與操作歷史）。確定嗎？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for key in list(self.settings.q.allKeys()):
            if key.startswith("options/"):
                self.settings.q.remove(key)
        self.settings.q.sync()
        if hasattr(self.settings, "migrate"):
            self.settings.migrate()
        if self.main_window is not None:
            self.main_window.apply_settings()
        self._load()
        QMessageBox.information(self, "設定", "已重設為預設值。")

