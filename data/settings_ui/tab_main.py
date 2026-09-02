# settings_ui/tab_main.py — Основные, Браузер, Эмоции
from PyQt5 import QtWidgets, QtCore
import json
import urllib.request
import config


class MainTabMixin:
    """Вкладки Основные / Браузер / Эмоции."""

    def _setup_main_tab(self, tab):
        layout = QtWidgets.QVBoxLayout(tab)

        layout.addWidget(QtWidgets.QLabel("API URL:"))
        self.api_url_edit = QtWidgets.QLineEdit()
        layout.addWidget(self.api_url_edit)

        layout.addWidget(QtWidgets.QLabel("API Key:"))
        self.api_key_edit = QtWidgets.QLineEdit()
        self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        layout.addWidget(self.api_key_edit)

        layout.addWidget(QtWidgets.QLabel("Модель:"))
        self.model_combo = QtWidgets.QComboBox()
        self.model_combo.setEditable(True)
        layout.addWidget(self.model_combo)

        refresh_btn = QtWidgets.QPushButton("🔄 Обновить список моделей")
        refresh_btn.setToolTip("Запросить у LM Studio список загруженных моделей.")
        refresh_btn.clicked.connect(self.load_models_list)
        layout.addWidget(refresh_btn)

        layout.addWidget(QtWidgets.QLabel("Temperature (0.0 - 2.0):"))
        self.temperature_edit = QtWidgets.QLineEdit()
        layout.addWidget(self.temperature_edit)

        layout.addWidget(QtWidgets.QLabel("Max Tokens:"))
        self.max_tokens_edit = QtWidgets.QLineEdit()
        layout.addWidget(self.max_tokens_edit)

        layout.addWidget(QtWidgets.QLabel("Скорость анимации (мс):"))
        self.anim_speed_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.anim_speed_slider.setRange(30, 500)
        self.anim_speed_slider.valueChanged.connect(self.update_anim_speed_label)
        anim_layout = QtWidgets.QHBoxLayout()
        anim_layout.addWidget(self.anim_speed_slider)
        self.anim_speed_label = QtWidgets.QLabel("80")
        anim_layout.addWidget(self.anim_speed_label)
        layout.addLayout(anim_layout)

        layout.addWidget(QtWidgets.QLabel("Размер персонажа (px):"))
        self.size_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.size_slider.setRange(100, 800)
        self.size_slider.valueChanged.connect(self.update_size_label)
        size_layout = QtWidgets.QHBoxLayout()
        size_layout.addWidget(self.size_slider)
        self.size_label = QtWidgets.QLabel("302")
        size_layout.addWidget(self.size_label)
        layout.addLayout(size_layout)

        self.internet_cb = QtWidgets.QCheckBox("Разрешить доступ в интернет")
        layout.addWidget(self.internet_cb)

        self.pc_cb = QtWidgets.QCheckBox("Разрешить управление ПК")
        layout.addWidget(self.pc_cb)

        self.safe_mode_cb = QtWidgets.QCheckBox("Безопасный режим (подтверждение команд)")
        self.safe_mode_cb.setChecked(True)
        layout.addWidget(self.safe_mode_cb)

        layout.addStretch()

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

    def _setup_emotion_tab(self, tab):
        layout = QtWidgets.QVBoxLayout(tab)

        self.show_avatar_cb = QtWidgets.QCheckBox("Показывать аватар на рабочем столе")
        self.show_avatar_cb.toggled.connect(self._on_show_avatar_toggled)
        layout.addWidget(self.show_avatar_cb)

        self.nsfw_enabled_cb = QtWidgets.QCheckBox("🔞 Разрешить NSFW анимации")
        self.nsfw_enabled_cb.setStyleSheet("color: #ff6b6b; font-weight: bold;")
        layout.addWidget(self.nsfw_enabled_cb)

        layout.addWidget(QtWidgets.QLabel("Частота NSFW (0-100%):"))
        self.nsfw_frequency_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.nsfw_frequency_slider.setRange(0, 100)
        self.nsfw_frequency_slider.valueChanged.connect(self.update_nsfw_label)
        nsfw_layout = QtWidgets.QHBoxLayout()
        nsfw_layout.addWidget(self.nsfw_frequency_slider)
        self.nsfw_frequency_label = QtWidgets.QLabel("45%")
        nsfw_layout.addWidget(self.nsfw_frequency_label)
        layout.addLayout(nsfw_layout)

        layout.addWidget(QtWidgets.QLabel("Анимация по умолчанию:"))
        self.default_anim_combo = QtWidgets.QComboBox()
        self.default_anim_combo.addItems(["neutral", "happy", "idle", "thinking", "love"])
        layout.addWidget(self.default_anim_combo)

        layout.addStretch()


    def update_anim_speed_label(self, value):
        self.anim_speed_label.setText(str(value))

    def update_size_label(self, value):
        self.size_label.setText(str(value))

    def update_nsfw_label(self, value):
        self.nsfw_frequency_label.setText(f"{value}%")

    def _host_window(self):
        host = getattr(self, "parent", None)
        if callable(host):
            try:
                host = host()
            except Exception:
                host = None
        if host is not None and hasattr(host, "avatar_window"):
            return host
        w = self.parent() if callable(getattr(self, "parent", None)) else None
        if w is not None and hasattr(w, "avatar_window"):
            return w
        return None

    def _on_show_avatar_toggled(self, checked):
        try:
            import config
            config.SHOW_AVATAR = bool(checked)
        except Exception:
            pass
        host = self._host_window()
        av = getattr(host, "avatar_window", None) if host is not None else None
        if av is None:
            return
        if checked:
            try:
                av.show()
                av.raise_()
            except Exception:
                pass
        else:
            try:
                av.hide()
            except Exception:
                pass


    def load_models_list(self):
        try:
            api_url = self.api_url_edit.text().strip() or config.API_URL
            api_key = self.api_key_edit.text().strip() or config.API_KEY

            req = urllib.request.Request(
                f"{api_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
            if True:
                models = data.get("data", [])
                if models:
                    model_names = []
                    for model in models:
                        name = model.get("id", model.get("name", "unknown"))
                        model_names.append(name)
                    self.model_combo.clear()
                    self.model_combo.addItems(model_names)
                    current = config.MODEL_NAME
                    index = self.model_combo.findText(current)
                    if index >= 0:
                        self.model_combo.setCurrentIndex(index)
                    return
        except Exception as e:
            print(f"Не удалось загрузить модели: {e}")
            if self.model_combo.count() == 0:
                self.model_combo.addItem(config.MODEL_NAME)

