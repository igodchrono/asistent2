# settings_ui — вкладки диалога настроек (сплит settings_dialog)
from PyQt5 import QtWidgets, QtGui, QtCore
import os
import config

class TabBrowserMixin:
    def _setup_browser_tab(self, tab):
        layout = QtWidgets.QVBoxLayout(tab)

        layout.addWidget(QtWidgets.QLabel("Браузер:"))
        self.browser_combo = QtWidgets.QComboBox()
        self.browser_combo.addItems(["chrome", "edge", "firefox", "yandex", "opera", "brave"])
        layout.addWidget(self.browser_combo)

        layout.addWidget(QtWidgets.QLabel("Путь к браузеру:"))
        self.browser_path_edit = QtWidgets.QLineEdit()
        self.browser_path_edit.setPlaceholderText(
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
        )
        layout.addWidget(self.browser_path_edit)

        layout.addWidget(QtWidgets.QLabel("Поисковая система:"))
        self.search_engine_combo = QtWidgets.QComboBox()
        self.search_engine_combo.addItems(["google", "duckduckgo", "bing", "yandex"])
        layout.addWidget(self.search_engine_combo)

        self.search_open_browser_cb = QtWidgets.QCheckBox("Открывать браузер при поиске")
        self.search_open_browser_cb.setChecked(True)
        layout.addWidget(self.search_open_browser_cb)

        layout.addStretch()
