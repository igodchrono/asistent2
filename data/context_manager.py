# context_manager.py — единый источник настроения + опциональный полный промпт
# Mood-логика больше не дублируется в assistant_core.
import re
import time
from typing import List, Dict, Optional

from memory_manager import MemoryManager
from persistent_memory import PersistentMemory
from rag_engine import RAGEngine

import config
import logging

logger = logging.getLogger(__name__)


class ContextManager:
    """
    Управление контекстом и настроением пользователя.
    Единственный источник mood для LMAssistant.
    """

    def __init__(self, rag: Optional[RAGEngine] = None):
        self.memory = MemoryManager(config.DB_PATH)
        self.persistent_memory = PersistentMemory(config.PERSISTENT_MEMORY_DB)

        # Можно передать уже созданный RAG из LMAssistant, чтобы не дублировать индекс
        if rag is not None:
            self.rag = rag
            self._owns_rag = False
        else:
            self.rag = RAGEngine(
                db_path=getattr(config, "ADVANCED_RAG_DB", "rag.db"),
                api_url=config.API_URL,
                model_name=config.MODEL_NAME,
                dimension=getattr(config, "ADVANCED_RAG_DIMENSION", 512),
            )
            self._owns_rag = True
            if getattr(config, "RAG_AUTO_INDEX", True):
                try:
                    self.rag.auto_index_from_config()
                    logger.info("RAG автоиндексация (ContextManager)")
                except Exception as e:
                    logger.warning(f"RAG ошибка авто-индексации: {e}")

        self.current_project = None
        self.last_user_activity = time.time()
        self._user_mood = "neutral"
        self._user_mood_until = 0.0
        self._self_mood = "neutral"
        self._self_mood_until = 0.0
        self._silence_strikes = 0

        self._tired_re = re.compile(
            r"(устал|устала|нет сил|выгорел|выгорела|спать хочу|хочу спать|"
            r"голова болит|мигрень|плохо себя|неважно|exhausted|tired|sleepy|"
            r"не до шуток|не в настроении|отстань пожалуйста)",
            re.I,
        )
        self._rude_re = re.compile(
            r"(заткнись|задолбал|задолбала|бесит|тупая|тупой|иди нах|"
            r"пошла нах|отстань|заткни|дур[аa]|идиот|ненавижу тебя|"
            r"shut up|stupid|fuck you|отвали)",
            re.I,
        )
        self._playful_re = re.compile(
            r"(пошло|пошл[аоую]|пошалим|шали|флирт|возбуди|возбуд|"
            r"раздень|разденься|голая|голую|секс|эротик|18\+|nsfw|"
            r"будь плохой|плохая девочка|шепчи|на ушко|хвостиком|"
            r"хочу тебя|обними крепче|поцелуй|поцелу[йи]|"
            r"игрив|шаловлив|соблазн|грязн[оа]|неприличн|"
            r"sexy|horny|tease me|be naughty|undress|flirt)",
            re.I,
        )
        self._soft_reset_re = re.compile(
            r"(спасибо|прости|извини|ты молодец|норм|всё ок|все ок|"
            r"давай дальше|добро|хорош|хватит пошлости|без пошлости|"
            r"прекрати|стоп флирт|не пошло)",
            re.I,
        )
        self._sad_re = re.compile(
            r"(грустн|печал|тоск|одинок|плохо настроен|депресс|плачу|"
            r"слезы|слёзы|жаль|обидно|не хочу жить|sad|upset)",
            re.I,
        )
        self._happy_re = re.compile(
            r"(ура|супер|класс|круто|обожаю|счастлив|рада? |весел|"
            r"отличн|люблю тебя|спасибо большое|ты лучшая|yay|great)",
            re.I,
        )

        logger.info("ContextManager инициализирован (единый mood + self + time)")

    def touch_activity(self):
        self.last_user_activity = time.time()
        self._silence_strikes = 0
        if self._self_mood in ("bored", "sad", "hurt") and time.time() >= self._self_mood_until:
            self.set_self_mood("happy", hold=180)

    def get_idle_time(self) -> float:
        return time.time() - self.last_user_activity

    def time_bucket(self) -> str:
        try:
            from time_context import time_bucket
            return time_bucket()
        except Exception:
            h = time.localtime().tm_hour
            if h < 6:
                return "night"
            if h < 11:
                return "morning"
            if h < 18:
                return "day"
            if h < 23:
                return "evening"
            return "late"

    def set_self_mood(self, mood: str, hold: float = 300):
        self._self_mood = mood or "neutral"
        self._self_mood_until = time.time() + max(30.0, float(hold))

    def get_self_mood(self) -> str:
        now = time.time()
        if self._self_mood_until and now > self._self_mood_until:
            try:
                from time_context import default_self_mood
                self._self_mood = default_self_mood(self.time_bucket())
            except Exception:
                self._self_mood = "neutral"
            self._self_mood_until = now + 120
        return self._self_mood

    def get_user_mood(self) -> str:
        if self._user_mood_until and time.time() > self._user_mood_until:
            self._user_mood = "neutral"
        return self._user_mood

    def tick_silence(self, idle_seconds: Optional[float] = None) -> str:
        """Тишина копит её настроение: neutral → bored → sad → hurt."""
        idle = self.get_idle_time() if idle_seconds is None else float(idle_seconds)
        bucket = self.time_bucket()
        step = 180.0
        if bucket in ("night", "late"):
            step = 420.0
        if idle < step:
            return self.get_self_mood()
        self._silence_strikes = min(self._silence_strikes + 1, 3)
        if self._silence_strikes >= 3:
            self.set_self_mood("hurt", hold=600)
        elif self._silence_strikes == 2:
            self.set_self_mood("sad", hold=480)
        else:
            self.set_self_mood("bored", hold=360)
        if bucket in ("night", "late") and self._self_mood in ("bored", "neutral"):
            self.set_self_mood("sleepy", hold=400)
        return self.get_self_mood()

    def on_command_result(self, ok: bool):
        if ok:
            self.set_self_mood("proud", hold=120)
        else:
            self.set_self_mood("embarrassed", hold=90)

    def detect_mood(self, text: str) -> str:
        """Настроение хозяина + реакция её self_mood."""
        if not text or not str(text).strip():
            return self.get_user_mood()

        t = str(text)
        now = time.time()
        hold = float(getattr(config, "MOOD_HOLD_SECONDS", 900) or 900)
        playful_hold = float(getattr(config, "MOOD_PLAYFUL_HOLD_SECONDS", hold) or hold)

        if self._rude_re.search(t):
            self._user_mood = "rude"
            self._user_mood_until = now + hold
            self.set_self_mood("hurt", hold=min(hold, 400))
            return "rude"
        if self._tired_re.search(t):
            self._user_mood = "tired"
            self._user_mood_until = now + hold
            self.set_self_mood("sleepy", hold=200)
            return "tired"
        if self._sad_re.search(t):
            self._user_mood = "sad"
            self._user_mood_until = now + hold
            self.set_self_mood("sad", hold=240)
            return "sad"
        if self._playful_re.search(t) and getattr(config, "NSFW_ENABLED", True):
            self._user_mood = "playful"
            self._user_mood_until = now + playful_hold
            self.set_self_mood("playful", hold=min(playful_hold, 400))
            return "playful"
        if self._happy_re.search(t):
            self._user_mood = "happy"
            self._user_mood_until = now + min(hold, 400)
            self.set_self_mood("happy", hold=240)
            return "happy"
        if self._soft_reset_re.search(t):
            self._user_mood = "neutral"
            self._user_mood_until = 0
            self.set_self_mood("neutral", hold=120)
            return "neutral"
        if self._user_mood_until > now:
            return self._user_mood
        self._user_mood = "neutral"
        return "neutral"

    def suggested_anim(self) -> str:
        user = self.get_user_mood()
        selfm = self.get_self_mood()
        user_map = {
            "sad": "sad",
            "tired": "sleepy",
            "rude": "pouting",
            "happy": "happy",
            "playful": "flirty",
        }
        if user in user_map:
            return user_map[user]
        self_map = {
            "happy": "happy",
            "bored": "idle",
            "sad": "sad",
            "hurt": "pouting",
            "proud": "proud",
            "sleepy": "sleepy",
            "playful": "playful",
            "embarrassed": "shy",
            "neutral": None,
        }
        anim = self_map.get(selfm)
        if anim:
            return anim
        try:
            from time_context import default_anim
            return default_anim(self.time_bucket())
        except Exception:
            return "neutral"

    def get_mood_prompt_addon(self) -> str:
        """Одна карточка состояния: время + хозяин + она."""
        try:
            from time_context import format_clock, time_label
            clock = format_clock()
            label = time_label(self.time_bucket())
        except Exception:
            clock = time.strftime("%H:%M")
            label = self.time_bucket()
        user = self.get_user_mood()
        selfm = self.get_self_mood()
        anim = self.suggested_anim()
        lines = [
            f"Сейчас: {clock} ({label}).",
            f"Настроение хозяина: {user}. Твоё настроение: {selfm}.",
            f"Поставь [ANIM:{anim}], если нет более точного тега.",
        ]
        extra = {
            "tired": "Говори мягко и коротко, без шуток и пошлости.",
            "rude": "Не зеркаль грубость. Спокойно, можно чуть обидеться один раз.",
            "sad": "Поддержи, без бодрости и без флирта.",
            "playful": "Можно игриво, если NSFW включён. Без грубости.",
            "happy": "Можно чуть светлее обычного.",
        }.get(user, "")
        self_extra = {
            "bored": "Тебе скучно без хозяина — намёк короткий, не ной простынёй.",
            "hurt": "Ты задета тишиной или грубостью — коротко и без истерики.",
            "sleepy": "Сонный тон, короче обычного.",
            "proud": "Чуть довольная собой после удачной команды.",
            "embarrassed": "Слегка смущённо: команда не вышла.",
        }.get(selfm, "")
        if extra:
            lines.append(extra)
        if self_extra:
            lines.append(self_extra)
        return "\n" + "\n".join(lines) + "\n"

    def build_system_prompt(self, user_text: str) -> str:
        """
        Полный system prompt (опционально, если кто-то хочет собрать всё здесь).
        LMAssistant сейчас собирает промпт сам + берёт только mood_addon.
        """
        system_prompt = config.SYSTEM_PROMPT

        memory_context = self.persistent_memory.get_context_for_prompt(
            query=user_text,
            scope="global",
            limit=config.MAX_MEMORIES_IN_CONTEXT,
        )
        if self.current_project:
            project_context = self.persistent_memory.get_context_for_prompt(
                query=user_text,
                scope="project",
                limit=config.MAX_MEMORIES_IN_CONTEXT,
            )
            if project_context:
                memory_context += "\n\n=== ПРОЕКТ ===\n" + project_context

        if memory_context:
            system_prompt += "\n" + memory_context

        if getattr(config, "ADVANCED_RAG_ENABLED", False):
            try:
                from rag_engine import RAGEngine as RE
                mode = RE.MODE_HYBRID if getattr(config, "RAG_HYBRID_MODE", False) else None
                # get_context может быть sync-обёрткой
                rag_context = self.rag.get_context(user_text or "", limit=4)
                if asyncio_is_coro(rag_context):
                    # на всякий случай
                    rag_context = ""
                if rag_context:
                    system_prompt += "\n" + rag_context
            except Exception as e:
                logger.warning(f"RAG ошибка: {e}")

        suggestion = self.persistent_memory.get_contextual_suggestion()
        if suggestion:
            system_prompt += f"\n[КОНТЕКСТУАЛЬНАЯ ПОДСКАЗКА] {suggestion}"

        mood_add = self.get_mood_prompt_addon()
        if mood_add:
            system_prompt += mood_add

        return system_prompt

    def save_history(self, history: List[Dict]):
        pass

    def close(self):
        self.memory.close()
        self.persistent_memory.close()
        if self._owns_rag:
            self.rag.close()
        logger.info("ContextManager закрыт")


def asyncio_is_coro(obj) -> bool:
    import inspect
    return inspect.iscoroutine(obj) or inspect.isawaitable(obj)
