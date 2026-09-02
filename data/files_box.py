# files_box.py — папка Лисички: скрины, заметки, загрузки
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import config


def root() -> str:
    return getattr(config, "FILES_DIR", os.path.join(config.DATA_DIR, "files"))


def screenshots() -> str:
    return getattr(config, "SCREENSHOTS_DIR", os.path.join(root(), "screenshots"))


def downloads() -> str:
    return getattr(config, "DOWNLOADS_DIR", os.path.join(root(), "downloads"))


def notes_dir() -> str:
    return getattr(config, "NOTES_DIR", os.path.join(root(), "notes"))


def documents() -> str:
    return getattr(config, "DOCUMENTS_DIR", os.path.join(root(), "documents"))


def ensure() -> None:
    for p in (root(), screenshots(), downloads(), notes_dir(), documents()):
        os.makedirs(p, exist_ok=True)


def _stamp(ext: str) -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ext


def save_note(text: str, title: str = "") -> str:
    ensure()
    text = (text or "").strip()
    if not text:
        raise ValueError("пустая заметка")
    name = (title or "note").strip()
    name = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in name)[:40] or "note"
    path = os.path.join(notes_dir(), f"{name}_{_stamp('.txt')}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + ("\n" if not text.endswith("\n") else ""))
    return path


def save_screenshot(text: str = "") -> str:
    """PNG выбранного монитора. text — «центрального», «левый» и т.д."""
    ensure()
    from PIL import Image
    import io
    try:
        from screen_watch import resolve_monitor, _grab_region
        mon, _label = resolve_monitor(text or "")
        raw = _grab_region(mon, max_side=4096)
        if raw:
            img = Image.open(io.BytesIO(raw))
            path = os.path.join(screenshots(), _stamp(".png"))
            img.save(path, "PNG")
            return path
    except Exception:
        pass
    from PIL import ImageGrab
    try:
        img = ImageGrab.grab(all_screens=True)
    except TypeError:
        img = ImageGrab.grab()
    path = os.path.join(screenshots(), _stamp(".png"))
    img.save(path, "PNG")
    return path


def list_recent(folder: str, limit: int = 8) -> list:
    if not folder or not os.path.isdir(folder):
        return []
    rows = []
    try:
        names = os.listdir(folder)
    except Exception:
        return []
    for name in names:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        try:
            rows.append((os.path.getmtime(path), name, path))
        except Exception:
            continue
    rows.sort(reverse=True)
    return rows[:limit]


def prompt_block(limit: int = 6) -> str:
    ensure()
    parts = ["Файлы ассистента (ссылайся по имени, не выдумывай другие):"]
    groups = (
        ("скриншоты", screenshots()),
        ("загрузки", downloads()),
        ("заметки", notes_dir()),
        ("документы", documents()),
    )
    any_file = False
    for title, folder in groups:
        items = list_recent(folder, limit)
        if not items:
            parts.append(f"- {title}: пусто")
            continue
        any_file = True
        parts.append(f"- {title}: " + ", ".join(name for _, name, _ in items))
        if title == "заметки":
            for _, name, path in items[:2]:
                try:
                    with open(path, encoding="utf-8") as f:
                        snippet = f.read(180).replace("\n", " ").strip()
                    if snippet:
                        parts.append(f"  · {name}: {snippet}")
                except Exception:
                    pass
    if not any_file:
        parts.append("(пока пусто — не говори, что файлы уже есть)")
    return "\n".join(parts)
