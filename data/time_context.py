# time_context.py — локальные часы Windows / системы
from __future__ import annotations

from datetime import datetime
from typing import Optional


def now_local() -> datetime:
    return datetime.now()


def format_clock(dt: Optional[datetime] = None) -> str:
    dt = dt or now_local()
    weekdays = (
        "понедельник", "вторник", "среда", "четверг",
        "пятница", "суббота", "воскресенье",
    )
    return f"{dt.strftime('%H:%M')}, {weekdays[dt.weekday()]}"


def time_bucket(dt: Optional[datetime] = None) -> str:
    h = (dt or now_local()).hour
    if 0 <= h < 6:
        return "night"
    if 6 <= h < 11:
        return "morning"
    if 11 <= h < 18:
        return "day"
    if 18 <= h < 23:
        return "evening"
    return "late"


def time_label(bucket: Optional[str] = None) -> str:
    return {
        "night": "глубокая ночь",
        "morning": "утро",
        "day": "день",
        "evening": "вечер",
        "late": "поздно вечером",
    }.get(bucket or time_bucket(), "день")


def default_self_mood(bucket: Optional[str] = None) -> str:
    return {
        "night": "sleepy",
        "morning": "neutral",
        "day": "neutral",
        "evening": "playful",
        "late": "sleepy",
    }.get(bucket or time_bucket(), "neutral")


def default_anim(bucket: Optional[str] = None) -> str:
    return {
        "night": "sleepy",
        "morning": "idle",
        "day": "neutral",
        "evening": "idle_sly",
        "late": "sleepy",
    }.get(bucket or time_bucket(), "neutral")


def greeting_interval_factor(bucket: Optional[str] = None) -> float:
    return {
        "night": 2.6,
        "late": 1.8,
        "morning": 1.2,
        "day": 1.0,
        "evening": 0.9,
    }.get(bucket or time_bucket(), 1.0)


def get_greeting_hint() -> str:
    b = time_bucket()
    return {
        "night": "Сейчас ночь — говори тихо и коротко, без энергичности.",
        "morning": "Утро — мягко, без давления.",
        "day": "Обычный день.",
        "evening": "Вечер — можно чуть живее.",
        "late": "Поздно — не шуми, не обижайся громко.",
    }.get(b, "")


def get_time_prompt_addon() -> str:
    b = time_bucket()
    return (
        f"Сейчас на часах ПК: {format_clock()} ({time_label(b)}). "
        f"{get_greeting_hint()}"
    )
