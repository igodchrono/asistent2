# settings_dialog.py — тонкий фасад (вкладки в settings_ui/)
# API для gui: from settings_dialog import SettingsDialog
from PyQt5 import QtWidgets, QtGui, QtCore

import config
from settings_manager import (
    save_settings as save_user_settings,
    load_settings as load_user_settings,
    apply_to_config,
    reload_config,
)

from settings_ui import (
    MainTabMixin,
    VoiceTabMixin,
    MemoryTabMixin,
    PersonaTabMixin,
    GreetingTabMixin,
    TestTabMixin,
)


class SettingsDialog(
    MainTabMixin,
    VoiceTabMixin,
    MemoryTabMixin,
    PersonaTabMixin,
    GreetingTabMixin,
    TestTabMixin,
    QtWidgets.QDialog,
):
    """Диалог настроек. Логика вкладок — в settings_ui/tab_*.py."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("Настройки ассистента")
        self.setModal(True)
        self.setGeometry(200, 200, 720, 860)
        self._loading_settings = False
        self.initUI()
        self.load_current_settings()
        self.load_models_list()

    def initUI(self):
        self.tab_widget = QtWidgets.QTabWidget()

        main_tab = QtWidgets.QWidget()
        self._setup_main_tab(main_tab)
        self.tab_widget.addTab(main_tab, "Основные")

        browser_tab = QtWidgets.QWidget()
        self._setup_browser_tab(browser_tab)
        self.tab_widget.addTab(browser_tab, "🌐 Браузер")

        emotion_tab = QtWidgets.QWidget()
        self._setup_emotion_tab(emotion_tab)
        self.tab_widget.addTab(emotion_tab, "😊 Эмоции")

        persona_tab = QtWidgets.QWidget()
        self._setup_persona_tab(persona_tab)
        self.tab_widget.addTab(persona_tab, "🎭 Персонаж")

        memory_tab = QtWidgets.QWidget()
        self._setup_memory_tab(memory_tab)
        self.tab_widget.addTab(memory_tab, "🧠 Память")

        voice_tab = QtWidgets.QWidget()
        self._setup_voice_tab(voice_tab)
        self.tab_widget.addTab(voice_tab, "🎤 Голос")

        greeting_tab = QtWidgets.QWidget()
        self._setup_greeting_tab(greeting_tab)
        self.tab_widget.addTab(greeting_tab, "💬 Авто-сообщения")

        test_tab = QtWidgets.QWidget()
        self._setup_test_tab(test_tab)
        self.tab_widget.addTab(test_tab, "🧪 Тест")

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.tab_widget)

        btn_layout = QtWidgets.QHBoxLayout()
        save_btn = QtWidgets.QPushButton("Сохранить")
        save_btn.clicked.connect(self.save_settings)
        btn_layout.addWidget(save_btn)
        cancel_btn = QtWidgets.QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        try:
            from settings_ui.tips import apply_tooltips
            apply_tooltips(self)
        except Exception:
            pass
        save_btn.setToolTip("Записать настройки в settings.json и применить сразу.")
        cancel_btn.setToolTip("Закрыть окно без сохранения.")

    def load_current_settings(self):
        self._loading_settings = True
        try:
            self._load_current_settings_inner()
        finally:
            self._loading_settings = False

    def _load_current_settings_inner(self):
        self.api_url_edit.setText(config.API_URL)
        self.api_key_edit.setText(config.API_KEY)
        self.model_combo.setEditText(config.MODEL_NAME)
        self.temperature_edit.setText(str(config.TEMPERATURE))
        self.max_tokens_edit.setText(str(config.MAX_TOKENS))
        self.anim_speed_slider.setValue(config.ANIMATION_SPEED)
        self.anim_speed_label.setText(str(config.ANIMATION_SPEED))
        self.size_slider.setValue(config.AVATAR_SIZE)
        self.size_label.setText(str(config.AVATAR_SIZE))
        self.internet_cb.setChecked(config.ENABLE_INTERNET)
        self.pc_cb.setChecked(config.ENABLE_PC_CONTROL)
        self.safe_mode_cb.setChecked(config.SAFE_MODE)

        browser = getattr(config, "DEFAULT_BROWSER", "chrome")
        idx = self.browser_combo.findText(browser)
        if idx >= 0:
            self.browser_combo.setCurrentIndex(idx)
        self.browser_path_edit.setText(getattr(config, "BROWSER_PATH", ""))

        engine = getattr(config, "SEARCH_ENGINE", "google")
        idx = self.search_engine_combo.findText(engine)
        if idx >= 0:
            self.search_engine_combo.setCurrentIndex(idx)
        self.search_open_browser_cb.setChecked(getattr(config, "SEARCH_OPEN_BROWSER", True))

        if hasattr(self, "show_avatar_cb"):
            self.show_avatar_cb.setChecked(getattr(config, "SHOW_AVATAR", True))
        self.nsfw_enabled_cb.setChecked(config.NSFW_ENABLED)
        self.nsfw_frequency_slider.setValue(int(config.NSFW_FREQUENCY * 100))
        self.nsfw_frequency_label.setText(f"{int(config.NSFW_FREQUENCY * 100)}%")

        default_anim = getattr(config, "DEFAULT_ANIMATION", "neutral")
        idx = self.default_anim_combo.findText(default_anim)
        if idx >= 0:
            self.default_anim_combo.setCurrentIndex(idx)

        # --- Голос ---
        self.voice_input_cb.setChecked(config.ENABLE_VOICE_INPUT)
        self.voice_output_cb.setChecked(config.ENABLE_VOICE_OUTPUT)
        mode = getattr(config, "VOICE_INPUT_MODE", "push") or "push"
        if hasattr(self, "voice_mode_combo"):
            for i in range(self.voice_mode_combo.count()):
                if self.voice_mode_combo.itemData(i) == mode:
                    self.voice_mode_combo.setCurrentIndex(i)
                    break
        if hasattr(self, "wake_word_edit"):
            self.wake_word_edit.setText(getattr(config, "WAKE_WORD", "лисичка") or "лисичка")

        stt = getattr(config, "VOICE_RECOGNITION_ENGINE", "vosk")
        for i in range(self.stt_engine_combo.count()):
            if self.stt_engine_combo.itemData(i) == stt:
                self.stt_engine_combo.setCurrentIndex(i)
                break

        self.voice_lang_edit.setText(getattr(config, "VOICE_LANGUAGE", "ru-RU"))
        self.google_stt_key_edit.setText(getattr(config, "GOOGLE_SPEECH_API_KEY", "") or "")
        if hasattr(self, "mic_combo"):
            self._refresh_audio_devices()
            mic = getattr(config, "VOICE_INPUT_DEVICE", None)
            for i in range(self.mic_combo.count()):
                if self.mic_combo.itemData(i) == mic or (
                    mic is not None and str(self.mic_combo.itemData(i)) == str(mic)
                ):
                    self.mic_combo.setCurrentIndex(i)
                    break
            spk = getattr(config, "VOICE_OUTPUT_DEVICE", None)
            for i in range(self.speaker_combo.count()):
                if self.speaker_combo.itemData(i) == spk or (
                    spk is not None and str(self.speaker_combo.itemData(i)) == str(spk)
                ):
                    self.speaker_combo.setCurrentIndex(i)
                    break

        tts = getattr(config, "VOICE_SYNTHESIS_ENGINE", "edge-tts")
        for i in range(self.tts_engine_combo.count()):
            if self.tts_engine_combo.itemData(i) == tts:
                self.tts_engine_combo.setCurrentIndex(i)
                break

        self._set_voice_id(getattr(config, "VOICE_NAME", "xenia") or "xenia")
        self.speed_slider.setValue(config.VOICE_SPEED)
        self.speed_label.setText(str(config.VOICE_SPEED))

        vol = int(float(getattr(config, "VOICE_VOLUME", 1.0)) * 100)
        self.volume_slider.setValue(vol)
        self.volume_label.setText(f"{vol}%")

        self.tts_api_url_edit.setText(getattr(config, "VOICE_TTS_API_URL", "") or "")
        self.tts_api_key_edit.setText(getattr(config, "VOICE_TTS_API_KEY", "") or "")
        self.tts_model_edit.setText(getattr(config, "VOICE_TTS_MODEL", "tts-1") or "tts-1")

        self._on_tts_engine_changed()
        self._on_stt_engine_changed()
        self._refresh_audio_devices()

        # --- Авто-сообщения ---
        self.greeting_enabled_cb.setChecked(getattr(config, "ENABLE_AUTO_GREETING", True))
        self.greeting_use_llm_cb.setChecked(getattr(config, "GREETING_USE_LLM", True))
        if hasattr(self, "screen_vision_enabled_cb"):
            self.screen_vision_enabled_cb.setChecked(getattr(config, "SCREEN_VISION_ENABLED", True))
        if hasattr(self, "screen_vision_auto_cb"):
            self.screen_vision_auto_cb.setChecked(getattr(config, "SCREEN_VISION_AUTO", False))
        if hasattr(self, "screen_vision_interval_slider"):
            sec = int(getattr(config, "SCREEN_VISION_AUTO_INTERVAL", 60) or 60)
            mins = max(1, min(30, int(round(sec / 60.0)) or 1))
            self.screen_vision_interval_slider.setValue(mins)
            self.screen_vision_interval_label.setText(f"{mins} мин")
        if hasattr(self, "_refresh_monitor_list"):
            self._refresh_monitor_list()
        self.greeting_min_slider.setValue(getattr(config, "GREETING_INTERVAL_MIN", 180))
        self.greeting_min_label.setText(str(self.greeting_min_slider.value()))
        self.greeting_max_slider.setValue(getattr(config, "GREETING_INTERVAL_MAX", 300))
        self.greeting_max_label.setText(str(self.greeting_max_slider.value()))
        nsfw = int(getattr(config, "GREETING_NSFW_CHANCE", 0.45) * 100)
        self.greeting_nsfw_slider.setValue(nsfw)
        self.greeting_nsfw_label.setText(f"{nsfw}%")

    def save_settings(self):
        try:
            tts_engine = self.tts_engine_combo.currentData() or "edge-tts"
            stt_engine = self.stt_engine_combo.currentData() or "vosk"

            new_settings = {
                "API_URL": self.api_url_edit.text().strip() or config.API_URL,
                "API_KEY": self.api_key_edit.text().strip() or config.API_KEY,
                "MODEL_NAME": self.model_combo.currentText().strip() or config.MODEL_NAME,
                "TEMPERATURE": float(self.temperature_edit.text().strip() or 0.85),
                "MAX_TOKENS": int(self.max_tokens_edit.text().strip() or 4000),
                "ANIMATION_SPEED": self.anim_speed_slider.value(),
                "AVATAR_SIZE": self.size_slider.value(),
                "ENABLE_INTERNET": self.internet_cb.isChecked(),
                "ENABLE_PC_CONTROL": self.pc_cb.isChecked(),
                "SAFE_MODE": self.safe_mode_cb.isChecked(),
                "DEFAULT_BROWSER": self.browser_combo.currentText(),
                "BROWSER_PATH": self.browser_path_edit.text().strip(),
                "SEARCH_ENGINE": self.search_engine_combo.currentText(),
                "SEARCH_OPEN_BROWSER": self.search_open_browser_cb.isChecked(),
                "SHOW_AVATAR": bool(getattr(self, "show_avatar_cb", None) and self.show_avatar_cb.isChecked()),
                "NSFW_ENABLED": self.nsfw_enabled_cb.isChecked(),
                "NSFW_FREQUENCY": self.nsfw_frequency_slider.value() / 100.0,
                "DEFAULT_ANIMATION": self.default_anim_combo.currentText(),
                # Голос
                "ACTIVE_CHARACTER": (
                    self.character_combo.currentData()
                    if hasattr(self, "character_combo") else getattr(config, "ACTIVE_CHARACTER", "лисичка")
                ) or "лисичка",
                "ACTIVE_USER": (
                    self.user_persona_combo.currentData()
                    if hasattr(self, "user_persona_combo") else getattr(config, "ACTIVE_USER", "default")
                ) or "default",
                "ENABLE_VOICE_INPUT": self.voice_input_cb.isChecked(),
                "ENABLE_VOICE_OUTPUT": self.voice_output_cb.isChecked(),
                "VOICE_INPUT_MODE": self._get_voice_mode(),
                "WAKE_WORD": (
                    (self.wake_word_edit.text().strip()
                     if hasattr(self, "wake_word_edit") else "")
                    or "лисичка"
                ),
                "VOICE_RECOGNITION_ENGINE": stt_engine,
                "VOICE_LANGUAGE": self.voice_lang_edit.text().strip() or "ru-RU",
                "GOOGLE_SPEECH_API_KEY": self.google_stt_key_edit.text().strip(),
                "VOICE_INPUT_DEVICE": (
                    self.mic_combo.currentData()
                    if hasattr(self, "mic_combo") else None
                ),
                "VOICE_OUTPUT_DEVICE": (
                    self.speaker_combo.currentData()
                    if hasattr(self, "speaker_combo") else None
                ),
                "VOICE_SYNTHESIS_ENGINE": tts_engine,
                "VOICE_NAME": self._get_voice_id() or "xenia",
                "SILERO_SPEAKER": self._get_voice_id() or "xenia",
                "VOICE_SPEED": self.speed_slider.value(),
                "VOICE_VOLUME": self.volume_slider.value() / 100.0,
                "VOICE_TTS_API_URL": self.tts_api_url_edit.text().strip(),
                "VOICE_TTS_API_KEY": self.tts_api_key_edit.text().strip(),
                "VOICE_TTS_MODEL": self.tts_model_edit.text().strip() or "tts-1",
                # Авто-сообщения
                "ENABLE_AUTO_GREETING": self.greeting_enabled_cb.isChecked(),
                "GREETING_USE_LLM": self.greeting_use_llm_cb.isChecked(),
                "SCREEN_VISION_ENABLED": (
                    self.screen_vision_enabled_cb.isChecked()
                    if hasattr(self, "screen_vision_enabled_cb")
                    else getattr(config, "SCREEN_VISION_ENABLED", True)
                ),
                "SCREEN_VISION_AUTO": (
                    self.screen_vision_auto_cb.isChecked()
                    if hasattr(self, "screen_vision_auto_cb")
                    else getattr(config, "SCREEN_VISION_AUTO", False)
                ),
                "SCREEN_ALLOWED_MONITORS": (
                    self._allowed_monitors_from_ui()
                    if hasattr(self, "_allowed_monitors_from_ui")
                    else getattr(config, "SCREEN_ALLOWED_MONITORS", None)
                ),
                "SCREEN_VISION_AUTO_INTERVAL": (
                    int(self.screen_vision_interval_slider.value()) * 60
                    if hasattr(self, "screen_vision_interval_slider")
                    else int(getattr(config, "SCREEN_VISION_AUTO_INTERVAL", 60) or 60)
                ),
                "GREETING_INTERVAL_MIN": self.greeting_min_slider.value(),
                "GREETING_INTERVAL_MAX": self.greeting_max_slider.value(),
                "GREETING_NSFW_CHANCE": self.greeting_nsfw_slider.value() / 100.0,
            }

            ok = save_user_settings(new_settings)
            if not ok:
                raise RuntimeError("settings.json не записался")
            try:
                import character_manager as _cm
                if hasattr(self, "character_combo"):
                    config.ACTIVE_CHARACTER = self.character_combo.currentData() or "лисичка"
                if hasattr(self, "user_persona_combo"):
                    config.ACTIVE_USER = self.user_persona_combo.currentData() or "default"
                _cm.apply_to_config()
                print(f"🎭 Активный персонаж: {config.ACTIVE_CHARACTER}, user: {config.ACTIVE_USER}")
                try:
                    assistant = getattr(self, "assistant", None)
                    if assistant is None:
                        host = self.parent() or self.window()
                        assistant = getattr(host, "assistant", None) if host is not None else None
                    if assistant and hasattr(assistant, "switch_character"):
                        hist = assistant.switch_character(config.ACTIVE_CHARACTER)
                        host = self.parent() or self.window()
                        if host is not None and hasattr(host, "reload_character_chat"):
                            host.reload_character_chat(
                                hist, character=config.ACTIVE_CHARACTER
                            )
                except Exception as _sw:
                    print(f"⚠️ switch_character: {_sw}")
                # переиндексация RAG под новые md
                try:
                    assistant = getattr(self, "assistant", None)
                    if assistant is None:
                        host = self.parent() or self.window()
                        assistant = getattr(host, "assistant", None) if host is not None else None
                    rag = getattr(assistant, "rag", None) if assistant is not None else None
                    reindex = getattr(rag, "auto_index_from_config_async", None) if rag is not None else None
                    if callable(reindex):
                        import asyncio
                        asyncio.ensure_future(reindex())
                        print("🎭 RAG: переиндексация запущена")
                except Exception as _re:
                    print(f"⚠️ RAG reindex: {_re}")
            except Exception as _ce:
                print(f"⚠️ persona apply: {_ce}")

            # Сразу наложить на config (без перезапуска для части настроек)
            for k, v in new_settings.items():
                try:
                    setattr(config, k, v)
                except Exception:
                    pass

            mode_now = getattr(config, "VOICE_INPUT_MODE", "?")
            wake_now = getattr(config, "WAKE_WORD", "?")
            print(f"💾 Сохранено: VOICE_INPUT_MODE={mode_now!r}, WAKE_WORD={wake_now!r}")

            # Перезапуск continuous listen при wake
            try:
                parent = self.parent
                vc = getattr(parent, "voice_controller", None) if parent else None
                if vc and hasattr(vc, "apply_settings"):
                    vc.apply_settings()
                if parent and mode_now in ("wake", "always", "hotword", "keyword"):
                    import asyncio
                    async def _restart_wake():
                        try:
                            await vc.stop_listening_async()
                        except Exception:
                            pass
                        vc.set_callback(
                            lambda text: parent.voice_result_signal.emit(text or "")
                        )
                        await vc.start_listening_async()
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.ensure_future(_restart_wake())
                    except Exception as e:
                        print(f"⚠️ restart wake: {e}")
            except Exception as e:
                print(f"⚠️ post-save voice: {e}")


            for key, value in new_settings.items():
                setattr(config, key, value)

            # Единый источник: settings.json уже сохранён → config синхронизирован
            try:
                apply_to_config(config)
            except Exception as _ae:
                print(f"⚠️ apply_to_config: {_ae}")

            if hasattr(self.parent, "assistant"):
                assistant = self.parent.assistant
                assistant.api_url = new_settings["API_URL"]
                assistant.api_key = new_settings["API_KEY"]
                assistant.model_name = new_settings["MODEL_NAME"]
                assistant.temperature = new_settings["TEMPERATURE"]
                assistant.max_tokens = new_settings["MAX_TOKENS"]

            if hasattr(self.parent, "avatar_window"):
                avatar = self.parent.avatar_window
                avatar.set_size(new_settings["AVATAR_SIZE"])
                avatar.set_anim_speed(new_settings["ANIMATION_SPEED"])
                if new_settings.get("SHOW_AVATAR", True):
                    avatar.load_all_animations()
                    avatar.show_static("neutral")
                    avatar.show()
                else:
                    avatar.hide()

            # Обновить voice controller на лету
            if hasattr(self.parent, "voice_controller") and self.parent.voice_controller:
                vc = self.parent.voice_controller
                if hasattr(vc, "apply_settings"):
                    vc.apply_settings()
                else:
                    vc.set_voice_params(
                        voice=new_settings["VOICE_NAME"],
                        rate=new_settings["VOICE_SPEED"],
                        volume=new_settings["VOICE_VOLUME"],
                    )

            try:
                host = self.parent if not callable(self.parent) else self.parent()
                ast = getattr(host, "assistant", None)
                lc = getattr(ast, "_lifecycle", None) or getattr(ast, "lifecycle", None)
                if lc and hasattr(lc, "start"):
                    lc.start()
            except Exception as _le:
                print("lifecycle after save:", _le)
            QtWidgets.QMessageBox.information(self, "Успех", "Настройки сохранены!")
            self.accept()

        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "Ошибка", f"Не удалось сохранить настройки: {e}"
            )

