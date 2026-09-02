# -*- coding: utf-8 -*-
"""Чат и persistent — короткая реплика. Система и OCR — в лог."""
from __future__ import annotations

import os
import re
from datetime import datetime

_SYS = re.compile(
    r"(?i)(\[система\]|\[снято:|vl не прочитала|ocr |"
    r"заметка:\s*[a-z]:\\|скриншот:\s*[a-z]:\\|https?://|"
    r"видимые элементы|адресная строка|верхняя панель)"
)
_CMD = re.compile(
    r"\[(?:ANIM|SCENE|SEARCH|LAUNCH|OPEN|RUN|NOTE|NOTEPAD|REMEMBER[^\]]*|"
    r"СИСТЕМА|SYSTEM)[^\]]*\]",
    re.I,
)


def is_system_or_ocr(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if _SYS.search(t):
        return True
    if t.startswith(("📝", "📸", "📂", "❎", "🔍", "👁", "⚙️", "✅", "❌", "⛔")):
        return True
    if "[снято:" in t.lower():
        return True
    if t.count("\n") > 6 or len(t) > 500:
        return True
    return False


def clean_reply(text: str, limit: int = 180) -> str:
    """Короткая реплика для истории и persistent."""
    if not text:
        return ""
    t = _CMD.sub(" ", text)
    t = re.sub(r"\[снято:[^\]]*\]", " ", t)
    t = re.sub(r"^\[СИСТЕМА\].*$", "", t, flags=re.I | re.M)
    t = re.sub(r"(?i)поиск в интернете…?", "", t)
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"(?m)^#{1,3}\s+.*$", "", t)
    t = re.sub(r"(?m)^>\s*", "", t)
    kept = []
    for line in t.splitlines():
        s = line.strip(" \t-•*")
        if not s:
            continue
        if is_system_or_ocr(s):
            continue
        if re.match(r"(?i)^(youtube|google|gmail|chrome)\b", s):
            continue
        kept.append(s)
    t = " ".join(kept)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip() + "…"
    return t


def log_system(kind: str, text: str, data_dir: str = "") -> None:
    """Система и OCR — отдельный файл, не в чат-память."""
    raw = (text or "").strip()
    if not raw:
        return
    try:
        import config
        root = data_dir or getattr(config, "DATA_DIR", ".") or "."
    except Exception:
        root = data_dir or "."
    path = os.path.join(root, "logs", "system.log")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = raw.replace("\n", " | ")[:800]
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} [{kind}] {line}\n")
    except Exception:
        pass
