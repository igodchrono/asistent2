# -*- coding: utf-8 -*-
"""Текст для TTS: только реплика персонажа, без сцены и символов."""
from __future__ import annotations
import re
import html as _html

_CMD = re.compile(
    r"\[(?:ANIM|SCENE|SEARCH|LAUNCH|OPEN|RUN|WRITE|NOTEPAD|MINIMIZE|MAXIMIZE|SWITCH|"
    r"CLOSE_WINDOW|CLOSE_TAB|CLOSE_ALL_TABS|WINDOWS|PROCESSES|KILL|SCREENSHOT|"
    r"DESKTOP|LOCK|SHUTDOWN|RESTART|VOLUME|VOLUME_UP|VOLUME_DOWN|MUTE|UNMUTE|"
    r"MONITOR_OFF|CLIPBOARD_GET|CLIPBOARD_SET|CLIPBOARD_APPEND|NOTE|REMINDER|"
    r"READ_SCREEN|SCREEN_ANALYSIS|DISK_SPACE|CREATE_FOLDER|COPY|MOVE|DELETE|"
    r"RENAME|EMPTY_RECYCLE|REMEMBER_ALIAS|ALIAS_LIST|ALIAS_DELETE|REMEMBER_APP|"
    r"СИСТЕМА|SYSTEM)[^\]]*\]",
    re.I,
)
_STAGE = re.compile(r"\*[^*]{1,240}\*")
_PAREN = re.compile(r"\([^)]{0,160}\)")
_MD_HEAD = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
_URL = re.compile(r"https?://\S+", re.I)
_SYS_LINE = re.compile(
    r"(?i)^\s*("
    r"\[снято:|📝|📸|📂|❎|⚙️|🔍|👁|✅|❌|⛔|🦊\s*конфиг|"
    r"заметка:|скриншот:|поиск:|закрыто:|настройки:|"
    r"вкладк|кнопк|часы:|панел[ьи]|видимые элементы|"
    r"верхняя панель|нижняя панель|адресная строка"
    r")"
)
_ENV_START = re.compile(
    r"(?i)^\s*("
    r"на (центральном|среднем|левом|правом|экране|мониторе)|"
    r"вот что я вижу|"
    r"открыт (браузер|чат|проводник|калькулятор)|"
    r"текст, который ты"
    r")"
)


def for_speech(text: str) -> str:
    if not text:
        return ""
    t = _html.unescape(str(text))
    t = _CMD.sub(" ", t)
    t = re.sub(r"\[снято:[^\]]*\]", " ", t)
    t = _STAGE.sub(" ", t)
    t = _PAREN.sub(" ", t)
    t = _URL.sub(" ", t)
    t = _MD_HEAD.sub("", t)
    t = t.replace("**", " ").replace("__", " ").replace("```", " ")
    t = t.replace(">", " ").replace("#", " ")

    kept = []
    for raw in t.splitlines():
        line = raw.strip(" \t-•*")
        if not line:
            continue
        if _SYS_LINE.search(line):
            continue
        if _ENV_START.search(line):
            continue
        if re.match(r"(?i)^(youtube|google|gmail|chrome|диск \()", line):
            continue
        kept.append(line)

    t = " ".join(kept)
    t = re.sub(r"[\[\]{}<>|=~^]", " ", t)
    t = re.sub(r"[🦊🐱💕😏😉😊😢😡❤️🎭📸📝📂🔍👁✅❌⛔⚙️❎✨🌙💧💋🎨🐾💖]+", " ", t)
    t = re.sub(r"[^\w\s.,!?;:—…\-а-яА-ЯёЁa-zA-Z0-9]", " ", t, flags=re.U)
    t = re.sub(r"\s+", " ", t).strip(" .,;:-")
    if len(t) < 2:
        return ""
    return t
