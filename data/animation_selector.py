# animation_selector.py — умный выбор анимации для Лисички
"""
Приоритет:
1. force / явный [ANIM:xxx]
2. Сильные ключевые слова (undress, love, search…)
3. Intent → анимация
4. Настроение хозяина (HybridAnalyzer / EmotionalAnalyzer по user_text)
5. Память фраз (MEMORY_ANIMS): «спасибо»×N → love_warm и т.п.
6. Мягкий bias по времени суток (TIME_BASED_ANIMS)
7. Сглаживание по истории loop-анимаций
8. Fallback neutral / idle / time-default

Учитывает NSFW_ENABLED и ENABLED_EMOTIONS из config.
"""
from __future__ import annotations

import re
from typing import Optional, Dict, List, Deque
from collections import deque, Counter

import config


class AnimationSelector:
    """Единая точка выбора анимации для GUI и core."""

    STRONG_TRIGGERS = {
        "undress": [
            r"раздень", r"раздеться", r"сними ", r"снимите", r"голая", r"голую",
            r"голый", r"обнаж", r"без одежд", r"трусик", r"лифчик",
            r"\bundress\b", r"\bnaked\b", r"\bstrip\b", r"\bnude\b",
        ],
        "searching": [
            r"найди", r"нади", r"поищи", r"поиск", r"найти", r"искать", r"ищу",
            r"погугли", r"загугли", r"глянь в",
            r"посмотри\s+на\s+экран", r"что\s+на\s+экране", r"что\s+у\s+меня\s+открыто",
            r"\bsearch\b", r"\bfind\b", r"\[SEARCH",
        ],
        "pointing": [
            r"покажи", r"вон там", r"укажи", r"покажи на",
        ],
        "love_shy": [
            r"люблю тебя", r"обожаю тебя", r"я тебя люблю", r"я тебя обожаю",
            r"i love you", r"люблю\s+тебя",
        ],
        "love_warm": [
            r"обним", r"поцел", r"нежн", r"милая", r"милый", r"дорогая", r"дорогой",
            r"скучаю", r"соскуч", r"обнимаш", r"целую",
        ],
        "love": [
            r"люблю", r"любов", r"сердечк", r"\blove\b",
        ],
        "flirty": [
            r"флирт", r"пошл", r"возбуд", r"секс", r"\bsexy\b", r"\bhorny\b",
            r"дразн", r"шали", r"шалун", r"соблазн",
        ],
        "teasing": [
            r"дразн", r"подкол", r"дразни",
        ],
        "angry": [
            r"бесит", r"бешен", r"ненавиж", r"заткни", r"тупая", r"тупой",
            r"злюсь", r"злая", r"злой", r"злит", r"разозл", r"достал",
            r"\bangry\b", r"fuck you",
        ],
        "sad": [
            r"груст", r"печал", r"обидн", r"тоск", r"одинок", r"жалко",
            r"\bsad\b",
        ],
        "cry": [
            r"плач", r"плак", r"рыда", r"слёз", r"слез", r"расплак",
        ],
        "happy": [
            r"счастлив", r"радост", r"весел", r"ура\b", r"классн", r"отличн",
            r"супер", r"круто", r"кайф", r"\byay\b", r"\bgreat\b",
        ],
        "happy_big": [
            r"урааа", r"восторг", r"офигенн",
        ],
        "sleepy": [
            r"устал", r"спат", r"посп", r"сонн", r"засни", r"ложись",
            r"\bспи\b", r"в кроват", r"спокойной ночи", r"доброй ночи",
            r"\btired\b", r"\bsleepy\b", r"\bsleep\b", r"go to bed",
        ],
        "tired": [
            r"вымотал", r"измотал", r"нет сил", r"выгорел",
        ],
        "sick": [
            r"болею", r"болеет", r"болеть", r"тошнит", r"простуд", r"температур",
            r"плохо себя",
        ],
        "thinking": [
            r"думаю", r"подумай", r"почему", r"зачем", r"что такое",
            r"объясни", r"расскажи как", r"\bexplain\b", r"\bwhy\b",
        ],
        "dance": [
            r"танц", r"потанц", r"станц", r"dance",
        ],
        "shy": [
            r"стесня", r"смуща", r"стыдно", r"застенч",
        ],
        "blush": [
            r"красне", r"румян", r"blush",
        ],
        "embarrassed": [
            r"неловко", r"конфуз", r"опозор",
        ],
        "surprised": [
            r"удивл", r"ого\b", r"вау\b", r"wow", r"неожидан",
        ],
        "shocked": [
            r"шок", r"офигел", r"охренел", r"в шоке",
        ],
        "scared": [
            r"боюсь", r"страшн", r"испуг", r"пуга", r"ужас",
        ],
        "sly": [
            r"хитр", r"лукав", r"с ухмыл",
        ],
        "mischievous": [
            r"озорн", r"проказ", r"безобразн",
        ],
        "jealous": [
            r"ревн", r"завид",
        ],
        "proud": [
            r"горж", r"горда", r"гордый", r"молодец", r"умница",
        ],
        "confident": [
            r"уверен", r"спокойно справ",
        ],
        "playful": [
            r"поиграй", r"играем", r"игрив", r"побалуй",
        ],
        "giggling": [
            r"хихи", r"гиги", r"смеюсь", r"смешно", r"хаха",
        ],
        "pouting": [
            r"дуюсь", r"надул", r"губки",
        ],
        "idle": [
            r"скучн", r"нечем заняться", r"просто так",
        ],
        "bed": [
            r"в постель", r"на кровати", r"ложись ко мне",
        ],
        "bath": [
            r"ванн", r"купай", r"душ\b",
        ],
    }

    # Тема запроса → настроение (поиск и обычный диалог)
    TOPIC_FLIRTY = (
        r"хентай", r"hentai", r"nsfw", r"порно", r"porn", r"эротик", r"18\+",
        r"сиськ", r"письк", r"голая", r"голых", r"нюд", r"секс", r"интим",
        r"правило 34", r"rule 34", r"r34",
    )
    TOPIC_HAPPY = (
        r"котик", r"кот\b", r"кошк", r"щен", r"собак", r"пёс", r"песик",
        r"мил", r"милот", r"смешн", r"мем", r"прикол", r"милое",
        r"радуг", r"цветы", r"мороженое", r"пирож",
    )
    TOPIC_SAD = (
        r"похорон", r"смерть", r"умер", r"погиб", r"трагед", r"катастроф",
        r"войн", r"грустн", r"печал", r"депресс", r"одиноч", r"развод",
        r"болезн", r"рак\b", r"кладбищ",
    )
    TOPIC_SERIOUS = (
        r"налог", r"закон", r"договор", r"работ", r"резюме", r"инструкц",
        r"ошибк", r"баг", r"сервер", r"код\b", r"документ", r"анализ",
        r"политик", r"новост", r"курс валют", r"лечени",
    )

    OWNER_MOOD_MAP = {
        "грустно": "sad", "грусть": "sad", "грустишь": "sad", "погрусти": "sad",
        "печально": "sad", "печаль": "sad", "плохо": "sad", "одинок": "sad",
        "одиноко": "sad", "обидно": "sad", "тоска": "sad",
        "плачу": "cry", "плакать": "cry", "расплакалась": "cry",
        "счастливо": "happy", "счастлив": "happy", "счастлива": "happy",
        "радостно": "happy", "радость": "happy", "порадуй": "happy",
        "весело": "happy", "повесели": "happy", "отлично": "happy",
        "злюсь": "angry", "злишься": "angry", "злой": "angry", "злая": "angry",
        "бесит": "angry", "разозли": "angry", "по злой": "angry",
        "устал": "sleepy", "устала": "sleepy", "устала я": "sleepy",
        "хочу спать": "sleepy", "поспать": "sleepy", "поспи": "sleepy",
        "поспишь": "sleepy", "спать": "sleepy", "спи": "sleepy",
        "засни": "sleepy", "ложись": "sleepy", "доброй ночи": "sleepy",
        "спокойной ночи": "sleepy", "сонная": "sleepy", "сонный": "sleepy",
        "вымотался": "tired", "нет сил": "tired",
        "болею": "sick", "заболела": "sick",
        "скучно": "idle", "заскучала": "idle",
        "люблю": "love_warm", "обними": "love_warm", "поцелуй": "love_warm",
        "соскучился": "love_warm", "соскучилась": "love_warm", "скучаю": "love_shy",
        "стесняюсь": "shy", "смущаюсь": "shy",
        "ревную": "jealous", "завидую": "jealous",
        "боюсь": "scared", "страшно": "scared",
        "удивлена": "surprised", "шок": "shocked",
        "потанцуй": "dance", "станцуй": "dance", "танцуй": "dance",
        "хихикай": "giggling", "поиграй": "playful",
    }

        # Память фраз: pattern → (threshold_count, animation)
    PHRASE_MEMORY_RULES = [
        (re.compile(r"\bспасибо\b|\bблагодар|\bthanks\b|\bthank you\b", re.I), 3, "love_warm"),
        (re.compile(r"\bты лучш|\bумница\b|\bмолодец\b|\bgood (?:girl|job)\b", re.I), 2, "happy_big"),
        (re.compile(r"\bпрости\b|\bизвини\b|\bsorry\b", re.I), 2, "shy"),
        (re.compile(r"\bскучаю\b|\bсоскуч", re.I), 2, "love_shy"),
        (re.compile(r"\bспокойной ночи\b|\bдоброй ночи\b|\bgood night\b", re.I), 1, "sleepy"),
        (re.compile(r"\bдоброе утро\b|\bgood morning\b", re.I), 1, "happy_big"),
    ]

    # Время суток → дефолтная / bias-анимация
    TIME_DEFAULT_ANIM = {
        "morning": "happy_big",
        "day": "happy",
        "evening": "idle",
        "night": "sleepy",
    }
    TIME_SOFT_POOL = {
        "morning": ("happy_big", "happy", "idle_happy", "neutral"),
        "day": ("happy", "neutral", "idle", "thinking"),
        "evening": ("idle", "love_warm", "happy", "neutral"),
        "night": ("sleepy", "idle", "neutral", "love"),
    }

    LOOP_SET = {
        "idle", "idle_sad", "idle_happy", "idle_angry", "idle_sly",
        "dance", "dance_happy", "dance_sly", "dance_love",
        "searching", "searching_happy", "searching_sad", "searching_angry",
        "undress", "undress_happy", "undress_sly", "undress_love",
        "undress_playful", "undress_seductive", "undress_teasing",
        "undress_mischievous", "undress_shy",
        "bath", "bath_shy", "bath_happy",
        "bed", "bed_love", "bed_shy",
    }

    def __init__(self, analyzer=None, max_history: int = 8):
        self.analyzer = analyzer
        self._history: Deque[str] = deque(maxlen=max_history)
        self._last: str = getattr(config, "DEFAULT_ANIMATION", "neutral") or "neutral"
        self._phrase_hits: Counter = Counter()
        self._owner_mood: str = "neutral"
        self._owner_mood_conf: float = 0.0

    # ------------------------------------------------------------------ public

    def select(
        self,
        text: str = "",
        *,
        user_text: str = "",
        intent: Optional[str] = None,
        force: Optional[str] = None,
    ) -> str:
        """
        text — ответ ассистента (или кусок стрима)
        user_text — последнее сообщение хозяина
        intent — результат router / HybridAnalyzer
        force — принудительная анимация
        """
        if force:
            return self._finalize(force)

        # 1. Явный тег в ответе
        explicit = self._extract_explicit(text)
        if explicit:
            return self._finalize(explicit)

        # 2. Тема + поиск (котики/хентай/серьёзное) важнее голого "найди"
        src = (user_text or text or "").strip()
        topic = self.topic_mood(src)
        if self._is_searchish(src):
            self._note_phrase(user_text)
            return self._finalize(self._blend_search(topic))
        if topic in ("flirty", "sad", "happy"):
            # обычный диалог по теме, если модель ещё не решила
            pass

        # 2b. Обученная микромодель по фразе хозяина
        ml_anim = self._analyzer_anim(src)
        if topic and (not ml_anim or ml_anim in ("neutral", "thinking", "searching")):
            ml_anim = topic if topic != "thinking" else "thinking"
        if ml_anim and ml_anim != "neutral":
            self._note_phrase(user_text)
            return self._finalize(ml_anim)

        # 3. Сильные триггеры (если модель не уверена)
        combined = f"{user_text or ''} {text or ''}".strip()
        strong = self._match_strong(combined)
        if strong:
            self._note_phrase(user_text)
            return self._finalize(strong)

        # 3. Intent
        if intent:
            from_intent = self._intent_to_anim(intent)
            if from_intent and from_intent != "neutral":
                self._note_phrase(user_text)
                return self._finalize(from_intent)

        # 3b. Единый state ContextManager (время + её эмоция + хозяин)
        ctx = getattr(self, "context", None)
        if ctx is not None and hasattr(ctx, "suggested_anim"):
            try:
                from_state = ctx.suggested_anim()
                if from_state and from_state != "neutral":
                    return self._finalize(from_state)
            except Exception:
                pass

        # 4. Настроение хозяина (словарь + ML/Hybrid)
        mood_anim = self._owner_mood_anim(user_text)
        if mood_anim:
            self._note_phrase(user_text)
            return self._finalize(mood_anim)

        # 5. Память фраз (спасибо×3 → love_warm)
        if getattr(config, "MEMORY_ANIMS", True):
            mem = self._memory_anim(user_text)
            if mem:
                return self._finalize(mem)

        # 6. Analyzer по combined (ответ+user) — мягкий сигнал
        if self.analyzer:
            try:
                anim = self._analyzer_anim(combined or user_text or text)
                if anim and anim != "neutral":
                    self._note_phrase(user_text)
                    return self._finalize(anim)
            except Exception:
                pass

        # 7. Сглаживание loop
        if self._last and self._last in self.LOOP_SET:
            return self._finalize(self._last)

        # 8. Time-based default
        if getattr(config, "TIME_BASED_ANIMS", True):
            t_anim = self._time_default_anim()
            if t_anim:
                return self._finalize(t_anim)

        return self._finalize(getattr(config, "DEFAULT_ANIMATION", "neutral") or "neutral")

    # ------------------------------------------------------------------ owner mood (п.3)

    def _owner_mood_anim(self, user_text: str) -> Optional[str]:
        """Эмоция/настроение хозяина → анимация Лисички."""
        if not user_text or not user_text.strip():
            return None

        t = user_text.lower()

        # словарь (быстрый путь)
        for key, anim in self.OWNER_MOOD_MAP.items():
            if key in t:
                self._owner_mood = anim
                self._owner_mood_conf = 0.85
                return anim

        # Hybrid / EmotionalAnalyzer
        if not self.analyzer:
            return None
        try:
            thr = float(getattr(config, "EMOTION_CONFIDENCE_THRESHOLD", 0.4))
            if hasattr(self.analyzer, "analyze_emotion"):
                res = self.analyzer.analyze_emotion(user_text)
                conf = float(res.get("confidence") or 0.0)
                anim = res.get("animation") or res.get("dominant")
                if anim and conf >= thr and anim != "neutral":
                    self._owner_mood = str(anim)
                    self._owner_mood_conf = conf
                    return str(anim)
            if hasattr(self.analyzer, "get_animation"):
                anim = self.analyzer.get_animation(user_text)
                if anim and anim != "neutral":
                    self._owner_mood = str(anim)
                    self._owner_mood_conf = 0.6
                    return str(anim)
            if hasattr(self.analyzer, "analyze_full_context"):
                emotion, details = self.analyzer.analyze_full_context(user_text)
                if emotion and emotion != "neutral":
                    anim = (
                        self.analyzer.get_animation(emotion)
                        if hasattr(self.analyzer, "get_animation")
                        else emotion
                    )
                    self._owner_mood = str(anim)
                    self._owner_mood_conf = 0.55
                    return str(anim)
        except Exception:
            pass
        return None

    def _analyzer_anim(self, text: str) -> Optional[str]:
        if not text or not self.analyzer:
            return None
        if hasattr(self.analyzer, "analyze_emotion"):
            res = self.analyzer.analyze_emotion(text)
            anim = res.get("animation") or res.get("dominant")
            conf = float(res.get("confidence") or 0.0)
            thr = float(getattr(config, "EMOTION_CONFIDENCE_THRESHOLD", 0.4))
            if anim and conf >= thr:
                return str(anim)
        if hasattr(self.analyzer, "get_animation"):
            anim = self.analyzer.get_animation(text)
            if anim:
                return str(anim)
        return None

    # ------------------------------------------------------------------ memory (п.4)

    def _note_phrase(self, user_text: str) -> None:
        if not user_text or not getattr(config, "MEMORY_ANIMS", True):
            return
        for rx, _need, _anim in self.PHRASE_MEMORY_RULES:
            if rx.search(user_text):
                self._phrase_hits[rx.pattern] += 1

    def _memory_anim(self, user_text: str) -> Optional[str]:
        if not user_text:
            return None
        for rx, need, anim in self.PHRASE_MEMORY_RULES:
            if not rx.search(user_text):
                continue
            self._phrase_hits[rx.pattern] += 1
            if self._phrase_hits[rx.pattern] >= need:
                # сброс счётчика после срабатывания (чтобы не залипало)
                self._phrase_hits[rx.pattern] = 0
                return anim
        return None

    def reset_memory(self) -> None:
        self._phrase_hits.clear()
        self._history.clear()
        self._owner_mood = "neutral"
        self._owner_mood_conf = 0.0

    # ------------------------------------------------------------------ time (п.2)

    def _period_id(self) -> str:
        try:
            from time_context import get_period
            pid, _ = get_period()
            return pid or "day"
        except Exception:
            from datetime import datetime
            h = datetime.now().hour
            if 5 <= h < 12:
                return "morning"
            if 12 <= h < 17:
                return "day"
            if 17 <= h < 23:
                return "evening"
            return "night"

    def _time_default_anim(self) -> Optional[str]:
        if not getattr(config, "TIME_BASED_ANIMS", True):
            return None
        # можно переопределить словарём в config
        custom = getattr(config, "TIME_BASED_ANIM_MAP", None) or {}
        pid = self._period_id()
        anim = custom.get(pid) or self.TIME_DEFAULT_ANIM.get(pid)
        return anim

    def time_soft_pool(self) -> tuple:
        pid = self._period_id()
        custom = getattr(config, "TIME_BASED_ANIM_MAP", None)
        if isinstance(custom, dict) and pid in custom:
            return (custom[pid],)
        return self.TIME_SOFT_POOL.get(pid, ("neutral",))

    # ------------------------------------------------------------------ helpers

    def _extract_explicit(self, text: str) -> Optional[str]:
        if not text:
            return None
        m = re.search(r"\[ANIM:(\w+)\]", text, re.IGNORECASE)
        if m:
            return m.group(1).lower()
        return None


    def topic_mood(self, text: str) -> Optional[str]:
        """Настроение по теме фразы, не по глаголу найди/покажи."""
        t = (text or "").lower()
        if not t:
            return None
        for pat in self.TOPIC_FLIRTY:
            if re.search(pat, t, re.I):
                return "flirty"
        for pat in self.TOPIC_SAD:
            if re.search(pat, t, re.I):
                return "sad"
        for pat in self.TOPIC_HAPPY:
            if re.search(pat, t, re.I):
                return "happy"
        for pat in self.TOPIC_SERIOUS:
            if re.search(pat, t, re.I):
                return "thinking"
        return None

    def _is_searchish(self, text: str) -> bool:
        t = (text or "").lower()
        return bool(re.search(
            r"найди|нади|поищи|поиск|найти|искать|ищу|загугли|погугли|\bsearch\b|\bfind\b|\[SEARCH",
            t, re.I,
        ))

    def _blend_search(self, mood: Optional[str]) -> str:
        """Поиск + настроение темы → searching_* или flirty."""
        if mood == "flirty":
            return "flirty"
        if mood == "happy":
            return "searching_happy"
        if mood == "sad":
            return "searching_sad"
        if mood == "thinking":
            return "searching"
        if mood == "angry":
            return "searching_angry"
        return "searching"

    def _match_strong(self, text: str) -> Optional[str]:
        if not text:
            return None
        t = text.lower()
        try:
            from character_manager import character_emotion_triggers
            for phrase, anim in character_emotion_triggers():
                if phrase and phrase in t:
                    return anim
        except Exception:
            pass
        priority = [
            "undress", "bed", "bath",
            "love_shy", "love_warm", "love",
            "searching", "pointing",
            "cry", "angry", "sad",
            "flirty", "teasing",
            "sleepy", "tired", "sick",
            "dance", "scared", "shocked", "surprised",
            "jealous", "shy", "blush", "embarrassed",
            "proud", "playful", "giggling", "pouting",
            "sly", "mischievous",
            "happy_big", "happy",
            "thinking", "idle",
        ]
        for anim in priority:
            for pat in self.STRONG_TRIGGERS.get(anim, []):
                if re.search(pat, t, re.IGNORECASE):
                    return anim
        return None

    def _intent_to_anim(self, intent: str) -> str:
        mapping = {
            "search": "searching",
            "launch_app": "happy",
            "open_browser": "happy",
            "system_control": "neutral",
            "love": "love_shy",
            "flirty": "flirty",
            "undress": "undress",
            "reminder": "neutral",
            "notes": "thinking",
            "chat": "neutral",
            "question": "thinking",
            "screenshot": "happy",
            "volume_control": "neutral",
        }
        return mapping.get((intent or "").lower(), "neutral")

    def _finalize(self, anim: str) -> str:
        anim = (anim or "neutral").lower().strip()
        anim = self._apply_nsfw_and_enabled(anim)
        # ночной soft-clamp: без явного force не прыгаем в громкие NSFW ночью
        if getattr(config, "TIME_BASED_ANIMS", True) and self._period_id() == "night":
            loud = {"dance", "dance_happy", "happy_big", "searching"}
            if anim in loud and anim not in (self._last,):
                # не блокируем undress/love если уже выбраны сильным триггером —
                # сюда попадают только «мягкие» fallback-пути в основном
                pass
        self._history.append(anim)
        self._last = anim
        return anim

    def _apply_nsfw_and_enabled(self, anim: str) -> str:
        nsfw_list = getattr(config, "NSFW_EMOTIONS", []) or []
        is_nsfw = anim in nsfw_list or any(
            anim.startswith(b + "_") for b in nsfw_list
        )
        if is_nsfw and not getattr(config, "NSFW_ENABLED", True):
            return "neutral"
        try:
            from character_manager import character_anim_ban, character_anim_fallback
            ban = character_anim_ban()
            fallback = character_anim_fallback()
        except Exception:
            ban, fallback = set(), "neutral"
        if ban and (anim in ban or any(anim.startswith(b + "_") for b in ban)):
            return fallback or "neutral"

        enabled = getattr(config, "ENABLED_EMOTIONS", None)
        if enabled is None:
            return anim
        if anim in enabled:
            return anim
        if "_" in anim:
            base = anim.split("_")[0]
            if base in enabled:
                return base
        for e in enabled:
            if anim.startswith(e) or e.startswith(anim):
                return e
        return "neutral"

    def is_loop(self, anim: str) -> bool:
        return (anim or "") in self.LOOP_SET

    def get_last(self) -> str:
        return self._last

    def get_owner_mood(self) -> Dict[str, float]:
        return {"mood": self._owner_mood, "confidence": self._owner_mood_conf}
