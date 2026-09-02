# chat_panel.py — виджет чата (вынесен из gui.py)
"""
Отвечает за:
- отображение сообщений (user / assistant / system / reminder)
- безопасный HTML (escape + linkify)
- streaming-обновление ответа Лисички
- очистку команд и [ANIM] из видимого текста
"""

from __future__ import annotations

import re
import time
import html as _html
from typing import Optional, Callable

from PyQt5 import QtWidgets, QtGui, QtCore


class ChatPanel(QtWidgets.QWidget):
    """Панель чата: QTextBrowser + индикатор печати."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._html_before_stream: Optional[str] = None
        self._last_update_time: float = 0.0
        self._pending_text: str = ""
        self._last_early_anim: Optional[str] = None
        self._on_early_anim: Optional[Callable[[str], None]] = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.chat_display = QtWidgets.QTextBrowser()
        self.chat_display.setReadOnly(True)
        chat_font = QtGui.QFont()
        for family in ("Segoe UI", "Noto Sans", "DejaVu Sans", "Arial", "Sans Serif"):
            chat_font.setFamily(family)
            if QtGui.QFontInfo(chat_font).family():
                break
        chat_font.setPointSize(12)
        self.chat_display.setFont(chat_font)
        self.chat_display.setOpenExternalLinks(True)
        self.chat_display.setOpenLinks(True)
        self.chat_display.document().setDefaultFont(chat_font)
        self.chat_display.setStyleSheet(
            "QTextBrowser { background-color: #1a1d23; color: #e8e8e8; "
            "border: 1px solid #333; border-radius: 8px; padding: 8px; }"
        )
        layout.addWidget(self.chat_display)

        self.typing_indicator = QtWidgets.QLabel("🖊️ печатает...")
        self.typing_indicator.setStyleSheet("color: #888; font-style: italic;")
        self.typing_indicator.hide()
        layout.addWidget(self.typing_indicator)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def set_early_anim_callback(self, cb: Callable[[str], None]):
        """Вызывается при появлении [ANIM:…] во время стрима."""
        self._on_early_anim = cb

    def append_user(self, text: str):
        self.chat_display.append(self._format_user_html(text))
        self._scroll_bottom()

    def append_assistant(self, text: str):
        self.chat_display.append(self._format_assistant_html(text))
        self._scroll_bottom()

    def append_system(self, text: str, kind: str = "system"):
        self.chat_display.append(self._format_system_html(text, kind=kind))
        self._scroll_bottom()

    def append_raw_html(self, html: str):
        self.chat_display.append(html)
        self._scroll_bottom()

    def clear(self):
        self.chat_display.clear()
        self._html_before_stream = None
        self._pending_text = ""

    def show_typing(self, show: bool = True):
        if show:
            self.typing_indicator.show()
        else:
            self.typing_indicator.hide()

    def show_generation_placeholder(self):
        self.chat_display.append("🔄 Генерация...")
        self._scroll_bottom()

    def remove_generation_placeholder(self):
        doc = self.chat_display.document()
        cursor = QtGui.QTextCursor(doc)
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.movePosition(QtGui.QTextCursor.StartOfBlock, QtGui.QTextCursor.KeepAnchor)
        text = cursor.selectedText()
        if "Генерация..." in text or "🔄" in text:
            cursor.removeSelectedText()
            if not cursor.atStart():
                cursor.deletePreviousChar()

    # --- Streaming ---

    def begin_stream(self):
        self.remove_generation_placeholder()
        self._html_before_stream = self.chat_display.toHtml()
        self._last_update_time = 0.0
        self._pending_text = ""
        self._last_early_anim = None

    def update_stream(self, text: str, force: bool = False):
        if self._html_before_stream is None:
            return

        now = time.time()
        if not force and (now - self._last_update_time) < 0.12:
            self._pending_text = text
            self._try_early_anim(text)
            return

        self._last_update_time = now
        self._pending_text = ""

        scrollbar = self.chat_display.verticalScrollBar()
        was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 40

        assistant_html = self._format_assistant_html(text)
        self.chat_display.setHtml(self._html_before_stream + assistant_html)

        if was_at_bottom:
            scrollbar.setValue(scrollbar.maximum())

        self._try_early_anim(text)

    def finalize_stream(self, full_response: str) -> str:
        """Завершает стрим, возвращает очищенный текст (без команд)."""
        if self._pending_text and len(self._pending_text) >= len(full_response):
            full_response = self._pending_text

        self.update_stream(full_response, force=True)
        self._html_before_stream = None
        self._pending_text = ""
        self._scroll_bottom()
        return self.clean_assistant_text(full_response)

    def increase_font(self):
        font = self.chat_display.font()
        font.setPointSize(font.pointSize() + 1)
        self.chat_display.setFont(font)

    def decrease_font(self):
        font = self.chat_display.font()
        font.setPointSize(max(8, font.pointSize() - 1))
        self.chat_display.setFont(font)

    def anchor_clicked_connect(self, slot):
        self.chat_display.anchorClicked.connect(slot)

    # ------------------------------------------------------------------
    # Форматирование
    # ------------------------------------------------------------------

    @staticmethod
    def clean_assistant_text(reply: str) -> str:
        if not reply:
            return ""
        t = reply
        t = _html.unescape(t)
        t = re.sub(r"&\s*quot\s*;", '"', t, flags=re.I)
        t = re.sub(r"&\s*amp\s*;", "&", t, flags=re.I)
        t = re.sub(r"&\s*lt\s*;", "<", t, flags=re.I)
        t = re.sub(r"&\s*gt\s*;", ">", t, flags=re.I)
        t = re.sub(r"&\s*#\s*39\s*;", "'", t, flags=re.I)
        t = re.sub(r"&\s*apos\s*;", "'", t, flags=re.I)
        t = re.sub(r"&\s*nbsp\s*;", " ", t, flags=re.I)
        t = _html.unescape(t)

        t = re.sub(r"\[ANIM:\w+\]", "", t, flags=re.I)
        t = re.sub(
            r"\[(?:SEARCH|LAUNCH|OPEN|RUN|WRITE|NOTEPAD|MINIMIZE|MAXIMIZE|SWITCH|"
            r"CLOSE_WINDOW|CLOSE_TAB|CLOSE_ALL_TABS|WINDOWS|PROCESSES|KILL|SCREENSHOT|"
            r"DESKTOP|LOCK|SHUTDOWN|RESTART|VOLUME|VOLUME_UP|VOLUME_DOWN|MUTE|UNMUTE|"
            r"MONITOR_OFF|CLIPBOARD_GET|CLIPBOARD_SET|CLIPBOARD_APPEND|NOTE|REMINDER|"
            r"READ_SCREEN|SCREEN_ANALYSIS|DISK_SPACE|CREATE_FOLDER|COPY|MOVE|DELETE|"
            r"RENAME|EMPTY_RECYCLE|REMEMBER_ALIAS|ALIAS_LIST|ALIAS_DELETE|REMEMBER_APP)"
            r"\s*[^\]]*\]",
            "",
            t,
            flags=re.I,
        )
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()

    @staticmethod
    def _trim_url(url: str) -> str:
        if not url:
            return url
        while url and url[-1] in ".,;:!?…»\"'":
            url = url[:-1]
        while url and url[-1] in ")]}>":
            opener = {")": "(", "]": "[", "}": "{", ">": "<"}.get(url[-1])
            if opener and url.count(opener) >= url.count(url[-1]):
                break
            url = url[:-1]
        return url

    @staticmethod
    def _looks_like_url(s: str) -> bool:
        s = s.lower()
        if s.startswith(("http://", "https://", "www.")):
            return True
        return bool(
            re.match(
                r"^[a-z0-9]([a-z0-9\-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)+(/|\?|#|$)",
                s,
                re.I,
            )
        )

    def _safe_linkify(self, plain: str) -> str:
        if not plain:
            return ""
        placeholders = []

        def put_link(href: str, label: str) -> str:
            href = self._trim_url(href)
            if href.lower().startswith("www."):
                href = "https://" + href
            href_safe = _html.escape(href, quote=True)
            label_safe = _html.escape(label)
            idx = len(placeholders)
            placeholders.append(
                f'<a href="{href_safe}" '
                f'style="color:#6cb6ff;text-decoration:underline;" '
                f'title="{href_safe}">{label_safe}</a>'
            )
            return f"\x00PH{idx}\x00"

        md_re = re.compile(
            r"\[([^\]]{1,200})\]\(\s*(https?://[^\s\)]+|www\.[^\s\)]+)\s*\)", re.I
        )
        work = md_re.sub(lambda m: put_link(m.group(2), m.group(1)), plain)

        url_re = re.compile(r"(?P<url>(?:https?://|www\.)[^\s<>'\"\\]+)", re.I)

        def url_repl(m):
            raw = self._trim_url(m.group("url"))
            if not self._looks_like_url(raw):
                return m.group(0)
            return put_link(raw, raw)

        work = url_re.sub(url_repl, work)

        parts = re.split(r"(\x00PH\d+\x00)", work)
        out = []
        for p in parts:
            mm = re.match(r"\x00PH(\d+)\x00", p)
            if mm:
                out.append(placeholders[int(mm.group(1))])
            else:
                out.append(_html.escape(p))
        return "".join(out)

    @staticmethod
    def _who() -> str:
        try:
            import config
            from character_manager import character_display_name
            return character_display_name()
        except Exception:
            try:
                import config
                return str(getattr(config, "ACTIVE_CHARACTER", "персонаж") or "персонаж")
            except Exception:
                return "персонаж"

    def _format_assistant_html(self, text: str) -> str:
        clean = self.clean_assistant_text(text) or "✨"
        body = self._safe_linkify(clean).replace("\n", "<br>")
        return (
            '<div style="margin:8px 0; padding:10px 12px; background:#3a3228; '
            "border-left:4px solid #e8a54b; border-radius:8px; color:#f5e6c8; "
            'line-height:1.5; font-size:14px;">'
            f'<div style="color:#e8a54b; font-weight:600; margin-bottom:6px;">{self._who()}</div>'
            f"<div>{body}</div></div>"
        )

    def _format_user_html(self, text: str) -> str:
        body = self._safe_linkify(text or "").replace("\n", "<br>")
        return (
            '<div style="margin:8px 0; padding:10px 12px; background:#2a3340; '
            "border-left:4px solid #5b9fd4; border-radius:8px; color:#e8eef5; "
            'line-height:1.5; font-size:14px;">'
            '<div style="color:#5b9fd4; font-weight:600; margin-bottom:6px;">👤 Вы</div>'
            f"<div>{body}</div></div>"
        )

    def _format_system_html(self, text: str, kind: str = "system") -> str:
        body = self._safe_linkify(text or "").replace("\n", "<br>")
        if kind == "reminder":
            color, title, bg = "#f0c14b", "⏰ Напоминание", "#3a3820"
        else:
            color, title, bg = "#ff6b6b", "⚠️ Система", "#3a2a2a"
        return (
            f'<div style="margin:6px 0; padding:8px 10px; background:{bg}; '
            f'border-left:3px solid {color}; border-radius:6px; color:#ddd; font-size:13px;">'
            f'<b style="color:{color};">{title}:</b> {body}</div>'
        )

    def _try_early_anim(self, text: str):
        match = re.search(r"\[ANIM:(\w+)\]", text or "", re.IGNORECASE)
        if not match:
            return
        anim = match.group(1).lower()
        if self._last_early_anim == anim:
            return
        self._last_early_anim = anim
        if self._on_early_anim:
            try:
                self._on_early_anim(anim)
            except Exception:
                pass

    def _scroll_bottom(self):
        scrollbar = self.chat_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
