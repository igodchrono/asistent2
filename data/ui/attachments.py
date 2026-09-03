# ui/attachments.py — вложения и полноэкранный просмотр
from __future__ import annotations

import os
import re
import base64

from PyQt5 import QtWidgets, QtGui, QtCore


class AttachmentMixin:
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

        if ext in (".png", ".jpg", ".jpeg", ".bmp", ".gif"):
            self.insert_image_preview(file_path)
        else:
            try:
                content = self.assistant.read_file_content(file_path, max_chars=500)
                preview = content[:500] + ("..." if len(content) > 500 else "")
                file_icon = "📄"
                if ext == ".pdf":
                    file_icon = "📕"
                elif ext in (".docx", ".doc"):
                    file_icon = "📘"
                elif ext in (".xlsx", ".xls"):
                    file_icon = "📊"
                elif ext == ".pptx":
                    file_icon = "📙"
                self.chat_display.append(
                    f"{file_icon} Файл прикреплён: {os.path.basename(file_path)} (тип: {ext})\n```\n{preview}\n```"
                )
                scrollbar = self.chat_display.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
            except Exception as e:
                self.chat_display.append(f"❌ Не удалось прочитать файл: {e}")

    def insert_image_preview(self, file_path):
        with open(file_path, "rb") as f:
            data = f.read()
        b64 = base64.b64encode(data).decode("utf-8")
        if file_path.lower().endswith(".png"):
            mime = "image/png"
        elif file_path.lower().endswith((".jpg", ".jpeg")):
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
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
        )
        window.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        label = QtWidgets.QLabel(window)
        pix = QtGui.QPixmap(file_path)
        screen = QtWidgets.QApplication.primaryScreen().size()
        pix = pix.scaled(
            screen.width(),
            screen.height(),
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
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
