# settings_ui/tab_greeting.py — авто-сообщения
from PyQt5 import QtWidgets, QtCore
import config


class GreetingTabMixin:
    """Вкладка 💬 Авто-сообщения."""

    def _setup_greeting_tab(self, tab):
        """Вкладка настроек авто-сообщений."""
        layout = QtWidgets.QVBoxLayout(tab)

        # Включение/выключение
        self.greeting_enabled_cb = QtWidgets.QCheckBox("Включить авто-сообщения")
        self.greeting_enabled_cb.setToolTip("Ассистент будет сам напоминать о себе при простое")
        self.greeting_enabled_cb.toggled.connect(self._apply_live_runtime)
        layout.addWidget(self.greeting_enabled_cb)

        layout.addWidget(QtWidgets.QLabel(""))

        # Использовать LLM для генерации
        self.greeting_use_llm_cb = QtWidgets.QCheckBox("Генерировать сообщения через ИИ (вместо шаблонов)")
        self.greeting_use_llm_cb.setToolTip("Сообщения будут уникальными, а не заранее заготовленными")
        self.greeting_use_llm_cb.toggled.connect(self._apply_live_runtime)
        layout.addWidget(self.greeting_use_llm_cb)

        self.screen_vision_enabled_cb = QtWidgets.QCheckBox("Смотреть экран (зрение)")
        self.screen_vision_enabled_cb.toggled.connect(self._apply_live_runtime)
        layout.addWidget(self.screen_vision_enabled_cb)
        self.screen_vision_auto_cb = QtWidgets.QCheckBox("Автопросмотр экрана с реакцией")
        self.screen_vision_auto_cb.setToolTip("Периодически смотрит монитор и пишет короткую реакцию")
        self.screen_vision_auto_cb.toggled.connect(self._apply_live_runtime)
        layout.addWidget(self.screen_vision_auto_cb)

        layout.addWidget(QtWidgets.QLabel("Автопросмотр раз в (минут):"))
        self.screen_vision_interval_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.screen_vision_interval_slider.setRange(1, 30)
        self.screen_vision_interval_slider.setValue(1)
        self.screen_vision_interval_slider.valueChanged.connect(self.update_screen_interval_label)
        self.screen_vision_interval_slider.valueChanged.connect(self._apply_live_runtime)
        siv = QtWidgets.QHBoxLayout()
        siv.addWidget(self.screen_vision_interval_slider)
        self.screen_vision_interval_label = QtWidgets.QLabel("1 мин")
        siv.addWidget(self.screen_vision_interval_label)
        layout.addLayout(siv)

        self.monitors_info_label = QtWidgets.QLabel("Мониторы: …")
        layout.addWidget(self.monitors_info_label)
        self.monitor_box = QtWidgets.QWidget()
        self.monitor_box_layout = QtWidgets.QVBoxLayout(self.monitor_box)
        self.monitor_box_layout.setContentsMargins(8, 0, 0, 0)
        layout.addWidget(self.monitor_box)
        refresh_mon = QtWidgets.QPushButton("Обновить список мониторов")
        refresh_mon.clicked.connect(self._refresh_monitor_list)
        layout.addWidget(refresh_mon)

        layout.addWidget(QtWidgets.QLabel(""))

        # Минимальный интервал
        layout.addWidget(QtWidgets.QLabel("Минимальный интервал (сек):"))
        self.greeting_min_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.greeting_min_slider.setRange(30, 600)
        self.greeting_min_slider.valueChanged.connect(self.update_greeting_min_label)
        self.greeting_min_slider.valueChanged.connect(self._apply_live_runtime)
        min_layout = QtWidgets.QHBoxLayout()
        min_layout.addWidget(self.greeting_min_slider)
        self.greeting_min_label = QtWidgets.QLabel("180")
        min_layout.addWidget(self.greeting_min_label)
        layout.addLayout(min_layout)

        # Максимальный интервал
        layout.addWidget(QtWidgets.QLabel("Максимальный интервал (сек):"))
        self.greeting_max_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.greeting_max_slider.setRange(60, 900)
        self.greeting_max_slider.valueChanged.connect(self.update_greeting_max_label)
        self.greeting_max_slider.valueChanged.connect(self._apply_live_runtime)
        max_layout = QtWidgets.QHBoxLayout()
        max_layout.addWidget(self.greeting_max_slider)
        self.greeting_max_label = QtWidgets.QLabel("300")
        max_layout.addWidget(self.greeting_max_label)
        layout.addLayout(max_layout)

        # Шанс NSFW
        layout.addWidget(QtWidgets.QLabel("Шанс пошлого сообщения (0-100%):"))
        self.greeting_nsfw_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.greeting_nsfw_slider.setRange(0, 100)
        self.greeting_nsfw_slider.valueChanged.connect(self.update_greeting_nsfw_label)
        nsfw_layout = QtWidgets.QHBoxLayout()
        nsfw_layout.addWidget(self.greeting_nsfw_slider)
        self.greeting_nsfw_label = QtWidgets.QLabel("45%")
        nsfw_layout.addWidget(self.greeting_nsfw_label)
        layout.addLayout(nsfw_layout)

        layout.addWidget(QtWidgets.QLabel(""))

        # Информация
        info_label = QtWidgets.QLabel(
            "💡 При включенной генерации через ИИ сообщения будут уникальными.\n"
            "При выключенной — используются заранее заготовленные шаблоны."
        )
        info_label.setStyleSheet("color: #888; font-size: 11px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Кнопка теста
        test_btn = QtWidgets.QPushButton("🔊 Тестовое сообщение")
        test_btn.clicked.connect(self.test_greeting)
        layout.addWidget(test_btn)

        layout.addStretch()


    # Голоса по движкам (для выпадающего списка)
    _VOICES = {
        "silero": [
            ("xenia — женский, моложе (Лисичка)", "xenia"),
            ("kseniya — женский", "kseniya"),
            ("baya — женский", "baya"),
            ("aidar — мужской", "aidar"),
            ("eugene — мужской", "eugene"),
        ],
        "silero-tts": [
            ("xenia — женский, моложе (Лисичка)", "xenia"),
            ("kseniya — женский", "kseniya"),
            ("baya — женский", "baya"),
            ("aidar — мужской", "aidar"),
            ("eugene — мужской", "eugene"),
        ],
        "edge-tts": [
            ("Svetlana (жен, RU)", "ru-RU-SvetlanaNeural"),
            ("Dariya (жен, RU)", "ru-RU-DariyaNeural"),
            ("Dmitry (муж, RU)", "ru-RU-DmitryNeural"),
            ("Jenny (жен, EN)", "en-US-JennyNeural"),
            ("Guy (муж, EN)", "en-US-GuyNeural"),
            ("Sonia (жен, EN-GB)", "en-GB-SoniaNeural"),
            ("Ryan (муж, EN-GB)", "en-GB-RyanNeural"),
        ],
        "openai": [
            ("alloy", "alloy"),
            ("echo", "echo"),
            ("fable", "fable"),
            ("onyx", "onyx"),
            ("nova", "nova"),
            ("shimmer", "shimmer"),
        ],
        "custom": [
            ("alloy", "alloy"),
            ("nova", "nova"),
            ("shimmer", "shimmer"),
        ],
        "pyttsx3": [
            ("(системный по умолчанию)", ""),
            ("Russian / RU (если есть в Windows)", "russian"),
            ("Zira (EN, Windows)", "zira"),
            ("Irina (RU, если установлен)", "irina"),
        ],
    }


    def update_greeting_min_label(self, value):
        self.greeting_min_label.setText(str(value))

    def update_greeting_max_label(self, value):
        self.greeting_max_label.setText(str(value))

    def update_greeting_nsfw_label(self, value):
        self.greeting_nsfw_label.setText(f"{value}%")


    def test_greeting(self):
        """Отправляет тестовое авто-сообщение."""
        if hasattr(self.parent, 'assistant'):
            # Используем существующий метод генерации из lifecycle_manager
            try:
                from lifecycle_manager import LifecycleManager
                # Создаём временный менеджер для теста
                lm = LifecycleManager(self.parent.assistant.executor)
                lm.set_assistant(self.parent.assistant)
                # Генерируем сообщение с mood=0 (грусть/скука)
                msg = lm._get_greeting_message(0)
                if hasattr(self.parent, '_send_reminder_to_gui'):
                    self.parent._send_reminder_to_gui(msg)
                QtWidgets.QMessageBox.information(
                    self, "Тест", f"Отправлено тестовое сообщение:\n\n{msg}"
                )
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Ошибка", f"Не удалось сгенерировать сообщение: {e}")
        else:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Ассистент не найден")



    def update_screen_interval_label(self, value):
        self.screen_vision_interval_label.setText(f"{int(value)} мин")

    def _apply_live_runtime(self, *_):
        """Галочки и слайдеры сразу в config + перезапуск фоновых потоков."""
        if getattr(self, "_loading_settings", False):
            return
        try:
            import config
            if hasattr(self, "greeting_enabled_cb"):
                config.ENABLE_AUTO_GREETING = self.greeting_enabled_cb.isChecked()
            if hasattr(self, "greeting_use_llm_cb"):
                config.GREETING_USE_LLM = self.greeting_use_llm_cb.isChecked()
            if hasattr(self, "screen_vision_enabled_cb"):
                config.SCREEN_VISION_ENABLED = self.screen_vision_enabled_cb.isChecked()
            if hasattr(self, "screen_vision_auto_cb"):
                config.SCREEN_VISION_AUTO = self.screen_vision_auto_cb.isChecked()
            if hasattr(self, "screen_vision_interval_slider"):
                config.SCREEN_VISION_AUTO_INTERVAL = int(self.screen_vision_interval_slider.value()) * 60
            if hasattr(self, "greeting_min_slider"):
                config.GREETING_INTERVAL_MIN = int(self.greeting_min_slider.value())
            if hasattr(self, "greeting_max_slider"):
                config.GREETING_INTERVAL_MAX = int(self.greeting_max_slider.value())
        except Exception as e:
            print("live config:", e)
            return
        try:
            from settings_manager import save_settings
            save_settings({
                "ENABLE_AUTO_GREETING": getattr(config, "ENABLE_AUTO_GREETING", False),
                "GREETING_USE_LLM": getattr(config, "GREETING_USE_LLM", False),
                "SCREEN_VISION_ENABLED": getattr(config, "SCREEN_VISION_ENABLED", True),
                "SCREEN_VISION_AUTO": getattr(config, "SCREEN_VISION_AUTO", False),
                "SCREEN_VISION_AUTO_INTERVAL": int(getattr(config, "SCREEN_VISION_AUTO_INTERVAL", 60) or 60),
                "GREETING_INTERVAL_MIN": int(getattr(config, "GREETING_INTERVAL_MIN", 180) or 180),
                "GREETING_INTERVAL_MAX": int(getattr(config, "GREETING_INTERVAL_MAX", 420) or 420),
            })
        except Exception as e:
            print("live save:", e)
        try:
            host = getattr(self, "parent", None)
            if callable(host):
                try:
                    host = host()
                except Exception:
                    host = None
            ast = getattr(host, "assistant", None) if host is not None else None
            lc = None
            if ast is not None:
                lc = getattr(ast, "_lifecycle", None) or getattr(ast, "lifecycle", None)
            if lc is None and host is not None:
                lc = getattr(host, "lifecycle", None)
            if lc is not None and hasattr(lc, "start"):
                lc.start()
        except Exception as e:
            print("live lifecycle:", e)

    def _refresh_monitor_list(self):
        lay = getattr(self, "monitor_box_layout", None)
        if lay is None:
            return
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._monitor_checks = []
        try:
            from screen_watch import list_monitors
            mons = list_monitors() or []
        except Exception as e:
            mons = []
            print("monitors:", e)
        n = len(mons)
        if hasattr(self, "monitors_info_label"):
            self.monitors_info_label.setText(
                f"Мониторов в системе: {n}" if n else "Мониторы не найдены (нужен Windows)"
            )
        allowed = getattr(__import__("config"), "SCREEN_ALLOWED_MONITORS", None)
        if allowed is None:
            allow_set = None
        else:
            try:
                allow_set = {int(x) for x in allowed}
            except Exception:
                allow_set = None
        sides = {0: "левый"}
        if n:
            sides[n - 1] = "правый"
        if n >= 3:
            sides[n // 2] = "средний"
        for m in mons:
            i = int(m.get("index", 0))
            side = sides.get(i, "")
            prim = " основной" if m.get("primary") else ""
            title = f"#{i+1} {side} {m.get('width')}x{m.get('height')}{prim}".replace("  ", " ")
            cb = QtWidgets.QCheckBox(f"Можно смотреть: {title}")
            cb.blockSignals(True)
            cb.setChecked(allow_set is None or i in allow_set)
            cb.blockSignals(False)
            cb.toggled.connect(self._apply_live_runtime)
            lay.addWidget(cb)
            self._monitor_checks.append((i, cb))

    def _allowed_monitors_from_ui(self):
        checks = getattr(self, "_monitor_checks", None) or []
        if not checks:
            return None
        on = [i for i, cb in checks if cb.isChecked()]
        if not on or len(on) == len(checks):
            return None
        return on
