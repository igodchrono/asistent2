# gui.py — главное окно (AvatarWindow и SettingsDialog вынесены)
import os
import sys
import re
import base64
import asyncio
import threading
import time
import random
import html as _html
from typing import Optional

from PyQt5 import QtWidgets, QtGui, QtCore
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from qasync import asyncSlot

import config
from system_controller import SystemController
from settings_manager import save_settings as save_user_settings, load_settings as load_user_settings
from persistent_memory import PersistentMemory
from voice_controller import VoiceController
from avatar_window import AvatarWindow
from settings_dialog import SettingsDialog
from chat_panel import ChatPanel
from gui_voice import VoiceInputMixin
from speech_text import for_speech

# Импорт микро-моделей
try:
    from micro_models import HybridAnalyzer
    MICRO_MODELS_AVAILABLE = True
except ImportError:
    MICRO_MODELS_AVAILABLE = False


class AssistantWindow(VoiceInputMixin, QtWidgets.QMainWindow):
    """Главное окно ассистента."""
    
    reminder_signal = pyqtSignal(str)
    alert_signal = pyqtSignal(str)
    voice_result_signal = pyqtSignal(str)  # из фонового потока STT
    voice_status_signal = pyqtSignal(str)  # статус в чат
    
    def __init__(self, assistant):
        super().__init__()
        self.assistant = assistant
        self.file_path = None
        self.voice_controller = None
        self.current_base_anim = "neutral"
        self.last_user_text = ""
        self._assistant_block_cursor = None
        self._last_update_time = 0
        self._pending_text = ""
        self._current_assistant_block = None
        self._html_before_stream = None
        self._last_early_anim = None

        # Инициализация анализатора эмоций
        self._init_emotion_analyzer()
        
        self.conversation_history = []
        self._expected_anim = "neutral"
        self._pending_anim = None
        self._explicit_anim = False

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

        # TTS не зависит от микрофона: контроллер нужен, если включена озвучка.
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

        # ===== УСТАНОВКА CALLBACK ДЛЯ АВТО-СООБЩЕНИЙ =====
        if hasattr(self.assistant, 'executor'):
            if hasattr(self.assistant.executor, 'reminder_manager'):
                self.assistant.executor.reminder_manager.set_callback(self._send_reminder_to_gui)
                print("✅ Callback для напоминаний установлен")
        
        # Информация о загруженном анализаторе
        if hasattr(self.emotional_analyzer, 'use_micro_models'):
            print(f"🤖 Используется гибридный анализатор (ML={'включен' if self.emotional_analyzer.use_micro_models else 'выключен'})")
        else:
            print("📝 Используется rule-based анализатор эмоций")
    
    def _init_emotion_analyzer(self):
        """Только shared emotion_service — без второго HybridAnalyzer."""
        try:
            from emotion_service import get_shared_analyzer
            # предпочитаем уже созданный в assistant
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
        # совместимость со старым кодом
        self.chat_display = self.chat_panel.chat_display
        self.typing_indicator = self.chat_panel.typing_indicator

        input_layout = QtWidgets.QHBoxLayout()
        self.input_field = QtWidgets.QLineEdit()
        self.input_field.setPlaceholderText("Введите сообщение...")
        self.input_field.returnPressed.connect(self.on_send_clicked)
        input_layout.addWidget(self.input_field)

        self.send_btn = QtWidgets.QPushButton("Отправить")
        self.send_btn.clicked.connect(self.on_send_clicked)
        input_layout.addWidget(self.send_btn)

        self.attach_btn = QtWidgets.QPushButton("📎")
        self.attach_btn.setToolTip("Прикрепить файл")
        self.attach_btn.clicked.connect(self.load_file)
        input_layout.addWidget(self.attach_btn)

        if config.ENABLE_VOICE_INPUT:
            self.voice_btn = QtWidgets.QPushButton("🎤")
            self.voice_btn.setToolTip("Голосовой ввод")
            self.voice_btn.clicked.connect(self.voice_input)
            input_layout.addWidget(self.voice_btn)

        self.sound_btn = QtWidgets.QPushButton()
        self.sound_btn.clicked.connect(self.toggle_voice_output)
        input_layout.addWidget(self.sound_btn)
        self._refresh_sound_btn()

        self.clear_btn = QtWidgets.QPushButton("🗑️")
        self.clear_btn.setToolTip("Очистить историю")
        self.clear_btn.clicked.connect(self.clear_chat)
        input_layout.addWidget(self.clear_btn)

        self.settings_btn = QtWidgets.QPushButton("⚙️")
        self.settings_btn.setToolTip("Настройки")
        self.settings_btn.clicked.connect(self.open_settings)
        input_layout.addWidget(self.settings_btn)

        self.status_indicator = QtWidgets.QLabel("●")
        self.status_indicator.setStyleSheet("color: #0f0; font-size: 16px;")
        self.status_indicator.setToolTip("Соединение с API установлено")
        input_layout.insertWidget(0, self.status_indicator)

        self.status_label = QtWidgets.QLabel("готово")
        self.status_label.setStyleSheet(
            "color:#9ab; font-size:12px; padding:0 8px; min-width:90px;"
        )
        self.status_label.setToolTip("Статус ассистента")
        input_layout.insertWidget(1, self.status_label)

        layout.addLayout(input_layout)

        self.send_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Return"), self)
        self.send_shortcut.activated.connect(self.on_send_clicked)

        self.font_shortcut_plus = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl++"), self)
        self.font_shortcut_plus.activated.connect(self.increase_font_size)

        self.font_shortcut_minus = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+-"), self)
        self.font_shortcut_minus.activated.connect(self.decrease_font_size)

        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; }
            QTextBrowser { background-color: #2d2d2d; color: #f0f0f0; border: 1px solid #444; border-radius: 6px; }
            QLineEdit { background-color: #2d2d2d; color: #f0f0f0; border: 1px solid #444; padding: 8px; border-radius: 6px; }
            QPushButton { background-color: #3a3a3a; color: #f0f0f0; border: 1px solid #555; padding: 6px 10px; border-radius: 5px; }
            QPushButton:hover { background-color: #4a4a4a; }
            QPushButton:disabled { background-color: #2a2a2a; color: #777; }
        """)
    
    # ===== ФОРМАТИРОВАНИЕ — только через ChatPanel =====

    @staticmethod
    def _clean_assistant_text(reply: str) -> str:
        """Делегат к ChatPanel.clean_assistant_text — единый источник."""
        return ChatPanel.clean_assistant_text(reply)

    # ===== ОСТАЛЬНЫЕ МЕТОДЫ =====

    
    def _send_reminder_to_gui(self, text):
        """Отправляет напоминание в GUI (потокобезопасно)."""
        self.reminder_signal.emit(text)
    
    def _send_alert_to_gui(self, text):
        self.alert_signal.emit(text)
    
    def _on_reminder_message(self, text):
        import re as _re
        raw = text or ""

        anim_match = _re.search(r"\[ANIM:(\w+)\]", raw, _re.I)
        if anim_match and hasattr(self, "avatar_window") and self.avatar_window:
            anim_name = anim_match.group(1).lower()
            self.current_base_anim = anim_name
            self.update_avatar_animation(anim_name)

        is_fox = bool(
            anim_match
            or raw.strip().startswith("🦊")
            or "[ANIM:" in raw.upper()
        )
        if is_fox:
            clean = _re.sub(r"\[ANIM:\w+\]", "", raw, flags=_re.I).strip()
            self.chat_panel.append_assistant(clean if clean else raw)
        else:
            self.chat_panel.append_system(raw, kind="reminder")

        self.chat_panel._scroll_bottom()

        if self.voice_controller:
            speak = for_speech(
                self.chat_panel.clean_assistant_text(raw)
                if hasattr(self.chat_panel, "clean_assistant_text")
                else raw
            )
            if speak:
                self.voice_controller.speak(speak)

    def _on_system_alert(self, text):
        self.chat_panel.append_system(text, kind="system")
    
    def _check_reminders(self):
        if hasattr(self, 'assistant'):
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
            if on else
            "Озвучка выключена — нажми, чтобы включить"
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
        self.send_btn.setEnabled(enabled)
        self.attach_btn.setEnabled(enabled)
        if hasattr(self, 'voice_btn'):
            self.voice_btn.setEnabled(enabled)
        self.clear_btn.setEnabled(enabled)
        self.settings_btn.setEnabled(enabled)
        self.input_field.setEnabled(enabled)

    def update_avatar_animation(self, anim_name, force_static=False, force_sprite=False):
        """Обновляет анимацию аватара."""
        if not hasattr(self, 'avatar_window') or not self.avatar_window:
            return

        anim_name = (anim_name or "neutral").lower().strip()
        print(f"🎬 update_avatar_animation: {anim_name} (static={force_static}, sprite={force_sprite})")

        # Проверка NSFW
        is_nsfw = False
        if hasattr(self, "emotional_analyzer") and self.emotional_analyzer:
            if hasattr(self.emotional_analyzer, "is_nsfw_emotion"):
                is_nsfw = self.emotional_analyzer.is_nsfw_emotion(anim_name)
            else:
                is_nsfw = anim_name in getattr(config, "NSFW_EMOTIONS", [])
        if not is_nsfw:
            _nsfw_set = getattr(config, "NSFW_EMOTIONS", []) or []
            is_nsfw = anim_name in _nsfw_set or any(anim_name.startswith(b + "_") for b in _nsfw_set)
        if is_nsfw and not getattr(config, "NSFW_ENABLED", True):
            print(f"🔞 NSFW отключено → neutral")
            anim_name = "neutral"
            is_nsfw = False

        # Проверка разрешённых эмоций
        enabled_emotions = getattr(config, "ENABLED_EMOTIONS", None)
        if enabled_emotions is not None and anim_name not in enabled_emotions:
            found = False
            for emotion in enabled_emotions:
                if anim_name.startswith(emotion) or emotion.startswith(anim_name):
                    anim_name = emotion
                    found = True
                    break
            if not found:
                print(f"⚠️ {anim_name} нет в ENABLED_EMOTIONS → neutral")
                anim_name = "neutral"

        # Загружаем анимации, если их нет
        if not self.avatar_window.animations and not self.avatar_window.static_frames:
            self.avatar_window.load_all_animations()

        has_sprite = (
            anim_name in self.avatar_window.animations
            and len(self.avatar_window.animations[anim_name]) > 1
        )
        has_static = anim_name in self.avatar_window.static_frames

        LOOP_EMOTIONS = {
            "idle", "idle_sad", "idle_happy", "idle_angry", "idle_sly",
            "dance", "dance_happy", "dance_sly", "dance_love",
            "searching", "searching_happy", "searching_sad", "searching_angry",
            "undress", "undress_happy", "undress_sly", "undress_love",
            "undress_playful", "undress_seductive", "undress_teasing",
            "undress_mischievous", "undress_shy",
            "bath", "bath_shy", "bath_happy",
            "bed", "bed_love", "bed_shy",
        }
        ONESHOT_EMOTIONS = {
            "happy_big", "surprised", "surprised_happy", "surprised_shocked",
            "shocked", "scared", "cry", "cry_sad", "cry_angry",
            "angry_frustrated", "proud", "proud_happy",
            "pointing", "pointing_happy", "pointing_angry", "pointing_love",
            "flirty", "flirty_happy", "teasing", "teasing_sly",
            "seductive", "seductive_happy",
            "mischievous", "mischievous_happy",
        }

        prefer_static = (
            force_static
            or anim_name not in LOOP_EMOTIONS and anim_name not in ONESHOT_EMOTIONS
        )
        prefer_loop = anim_name in LOOP_EMOTIONS
        prefer_oneshot = anim_name in ONESHOT_EMOTIONS

        if force_sprite:
            prefer_static = False

        print(f"   has_sprite={has_sprite}, has_static={has_static}, "
              f"prefer_static={prefer_static}, loop={prefer_loop}, oneshot={prefer_oneshot}")

        if has_sprite and not prefer_static:
            loop = prefer_loop and not prefer_oneshot
            ok = self.avatar_window.play_animation(anim_name, loop=loop)
            if ok:
                mode = "loop" if loop else "oneshot"
                print(f"▶️ Спрайт [{mode}]: {anim_name}")
            else:
                print(f"🖼️ Статика (спрайт не стартовал): {anim_name}")
        elif has_static:
            self.avatar_window.show_static(anim_name)
            print(f"🖼️ Статика: {anim_name}")
        else:
            fallback = None
            statics = self.avatar_window.static_frames
            anims = self.avatar_window.animations

            def _has(name: str) -> bool:
                return name in statics or name in anims

            # cry → cry_sad / cry_angry, если нет cry.png
            if not fallback:
                prefix = anim_name + "_"
                for pool in (statics, anims):
                    hits = [k for k in pool.keys() if k == anim_name or k.startswith(prefix)]
                    if hits:
                        prefer = [h for h in hits if h.endswith("_sad") or h.endswith("_happy") or h.endswith("_shy")]
                        fallback = (prefer or hits)[0]
                        break
            if "_" in anim_name:
                base = anim_name.split("_")[0]
                if not fallback and _has(base):
                    fallback = base
            if not fallback and is_nsfw and hasattr(self.emotional_analyzer, "get_static_fallback"):
                fb = self.emotional_analyzer.get_static_fallback(anim_name)
                if fb and _has(fb):
                    fallback = fb
            if not fallback and is_nsfw:
                for cand in ("undress", "undress_sly", "undress_love", "teasing", "playful", "sly"):
                    if _has(cand):
                        fallback = cand
                        break
            if not fallback:
                fallback = "neutral"

            if fallback in anims and len(anims.get(fallback) or []) > 1:
                self.avatar_window.play_animation(fallback, loop=False)
                print(f"▶️ Спрайт fallback: {fallback}")
            elif fallback in statics:
                self.avatar_window.show_static(fallback)
                print(f"🖼️ Статика fallback: {fallback}")
            else:
                self.avatar_window.show_static("neutral")
                print("🖼️ Fallback: neutral")

        if anim_name != "thinking":
            self.current_base_anim = anim_name

    def reload_avatar_animations(self):
        if hasattr(self, 'avatar_window'):
            self.avatar_window.load_all_animations()
            self.update_avatar_animation(self.current_base_anim)





    def _extract_animation(self, text: str) -> Optional[str]:
        """
        Извлечение анимации из текста.
        Приоритет: 1) прямой [ANIM:...], 2) анализатор эмоций
        """
        if not text:
            return None
        
        # ===== 1. ПРЯМОЙ ANIM-ТЕГ (ПРИОРИТЕТ) =====
        match = re.search(r'\[ANIM:(\w+)\]', text, re.IGNORECASE)
        if match:
            anim = match.group(1).lower()
            # GUI только применяет тег, не выбирает эмоцию заново.
            
            # Проверяем NSFW
            is_nsfw = anim in getattr(config, "NSFW_EMOTIONS", [])
            if is_nsfw and not getattr(config, "NSFW_ENABLED", True):
                print("🔞 NSFW отключено → neutral")
                return "neutral"
            
            # Проверяем разрешённые эмоции
            enabled = getattr(config, "ENABLED_EMOTIONS", None)
            if enabled is not None:
                if anim in enabled:
                    return anim
                # Если нет в списке — пробуем найти базовую
                if "_" in anim:
                    base = anim.split("_")[0]
                    if base in enabled:
                        return base
                # Пробуем найти частичное совпадение
                for e in enabled:
                    if anim.startswith(e) or e.startswith(anim):
                        return e
                return "neutral"
            
            return anim
        
        # Нет тега — не переопределяем. Приоритет: [ANIM] модели > selector в core.
        return None

    def set_assistant_status(self, kind: str, detail: str = ""):
        """idle / listening / thinking / searching / speaking / error / offline"""
        styles = {
            "idle": ("#0f0", "готово"),
            "listening": ("#0af", "слушаю…"),
            "thinking": ("#ff0", "думаю…"),
            "searching": ("#fa0", "ищу…"),
            "speaking": ("#c6f", "говорю…"),
            "error": ("#f44", "ошибка"),
            "offline": ("#888", "офлайн"),
        }
        color, text = styles.get(kind, ("#9ab", kind or "…"))
        if detail:
            text = f"{text} {detail}".strip()
        if getattr(self, "status_indicator", None) is not None:
            self.status_indicator.setStyleSheet(f"color: {color}; font-size: 16px;")
            self.status_indicator.setToolTip(text)
        if getattr(self, "status_label", None) is not None:
            self.status_label.setText(text)
            self.status_label.setStyleSheet(
                f"color:{color}; font-size:12px; padding:0 8px; min-width:90px;"
            )

    @asyncSlot()
    async def on_send_clicked(self):
        user_text = self.input_field.text().strip()
        if not user_text and not self.file_path:
            return

        self.last_user_text = user_text
        self.stop_tts()
        # сброс auto-greeting / mood
        try:
            if hasattr(self.assistant, "context") and self.assistant.context:
                self.assistant.context.touch_activity()
            lm = getattr(self.assistant, "lifecycle", None) or getattr(self, "lifecycle", None)
            if lm and hasattr(lm, "update_activity"):
                lm.update_activity()
        except Exception:
            pass
        
        # ===== ПРОВЕРКА: ЕСЛИ ПОЛЬЗОВАТЕЛЬ ОТПРАВИЛ [ANIM:...] =====
        anim_match = re.search(r'\[ANIM:(\w+)\]', user_text, re.IGNORECASE)
        if anim_match:
            anim_name = anim_match.group(1).lower()
            # Проверяем NSFW
            is_nsfw = anim_name in getattr(config, "NSFW_EMOTIONS", [])
            if not (is_nsfw and not getattr(config, "NSFW_ENABLED", True)):
                print(f"🎬 Прямая анимация от пользователя: {anim_name}")
                self.update_avatar_animation(anim_name)
                # Если только анимация — не отправляем в LLM
                if user_text.strip().lower() == f"[anim:{anim_name}]".lower():
                    self.input_field.clear()
                    self.chat_panel.append_user(f"[Анимация: {anim_name}]")
                    # Показываем статику анимации на пару секунд
                    return
        
        self._assistant_block_cursor = None
        self._last_update_time = 0
        self._pending_text = ""
        self._current_assistant_block = None

        self.conversation_history.append({"role": "user", "content": user_text})

        # До ответа модели не угадываем анимацию повторно — ждём [ANIM:] из стрима.
        self._expected_anim = None

        self.set_buttons_enabled(False)

        display_text = user_text if user_text else "[Без текста]"
        if self.file_path:
            ext = os.path.splitext(self.file_path)[1].lower()
            icon = "🖼️" if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.gif') else "📄"
            display_text += f" ({icon} {os.path.basename(self.file_path)})"
        self.chat_panel.append_user(display_text)
        self.input_field.clear()

        file_path = self.file_path
        self.file_path = None

        self.chat_panel.show_generation_placeholder()

        self.chat_panel.show_typing(True)
        self.set_assistant_status("thinking")

        if hasattr(self, 'avatar_window') and self.avatar_window:
            pre = None
            sel = getattr(self.assistant, "anim_selector", None) if hasattr(self, "assistant") else None
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
                if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.gif'):
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

    def load_file(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Выберите файл", "",
            "Все файлы (*.*);;"
            "Изображения (*.png *.jpg *.jpeg *.bmp *.gif);;"
            "Текстовые файлы (*.txt *.py *.js *.json *.md *.csv *.log);;"
            "Документы (*.pdf *.docx *.xlsx *.xls *.pptx)"
        )
        if not file_path:
            return

        self.file_path = file_path
        ext = os.path.splitext(file_path)[1].lower()

        if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.gif'):
            self.insert_image_preview(file_path)
        else:
            try:
                content = self.assistant.read_file_content(file_path, max_chars=500)
                preview = content[:500] + ("..." if len(content) > 500 else "")
                file_icon = "📄"
                if ext == '.pdf':
                    file_icon = "📕"
                elif ext in ('.docx', '.doc'):
                    file_icon = "📘"
                elif ext in ('.xlsx', '.xls'):
                    file_icon = "📊"
                elif ext == '.pptx':
                    file_icon = "📙"
                self.chat_display.append(f"{file_icon} Файл прикреплён: {os.path.basename(file_path)} (тип: {ext})\n```\n{preview}\n```")
                scrollbar = self.chat_display.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
            except Exception as e:
                self.chat_display.append(f"❌ Не удалось прочитать файл: {e}")

    def insert_image_preview(self, file_path):
        with open(file_path, "rb") as f:
            data = f.read()
        b64 = base64.b64encode(data).decode("utf-8")
        if file_path.lower().endswith('.png'):
            mime = "image/png"
        elif file_path.lower().endswith(('.jpg', '.jpeg')):
            mime = "image/jpeg"
        else:
            mime = "image/gif"

        html = f'''<a href="file:///{file_path}">
                    <img src="data:{mime};base64,{b64}" 
                         style="max-width: 100%; height: auto; max-height: 300px; border-radius: 8px;" />
                   </a>'''
        self.chat_display.append(html)
        scrollbar = self.chat_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def on_chat_link_clicked(self, url):
        s = url.toString()
        if s.startswith("file:///"):
            file_path = s[8:]
            if re.match(r"^/[A-Za-z]:/", file_path):
                file_path = file_path[1:]
            try:
                from urllib.parse import unquote
                file_path = unquote(file_path)
            except Exception:
                pass
            if os.path.exists(file_path):
                self.show_fullscreen_image(file_path)
            return
        if s.startswith("http://") or s.startswith("https://"):
            import webbrowser
            webbrowser.open(s)
            return

    def show_fullscreen_image(self, file_path):
        window = QtWidgets.QWidget()
        window.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool
        )
        window.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        label = QtWidgets.QLabel(window)
        pix = QtGui.QPixmap(file_path)
        screen = QtWidgets.QApplication.primaryScreen().size()
        pix = pix.scaled(screen.width(), screen.height(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        label.setPixmap(pix)
        label.setAlignment(QtCore.Qt.AlignCenter)

        layout = QtWidgets.QVBoxLayout(window)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)

        window.showFullScreen()

        def close_fullscreen(event):
            if event.button() == QtCore.Qt.LeftButton:
                window.close()
                if window in self.fullscreen_windows:
                    self.fullscreen_windows.remove(window)

        label.mousePressEvent = close_fullscreen
        self.fullscreen_windows.append(window)

    def clear_chat(self):
        self.assistant.clear_history()
        self.chat_panel.clear()
        self.chat_panel.append_system("[История очищена]")
        self.avatar_window.show_static("neutral")
        self._assistant_block_cursor = None
        self._current_assistant_block = None

    def reload_character_chat(self, history=None, character=None):
        """После смены персонажа показать его сохранённый диалог."""
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
        print("[DEBUG] closeEvent: full shutdown...", flush=True)
        try:
            if hasattr(self, "reminder_timer") and self.reminder_timer:
                self.reminder_timer.stop()
        except Exception:
            pass
        for w in getattr(self, "fullscreen_windows", []) or []:
            try:
                w.close()
            except Exception:
                pass
        # lifecycle + assistant + apps.db
        try:
            asst = getattr(self, "assistant", None)
            if asst is not None:
                lc = getattr(asst, "_lifecycle", None) or getattr(asst, "lifecycle", None)
                if lc is not None and hasattr(lc, "stop"):
                    lc.stop()
                if hasattr(asst, "shutdown"):
                    asst.shutdown()
        except Exception as e:
            print(f"[DEBUG] closeEvent shutdown: {e}", flush=True)
        try:
            lm = getattr(self, "lifecycle", None)
            if lm is not None and hasattr(lm, "stop"):
                lm.stop()
        except Exception:
            pass
        event.accept()
        # Выход из Qt и asyncio-loop (иначе python.exe висит)
        try:
            from PyQt5 import QtWidgets, QtCore
            app = QtWidgets.QApplication.instance()
            if app is not None:
                QtCore.QTimer.singleShot(100, app.quit)
        except Exception:
            pass
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
        print("[DEBUG] closeEvent: quit scheduled", flush=True)