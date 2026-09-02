# -*- coding: utf-8 -*-
"""Пинг LM Studio / OpenAI-совместимого сервера. Никогда не валит запуск."""
from __future__ import annotations

import time
import urllib.request
import urllib.error

import config

_last = {"ok": None, "t": 0.0}


def api_base() -> str:
    return (getattr(config, "API_URL", "") or "").rstrip("/")


def ping(timeout: float = None) -> bool:
    """True если /models отвечает. Короткий таймаут. Результат кэшируется 8 сек."""
    timeout = float(timeout if timeout is not None else getattr(config, "LLM_PING_TIMEOUT", 1.5))
    now = time.monotonic()
    if _last["ok"] is not None and (now - _last["t"]) < 8:
        return bool(_last["ok"])
    url = api_base()
    if not url:
        _last.update(ok=False, t=now)
        return False
    try:
        req = urllib.request.Request(
            url + "/models",
            headers={"Authorization": f"Bearer {getattr(config, 'API_KEY', 'not-needed')}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ok = 200 <= getattr(r, "status", 200) < 500
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        ok = False
    except Exception:
        ok = False
    _last.update(ok=ok, t=now)
    return ok


def invalidate():
    _last.update(ok=None, t=0.0)


def offline_reply() -> str:
    who = str(getattr(config, "ACTIVE_CHARACTER", "") or "лисичка").strip().lower()
    host = api_base() or "сервер LLM"
    lines = {
        "мила": f"[ANIM:pouting] сервер выкл. команды работают, болтать нечем пока не включишь {host}",
        "раиса": f"[ANIM:tired] Внучек, мозги у меня сегодня выключены ({host}). Окна и поиск — могу. Поболтаем, когда сервер запустишь.",
    }
    return lines.get(who, f"[ANIM:thinking] Сервер ИИ не запущен ({host}). "
                     "Окна, блокнот, поиск и настройки работают. "
                     "Включи LM Studio — и я снова буду болтать.")
