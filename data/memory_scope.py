# memory_scope.py — общие факты vs память конкретного персонажа
from __future__ import annotations

from typing import List

import config


SHARED_USER_CATEGORIES = {
    "user", "profile", "имя", "name", "хозяин", "хобби", "интерес",
    "предпочтен", "факт", "fact", "city", "город",
}

SHARED_PC_CATEGORIES = {
    "app", "app_alias", "программа", "program", "софт", "приложение",
    "alias", "path", "путь", "диск", "pc", "project", "проект",
}


def active_character() -> str:
    name = (getattr(config, "ACTIVE_CHARACTER", None) or "лисичка").strip()
    return name or "лисичка"


def character_scope(name: str = None) -> str:
    return f"character:{(name or active_character())}"


def scope_for_category(category: str) -> str:
    cat = (category or "").strip().lower()
    if cat in SHARED_USER_CATEGORIES or cat.startswith("user") or cat.startswith("profile"):
        return "user"
    if cat in SHARED_PC_CATEGORIES or cat.startswith("app") or cat.startswith("project"):
        return "pc"
    return character_scope()


def prompt_scopes(name: str = None) -> List[str]:
    """Что подмешивать в промпт: общие слои + текущий персонаж + legacy global."""
    return ["user", "pc", "project", "global", character_scope(name)]
