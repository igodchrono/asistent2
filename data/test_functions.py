# test_functions.py — быстрая проверка команд / экрана / истории
# Запуск:
#   D:\asistent\python\python.exe D:\asistent\data\test_functions.py
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ok = 0
bad = 0


def check(name: str, cond, got=None):
    global ok, bad
    if cond:
        ok += 1
        print(f"  OK  {name}")
    else:
        bad += 1
        extra = f"  → {got!r}" if got is not None else ""
        print(f"  FAIL {name}{extra}")


def test_commands():
    print("\n=== commands ===")
    from commands import parse_user

    c = parse_user("открой блокнот")
    check("блокнот → notepad", c and c.kind == "notepad", c)

    c = parse_user("открой блакнот")
    check("опечатка блакнот → notepad", c and c.kind == "notepad", c)

    c = parse_user("найди кошек")
    check("найди кошек → search", c and c.kind == "search" and "кош" in c.target, c)

    c = parse_user("открой блокнот в гугле")
    check("блокнот в гугле не search-ловушка или launch", c is None or c.kind in ("notepad", "search"), c)

    c = parse_user("найди картинки кошек")
    check("картинки → search", c and c.kind == "search", c)

    c = parse_user("я тебя люблю")
    check("любовь не команда", c is None, c)

    c = parse_user("посмотри на экран")
    check("экран не команда launch/search", c is None, c)

    c = parse_user("выключи звук")
    check("mute → pc", c and c.kind == "pc" and c.target == "mute", c)

    c = parse_user("открой калькулятор")
    check("калькулятор → launch", c and c.kind == "launch", c)


def test_screen():
    print("\n=== screen_watch ===")
    from screen_watch import (
        is_look_command,
        extract_scene,
        extract_anim,
        infer_anim_from_text,
        scene_to_anim,
    )

    check("посмотри", is_look_command("посмотри"))
    check("посмотри на экран", is_look_command("посмотри на экран"))
    check("что на экране", is_look_command("что у меня на экране"))
    check("найди котиков не look", not is_look_command("найди котиков"))
    check("открой блокнот не look", not is_look_command("открой блокнот"))

    sc, an = extract_scene("[SCENE:work] текст")
    check("SCENE work", sc == "work", (sc, an))
    check("work больше не thinking", scene_to_anim("work") != "thinking", scene_to_anim("work"))

    check("ANIM flirty", extract_anim("[ANIM:flirty] привет") == "flirty")
    check("Comfy → searching_happy", infer_anim_from_text("Хозяин в ComfyUI, очередь задач") == "searching_happy")
    check("папка → pointing", infer_anim_from_text("смотрит папку на диске D") == "pointing")
    check("ошибка → shocked", infer_anim_from_text("traceback error на экране") == "shocked")
    check("котики → happy", infer_anim_from_text("на экране котики милые") == "happy")


def test_history():
    print("\n=== history clean ===")
    try:
        from assistant_core import LMAssistant
    except Exception as e:
        print(f"  SKIP assistant_core ({e})")
        return

    raw = "[ANIM:thinking] [SCENE:work] [СИСТЕМА] 🔍 Поиск:\n### Заголовок\n> цитата\nПривет хозяин"
    clean = LMAssistant._clean_for_history(raw, limit=360)
    check("нет ANIM", "[ANIM" not in clean, clean)
    check("нет SCENE", "[SCENE" not in clean, clean)
    check("нет СИСТЕМА", "СИСТЕМА" not in clean, clean)
    check("остался текст", "Привет" in clean, clean)
    long = "слово " * 400
    short = LMAssistant._clean_for_history(long, limit=80)
    check("режет длинное", len(short) <= 90, len(short))


def test_peek_priority():
    print("\n=== приоритет кадра экрана ===")
    from screen_watch import extract_scene, extract_anim, infer_anim_from_text

    msg = "[SCENE:work] Хозяин работает с нейросетью ComfyUI, очередь задач."
    scene, scene_anim = extract_scene(msg)
    tag = extract_anim(msg)
    text = infer_anim_from_text(msg)
    anim = tag or text or scene_anim or "idle"
    if anim == "thinking" and text and text != "thinking":
        anim = text
    check("Comfy+work не thinking", anim != "thinking", anim)
    check("Comfy+work → searching_* или text hint", anim.startswith("searching") or anim == "pointing", anim)


if __name__ == "__main__":
    print("🦊 тесты функций Лисички")
    try:
        test_commands()
        test_screen()
        test_history()
        test_peek_priority()
    except Exception as e:
        bad += 1
        print(f"\nCRASH: {e}")
        import traceback
        traceback.print_exc()
    print(f"\n=== итог: {ok} ok, {bad} fail ===")
    sys.exit(1 if bad else 0)
