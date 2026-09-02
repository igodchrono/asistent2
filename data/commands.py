# commands.py — один вход для блокнота / браузера / ПК
# Ядро не исполняет эти фразы само. Сюда же можно слать теги из LLM.
from __future__ import annotations

import logging
import os
import re
import subprocess
import webbrowser
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus

import config

logger = logging.getLogger(__name__)

APPS = {
    "блокнот": "notepad.exe",
    "блакнот": "notepad.exe",
    "notepad": "notepad.exe",
    "калькулятор": "calc.exe",
    "калкулятор": "calc.exe",
    "проводник": "explorer.exe",
    "explorer": "explorer.exe",
    "диспетчер задач": "taskmgr.exe",
    "диспетчер задачь": "taskmgr.exe",
    "диспетчер": "taskmgr.exe",
    "таскменеджер": "taskmgr.exe",
    "taskmgr": "taskmgr.exe",
    "task manager": "taskmgr.exe",
    "cmd": "cmd.exe",
    "командная строка": "cmd.exe",
    "powershell": "powershell.exe",
    "paint": "mspaint.exe",
    "паинт": "mspaint.exe",
    "рисунок": "mspaint.exe",
}

# русские имена → то, что Windows часто понимает через start
NAME_ALIAS = {
    "телеграм": "telegram",
    "telegram": "telegram",
    "стим": "steam",
    "steam": "steam",
    "касперский": "kaspersky",
    "kaspersky": "kaspersky",
    "хром": "chrome",
    "chrome": "chrome",
    "дискорд": "discord",
    "discord": "discord",
    "вайбер": "viber",
    "ворд": "winword",
    "excel": "excel",
    "эксель": "excel",
}

URI_APPS = {
    "настройки виндус": "ms-settings:",
    "настройки виндовс": "ms-settings:",
    "настройки windows": "ms-settings:",
    "настройки": "ms-settings:",
    "параметры": "ms-settings:",
}

SKIP_TARGETS = frozenset({
    "его", "её", "ее", "это", "то", "вот", "их", "ту", "тот",
})


def _user_home() -> str:
    return os.path.expanduser("~")


def _first_existing(*paths) -> Optional[str]:
    for p in paths:
        if p and os.path.isdir(p):
            return p
    return None


def folder_path(name: str) -> Optional[str]:
    home = _user_home()
    key = (name or "").lower().strip()
    table = {
        "загрузки": (getattr(config, "DOWNLOADS_DIR", ""), "Downloads", "Загрузки"),
        "downloads": (getattr(config, "DOWNLOADS_DIR", ""), "Downloads", "Загрузки"),
        "документы": ("Documents", "Документы"),
        "documents": ("Documents", "Документы"),
        "рабочий стол": ("Desktop", "Рабочий стол"),
        "desktop": ("Desktop", "Рабочий стол"),
        "картинки": ("Pictures", "Изображения", "Картинки"),
        "изображения": ("Pictures", "Изображения"),
        "скриншоты": (
            getattr(config, "SCREENSHOTS_DIR", ""),
            os.path.join("Pictures", "Screenshots"),
            os.path.join("Изображения", "Снимки экрана"),
        ),
        "загрузки лисички": (getattr(config, "DOWNLOADS_DIR", ""),),
        "файлы лисички": (getattr(config, "FILES_DIR", ""),),
        "заметки": (getattr(config, "NOTES_DIR", ""),),
        "сохранения": ("Documents", "Документы", "Saved Games"),
        "видео": ("Videos", "Видео"),
        "музыка": ("Music", "Музыка"),
    }
    names = table.get(key)
    if not names:
        return None
    cands = []
    for n in names:
        cands.append(n if os.path.isabs(n) else os.path.join(home, n))
    return _first_existing(*cands) or cands[0]


def normalize_target(s: str) -> str:
    t = (s or "").strip().lower()
    t = t.replace("ё", "е")
    t = re.sub(r"\s+", " ", t)
    t = t.replace("виндус", "windows").replace("виндовс", "windows")
    t = t.replace("задачь", "задач")
    return t

_PREFIX = (
    r"(?i)^\s*(?:(?:лисичка|лис[ая]|мила|раиса|мороз|шип|"
    r"пожалуйста|плиз|слушай|послушай|слышь|ну)[,\s]+)*"
)
SEARCH_START = re.compile(
    _PREFIX + r"(?:найд[иуёе]?|нади|поищи|поиск|загугли|погугли|google|гугл)\s+"
)
OPEN_START = re.compile(
    _PREFIX + r"(?:открой|открыть|запусти|запуск)\s+"
)
SITE_HINT = re.compile(r"(?i)(сайт|вкладк|браузер|гугл|яндекс|youtube|ютуб|http)")
IMG_HINT = re.compile(r"(?i)(картин|кортин|фото|изображен|\bpic\b|\bimage)")


@dataclass
class Cmd:
    kind: str  # notepad | launch | search | pc
    target: str = ""
    extra: str = ""
    anim: str = "pointing"


def _strip_tail(s: str) -> str:
    s = (s or "").strip(" \t.!?…,")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _clean_search_query(q: str) -> str:
    """Убрать служебные «в интернете/в гугле» и хвосты действий из поискового запроса."""
    s = _strip_tail(q or "")
    if not s:
        return ""
    patterns = [
        r"(?i)^(?:пожалуйста|плиз|пожалуйсто)[,\s]+",
        r"(?i)^(?:мне|мне\s+нужно|нужно|надо)[,\s]+",
        r"(?i)^(?:в\s+интернете|в\s+сети|в\s+гугле|в\s+google|в\s+яндексе|в\s+web|в\s+вебе|"
        r"через\s+гугл|через\s+google|онлайн|в\s+поисковике)\s+",
        r"(?i)\s+(?:в\s+интернете|в\s+сети|в\s+гугле|в\s+google|онлайн)\s*$",
        r"(?i)^(?:информацию\s+о|инфу\s+о|про|о)\s+",
        # хвосты составных команд: не должны попадать в Google
        r"(?i)\s*(?:и\s+)?(?:потом\s+)?(?:сделай|сделать|сними|снять|сохрани)?\s*"
        r"(?:скриншот|скрин|screenshot).*$",
        r"(?i)\s*(?:и\s+)?(?:потом\s+)?(?:проанализир\w*|разбер\w*|прочитай|прочти|опиши)\s*"
        r"(?:текст|экран|содержимое|что\s+там)?.*$",
        r"(?i)\s*(?:и\s+)?(?:открой|открыть|запусти).*$",
    ]
    prev = None
    while prev != s:
        prev = s
        for pat in patterns:
            s = re.sub(pat, "", s).strip()
        s = _strip_tail(s)
    # «книгу про X» → «книга про X» чуть естественнее для поиска
    s = re.sub(r"(?i)^книгу\s+", "книга ", s)
    s = re.sub(r"(?i)^книжки\s+", "книга ", s)
    return s




def parse_user(text: str) -> Optional[Cmd]:
    """Только явные фразы хозяина. Сомнительное → None (пусть идёт в LLM)."""
    t = (text or "").strip()
    if not t or len(t) > 400:
        return None

    try:
        from chat_settings import try_chat_setting
        st = try_chat_setting(t)
        if st:
            return Cmd("setting", st, anim="pointing")
    except Exception:
        pass

    if re.search(r"(?i)^\s*(сделай|сними|сохрани)\s+(скрин|скриншот)", t) or re.fullmatch(
        r"(?i)\s*скриншот\s*", t
    ):
        return Cmd("screenshot", extra=t, anim="pointing")

    mclose = re.match(
        r"(?i)^\s*(?:лисичка|лис[ая])?[,\s]*(закрой|закрыть|выключи окно)\s+(.+)$",
        t,
    )
    if mclose:
        tgt = normalize_target(_strip_tail(mclose.group(2)))
        if tgt and tgt not in SKIP_TARGETS:
            return Cmd("close", tgt, anim="pointing")

    # Явный текст: «запиши купить молоко в блокнот»
    m_write = re.search(
        r"(?i)(?:запиши|заметка|сохрани(?:\s+заметк[уа])?)\s+"
        r"(?:в\s+блокнот\s+)?(?:мне\s+)?(?:текст\s+)?"
        r"[:«\"']?\s*(.+)$",
        t,
    )
    from_screen = bool(re.search(
        r"(?i)(с экрана|с монитора|что видишь|этот текст|ocr|скопируй)",
        t,
    ))
    paste_only = bool(re.search(
        r"(?i)(встав\w*|скопир\w*).{0,40}блокнот|блокнот.{0,30}(встав|текст с экрана)",
        t,
    ))
    if m_write:
        rest = m_write.group(1).strip(" .!?,«»\"'")
        rest = re.sub(r"(?i)\s+в\s+блокнот\s*$", "", rest).strip()
        if rest and not from_screen and rest.lower() not in (
            "текст", "это", "то", "всё", "все", "сюда",
        ):
            return Cmd("note", rest, extra=t, anim="pointing")
    if paste_only or from_screen and re.search(r"(?i)блокнот", t):
        return Cmd("note", "__SCREEN_OCR__", extra=t, anim="pointing")

    mnote = re.match(
        r"(?i)^\s*(запиши(?:\s+в\s+блокнот)?|заметка|сохрани\s+заметк[уа])\s*[:\-]?\s*(.+)$",
        t,
    )
    if mnote and mnote.group(2).strip():
        rest = mnote.group(2).strip()
        if re.search(r"(?i)(с экрана|что видишь|этот текст|с монитора)", rest):
            rest = "__SCREEN_OCR__"
        return Cmd("note", rest, anim="pointing")

    m = OPEN_START.match(t)
    if m:
        rest = _strip_tail(t[m.end():])
        if not rest:
            return None
        key = normalize_target(rest)
        if key in SKIP_TARGETS:
            return None
        if SITE_HINT.search(rest) or rest.startswith("http"):
            return Cmd("search", rest, anim="searching")
        if key.startswith("папк") or "папку" in key:
            rest2 = re.sub(r"^папк[уие]\s+(со?\s+)?", "", key).strip()
            if folder_path(rest2) or rest2 in ("скриншот", "скриншотом", "скринами"):
                return Cmd("folder", "скриншоты" if "скрин" in rest2 else rest2, anim="pointing")
        if folder_path(key) or key in ("загрузки", "документы", "рабочий стол", "скриншоты", "сохранения"):
            return Cmd("folder", key, anim="pointing")
        if key in URI_APPS:
            return Cmd("uri", key, anim="pointing")
        if key in APPS or key in ("блокнот", "блакнот", "notepad"):
            return Cmd(
                "notepad" if any(x in key for x in ("блокнот", "notepad", "блакнот")) else "launch",
                key,
                anim="pointing",
            )
        if IMG_HINT.search(rest):
            return Cmd("search", rest, anim="searching")
        if len(rest.split()) <= 4 and not SEARCH_START.match(t):
            return Cmd("launch", key, anim="pointing")
        return None

    # «открой/найди книгу про X» → поиск книги (нет локального файла)
    m_book = re.search(
        r"(?i)(?:открой|открыть|найд[иуёе]?|нади|поищи)\s+(?:мне\s+)?(?:книгу|книга|pdf)\s+(?:про|по|о)?\s*(.+)$",
        t,
    )
    if m_book:
        rest = _clean_search_query(m_book.group(1))
        if rest:
            q = rest if re.search(r"(?i)книг", rest) else f"книга {rest}"
            q = _clean_search_query(q)
            print(f"[DEBUG] parse BOOK SEARCH -> {q!r}", flush=True)
            return Cmd("search", q, anim="searching")

    m = SEARCH_START.match(t)
    if m:
        rest = _clean_search_query(t[m.end():])
        if not rest or rest.lower() in ("это", "то", "вот"):
            return None
        print(f"[DEBUG] parse SEARCH -> {rest!r}", flush=True)
        return Cmd("search", rest, anim="searching")

    msoft = re.search(
        r"(?i)(?:можешь|сможешь)\s+(?:пожалуйста\s+)?(?:найти|поискать|нади|погуглить)\s+(.+)$",
        t,
    )
    if msoft:
        rest = _clean_search_query(msoft.group(1))
        if rest and rest.lower() not in ("это", "то", "вот"):
            return Cmd("search", rest, anim="searching")

    if IMG_HINT.search(t) and re.search(r"(?i)(найд|нади|поищ|покажи|скинь|гугл)", t):
        if not re.search(r"(?i)настройк|экран|монитор", t):
            q = re.sub(
                r"(?i)^\s*(?:лисичка|мила|раиса|пожалуйста|плиз|слушай)[,\s]+",
                "",
                t,
            )
            q = re.sub(
                r"(?i)(найд[иуёе]?|нади|поищи|покажи|скинь|погугли|загугли)\s+",
                "",
                q,
                count=1,
            )
            q = _clean_search_query(q)
            if q and len(q) >= 2:
                return Cmd("search", q, anim="searching")

    # Погода / «какая погода» / «погода в X»
    m_w = re.search(
        r"(?i)(?:какая\s+)?погод[аеуы]?\s*(?:сегодня|сейчас|завтра)?\s*(?:в\s+|для\s+)?(.+)?$",
        t,
    )
    if re.search(r"(?i)\bпогод", t) and not re.search(r"(?i)настройк|экран", t):
        place = ""
        m_place = re.search(
            r"(?i)погод\w*\s*(?:сегодня|сейчас|завтра)?\s*(?:в\s+|для\s+|по\s+)?(.+)$",
            t,
        )
        if m_place and m_place.group(1):
            place = _clean_search_query(m_place.group(1))
            place = re.sub(r"(?i)^(сегодня|сейчас|завтра)\s*", "", place).strip()
        if place:
            if not re.match(r"(?i)^(в|во|для|по)\s", place):
                place = f"в {place}"
            q = f"погода {place}"
        else:
            q = "погода сегодня"
        q = _clean_search_query(q)
        print(f"[DEBUG] parse WEATHER -> {q!r}", flush=True)
        return Cmd("search", q, anim="searching")

    # «дай посмотрим X», «посмотрим X», «покажи про X» (не экран)
    m_look = re.search(
        r"(?i)(?:дай\s+)?(?:посмотрим|глянем|глянуть|посмотреть|посмотри)\s+(.+)$",
        t,
    )
    if m_look and not re.search(r"(?i)экран|монитор|окно", t):
        rest = _clean_search_query(m_look.group(1))
        if rest and len(rest) >= 2:
            print(f"[DEBUG] parse LOOKUP -> {rest!r}", flush=True)
            return Cmd("search", rest, anim="searching")

    m_show = re.search(
        r"(?i)(?:покажи|скинь|найди\s+инфу|информация\s+о)\s+(.+)$",
        t,
    )
    if m_show and not re.search(r"(?i)экран|монитор|настройк|окно", t):
        rest = _clean_search_query(m_show.group(1))
        if rest and len(rest) >= 2 and not IMG_HINT.search(t):
            # «покажи картинки» already handled; plain «покажи X» = search
            print(f"[DEBUG] parse SHOW -> {rest!r}", flush=True)
            return Cmd("search", rest, anim="searching")

    low = t.lower()
    if re.search(r"(?i)(выключи|выключить)\s+(звук|музон)", low):
        return Cmd("pc", "mute", anim="pointing")
    if re.search(r"(?i)(громче|прибавь\s+звук)", low):
        return Cmd("pc", "vol_up", anim="pointing")
    if re.search(r"(?i)(тише|убавь\s+звук)", low):
        return Cmd("pc", "vol_down", anim="pointing")
    if re.fullmatch(r"(?i)\s*(заблокируй\s+(пк|комп|компьютер)|lock\s+pc)\s*", t):
        return Cmd("pc", "lock", anim="pointing")
    return None


def _pc_ok() -> bool:
    return bool(getattr(config, "ENABLE_PC_CONTROL", True))


def _net_ok() -> bool:
    return bool(getattr(config, "ENABLE_INTERNET", True))


def _open_app(exe_or_name: str) -> str:
    if not _pc_ok():
        return "⛔ Управление ПК выключено"
    key = (exe_or_name or "").strip().lower()
    exe = APPS.get(key, exe_or_name)
    try:
        if exe.lower().endswith(".exe") and os.path.sep not in exe:
            subprocess.Popen(
                ["cmd", "/c", "start", "", exe],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
            return f"📂 {exe}"
        subprocess.Popen(
            exe if os.path.sep in exe else ["cmd", "/c", "start", "", exe],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        return f"📂 {exe_or_name}"
    except Exception as e:
        logger.error("launch: %s", e)
        return f"❌ Не открылось: {exe_or_name}"


def _open_notepad() -> str:
    if not _pc_ok():
        return "⛔ Управление ПК выключено"
    try:
        from system_controller import SystemController
        if hasattr(SystemController, "open_notepad_with_text"):
            return SystemController.open_notepad_with_text("")
    except Exception:
        pass
    return _open_app("notepad.exe")


def _search_urls(q: str):
    intent = "images" if IMG_HINT.search(q or "") else "web"
    if re.search(r"(?i)(видео|youtube|ютуб)", q or ""):
        intent = "video"
    engine = (getattr(config, "SEARCH_ENGINE", "google") or "google").lower()
    enc = quote_plus(q)
    if intent == "images":
        if engine == "yandex":
            search = f"https://yandex.ru/images/search?text={enc}"
        elif engine == "bing":
            search = f"https://www.bing.com/images/search?q={enc}"
        else:
            search = f"https://www.google.com/search?tbm=isch&q={enc}"
    elif intent == "video":
        search = f"https://www.youtube.com/results?search_query={enc}"
    elif engine == "yandex":
        search = f"https://yandex.ru/search/?text={enc}"
    elif engine == "bing":
        search = f"https://www.bing.com/search?q={enc}"
    else:
        search = f"https://www.google.com/search?q={enc}"
    return intent, search



def _normalize_url_key(url: str) -> str:
    u = (url or "").strip().lower()
    u = u.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    if u.startswith("https://"):
        u = u[8:]
    elif u.startswith("http://"):
        u = u[7:]
    if u.startswith("www."):
        u = u[4:]
    return u


def _is_url_blocked(url: str) -> bool:
    """True если в памяти помечено «не открывать» эту ссылку."""
    try:
        from persistent_memory import PersistentMemory
        import config as _cfg
        from memory_scope import prompt_scopes
        pm = PersistentMemory(getattr(_cfg, "PERSISTENT_MEMORY_DB", "persistent_memory.db"))
        try:
            key = _normalize_url_key(url)
            if not key:
                return False
            rows = pm.list_all(scope=None, category=None, limit=500)
            for r in rows:
                cat = (r.get("category") or "").lower()
                if cat not in ("blocked_url", "no_open", "ссылка", "link", "url"):
                    # также ищем value с флагом no_open
                    val = (r.get("value") or "").lower()
                    if "no_open" not in val and "не откры" not in val and "blocked" not in val:
                        continue
                val = (r.get("value") or "")
                k = (r.get("key") or "")
                blob = f"{k} {val}".lower()
                nk = _normalize_url_key(val) or _normalize_url_key(k)
                if nk and (nk in key or key in nk):
                    return True
                if key and key in blob:
                    return True
            return False
        finally:
            try:
                pm.close()
            except Exception:
                pass
    except Exception as e:
        logger.debug("block url check: %s", e)
        return False

def _open_url(url: str) -> bool:
    path = (getattr(config, "BROWSER_PATH", "") or "").strip()
    try:
        if path and os.path.isfile(path):
            subprocess.Popen([path, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except Exception:
        pass
    try:
        webbrowser.open_new_tab(url)
        return True
    except Exception as e:
        logger.warning("browser: %s", e)
        return False



def _score_result(title: str, snippet: str, query: str) -> float:
    q_words = [w for w in re.findall(r"\w+", (query or "").lower()) if len(w) > 2]
    if not q_words:
        return 0.0
    blob = f"{title or ''} {snippet or ''}".lower()
    hit = sum(1 for w in q_words if w in blob)
    score = hit / max(len(q_words), 1)
    # бонус за pdf/книгу если в запросе книга
    if re.search(r"(?i)книг|pdf|учебник|гидравлик", query or ""):
        if re.search(r"(?i)pdf|book|книга|учебник|lib|archive\.org|pdfdrive", blob):
            score += 0.35
        if re.search(r"(?i)\.pdf\b", blob):
            score += 0.25
    # штраф за мусор
    if re.search(r"(?i)(login|sign in|cookie|captcha|advert)", blob):
        score -= 0.3
    return score


def _fetch_ddg_results(q: str, limit: int = 8) -> list:
    """Парсинг HTML DuckDuckGo (без API-ключа)."""
    import requests
    from html import unescape
    results = []
    try:
        url = "https://html.duckduckgo.com/html/"
        r = requests.post(
            url,
            data={"q": q},
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
            timeout=12,
        )
        r.raise_for_status()
        html = r.text
        # result blocks
        blocks = re.findall(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
            r'.*?class="result__snippet"[^>]*>(.*?)</(?:a|td|div)',
            html,
            flags=re.I | re.S,
        )
        if not blocks:
            # fallback: только ссылки result__a
            blocks = [
                (href, title, "")
                for href, title in re.findall(
                    r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                    html,
                    flags=re.I | re.S,
                )
            ]
        for href, title, snip in blocks:
            href = unescape(href.strip())
            # DDG redirect: //duckduckgo.com/l/?uddg=...
            m = re.search(r"[?&]uddg=([^&]+)", href)
            if m:
                from urllib.parse import unquote
                href = unquote(m.group(1))
            if not href.startswith("http"):
                continue
            if "duckduckgo.com" in href and "uddg" not in href:
                continue
            title = re.sub(r"<[^>]+>", "", unescape(title)).strip()
            snip = re.sub(r"<[^>]+>", "", unescape(snip)).strip()
            results.append({"url": href, "title": title, "snippet": snip})
            if len(results) >= limit:
                break
    except Exception as e:
        logger.warning("ddg fetch: %s", e)
    return results


def _pick_best_result(q: str, results: list) -> dict | None:
    if not results:
        return None
    ranked = sorted(
        results,
        key=lambda r: _score_result(r.get("title", ""), r.get("snippet", ""), q),
        reverse=True,
    )
    best = ranked[0]
    score = _score_result(best.get("title", ""), best.get("snippet", ""), q)
    print(
        f"[DEBUG] best result score={score:.2f} title={best.get('title')!r} url={best.get('url')!r}",
        flush=True,
    )
    # если всё совсем мимо — всё равно берём первый из выдачи
    return best


def _search_open_best(q: str, search_page_url: str, intent: str) -> str:
    """1) вкладка поиска  2) лучший результат второй вкладкой."""
    open_search = bool(getattr(config, "SEARCH_OPEN_BROWSER", True))
    open_best = bool(getattr(config, "SEARCH_OPEN_BEST_RESULT", True))
    # картинки/видео — только страница поиска
    if intent in ("images", "video"):
        opened = _open_url(search_page_url) if open_search else False
        if intent == "images":
            return f"🔍 Поиск картинок: {q}" if opened else f"🔍 {search_page_url}"
        return f"🔍 Поиск видео: {q}" if opened else f"🔍 {search_page_url}"

    opened_search = False
    if open_search:
        opened_search = _open_url(search_page_url)

    best_line = ""
    if open_best and intent == "web":
        results = _fetch_ddg_results(q, limit=8)
        print(f"[DEBUG] ddg results: {len(results)}", flush=True)
        best = _pick_best_result(q, results)
        if best and best.get("url"):
            # не открывать тот же URL что страница поиска
            if best["url"].rstrip("/") != search_page_url.rstrip("/"):
                ok = _open_url(best["url"])
                title = (best.get("title") or "")[:80]
                if ok:
                    best_line = f" · лучшее: {title or best['url']}"
                else:
                    best_line = f" · не открылось: {best['url']}"
            else:
                best_line = " · лучший = страница поиска"
        else:
            best_line = " · подходящая ссылка не найдена"

    if opened_search:
        return f"🔍 Поиск: {q}{best_line}"
    return f"🔍 {search_page_url}{best_line}"

def _search(q: str) -> str:
    if not _net_ok():
        return "🌐 Поиск выключен"
    q = _clean_search_query(q or "")
    print(f"[DEBUG] search query -> {q!r}", flush=True)
    if len(q) < 2:
        return "⚠️ Пустой поиск"
    # Прямая ссылка, которую просили не открывать
    if q.startswith("http://") or q.startswith("https://"):
        if _is_url_blocked(q):
            return f"🔗 Ссылка в памяти как «не открывать»: {q}"
        opened = _open_url(q) if getattr(config, "SEARCH_OPEN_BROWSER", True) else False
        return f"🔗 {q}" if opened else f"🔗 (не открыто) {q}"
    intent, url = _search_urls(q)
    if _is_url_blocked(url):
        return f"🔗 Не открываю (запомнено): {url}"
    return _search_open_best(q, url, intent)


def _pc(action: str) -> str:
    if not _pc_ok():
        return "⛔ Управление ПК выключено"
    if action == "lock":
        if getattr(config, "SAFE_MODE", True):
            return "🔒 Блокировка только с подтверждением"
        try:
            subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
            return "🔒 Экран заблокирован"
        except Exception as e:
            return f"❌ lock: {e}"
    try:
        import pyautogui
        if action == "mute":
            pyautogui.press("volumemute")
            return "🔇 Звук"
        if action == "vol_up":
            pyautogui.press("volumeup", presses=3)
            return "🔊 Громче"
        if action == "vol_down":
            pyautogui.press("volumedown", presses=3)
            return "🔉 Тише"
    except Exception as e:
        logger.error("pc: %s", e)
        return f"❌ ПК: {e}"
    return "⚠️ Неизвестная ПК-команда"


def _open_folder(name: str) -> str:
    path = folder_path(name) or folder_path(normalize_target(name))
    if not path:
        return f"❌ Папка «{name}» не найдена"
    try:
        subprocess.Popen(["explorer.exe", path])
        return f"📂 {path}"
    except Exception as e:
        return f"❌ Папка: {e}"


def _open_uri(key: str) -> str:
    uri = URI_APPS.get(normalize_target(key), key)
    try:
        os.startfile(uri)  # type: ignore[attr-defined]
        return f"⚙️ {uri}"
    except Exception:
        try:
            subprocess.Popen(["cmd", "/c", "start", "", uri], shell=False)
            return f"⚙️ {uri}"
        except Exception as e:
            return f"❌ {e}"


CLOSE_PROCS = {
    "браузер": ["chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"],
    "хром": ["chrome.exe"],
    "chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "firefox": ["firefox.exe"],
    "блокнот": ["notepad.exe"],
    "калькулятор": [
        "CalculatorApp.exe", "calculator.exe", "calc.exe",
        "win32calc.exe",
    ],
    "диспетчер задач": ["taskmgr.exe"],
    "диспетчер": ["taskmgr.exe"],
    "телеграм": ["telegram.exe"],
    "telegram": ["telegram.exe"],
    "стим": ["steam.exe"],
    "steam": ["steam.exe"],
    "дискорд": ["discord.exe"],
}


_PROTECTED = frozenset({
    "python.exe", "pythonw.exe", "dwm.exe", "csrss.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "smss.exe", "system", "idle",
})


def _running_images() -> list:
    try:
        r = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return []
    out = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith('"'):
            continue
        name = line.split(",", 1)[0].strip('"')
        if name:
            out.append(name)
    return out


def _images_for_query(name: str) -> list:
    key = normalize_target(name)
    ordered = []
    seen = set()

    def add(exe: str):
        e = (exe or "").strip()
        if not e:
            return
        if not e.lower().endswith(".exe"):
            e = e + ".exe"
        low = e.lower()
        if low in seen or low in _PROTECTED:
            return
        seen.add(low)
        ordered.append(e)

    for exe in CLOSE_PROCS.get(key, []):
        add(exe)
    if key in APPS:
        add(APPS[key])
    if key in NAME_ALIAS:
        add(NAME_ALIAS[key])
    add(key)

    q = key.replace(".exe", "")
    alias = (NAME_ALIAS.get(key, "") or "").replace(".exe", "")
    for img in _running_images():
        low = img.lower()
        stem = low[:-4] if low.endswith(".exe") else low
        if q and (q in stem or stem in q):
            add(img)
        elif alias and alias in stem:
            add(img)
    return ordered


def _close_explorer_folder(hint: str) -> str:
    """Закрыть окно папки, не убивая проводник Windows."""
    hint = (hint or "").lower()
    titles = []
    if re.search(r"загруз", hint):
        titles += ["downloads", "Загрузки", "загрузки"]
    if re.search(r"документ", hint):
        titles += ["Documents", "Документы"]
    if re.search(r"рабоч", hint):
        titles += ["Desktop", "Рабочий стол"]
    if not titles:
        titles = [hint.strip()[:40]] if hint.strip() else []
    closed = []
    ps = (
        "$sh = New-Object -ComObject Shell.Application; "
        "$want = @({want}); "
        "foreach ($w in @($sh.Windows())) {{ "
        "  try {{ $t = [string]$w.LocationName + ' ' + [string]$w.LocationURL; "
        "    foreach ($k in $want) {{ if ($t -like ('*'+$k+'*')) {{ $w.Quit(); }} }} "
        "  }} catch {{}} }}"
    ).format(want=",".join("'{0}'".format(x.replace("'", "")) for x in titles if x))
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=12,
        )
        if r.returncode == 0:
            closed.append("окно папки")
    except Exception:
        pass
    if closed:
        return "❎ Закрыто: " + ", ".join(closed)
    return "❌ Окно папки не закрылось: " + (hint or "?")


def _close_app(name: str) -> str:
    if not _pc_ok():
        return "⛔ Управление ПК выключено"
    if re.search(r"(?i)(папк|загруз|download|проводник|explorer)", name or ""):
        return _close_explorer_folder(name)
    procs = _images_for_query(name)
    if not procs:
        return f"❌ Не поняла, что закрыть: {name}"
    killed = []
    for exe in procs:
        if exe.lower() in _PROTECTED:
            continue
        try:
            r = subprocess.run(
                ["taskkill", "/IM", exe, "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if r.returncode == 0:
                killed.append(exe)
        except Exception:
            continue
    if not killed and re.search(r"(?i)калькул|calc", name or ""):
        for title in ("Калькулятор", "Calculator"):
            try:
                r = subprocess.run(
                    ["taskkill", "/F", "/FI", f"WINDOWTITLE eq {title}*"],
                    capture_output=True, text=True, timeout=8,
                )
                if r.returncode == 0 and "PID" in (r.stdout or "").upper():
                    killed.append(title)
            except Exception:
                pass
    if killed:
        return "❎ Закрыто: " + ", ".join(dict.fromkeys(killed))
    return "❌ Не закрылось (нет такого процесса): " + ", ".join(procs[:6])


def execute(cmd: Cmd) -> str:
    print(f"[DEBUG] execute kind={cmd.kind!r} target={getattr(cmd, 'target', None)!r}", flush=True)
    if cmd.kind == "setting":
        return cmd.target
    if cmd.kind == "close":
        return _close_app(cmd.target)
    if cmd.kind == "screenshot":
        try:
            from files_box import save_screenshot
            path = save_screenshot(cmd.extra or "")
            return f"📸 Скриншот: {path}"
        except Exception as e:
            return f"❌ Скрин: {e}"
    if cmd.kind == "note":
        try:
            from files_box import save_note
            body = cmd.target or ""
            if body in ("__SCREEN_OCR__", "__OCR__", "экран") or re.search(
                r"(?i)^(текст с экрана|с монитора|что видишь)$", body
            ):
                try:
                    from screen_watch import (
                        last_ocr_text, ocr_image, capture_jpeg,
                        ocr_via_vl, _ocr_usable,
                    )
                    cap = capture_jpeg(text=cmd.extra or "средний монитор")
                    body = ""
                    err = ""
                    if cap:
                        try:
                            body = ocr_via_vl(cap)
                        except Exception as e:
                            err = str(e)
                            body = ""
                    if body and not _ocr_usable(body):
                        body = ""
                    try:
                        lab = os.path.join(
                            getattr(__import__("config"), "DATA_DIR", "."),
                            "cache", "screen_last.txt",
                        )
                        with open(lab, encoding="utf-8") as f:
                            where = f.read().strip()
                        if where and body:
                            body = f"[снято: {where}]\n\n{body}"
                    except Exception:
                        pass
                except Exception as e:
                    body, err = "", str(e)
                if not body:
                    body = (
                        "VL не прочитала экран. "
                        + (err or "проверь что 8B загружена и автосообщения выключены")
                    )
            path = save_note(body)
            try:
                subprocess.Popen(["notepad.exe", path])
            except Exception:
                pass
            return f"📝 Заметка: {path}"
        except Exception as e:
            return f"❌ Заметка: {e}"
    if cmd.kind == "notepad":
        return _open_notepad()
    if cmd.kind == "folder":
        return _open_folder(cmd.target)
    if cmd.kind == "uri":
        return _open_uri(cmd.target)
    if cmd.kind == "launch":
        key = normalize_target(cmd.target)
        if "блокнот" in key or "notepad" in key or "блакнот" in key:
            return _open_notepad()
        if key in APPS:
            return _open_app(APPS[key])
        if key in URI_APPS:
            return _open_uri(key)
        if key in NAME_ALIAS:
            return _open_app(NAME_ALIAS[key])
        return _open_app(cmd.target)
    if cmd.kind == "search":
        return _search(cmd.target)
    if cmd.kind == "pc":
        return _pc(cmd.target)
    return ""


def execute_tag(cmd_type: str, params=None) -> Optional[str]:
    """Тег от LLM / executor. None = пусть делает старый executor (алиасы, confirm)."""
    t = (cmd_type or "").upper().strip()
    if t == "SEARCH":
        q = params if isinstance(params, str) else str((params or {}).get("query") or params or "")
        q = q.strip()
        if len(q) < 2:
            return "⚠️ Пустой поиск"
        return execute(Cmd("search", q))
    if t == "NOTEPAD":
        return execute(Cmd("notepad", "блокнот"))
    if t in ("LAUNCH", "OPEN"):
        name = params if isinstance(params, str) else str(params or "")
        name = name.strip()
        if not name:
            return None
        key = name.lower()
        if key in APPS or "блокнот" in key or "notepad" in key or "блакнот" in key:
            return execute(Cmd("launch", name))
        if name.startswith("http"):
            return execute(Cmd("search", name))
        return None
    if t == "MUTE":
        return execute(Cmd("pc", "mute"))
    if t == "VOLUME_UP":
        return execute(Cmd("pc", "vol_up"))
    if t == "VOLUME_DOWN":
        return execute(Cmd("pc", "vol_down"))
    if t == "LOCK":
        return execute(Cmd("pc", "lock"))
    return None


def needs_scanner(cmd: Cmd) -> bool:
    """Не системный ярлык / папка / uri — искать через AppScanner."""
    if not cmd or cmd.kind != "launch":
        return False
    key = normalize_target(cmd.target)
    if key in APPS or key in NAME_ALIAS or key in URI_APPS:
        return False
    if "блокнот" in key or "notepad" in key:
        return False
    return True


def try_local(user_text: str) -> Optional[str]:
    """Если фраза — явная команда, вернуть '[ANIM:…] текст' и не звать LLM."""
    return handle_user(user_text)


def _who() -> str:
    return str(getattr(config, "ACTIVE_CHARACTER", "лисичка") or "лисичка").lower()


def flavor(kind: str, result: str = "") -> str:
    """1 фраза персонажа после команды. Без LLM."""
    who = _who()
    table = {
        "лисичка": {
            "search": "Ищу, хозяин.",
            "launch": "Открыла.",
            "notepad": "Блокнот открыла.",
            "folder": "Папку открыла.",
            "close": "Закрыла.",
            "note": "Записала.",
            "screenshot": "Сняла экран.",
            "pc": "Готово.",
            "setting": "Настройку поменяла.",
            "uri": "Открыла.",
        },
        "мила": {
            "search": "ок, ищу.",
            "launch": "открыла.",
            "notepad": "блокнот есть.",
            "folder": "папка открыта.",
            "close": "закрыла.",
            "note": "записала.",
            "screenshot": "сняла.",
            "pc": "ок.",
            "setting": "поменяла.",
            "uri": "открыла.",
        },
        "раиса": {
            "search": "Сейчас посмотрим, внучек.",
            "launch": "Открыла тебе.",
            "notepad": "Блокнот на столе.",
            "folder": "Папочку открыла.",
            "close": "Закрыла.",
            "note": "Записала, не потеряется.",
            "screenshot": "Снимок сделала.",
            "pc": "Сделано.",
            "setting": "Настроила.",
            "uri": "Открыла.",
        },
    }
    generic = {
        "search": "Ищу.",
        "launch": "Открыла.",
        "notepad": "Блокнот.",
        "folder": "Папка.",
        "close": "Закрыла.",
        "note": "Записала.",
        "screenshot": "Скрин.",
        "pc": "Готово.",
        "setting": "Настройка.",
        "uri": "Открыла.",
    }
    lines = table.get(who) or generic
    line = lines.get(kind) or lines.get("pc") or "Готово."
    if result and result.startswith("⛔"):
        return result
    if result and result.startswith("❌"):
        return result
    return line


def handle_user(user_text: str) -> Optional[str]:
    """
    Явная команда: исполнить один раз и вернуть короткую реплику.
    None → не команда, можно в LLM.
    """
    cmd = parse_user(user_text)
    if not cmd:
        return None
    result = execute(cmd)
    if not result:
        return None
    line = flavor(cmd.kind, result)
    anim = cmd.anim or "pointing"
    if result in (line, ""):
        return f"[ANIM:{anim}] {line}"
    if line in result:
        return f"[ANIM:{anim}] {result}"
    return f"[ANIM:{anim}] {line}\n{result}"
