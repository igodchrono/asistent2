# notes_manager.py
from __future__ import annotations

import os
import re
import threading
from datetime import datetime
from typing import List, Tuple

DEFAULT_NOTES_FILE = "notes.md"


class NotesManager:
    def __init__(self, path: str | None = None):
        self.path = path or DEFAULT_NOTES_FILE
        self.lock = threading.Lock()
        if not os.path.isfile(self.path):
            with open(self.path, "w", encoding="utf-8") as f:
                f.write("# Заметки Лисички\n\n")

    def add(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return "Пустая заметка."
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        line = f"- [{stamp}] {text}\n"
        with self.lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line)
        return f"Заметка сохранена: {text[:80]}"

    def list_notes(self, limit: int = 30) -> str:
        with self.lock:
            if not os.path.isfile(self.path):
                return "Заметок нет."
            with open(self.path, "r", encoding="utf-8") as f:
                lines = [ln.rstrip() for ln in f if ln.strip().startswith("- ")]
        if not lines:
            return "Заметок пока нет."
        return "Заметки:\n" + "\n".join(lines[-limit:])

    def search(self, query: str, limit: int = 15) -> str:
        q = (query or "").strip().lower()
        if not q:
            return self.list_notes(limit)
        with self.lock:
            with open(self.path, "r", encoding="utf-8") as f:
                lines = [ln.rstrip() for ln in f if ln.strip().startswith("- ")]
        hits = [ln for ln in lines if q in ln.lower()]
        if not hits:
            return f"По «{query}» ничего не найдено."
        return "Найдено:\n" + "\n".join(hits[-limit:])

    def clear(self, confirm: bool = False) -> str:
        if not confirm:
            return "Нужно подтверждение: [NOTE CLEAR confirm]"
        with self.lock:
            with open(self.path, "w", encoding="utf-8") as f:
                f.write("# Заметки Лисички\n\n")
        return "Все заметки очищены."