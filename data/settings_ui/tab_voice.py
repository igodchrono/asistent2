# settings_ui/tab_voice.py — STT / TTS / устройства
from PyQt5 import QtWidgets, QtCore
import config


class VoiceTabMixin:
    """Вкладка Голос + хелперы TTS/STT."""

    def _setup_voice_tab(self, tab):
        """Полные настройки голоса: STT + TTS (локальный / edge / внешний API)."""
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(inner)

        # --- Ввод / вывод ---
        layout.addWidget(QtWidgets.QLabel("<b>Включение</b>"))
        self.voice_input_cb = QtWidgets.QCheckBox("Включить голосовой ввод (микрофон)")
        layout.addWidget(self.voice_input_cb)

        self.voice_output_cb = QtWidgets.QCheckBox("Включить голосовой вывод (озвучка ответов)")
        layout.addWidget(self.voice_output_cb)

        # --- Распознавание (STT) ---
        layout.addWidget(QtWidgets.QLabel("<b>Распознавание речи (STT)</b>"))
        layout.addWidget(QtWidgets.QLabel("Движок распознавания:"))
        self.stt_engine_combo = QtWidgets.QComboBox()
        self.stt_engine_combo.addItem("Vosk (локальный, офлайн)", "vosk")
        self.stt_engine_combo.addItem("Google Speech (онлайн)", "google")
        self.stt_engine_combo.currentIndexChanged.connect(self._on_stt_engine_changed)
        layout.addWidget(self.stt_engine_combo)

        layout.addWidget(QtWidgets.QLabel("Язык распознавания:"))
        self.voice_lang_edit = QtWidgets.QLineEdit()
        self.voice_lang_edit.setPlaceholderText("ru-RU")
        layout.addWidget(self.voice_lang_edit)

        layout.addWidget(QtWidgets.QLabel("Google Speech API Key (только для google):"))
        self.google_stt_key_edit = QtWidgets.QLineEdit()
        self.google_stt_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.google_stt_key_edit.setPlaceholderText("оставьте пустым для бесплатного API")
        layout.addWidget(self.google_stt_key_edit)

        # --- Синтез (TTS) ---
        layout.addWidget(QtWidgets.QLabel("<b>Режим голосового ввода</b>"))
        self.voice_mode_combo = QtWidgets.QComboBox()
        self.voice_mode_combo.addItem("Кнопка 🎤 (нажал — сказал)", "push")
        self.voice_mode_combo.addItem("Всегда слушает + кодовое слово (как Алиса)", "wake")
        self.voice_mode_combo.setToolTip(
            "push — запись только по кнопке\n"
            "wake — микрофон всегда, команда после слова «лисичка» (настраивается)"
        )
        layout.addWidget(self.voice_mode_combo)

        layout.addWidget(QtWidgets.QLabel("Кодовое слово (wake-слово):"))
        self.wake_word_edit = QtWidgets.QLineEdit()
        self.wake_word_edit.setPlaceholderText("лисичка")
        self.wake_word_edit.setToolTip("Произнесите это слово, затем команду. Можно сменить в любой момент.")
        layout.addWidget(self.wake_word_edit)

        wake_hint = QtWidgets.QLabel(
            "Пример: «Лисичка, который час?» или «Лисичка» → пауза → «открой youtube»"
        )
        wake_hint.setWordWrap(True)
        wake_hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(wake_hint)

        layout.addWidget(QtWidgets.QLabel("<b>Устройства</b>"))
        layout.addWidget(QtWidgets.QLabel("Микрофон (вход):"))
        self.mic_combo = QtWidgets.QComboBox()
        self.mic_combo.setMinimumWidth(320)
        layout.addWidget(self.mic_combo)

        layout.addWidget(QtWidgets.QLabel("Динамики / выход:"))
        self.speaker_combo = QtWidgets.QComboBox()
        self.speaker_combo.setMinimumWidth(320)
        layout.addWidget(self.speaker_combo)

        refresh_dev_btn = QtWidgets.QPushButton("🔄 Обновить список устройств")
        refresh_dev_btn.clicked.connect(self._refresh_audio_devices)
        layout.addWidget(refresh_dev_btn)

        dev_hint = QtWidgets.QLabel(
            "Если микрофон «не слышит» — выбери правильное устройство и Сохрани. "
            "Смена динамиков на Windows через pygame ограничена (часто только default)."
        )
        dev_hint.setWordWrap(True)
        dev_hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(dev_hint)

        layout.addWidget(QtWidgets.QLabel("<b>Синтез речи (TTS)</b>"))
        layout.addWidget(QtWidgets.QLabel("Движок синтеза:"))
        self.tts_engine_combo = QtWidgets.QComboBox()
        self.tts_engine_combo.addItem("Silero (офлайн, xenia/kseniya)", "silero")
        self.tts_engine_combo.addItem("Edge-TTS (Microsoft, онлайн, бесплатно)", "edge-tts")
        self.tts_engine_combo.addItem("pyttsx3 (локальный / Windows SAPI / espeak)", "pyttsx3")
        self.tts_engine_combo.addItem("OpenAI TTS API (внешний)", "openai")
        self.tts_engine_combo.addItem("Custom HTTP API (свой сервер)", "custom")
        self.tts_engine_combo.currentIndexChanged.connect(self._on_tts_engine_changed)
        layout.addWidget(self.tts_engine_combo)

        self.tts_hint_label = QtWidgets.QLabel("")
        self.tts_hint_label.setWordWrap(True)
        self.tts_hint_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.tts_hint_label)

        layout.addWidget(QtWidgets.QLabel("Голос / Voice ID:"))
        self.voice_name_combo = QtWidgets.QComboBox()
        self.voice_name_combo.setEditable(True)  # можно вписать свой ID
        self.voice_name_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.voice_name_combo.setMinimumWidth(280)
        layout.addWidget(self.voice_name_combo)
        # совместимость со старым кодом
        self.voice_name_edit = self.voice_name_combo

        layout.addWidget(QtWidgets.QLabel("Скорость речи (−50 … +50):"))
        self.speed_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.speed_slider.setRange(-50, 50)
        self.speed_slider.valueChanged.connect(self.update_speed_label)
        speed_layout = QtWidgets.QHBoxLayout()
        speed_layout.addWidget(self.speed_slider)
        self.speed_label = QtWidgets.QLabel("0")
        speed_layout.addWidget(self.speed_label)
        layout.addLayout(speed_layout)

        layout.addWidget(QtWidgets.QLabel("Громкость (0–100%):"))
        self.volume_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.valueChanged.connect(self.update_volume_label)
        vol_layout = QtWidgets.QHBoxLayout()
        vol_layout.addWidget(self.volume_slider)
        self.volume_label = QtWidgets.QLabel("100%")
        vol_layout.addWidget(self.volume_label)
        layout.addLayout(vol_layout)

        # --- Внешний API TTS ---
        layout.addWidget(QtWidgets.QLabel("<b>Внешний TTS API</b> (для openai / custom)"))
        layout.addWidget(QtWidgets.QLabel("TTS API URL:"))
        self.tts_api_url_edit = QtWidgets.QLineEdit()
        self.tts_api_url_edit.setPlaceholderText(
            "https://api.openai.com/v1  или  http://127.0.0.1:8080/v1"
        )
        layout.addWidget(self.tts_api_url_edit)

        layout.addWidget(QtWidgets.QLabel("TTS API Key:"))
        self.tts_api_key_edit = QtWidgets.QLineEdit()
        self.tts_api_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.tts_api_key_edit.setPlaceholderText("sk-... или токен вашего сервера")
        layout.addWidget(self.tts_api_key_edit)

        layout.addWidget(QtWidgets.QLabel("TTS модель (openai: tts-1 / tts-1-hd):"))
        self.tts_model_edit = QtWidgets.QLineEdit()
        self.tts_model_edit.setPlaceholderText("tts-1")
        layout.addWidget(self.tts_model_edit)

        # --- Кнопки ---
        btn_row = QtWidgets.QHBoxLayout()
        test_btn = QtWidgets.QPushButton("🔊 Тест голоса")
        test_btn.clicked.connect(self.test_voice)
        btn_row.addWidget(test_btn)

        list_voices_btn = QtWidgets.QPushButton("📋 Список голосов TTS")
        list_voices_btn.clicked.connect(self.list_tts_voices)
        btn_row.addWidget(list_voices_btn)
        layout.addLayout(btn_row)

        layout.addStretch()
        scroll.setWidget(inner)
        tab_layout = QtWidgets.QVBoxLayout(tab)
        tab_layout.addWidget(scroll)

        self._on_tts_engine_changed()
        self._on_stt_engine_changed()
        self._refresh_audio_devices()




    def _populate_voice_list(self, engine: str = None):
        """Заполнить combo голосов под выбранный TTS."""
        if not hasattr(self, "voice_name_combo"):
            return
        engine = (engine or self.tts_engine_combo.currentData() or "silero") or "silero"
        engine = str(engine).lower()
        current = self._get_voice_id()

        voices = list(self._VOICES.get(engine) or self._VOICES.get("silero"))

        self.voice_name_combo.blockSignals(True)
        self.voice_name_combo.clear()
        for label, value in voices:
            self.voice_name_combo.addItem(label, value)

        # восстановить выбор / вписать текущий
        idx = -1
        for i in range(self.voice_name_combo.count()):
            if (self.voice_name_combo.itemData(i) or "").lower() == (current or "").lower():
                idx = i
                break
            if current and current.lower() in (self.voice_name_combo.itemText(i) or "").lower():
                idx = i
                break
        if idx >= 0:
            self.voice_name_combo.setCurrentIndex(idx)
        elif current:
            # свой ID не из списка
            self.voice_name_combo.setEditText(current)
        else:
            self.voice_name_combo.setCurrentIndex(0)
        self.voice_name_combo.blockSignals(False)


    def _get_voice_mode(self) -> str:
        """push | wake — только коды, не подписи UI."""
        if not hasattr(self, "voice_mode_combo"):
            return "push"
        data = self.voice_mode_combo.currentData()
        if data in ("push", "wake", "always", "hotword", "keyword"):
            return str(data)
        text = (self.voice_mode_combo.currentText() or "").lower()
        if "кодов" in text or "wake" in text or "алиса" in text or "всегда" in text:
            return "wake"
        return "push"

    def _get_voice_id(self) -> str:
        """Текущий Voice ID из combo (data или текст)."""
        if not hasattr(self, "voice_name_combo"):
            return ""
        data = self.voice_name_combo.currentData()
        if data is not None and str(data).strip() != "":
            return str(data).strip()
        # editable: пользователь вписал вручную
        text = (self.voice_name_combo.currentText() or "").strip()
        # если выбрали пункт вида "xenia — ...", data уже должен быть; иначе вытащим до "—"
        if "—" in text:
            text = text.split("—")[0].strip()
        if " - " in text:
            text = text.split(" - ")[0].strip()
        return text

    def _set_voice_id(self, voice: str):
        voice = (voice or "").strip()
        if not hasattr(self, "voice_name_combo"):
            return
        for i in range(self.voice_name_combo.count()):
            if (self.voice_name_combo.itemData(i) or "").lower() == voice.lower():
                self.voice_name_combo.setCurrentIndex(i)
                return
        if voice:
            self.voice_name_combo.setEditText(voice)


    def _refresh_audio_devices(self):
        """Заполнить списки микрофонов и динамиков."""
        try:
            from voice_controller import VoiceController
        except Exception:
            VoiceController = None

        # --- mic ---
        if hasattr(self, "mic_combo"):
            cur = None
            try:
                cur = self.mic_combo.currentData()
            except Exception:
                pass
            self.mic_combo.blockSignals(True)
            self.mic_combo.clear()
            self.mic_combo.addItem("(системный по умолчанию)", None)
            devices = []
            if VoiceController:
                try:
                    devices = VoiceController.list_input_devices()
                except Exception:
                    devices = []
            if not devices:
                try:
                    import speech_recognition as sr
                    for i, name in enumerate(sr.Microphone.list_microphone_names() or []):
                        devices.append({"index": i, "name": name})
                except Exception:
                    pass
            for d in devices:
                self.mic_combo.addItem(f'[{d["index"]}] {d["name"]}', d["index"])
            # restore
            if cur is not None:
                for i in range(self.mic_combo.count()):
                    if self.mic_combo.itemData(i) == cur:
                        self.mic_combo.setCurrentIndex(i)
                        break
            self.mic_combo.blockSignals(False)

        # --- speakers ---
        if hasattr(self, "speaker_combo"):
            cur = None
            try:
                cur = self.speaker_combo.currentData()
            except Exception:
                pass
            self.speaker_combo.blockSignals(True)
            self.speaker_combo.clear()
            outs = [{"index": None, "name": "(системный по умолчанию)"}]
            if VoiceController:
                try:
                    outs = VoiceController.list_output_devices() or outs
                except Exception:
                    pass
            for d in outs:
                label = d["name"] if d["index"] is None else f'[{d["index"]}] {d["name"]}'
                self.speaker_combo.addItem(label, d["index"])
            if cur is not None:
                for i in range(self.speaker_combo.count()):
                    if self.speaker_combo.itemData(i) == cur:
                        self.speaker_combo.setCurrentIndex(i)
                        break
            self.speaker_combo.blockSignals(False)

    def _on_tts_engine_changed(self, *_):
        engine = self.tts_engine_combo.currentData() or self.tts_engine_combo.currentText()
        self._populate_voice_list(engine)
        hints = {
            "silero": (
                "Офлайн Silero TTS. Голоса: xenia (моложе), kseniya, baya. "
                "Первый запуск может скачать модель (~50–100 МБ), дальше без интернета. "
                "Нужен: pip install torch"
            ),
            "silero-tts": (
                "То же, что silero."
            ),
            "edge-tts": (
                "Microsoft Edge TTS — бесплатно, нужен интернет. "
                "Голоса: ru-RU-SvetlanaNeural, ru-RU-DmitryNeural, en-US-JennyNeural и др."
            ),
            "pyttsx3": (
                "Локальный синтез (Windows SAPI / espeak). Интернет не нужен. "
                "Голос берётся из системы; поле «Голос» можно оставить пустым."
            ),
            "openai": (
                "OpenAI-совместимый TTS. Укажите API URL (например https://api.openai.com/v1) "
                "и ключ. Голоса: alloy, echo, fable, onyx, nova, shimmer."
            ),
            "custom": (
                "Свой HTTP-сервер. POST {API_URL}/audio/speech с JSON "
                "{model, input, voice}. Ответ — audio/mpeg или audio/wav."
            ),
        }
        self.tts_hint_label.setText(hints.get(engine, ""))

        # Показать/скрыть блок внешнего API
        need_api = engine in ("openai", "custom")
        for w in (
            self.tts_api_url_edit,
            self.tts_api_key_edit,
            self.tts_model_edit,
        ):
            w.setEnabled(need_api)

    def _on_stt_engine_changed(self, *_):
        engine = self.stt_engine_combo.currentData() or self.stt_engine_combo.currentText()
        self.google_stt_key_edit.setEnabled(engine == "google")


    def update_speed_label(self, value):
        self.speed_label.setText(str(value))

    def update_volume_label(self, value):
        self.volume_label.setText(f"{value}%")


    def test_voice(self):
        if hasattr(self.parent, "voice_controller") and self.parent.voice_controller:
            # Временно применяем выбранный движок для теста
            engine = self.tts_engine_combo.currentData() or "edge-tts"
            old = getattr(config, "VOICE_SYNTHESIS_ENGINE", "edge-tts")
            config.VOICE_SYNTHESIS_ENGINE = engine
            config.VOICE_NAME = self._get_voice_id() or config.VOICE_NAME
            config.SILERO_SPEAKER = config.VOICE_NAME
            config.VOICE_TTS_API_URL = self.tts_api_url_edit.text().strip()
            config.VOICE_TTS_API_KEY = self.tts_api_key_edit.text().strip()
            config.VOICE_TTS_MODEL = self.tts_model_edit.text().strip() or "tts-1"
            try:
                self.parent.voice_controller.test_speaker()
            finally:
                config.VOICE_SYNTHESIS_ENGINE = old
        else:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Голосовой контроллер не найден")


    def list_tts_voices(self):
        """Популярные голоса Silero / edge-tts."""
        engine = ""
        try:
            engine = self.tts_engine_combo.currentData() or ""
        except Exception:
            pass
        if engine in ("silero", "silero-tts"):
            voices = (
                "Silero (русский, офлайн):\n"
                "  xenia   — женский, моложе (рекомендуется для Лисички)\n"
                "  kseniya — женский\n"
                "  baya    — женский\n"
                "  aidar   — мужской\n"
                "  eugene  — мужской\n\n"
                "В поле «Голос» укажи: xenia  или  kseniya\n"
                "Первый запуск скачает модель (нужен интернет один раз)."
            )
            QtWidgets.QMessageBox.information(self, "Голоса Silero", voices)
            return
        self.list_edge_voices()

    def list_edge_voices(self):
        """Показать популярные голоса edge-tts."""
        voices = (
            "Русские:\n"
            "  ru-RU-SvetlanaNeural (жен)\n"
            "  ru-RU-DmitryNeural (муж)\n\n"
            "Английские:\n"
            "  en-US-JennyNeural, en-US-GuyNeural\n"
            "  en-GB-SoniaNeural, en-GB-RyanNeural\n\n"
            "OpenAI TTS:\n"
            "  alloy, echo, fable, onyx, nova, shimmer\n\n"
            "Полный список edge: в терминале → edge-tts --list-voices"
        )
        QtWidgets.QMessageBox.information(self, "Голоса", voices)

