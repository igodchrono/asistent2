# ui/window.py — главное окно: сборка модулей, без выбора эмоций за модель
import os
import re
import asyncio
from typing import Optional

from PyQt5 import QtWidgets, QtGui, QtCore
from PyQt5.QtCore import pyqtSignal, QTimer
from qasync import asyncSlot

import config
from settings_manager import save_settings as save_user_settings
from avatar_window import AvatarWindow
from settings_dialog import SettingsDialog
from chat_panel import ChatPanel
from gui_voice import VoiceInputMixin
from speech_text import for_speech

from .theme import WINDOW_QSS
from .composer import ComposerBar
from .status_bar import StatusController
from .avatar_ctrl import AvatarController
from .attachments import AttachmentMixin


class AssistantWindow(VoiceInputMixin, AttachmentMixin, QtWidgets.QMainWindow):
    """Главное окно ассистента. Ядро (LLM/RAG) только через self.assistant."""

    reminder_signal = pyqtSignal(str)
    alert_signal = pyqtSignal(str)
    voice_result_signal = pyqtSignal(str)
    voice_status_signal = pyqtSignal(str)

    def __init__(self, assistant):
        super().__init__()
        self.assistant = assistant
        self.file_path = None
        self.voice_controller = None
        self.last_user_text = ""
        self._assistant_block_cursor = None
        self._last_update_time = 0
        self._pending_text = ""
        self._current_assistant_block = None
        self._html_before_stream = None
        self._last_early_anim = None
        self.conversation_history = []
        self._expected_anim = "neutral"
        self._pending_anim = None
        self._explicit_anim = False

        self._init_emotion_analyzer()

        self.reminder_signal.connect(self._on_reminder_message)
        self.alert_signal.connect(self._on_system_alert)
        self.voice_result_signal.connect(self._on_voice_result)
        self.voice_status_signal.connect(self._on_voice_status)

        self.avatar_window = AvatarWindow()
        if hasattr(config, "ENABLED_EMOTIONS"):
            self.avatar_window.set_enabled_emotions(config.ENABLED_EMOTIONS)
        elif not self.avatar_window.static_frames:
            self.avatar_window.load_all_animations()
        self.avatar_window.show_static("neutral")
        if getattr(config, "SHOW_AVATAR", True):
            self.avatar_window.show()
        else:
            self.avatar_window.hide()

        self.avatar_ctrl = AvatarController(
            self, self.avatar_window, analyzer=getattr(self, "emotional_analyzer", None)
        )
        self.current_base_anim = self.avatar_ctrl.current_base_anim

        def _hide_for_shot():
            try:
                self.avatar_window.hide()
                self.hide()
            except Exception:
                pass

        def _show_after_shot():
            try:
                self.show()
                if getattr(config, "SHOW_AVATAR", True):
                    self.avatar_window.show()
            except Exception:
                pass

        self.assistant.hide_for_screenshot = _hide_for_shot
        self.assistant.show_after_screenshot = _show_after_shot

        self.voice_controller = self.assistant.init_voice()
        if self.voice_controller:
            self.voice_controller.set_avatar_window(self.avatar_window)
            mode = (getattr(config, "VOICE_INPUT_MODE", "push") or "push").lower()
            if mode in ("wake", "always", "hotword", "keyword"):
                self.voice_controller.set_callback(
                    lambda text: self.voice_result_signal.emit(text or "")
                )

        self.initUI()
        self.fullscreen_windows = []

        self.reminder_timer = QTimer()
        self.reminder_timer.timeout.connect(self._check_reminders)
        self.reminder_timer.start(1000)

        if hasattr(self.assistant, "executor"):
            if hasattr(self.assistant.executor, "reminder_manager"):
                self.assistant.executor.reminder_manager.set_callback(self._send_reminder_to_gui)
                print("✅ Callback для напоминаний установлен")

        if hasattr(self.emotional_analyzer, "use_micro_models"):
            print(
                f"🤖 Используется гибридный анализатор "
                f"(ML={'включен' if self.emotional_analyzer.use_micro_models else 'выключен'})"
            )
        else:
            print("📝 Используется rule-based анализатор эмоций")

    def _init_emotion_analyzer(self):
        try:
            from emotion_service import get_shared_analyzer

            if getattr(self.assistant, "analyzer", None):
                self.emotional_analyzer = self.assistant.analyzer
            else:
                self.emotional_analyzer = get_shared_analyzer()
            print("🤖 Эмоции: единый emotion_service")
        except Exception as e:
            print(f"⚠️ emotion_service: {e}")
            self.emotional_analyzer = getattr(self.assistant, "analyzer", None)

    def initUI(self):
        self.setWindowTitle("ИИ Ассистент — Чат")
        self.setGeometry(150, 150, 700, 600)
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        layout = QtWidgets.QVBoxLayout(central_widget)

        self.chat_panel = ChatPanel()
        self.chat_panel.set_early_anim_callback(self.update_avatar_animation)
        self.chat_panel.anchor_clicked_connect(self.on_chat_link_clicked)
        layout.addWidget(self.chat_panel)
        self.chat_display = self.chat_panel.chat_display
        self.typing_indicator = self.chat_panel.typing_indicator

        self.composer = ComposerBar()
        layout.addWidget(self.composer)

        self.input_field = self.composer.input_field
        self.send_btn = self.composer.send_btn
        self.attach_btn = self.composer.attach_btn
        self.sound_btn = self.composer.sound_btn
        self.clear_btn = self.composer.clear_btn
        self.settings_btn = self.composer.settings_btn
        self.status_indicator = self.composer.status_indicator
        self.status_label = self.composer.status_label
        self.status = StatusController(self.status_indicator, self.status_label)

        self.input_field.returnPressed.connect(self.on_send_clicked)
        self.send_btn.clicked.connect(self.on_send_clicked)
        self.attach_btn.clicked.connect(self.load_file)
        self.sound_btn.clicked.connect(self.toggle_voice_output)
        self.clear_btn.clicked.connect(self.clear_chat)
        self.settings_btn.clicked.connect(self.open_settings)

        if config.ENABLE_VOICE_INPUT:
            self.voice_btn = self.composer.add_voice_button()
            self.voice_btn.clicked.connect(self.voice_input)

        self._refresh_sound_btn()

        self.send_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Return"), self)
        self.send_shortcut.activated.connect(self.on_send_clicked)
        self.font_shortcut_plus = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl++"), self)
        self.font_shortcut_plus.activated.connect(self.increase_font_size)
        self.font_shortcut_minus = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+-"), self)
        self.font_shortcut_minus.activated.connect(self.decrease_font_size)

        self.setStyleSheet(WINDOW_QSS)

    @staticmethod
    def _clean_assistant_text(reply: str) -> str:
        return ChatPanel.clean_assistant_text(reply)

    def _send_reminder_to_gui(self, text):
        self.reminder_signal.emit(text)

    def _send_alert_to_gui(self, text):
        self.alert_signal.emit(text)

    def _on_reminder_message(self, text):
        raw = text or ""
        anim_match = re.search(r"\[ANIM:(\w+)\]", raw, re.I)
        if anim_match and getattr(self, "avatar_window", None):
            anim_name = anim_match.group(1).lower()
            self.current_base_anim = anim_name
            self.update_avatar_animation(anim_name)

        is_fox = bool(
            anim_match or raw.strip().startswith("🦊") or "[ANIM:" in raw.upper()
        )
        if is_fox:
            clean = re.sub(r"\[ANIM:\w+\]", "", raw, flags=re.I).strip()
            self.chat_panel.append_assistant(clean if clean else raw)
        else:
            self.chat_panel.append_system(raw, kind="reminder")

        self.chat_panel._scroll_bottom()

        if self.voice_controller:
            speak = for_speech(self.chat_panel.clean_assistant_text(raw))
            if speak:
                self.voice_controller.speak(speak)

    def _on_system_alert(self, text):
        self.chat_panel.append_system(text, kind="system")

    def _check_reminders(self):
        if hasattr(self, "assistant"):
            self.assistant.check_reminders_now()

    def increase_font_size(self):
        self.chat_panel.increase_font()

    def decrease_font_size(self):
        self.chat_panel.decrease_font()

    def stop_tts(self):
        if self.voice_controller and hasattr(self.voice_controller, "stop_speaking"):
            self.voice_controller.stop_speaking()

    def _refresh_sound_btn(self):
        on = bool(getattr(config, "ENABLE_VOICE_OUTPUT", False))
        if not hasattr(self, "sound_btn"):
            return
        self.sound_btn.setText("🔊" if on else "🔇")
        self.sound_btn.setToolTip(
            "Озвучка включена — нажми, чтобы выключить"
            if on
            else "Озвучка выключена — нажми, чтобы включить"
        )

    def toggle_voice_output(self):
        new = not bool(getattr(config, "ENABLE_VOICE_OUTPUT", False))
        config.ENABLE_VOICE_OUTPUT = new
        if not new:
            self.stop_tts()
        try:
            save_user_settings({"ENABLE_VOICE_OUTPUT": new})
        except Exception:
            pass
        self._refresh_sound_btn()

    def set_buttons_enabled(self, enabled):
        if hasattr(self, "composer"):
            self.composer.set_controls_enabled(enabled)
        else:
            self.send_btn.setEnabled(enabled)
            self.attach_btn.setEnabled(enabled)
            if hasattr(self, "voice_btn"):
                self.voice_btn.setEnabled(enabled)
            self.clear_btn.setEnabled(enabled)
            self.settings_btn.setEnabled(enabled)
            self.input_field.setEnabled(enabled)

    def update_avatar_animation(self, anim_name, force_static=False, force_sprite=False):
        self.avatar_ctrl.analyzer = getattr(self, "emotional_analyzer", None)
        self.avatar_ctrl.update(anim_name, force_static=force_static, force_sprite=force_sprite)
        self.current_base_anim = self.avatar_ctrl.current_base_anim

    def reload_avatar_animations(self):
        self.avatar_ctrl.reload()
        self.current_base_anim = self.avatar_ctrl.current_base_anim

    def _extract_animation(self, text: str) -> Optional[str]:
        return self.avatar_ctrl.extract_animation(text)

    def set_assistant_status(self, kind: str, detail: str = ""):
        self.status.set(kind, detail)

    @asyncSlot()
    async def on_send_clicked(self):
        user_text = self.input_field.text().strip()
        if not user_text and not self.file_path:
            return

        self.last_user_text = user_text
        self.stop_tts()
        try:
            if hasattr(self.assistant, "context") and self.assistant.context:
                self.assistant.context.touch_activity()
            lm = getattr(self.assistant, "lifecycle", None) or getattr(self, "lifecycle", None)
            if lm and hasattr(lm, "update_activity"):
                lm.update_activity()
        except Exception:
            pass

        anim_match = re.search(r"\[ANIM:(\w+)\]", user_text, re.IGNORECASE)
        if anim_match:
            anim_name = anim_match.group(1).lower()
            is_nsfw = anim_name in getattr(config, "NSFW_EMOTIONS", [])
            if not (is_nsfw and not getattr(config, "NSFW_ENABLED", True)):
                print(f"🎬 Прямая анимация от пользователя: {anim_name}")
                self.update_avatar_animation(anim_name)
                if user_text.strip().lower() == f"[anim:{anim_name}]".lower():
                    self.input_field.clear()
                    self.chat_panel.append_user(f"[Анимация: {anim_name}]")
                    return

        self._assistant_block_cursor = None
        self._last_update_time = 0
        self._pending_text = ""
        self._current_assistant_block = None
        self.conversation_history.append({"role": "user", "content": user_text})
        self._expected_anim = None

        self.set_buttons_enabled(False)

        display_text = user_text if user_text else "[Без текста]"
        if self.file_path:
            ext = os.path.splitext(self.file_path)[1].lower()
            icon = "🖼️" if ext in (".png", ".jpg", ".jpeg", ".bmp", ".gif") else "📄"
            display_text += f" ({icon} {os.path.basename(self.file_path)})"
        self.chat_panel.append_user(display_text)
        self.input_field.clear()

        file_path = self.file_path
        self.file_path = None

        self.chat_panel.show_generation_placeholder()
        self.chat_panel.show_typing(True)
        self.set_assistant_status("thinking")

        if getattr(self, "avatar_window", None):
            pre = None
            sel = getattr(self.assistant, "anim_selector", None)
            if sel and user_text:
                try:
                    pre = sel.select(user_text=user_text)
                except Exception:
                    pre = None
            if pre and pre not in ("neutral", "thinking", "idle"):
                self.update_avatar_animation(pre)
            else:
                self.update_avatar_animation("thinking")

        try:
            file_content = None
            image_path = None
            if file_path:
                ext = os.path.splitext(file_path)[1].lower()
                if ext in (".png", ".jpg", ".jpeg", ".bmp", ".gif"):
                    image_path = file_path
                else:
                    file_content = self.assistant.read_file_content(file_path, max_chars=5000)

            full_response = ""
            first_chunk = True
            self._last_early_anim = None

            async for chunk in self.assistant.generate_stream(
                user_text,
                stream_callback=None,
                image_path=image_path,
                file_content=file_content,
            ):
                if first_chunk:
                    self.chat_panel.begin_stream()
                    first_chunk = False
                full_response += chunk
                self.chat_panel.update_stream(full_response)
                await asyncio.sleep(0)

            if full_response:
                clean = self.chat_panel.finalize_stream(full_response)
                speak = for_speech(clean)
                if (
                    config.ENABLE_VOICE_OUTPUT
                    and getattr(self, "voice_controller", None)
                    and speak
                ):
                    self.set_assistant_status("speaking")
                    self.voice_controller.speak(speak)
            else:
                self.chat_panel.append_assistant("✨ Готово!")

        except asyncio.CancelledError:
            self.chat_panel.append_system("❌ Отменено")
        except Exception as e:
            self.chat_panel.append_system(f"❌ Ошибка: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.chat_panel.show_typing(False)
            self.set_assistant_status("idle")
            self.set_buttons_enabled(True)

    def clear_chat(self):
        self.assistant.clear_history()
        self.chat_panel.clear()
        self.chat_panel.append_system("[История очищена]")
        self.avatar_window.show_static("neutral")
        self._assistant_block_cursor = None
        self._current_assistant_block = None

    def reload_character_chat(self, history=None, character=None):
        self.chat_panel.clear()
        name = character or getattr(config, "ACTIVE_CHARACTER", "персонаж")
        self.chat_panel.append_system(f"[Персонаж: {name}]")
        try:
            self.avatar_window._frames_sig = None
            self.avatar_window.load_all_animations()
            self.avatar_window.show_static("neutral")
        except Exception as e:
            print("reload frames:", e)
        rows = history if history is not None else list(
            getattr(self.assistant, "conversation_history", []) or []
        )
        for msg in rows[-30:]:
            role = msg.get("role")
            text = msg.get("content") or ""
            if role == "user":
                self.chat_panel.append_user(text)
            elif role == "assistant":
                self.chat_panel.append_assistant(text)
        self._assistant_block_cursor = None
        self._current_assistant_block = None

    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec_()

    def closeEvent(self, event):
        self.reminder_timer.stop()
        for w in getattr(self, "fullscreen_windows", []) or []:
            try:
                w.close()
            except Exception:
                pass
        if hasattr(self, "assistant") and self.assistant:
            try:
                self.assistant.shutdown()
            except Exception:
                pass
        event.accept()
