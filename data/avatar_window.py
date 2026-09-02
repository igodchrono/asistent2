# avatar_window.py — окно анимированного аватара (вынесено из gui.py)
import os
import re

from PyQt5 import QtWidgets, QtGui, QtCore

import config
from emotion_analyzer import EmotionalAnalyzer


class AvatarWindow(QtWidgets.QWidget):
    """Окно с анимированным аватаром."""
    BASE_WIDTH = 380
    BASE_HEIGHT = 520

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)

        self.label = QtWidgets.QLabel(self)
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setStyleSheet("background: transparent;")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)

        self.animations = {}
        self.static_frames = {}
        self.current_anim = "neutral"
        self.current_frame_idx = 0
        self.anim_speed = config.ANIMATION_SPEED
        self.drag_pos = None
        self.is_animating = False
        self.anim_timer = None
        self.anim_finished_callback = None
        self.enabled_emotions = None

        self.current_width = config.AVATAR_SIZE
        self._frames_sig = None
        self.apply_size(self.current_width, reload_frames=False)
        self.start_animation()
        self.move_to_bottom_right()

    def set_enabled_emotions(self, emotions):
        self.enabled_emotions = emotions
        self.load_all_animations()
        self.show_static(self.current_anim)

    def move_to_bottom_right(self):
        screen = QtWidgets.QApplication.primaryScreen().geometry()
        x = screen.width() - self.width() - 20
        y = screen.height() - self.height() - 60
        self.move(x, y)

    def apply_size(self, new_width, reload_frames=True):
        self.current_width = new_width
        new_height = int(new_width * (self.BASE_HEIGHT / self.BASE_WIDTH))
        self.setFixedSize(new_width, new_height)
        if reload_frames:
            self.load_all_animations()
            self.show_static("neutral")
        self.repaint()

    def set_size(self, new_width):
        self.apply_size(new_width)

    def set_anim_speed(self, speed):
        self.anim_speed = speed
        if self.anim_timer:
            self.anim_timer.setInterval(speed)

    def reload_animations(self):
        self.load_all_animations()
        self.show_static(self.current_anim)

    def get_animation_names(self):
        return list(self.animations.keys())

    def has_animation(self, name):
        return name in self.animations and len(self.animations[name]) > 1

    def load_all_animations(self):
        """Загружает все анимации из папки frames."""
        base = config.FRAMES_DIR
        try:
            from character_manager import character_frames_dir
            base = str(character_frames_dir())
        except Exception:
            base = config.FRAMES_DIR
        print(f"🖼️ кадры: {base}")
        sig = (
            base,
            int(self.current_width),
            tuple(self.enabled_emotions) if self.enabled_emotions else None,
        )
        if self._frames_sig == sig and self.static_frames:
            return
        self._frames_sig = sig
        if not os.path.exists(base):
            os.makedirs(base)
            return

        target_w = int(self.current_width * 0.95)
        target_h = int(self.height() * 0.95)

        self.animations = {}
        self.static_frames = {}

        try:
            from splash import current as _boot
        except Exception:
            _boot = None

        _IMG_EXT = ('.png', '.jpg', '.jpeg', '.webp')
        n_jobs = 0
        for folder, _dirs, files in os.walk(base):
            _dirs[:] = [d for d in _dirs if not d.startswith('.')]
            names = set()
            for f in files:
                if f.lower().endswith(_IMG_EXT):
                    names.add(os.path.splitext(f)[0])
            n_jobs += len(names)
        if _boot and n_jobs:
            _boot.begin_jobs(n_jobs, "кадры", (25, 92))

        for folder, _dirs, files in os.walk(base):
            _dirs[:] = [d for d in _dirs if not d.startswith('.')]
            emotion_files = {}
            for f in files:
                if not f.lower().endswith(_IMG_EXT):
                    continue
                base_name = os.path.splitext(f)[0]
                base_name = re.sub(r'_(sprite|strip)_\d+(x\d+)?', '', base_name, flags=re.I)
                # WAS Image Save: happy#1 / happy_1 / happy1
                base_name = re.sub(r'[#_]?0*\d+$', '', base_name)
                if base_name not in emotion_files:
                    emotion_files[base_name] = []
                emotion_files[base_name].append(f)
            
            for emotion, file_list in emotion_files.items():
                if self.enabled_emotions is not None and emotion not in self.enabled_emotions:
                    continue
                if emotion in self.static_frames or emotion in self.animations:
                    continue
                
                frames = []
                static_frames = []
                
                sprite_files = [f for f in file_list if '_sprite' in f or '_strip' in f]
                static_files = [f for f in file_list if '_sprite' not in f and '_strip' not in f]
                
                for sf in sprite_files[:1]:
                    sprite_path = os.path.join(folder, sf)
                    pix = QtGui.QPixmap(sprite_path)
                    if pix.isNull():
                        continue
                    
                    base_name = os.path.splitext(sf)[0]
                    grid_match = re.search(r'_(\d+)x(\d+)$', base_name)
                    if grid_match:
                        cols = int(grid_match.group(1))
                        rows = int(grid_match.group(2))
                        frame_w = pix.width() // cols
                        frame_h = pix.height() // rows
                        for row in range(rows):
                            for col in range(cols):
                                frame = pix.copy(col * frame_w, row * frame_h, frame_w, frame_h)
                                if not frame.isNull():
                                    scaled = frame.scaled(target_w, target_h,
                                                          QtCore.Qt.KeepAspectRatio,
                                                          QtCore.Qt.SmoothTransformation)
                                    frames.append(scaled)
                    else:
                        match = re.search(r'_(\d+)$', base_name)
                        if match:
                            frame_count = int(match.group(1))
                        else:
                            frame_h = pix.height()
                            if frame_h == 0:
                                frame_count = 1
                            else:
                                frame_count = pix.width() // frame_h
                                if frame_count < 1:
                                    frame_count = 1
                        frame_h = pix.height()
                        frame_w = pix.width() // frame_count
                        for i in range(frame_count):
                            frame = pix.copy(i * frame_w, 0, frame_w, frame_h)
                            if not frame.isNull():
                                scaled = frame.scaled(target_w, target_h,
                                                      QtCore.Qt.KeepAspectRatio,
                                                      QtCore.Qt.SmoothTransformation)
                                frames.append(scaled)
                    break
                
                for sf in static_files[:1]:
                    img_path = os.path.join(folder, sf)
                    pix = QtGui.QPixmap(img_path)
                    if not pix.isNull():
                        pix = pix.scaled(target_w, target_h,
                                         QtCore.Qt.KeepAspectRatio,
                                         QtCore.Qt.SmoothTransformation)
                        static_frames.append(pix)
                
                if frames:
                    self.animations[emotion] = frames
                    print(f"✅ Загружена анимация: {emotion} ({len(frames)} кадров)")
                if static_frames:
                    self.static_frames[emotion] = static_frames[0]
                    print(f"✅ Загружена статика: {emotion}")
                if _boot:
                    _boot.tick(emotion)

        if not self.static_frames:
            dummy = QtGui.QPixmap(target_w, target_h)
            dummy.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(dummy)
            painter.setPen(QtCore.Qt.white)
            painter.drawText(dummy.rect(), QtCore.Qt.AlignCenter, "Добавьте кадры\nв папки frames/")
            painter.end()
            self.static_frames["neutral"] = dummy
            self.animations["neutral"] = [dummy]
            print("⚠️ Загружена заглушка")
        else:
            print(f"✅ Всего загружено: {len(self.static_frames)} статик, {len(self.animations)} анимаций")

    def show_static(self, name="neutral"):
        self.is_animating = False
        self.current_anim = name

        if self.anim_timer:
            self.anim_timer.stop()
            self.anim_timer = None

        pix = None
        if name in self.static_frames:
            pix = self.static_frames[name]
        else:
            keys = list(self.static_frames.keys())
            low = (name or "").lower()
            for k in keys:
                if k.lower().startswith(low) or low in k.lower():
                    pix = self.static_frames[k]
                    break
            
            if pix is None and keys:
                for prefer in ("neutral", "idle", "thinking"):
                    if prefer in self.static_frames:
                        pix = self.static_frames[prefer]
                        break
                if pix is None:
                    pix = self.static_frames[keys[0]]

        if pix is not None:
            self.label.setPixmap(pix)
            self.repaint()

    def play_animation(self, name, on_finished=None, loop=True):
        """Запускает спрайт-анимацию."""
        print(f"🎬 Запуск анимации: {name} (loop={loop})")

        _nsfw_set = getattr(EmotionalAnalyzer, "NSFW_EMOTIONS", None) or getattr(config, "NSFW_EMOTIONS", [])
        _is_nsfw = name in _nsfw_set or any(name.startswith(b + "_") for b in _nsfw_set)
        if _is_nsfw:
            if not getattr(config, "NSFW_ENABLED", True):
                print(f"🔞 NSFW отключено, заменяем {name} на neutral")
                name = "neutral"

        if self.enabled_emotions is not None and name not in self.enabled_emotions:
            fallback = self._find_closest_emotion(name)
            if fallback and fallback in self.animations:
                name = fallback
                print(f"🔄 Fallback на: {name}")
            else:
                name = "neutral"
                print(f"🔄 Fallback на neutral")

        if name not in self.animations or not self.animations[name]:
            self.load_all_animations()
            if name not in self.animations or not self.animations[name]:
                self.show_static(name)
                return False

        frames = self.animations[name]
        if not frames:
            self.show_static(name)
            return False

        if self.anim_timer:
            self.anim_timer.stop()
            self.anim_timer = None

        self.is_animating = True
        self.current_anim = name
        self.current_frame_idx = 0
        self._anim_loop = loop
        self.anim_finished_callback = on_finished

        self.label.setPixmap(frames[0])
        self.repaint()

        if len(frames) > 1:
            self.anim_timer = QtCore.QTimer()
            self.anim_timer.timeout.connect(self._animate_frame)
            self.anim_timer.start(self.anim_speed)
        else:
            self.is_animating = False
            if on_finished:
                on_finished()

        return True

    def _find_closest_emotion(self, name):
        if not self.enabled_emotions:
            return None
        
        if name in self.enabled_emotions:
            return name
        
        for emotion in self.enabled_emotions:
            if name.startswith(emotion) or emotion.startswith(name):
                return emotion
        
        name_parts = set(name.split('_'))
        best_match = None
        best_score = 0
        
        for emotion in self.enabled_emotions:
            emotion_parts = set(emotion.split('_'))
            score = len(name_parts & emotion_parts)
            if score > best_score:
                best_score = score
                best_match = emotion
        
        return best_match if best_score > 0 else "neutral"

    def _animate_frame(self):
        frames = self.animations.get(self.current_anim, [])
        if not frames:
            self.show_static("neutral")
            return

        next_idx = self.current_frame_idx + 1

        if not getattr(self, "_anim_loop", True) and next_idx >= len(frames):
            self.current_frame_idx = len(frames) - 1
            self.label.setPixmap(frames[self.current_frame_idx])
            self.repaint()
            if self.anim_timer:
                self.anim_timer.stop()
                self.anim_timer = None
            self.is_animating = False
            if self.current_anim in self.static_frames:
                self.show_static(self.current_anim)
            if self.anim_finished_callback:
                cb = self.anim_finished_callback
                self.anim_finished_callback = None
                cb()
            return

        self.current_frame_idx = next_idx % len(frames)
        self.label.setPixmap(frames[self.current_frame_idx])
        self.repaint()

    def stop_animation(self):
        if self.anim_timer:
            self.anim_timer.stop()
            self.anim_timer = None
        self.is_animating = False
        self.show_static(self.current_anim)

    def set_animation(self, name, loop=True):
        if name in self.animations and len(self.animations[name]) > 1:
            self.play_animation(name, loop=loop)
        else:
            self.show_static(name)

    def start_animation(self):
        pass

    def animate(self):
        pass

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.drag_pos = event.globalPos()

    def mouseMoveEvent(self, event):
        if event.buttons() == QtCore.Qt.LeftButton and self.drag_pos is not None:
            delta = event.globalPos() - self.drag_pos
            self.move(self.pos() + delta)
            self.drag_pos = event.globalPos()

    def mouseReleaseEvent(self, event):
        self.drag_pos = None

