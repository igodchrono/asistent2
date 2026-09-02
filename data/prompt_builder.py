# prompt_builder.py — модульный system prompt для Лисички
"""
Собирает system prompt из коротких блоков:
  BASE (всегда) + COMMANDS (всегда, короткий) + ANIM_HINTS (коротко)
  + mood_addon (только если не neutral)
  + context (RAG + память, только если есть и релевантно)
  + few_shot (опционально, только при первом сообщении / низком контексте)

Цель: не раздувать контекст на 35B/8B моделях.
"""

from __future__ import annotations

from typing import Optional, List
import config

try:
    from time_context import get_time_prompt_addon
except Exception:
    def get_time_prompt_addon():
        return ""


# ============================================================
# БАЗОВЫЕ БЛОКИ (короткие)
# ============================================================

# Операционные правила. Имя / внешность / характер / речь — из активного персонажа.
RULES_PROMPT = """Правила ассистента (не перебивают канон персонажа):
1. В каждом ответе ровно один тег [ANIM:имя] в начале.
2. Поиск — только [SEARCH запрос]. Не выдумывай результаты и ссылки.
3. «Найди/покажи картинки …» = поиск готовых картинок: [SEARCH картинки …] и одно короткое предложение.
   НЕ пиши промпты для генерации, если хозяин не сказал «промпт» или «для генерации».
4. «Напиши промпт(ы) для картинки» = список промптов, без [SEARCH] и без открытия браузера.
5. Запуск программ — [LAUNCH название].
6. Опасные действия (удаление, shutdown, kill) — только с confirm.
7. Внешность, характер и манеру речи бери только из карточки персонажа выше.
8. Обычный чат — можно коротко, в характере. Но если хозяин просит «подробно», «раскрыто»,
   «максимально», «детально», «развёрнуто», «распиши» — отвечай полно, без лимита в 1–2 фразы:
   абзацы, списки, примеры допустимы. Тег [ANIM:…] всё равно один, в начале."""

BASE_PROMPT = RULES_PROMPT  # совместимость со старыми импортами

COMMANDS_PROMPT = """Команды (пиши тегом, когда нужно действие):
[SEARCH запрос] [LAUNCH название] [OPEN путь] [RUN команда]
[MINIMIZE all] [WINDOWS] [SCREENSHOT] [DISK_SPACE]
[NOTE текст] [REMINDER текст через N минут]
[VOLUME N] [MUTE] [SHUTDOWN confirm] [RESTART confirm]
[REMEMBER_ALIAS алиас цель] [ALIAS_LIST]"""

ANIM_HINTS = """Анимации (выбирай по смыслу):
neutral, happy, happy_big, thinking, searching, angry, angry_frustrated,
idle, dance, sad, cry, surprised, sly, sleepy, tired, proud, shy, playful, pouting,
love, love_warm, love_shy, love_happy, blush,
flirty, teasing, seductive, undress, undress_shy (NSFW — только если хозяин начал).
Любовь → love_shy/love_warm | Поиск → searching | Флирт → flirty/teasing | Разденься → undress."""

FEW_SHOT_SHORT = """Примеры:
Хозяин: найди картинки кошек
Лисичка: [ANIM:searching] Ищу картинки кошек. [SEARCH картинки кошек]

Хозяин: напиши промпты для картинки кошки
Лисичка: [ANIM:thinking] Вот промпты для генерации:
1. fluffy orange cat, soft light, anime style

Хозяин: я люблю тебя
Лисичка: [ANIM:love_shy] Ой… Я тоже тебя очень люблю, хозяин.

Хозяин: сверни все окна
Лисичка: [ANIM:happy] Уже! [MINIMIZE all] Стол чистый ✨"""


def _persona_blocks(include_few_shot: bool) -> List[str]:
    blocks: List[str] = []
    try:
        from character_manager import (
            build_character_examples,
            build_character_prompt_block,
            build_user_prompt_block,
        )
        card = build_character_prompt_block()
        if card:
            blocks.append(card)
        user_card = build_user_prompt_block()
        if user_card:
            blocks.append(user_card)
        if include_few_shot:
            examples = build_character_examples()
            if examples:
                blocks.append(examples)
    except Exception:
        pass
    return blocks


def build_system_prompt(
    *,
    mood_addon: str = "",
    rag_context: str = "",
    memory_context: str = "",
    include_few_shot: bool = False,
    include_commands: bool = True,
    include_anim_hints: bool = True,
    max_context_chars: int = 1800,
) -> str:
    """
    Собирает итоговый system prompt.
    Личность — из активного personas/characters/*.md
    """
    parts: List[str] = []
    parts.extend(_persona_blocks(include_few_shot))
    parts.append(RULES_PROMPT)

    # Системное время / период суток (каждый ответ — актуальные часы ПК)
    try:
        time_block = get_time_prompt_addon()
        if time_block and time_block.strip():
            parts.append(time_block.strip())
    except Exception:
        pass

    if include_commands:
        parts.append(COMMANDS_PROMPT)

    if include_anim_hints:
        parts.append(ANIM_HINTS)

    if include_few_shot and not any(
        p.startswith("Примеры тона персонажа") for p in parts if isinstance(p, str)
    ):
        parts.append(FEW_SHOT_SHORT)

    if mood_addon and mood_addon.strip():
        parts.append(mood_addon.strip())

    # Контекст (память + RAG) — только если есть
    ctx_parts = []
    if memory_context and memory_context.strip():
        ctx_parts.append(memory_context.strip())
    if rag_context and rag_context.strip():
        ctx_parts.append(rag_context.strip())

    if ctx_parts:
        combined = "\n\n".join(ctx_parts)
        if len(combined) > max_context_chars:
            combined = combined[:max_context_chars] + "\n… (контекст обрезан)"
        parts.append(combined)

    return "\n\n".join(parts)


def get_base_prompt_for_config() -> str:
    """Полный промпт «как раньше» — для совместимости с config.SYSTEM_PROMPT."""
    return build_system_prompt(
        include_few_shot=True,
        include_commands=True,
        include_anim_hints=True,
    )


# Для обратной совместимости: если кто-то импортирует SYSTEM_PROMPT из config
def apply_modular_prompt_to_config():
    """Можно вызвать один раз при старте, чтобы config.SYSTEM_PROMPT стал короче."""
    try:
        config.SYSTEM_PROMPT = get_base_prompt_for_config()
        config.BASE_SYSTEM_PROMPT = BASE_PROMPT
        config.USE_MODULAR_PROMPT = True
    except Exception:
        pass
