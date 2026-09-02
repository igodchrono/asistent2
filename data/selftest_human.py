# -*- coding: utf-8 -*-
"""Прогон как живой человек по текущему маршрутизатору.

  D:\\asistent\\python\\python.exe selftest_human.py
  ... --browser          открыть поиск/папки реально
  ... --llm              короткие фразы в API (если сервер жив)
  ... --rounds 2
  ... --pc-audio         реально mute/громче (иначе только parse)
  ... --quick            один укороченный круг
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LOG = os.path.join(os.path.dirname(__file__), "selftest_human.log")
PAUSE = 0.45


def log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def say(text: str):
    log("👤 " + text)


def _ok_server():
    try:
        from llm_server import ping
        return ping(1.2)
    except Exception:
        return False


def do_handle(text: str) -> str:
    """Текущий путь: parse_user → execute → flavor (как в ядре)."""
    say(text)
    try:
        from commands import handle_user, parse_user
        raw = handle_user(text)
        if raw is None:
            cmd = parse_user(text)
            log("🦊 skip-llm parse=%s" % (getattr(cmd, "kind", None),))
            time.sleep(0.15)
            return "skip-llm"
        log("🦊 " + str(raw).replace("\n", " | ")[:240])
        time.sleep(PAUSE)
        return raw
    except Exception as e:
        log("🦊 handle ERR " + str(e))
        return "ERR " + str(e)


def do_parse_only(text: str) -> str:
    say(text)
    try:
        from commands import parse_user
        cmd = parse_user(text)
        if cmd is None:
            log("🦊 parse=None (уйдёт в LLM)")
            return "none"
        extra = getattr(cmd, "target", None) or getattr(cmd, "extra", "")
        line = "parse %s / %s / anim=%s" % (cmd.kind, extra, cmd.anim)
        log("🦊 " + line)
        return line
    except Exception as e:
        log("🦊 parse ERR " + str(e))
        return str(e)


def do_look(text: str) -> str:
    say(text)
    try:
        from screen_watch import capture_jpeg, last_ocr_text, is_look_command
        if not is_look_command(text):
            log("🦊 не look")
            return "not-look"
        path = capture_jpeg(text=text)
        ocr = last_ocr_text() or ""
        res = "👁 %s | ocr %s симв." % (path, len(ocr))
        log("🦊 " + res)
        time.sleep(PAUSE)
        return res
    except Exception as e:
        log("🦊 look ERR " + str(e))
        return str(e)


def do_anim(user_text: str, reply: str = "") -> str:
    say(user_text)
    try:
        from animation_selector import AnimationSelector
        sel = AnimationSelector()
        name = sel.select(reply or user_text, user_text=user_text)
        if isinstance(name, (tuple, list)):
            name = name[0]
        res = "🎭 %s" % name
        log("🦊 " + res)
        return res
    except Exception as e:
        log("🦊 anim ERR " + str(e))
        return str(e)


def do_llm(text: str) -> str:
    say(text)
    if not _ok_server():
        log("🦊 LLM offline")
        return "offline"
    try:
        import asyncio
        import aiohttp
        import config

        async def _one():
            url = (getattr(config, "API_URL", "") or "").rstrip("/")
            if not url.endswith("/chat/completions"):
                url = url + "/chat/completions"
            model = getattr(config, "FAST_MODEL", None) or getattr(config, "MODEL_NAME", "")
            who = getattr(config, "ACTIVE_CHARACTER", "лисичка")
            card = ""
            try:
                from character_manager import build_character_prompt_block
                card = build_character_prompt_block(800) or ""
            except Exception:
                card = ""
            sys_p = (card + "\n" if card else "") + (
                "Ты персонаж %s. Коротко, 1-2 фразы по карточке. "
                "Не называй себя Qwen и не называй себя чужим именем."
            ) % who
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_p},
                    {"role": "user", "content": text},
                ],
                "max_tokens": 60,
                "temperature": 0.4,
            }
            timeout = aiohttp.ClientTimeout(total=25, sock_connect=3)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.post(url, json=payload) as r:
                    data = await r.json(content_type=None)
                    return ((data.get("choices") or [{}])[0].get("message", {}) or {}).get("content", "")[:180]

        out = asyncio.run(_one()) or ""
        log("🦊 LLM " + out.replace("\n", " ")[:180])
        return out
    except Exception as e:
        log("🦊 LLM ERR " + str(e))
        return str(e)


def block_settings():
    log("-- настройки --")
    do_handle("покажи настройки")
    do_handle("включи OCR")
    do_handle("включи просмотр экрана")
    do_handle("включи автопросмотр")
    do_handle("включи автосообщения")
    do_handle("включи llm привет")
    do_handle("поставь порог OCR 0.4")
    do_handle("смени монитор по умолчанию на средний")
    do_handle("включи интернет")
    do_parse_only("какая модель")
    try:
        import config
        config.ENABLE_AUTO_GREETING = True
        config.GREETING_USE_LLM = True
        config.SCREEN_VISION_ENABLED = True
        config.SCREEN_VISION_AUTO = True
        log("flags greet=%s greet_llm=%s vision=%s auto_screen=%s" % (
            config.ENABLE_AUTO_GREETING, config.GREETING_USE_LLM,
            config.SCREEN_VISION_ENABLED, config.SCREEN_VISION_AUTO,
        ))
    except Exception as e:
        log("flags ERR " + str(e))


def block_notes(n: int):
    log("-- блокнот / заметки --")
    do_handle("запиши круг %s проверка блокнота в блокнот" % n)
    time.sleep(0.3)
    do_handle("закрой блокнот")
    do_handle("открой блокнот")
    time.sleep(0.3)
    do_handle("закрой блокнот")


def block_apps(heavy: bool):
    log("-- окна --")
    do_handle("открой калькулятор")
    time.sleep(0.4)
    do_handle("закрой калькулятор")
    if heavy:
        do_handle("открой paint")
        time.sleep(0.3)
        do_handle("закрой paint")
        do_handle("открой папку загрузки")
        time.sleep(0.5)
        do_handle("закрой папку загрузки")
        do_handle("открой папку документы")
        time.sleep(0.4)
        do_handle("закрой папку документы")


def block_screen():
    log("-- экран --")
    do_handle("сделай скриншот среднего монитора")
    do_look("смотри на центральный монитор")
    do_look("смотри на левый монитор")
    do_look("смотри на правый монитор")
    do_look("что ты видешь на экране")
    do_handle("вставь текст с экрана в блокнот")
    time.sleep(0.3)
    do_handle("закрой блокнот")
    do_handle("скопируй текст с центрального монитора в блокнот")
    time.sleep(0.3)
    do_handle("закрой блокнот")


def block_search(browser: bool, n: int):
    log("-- поиск --")
    queries = [
        "найди кошек",
        "найди котиков",
        "найди хентай",
        "найди как платить налог",
        "можешь найти картинки лис",
        "нади картинки кошек",
    ]
    from commands import parse_user, execute
    for i, q in enumerate(queries):
        say(q)
        cmd = parse_user(q)
        if cmd is None:
            log("🦊 parse=None")
            continue
        log("🦊 parse %s / %s" % (cmd.kind, cmd.target))
        if browser and n == 1 and cmd.kind == "search":
            log("🦊 execute search")
            log("🦊 " + str(execute(cmd))[:200])
            time.sleep(1.1)


def block_anim():
    log("-- эмоции / темы --")
    phrases = [
        ("поплачь", ""),
        ("поспи", ""),
        ("я тебя люблю", ""),
        ("бесит", ""),
        ("найди котиков", ""),
        ("найди хентай", ""),
        ("найди как платить налог", ""),
        ("привет", "Хозяин, я тут"),
        ("устала", ""),
        ("танцуй", ""),
    ]
    for u, r in phrases:
        do_anim(u, r)


def block_pc(audio: bool):
    log("-- пк --")
    do_parse_only("выключи звук")
    do_parse_only("громче")
    do_parse_only("тише")
    do_parse_only("заблокируй пк")
    if audio:
        do_handle("громче")
        do_handle("тише")


def block_combo():
    """Связки, которые раньше ломались."""
    log("-- комбинации --")
    do_handle("включи автосообщения")
    do_look("смотри на центральный монитор")
    do_handle("вставь текст с экрана в блокнот")
    do_handle("закрой блокнот")
    do_handle("открой калькулятор")
    do_handle("запиши после калькулятора тест в блокнот")
    do_handle("закрой блокнот")
    do_handle("закрой калькулятор")
    do_parse_only("открой сайт google.com")
    do_parse_only("найди видео кошек")
    do_anim("найди котиков", "")
    do_handle("покажи настройки")


def block_offline():
    log("-- офлайн сервер --")
    try:
        from llm_server import ping, offline_reply, api_base
        ok = ping(1.0)
        log("🔌 %s %s" % (api_base(), "online" if ok else "offline"))
        if not ok:
            log("🦊 " + offline_reply())
    except Exception as e:
        log("🔌 " + str(e))


def switch_character(name: str):
    import config
    config.ACTIVE_CHARACTER = name
    try:
        from character_manager import apply_character_paths, apply_to_config
        apply_character_paths(name)
        apply_to_config()
    except Exception as e:
        log("смена персонажа pack ERR " + str(e))
    log("🎭 персонаж → %s  frames=%s  mem=%s" % (
        name,
        getattr(config, "FRAMES_DIR", ""),
        getattr(config, "PERSISTENT_MEMORY_DB", ""),
    ))


def round_n(n: int, rounds: int, browser: bool, llm: bool, audio: bool, quick: bool, who: str = ""):
    log("\n===== %s  КРУГ %s/%s =====" % (who or "?", n, rounds))
    block_settings()
    block_notes(n)
    block_apps(heavy=(not quick and n == 1))
    block_screen()
    block_search(browser, n)
    block_anim()
    block_pc(audio and n == 1)
    if not quick:
        block_combo()
    block_offline()
    if llm:
        do_llm("привет коротко")
        do_llm("как тебя зовут")


def main():
    args = sys.argv[1:]
    browser = "--browser" in args
    llm = "--llm" in args
    audio = "--pc-audio" in args
    quick = "--quick" in args
    per = 1 if quick else 2
    who1 = "лисичка"
    who2 = "мила"
    if "--rounds" in args:
        i = args.index("--rounds")
        if i + 1 < len(args):
            per = max(1, int(args[i + 1]))
    if "--char2" in args:
        i = args.index("--char2")
        if i + 1 < len(args):
            who2 = args[i + 1]
    if os.path.isfile(LOG):
        try:
            os.remove(LOG)
        except Exception:
            pass
    log("старт human-selftest per=%s %s -> %s browser=%s llm=%s" % (
        per, who1, who2, browser, llm
    ))
    import config
    log("PC=%s OCR=%s NET=%s model=%s" % (
        getattr(config, "ENABLE_PC_CONTROL", None),
        getattr(config, "SCREEN_OCR_ENABLED", None),
        getattr(config, "ENABLE_INTERNET", None),
        getattr(config, "MODEL_NAME", None),
    ))
    for who in (who1, who2):
        switch_character(who)
        for i in range(1, per + 1):
            try:
                round_n(i, per, browser, llm, audio, quick, who=who)
            except Exception as e:
                log("%s круг %s упал: %s" % (who, i, e))
    switch_character(who1)
    do_handle("покажи настройки")
    log("готово -> selftest_human.log")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
