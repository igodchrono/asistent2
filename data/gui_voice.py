# gui_voice.py — голосовой ввод UI (вынесен из gui.py)
"""
Mixin для AssistantWindow: push-to-talk и обработка STT-сигналов.
Не трогает TTS (stop_tts остаётся в gui — кнопка там же).
"""
from __future__ import annotations

import asyncio
import threading

from PyQt5 import QtWidgets, QtCore

import config


class VoiceInputMixin:
    """Требует: voice_controller, voice_btn, voice_result_signal, voice_status_signal, input_field, on_send_clicked, avatar_window."""

    def voice_input(self):
        """Кнопка 🎤: push-to-talk (нажал → сказал → результат в чат)."""
        if not getattr(self, "voice_controller", None):
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Голосовой ввод не доступен.")
            return

        mode = (getattr(config, "VOICE_INPUT_MODE", "push") or "push").lower()

        if self.voice_controller.is_recording_now():
            self.voice_controller.is_recording = False
            self._set_voice_btn_idle()
            self.voice_status_signal.emit("⏹️ Запись остановлена")
            return

        self.voice_btn.setEnabled(False)
        self.voice_btn.setText("🔴")
        self.voice_btn.setStyleSheet("QPushButton { background-color: #ff4444; }")
        hint = "🎤 Слушаю..." if mode == "push" else "🎤 Слушаю одну фразу..."
        self.voice_status_signal.emit(hint)
        QtCore.QCoreApplication.processEvents()

        if hasattr(self, "avatar_window") and self.avatar_window:
            if "thinking" in getattr(self.avatar_window, "static_frames", {}):
                self.avatar_window.show_static("thinking")
            else:
                self.avatar_window.show_static("neutral")

        def _listen():
            try:
                text = self.voice_controller.listen_once() or ""
            except Exception as e:
                text = ""
                self.voice_status_signal.emit(f"❌ Ошибка микрофона: {e}")
            self.voice_result_signal.emit(text)

        threading.Thread(target=_listen, daemon=True, name="STT-push").start()

    def _set_voice_btn_idle(self):
        if hasattr(self, "voice_btn"):
            self.voice_btn.setEnabled(True)
            self.voice_btn.setText("🎤")
            self.voice_btn.setStyleSheet("")

    def _on_voice_status(self, msg: str):
        try:
            if hasattr(self, "chat_panel"):
                self.chat_panel.append_system(msg)
            elif hasattr(self, "chat_display"):
                self.chat_display.append(msg)
        except Exception:
            pass

    def _on_voice_result(self, text: str):
        """Главный поток Qt: STT → поле ввода → отправка."""
        self._set_voice_btn_idle()
        if hasattr(self, "avatar_window") and self.avatar_window:
            try:
                self.avatar_window.show_static("neutral")
            except Exception:
                pass

        text = (text or "").strip()
        if not text:
            self._on_voice_status("❌ Не удалось распознать речь")
            return

        self.input_field.setText(text)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.on_send_clicked())
            else:
                QtCore.QTimer.singleShot(
                    0, lambda: asyncio.ensure_future(self.on_send_clicked())
                )
        except Exception:
            try:
                self.on_send_clicked()
            except Exception as e:
                self._on_voice_status(f"❌ Не удалось отправить: {e}")
