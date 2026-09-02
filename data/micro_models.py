# micro_models.py
"""
Микро-модели для Лисички:
- Классификация интентов (rubert-tiny)
- Анализ эмоций (rubert-tiny-toxicity)
- Гибридный анализатор (ML + правила)

ИСПРАВЛЕНО:
- self.cache создаётся ДО _load_model (критический баг)
- единая обработка ошибок + logging
"""

import torch
import numpy as np
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from typing import Dict, List, Optional, Tuple
import json
import os
import re
import logging

logger = logging.getLogger(__name__)


class IntentClassifier:
    """
    Классификатор намерений на основе rubert-tiny.
    Определяет, что хочет пользователь: поиск, запуск, управление ПК или просто разговор.
    """

    INTENTS = [
        "search",
        "launch_app",
        "open_browser",
        "file_operation",
        "system_control",
        "reminder",
        "notes",
        "chat",
        "love",
        "question",
        "screenshot",
        "volume_control",
    ]

    def __init__(self, model_path: Optional[str] = None, use_cache: bool = True):
        # --- КРИТИЧНО: cache создаём ПЕРВЫМ, до любого _load_model ---
        self.use_cache = use_cache
        self.cache: Dict = {}
        self.cache_size = 100

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model_name = "cointegrated/rubert-tiny"
        self.tokenizer = None
        self.model = None

        self._is_finetuned = False
        self._load_model(model_path)
        self.fallback_rules = self._init_fallback_rules()
        logger.info(
            f"🤖 IntentClassifier инициализирован "
            f"(finetuned={getattr(self, '_is_finetuned', False)})"
        )

    def _load_model(self, model_path: Optional[str] = None):
        if model_path and os.path.exists(model_path):
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(model_path)
                self.model = AutoModelForSequenceClassification.from_pretrained(model_path)
                self.model.to(self.device)
                self.model.eval()
                logger.info(f"✅ Загружена модель интентов из {model_path}")

                intents_path = os.path.join(model_path, "intents.json")
                if os.path.exists(intents_path):
                    with open(intents_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if "intents" in data:
                            self.INTENTS = data["intents"]
                    # есть локальные веса + intents → считаем дообученной
                    self._is_finetuned = True
                # без intents.json но локальные веса — всё равно локальная
                elif any(
                    os.path.isfile(os.path.join(model_path, f))
                    for f in ("pytorch_model.bin", "model.safetensors")
                ):
                    self._is_finetuned = True
                return
            except Exception as e:
                logger.warning(f"⚠️ Не удалось загрузить модель из {model_path}: {e}")

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name,
                num_labels=len(self.INTENTS),
            )
            self.model.to(self.device)
            self.model.eval()
            logger.info(f"✅ Загружена базовая модель интентов ({self.model_name})")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки модели интентов: {e}", exc_info=True)
            self.tokenizer = None
            self.model = None

    def _init_fallback_rules(self) -> Dict:
        return {
            "search": [
                "найди", "поищи", "найти", "искать", "погугли", "загугли",
                "search", "look up", "найди в интернете",
            ],
            "launch_app": [
                "запусти", "открой программу", "запустить",
                "launch", "open app", "открыть приложение",
            ],
            "love": [
                "люблю", "обожаю", "love you", "❤️", "💕", "милый", "дорогой",
                "ты моя", "самая лучшая", "обожаю тебя", "безумно люблю",
            ],
            "system_control": [
                "выключи", "перезагрузи", "заблокируй", "shutdown", "restart",
                "блокировка", "завершение работы", "выключение",
            ],
            "reminder": [
                "напомни", "напоминание", "remind", "set reminder", "напомни мне",
            ],
            "notes": [
                "заметка", "запиши", "note", "save note", "заметки", "записать",
            ],
            "volume_control": [
                "громкость", "громче", "тише", "звук", "volume", "mute", "звук выключить",
            ],
            "screenshot": [
                "скриншот", "screenshot", "снимок экрана",
            ],
        }

    @staticmethod
    def _trigger_hit(text_lower: str, trigger: str) -> bool:
        t = (trigger or "").strip().lower()
        if not t:
            return False
        if " " in t:
            return t in text_lower
        return re.search(rf"(?<![а-яa-z0-9]){re.escape(t)}(?![а-яa-z0-9])", text_lower) is not None

    @staticmethod
    def _has_object(params: Dict, intent: str) -> bool:
        if intent == "search":
            q = re.sub(r"\s+", " ", str(params.get("query") or "")).strip(" .,-?!")
            return len(q) >= 2
        if intent == "launch_app":
            app = re.sub(r"\s+", " ", str(params.get("app") or "")).strip(" .,-?!")
            return len(app) >= 2
        return True

    def predict(self, text: str, threshold: float = 0.6) -> Dict:
        if not text or not text.strip():
            return {"intent": "chat", "confidence": 0.0, "params": {}}

        text_clean = text.strip()
        cache_key = text_clean[:100]

        if self.use_cache and cache_key in self.cache:
            return self.cache[cache_key]

        text_lower = text_clean.lower()
        # Правила: граница слова + для search/launch обязателен объект
        for intent, triggers in self.fallback_rules.items():
            for trigger in triggers:
                if not self._trigger_hit(text_lower, trigger):
                    continue
                params = self._extract_params(text_clean, intent)
                if intent in ("search", "launch_app") and not self._has_object(params, intent):
                    continue
                result = {
                    "intent": intent,
                    "confidence": 0.95,
                    "params": params,
                    "source": "rule",
                }
                self._cache_result(cache_key, result)
                return result

        # Без дообучения — не гоняем «сырой» classifier (шумные chat/labels)
        if not getattr(self, "_is_finetuned", False):
            result = {
                "intent": "chat",
                "confidence": 0.55,
                "params": {"text": text_clean},
                "source": "rule_fallback",
            }
            self._cache_result(cache_key, result)
            return result

        if self.model is None or self.tokenizer is None:
            result = {
                "intent": "chat",
                "confidence": 0.5,
                "params": {"text": text_clean},
                "source": "fallback",
            }
            self._cache_result(cache_key, result)
            return result

        try:
            inputs = self.tokenizer(
                text_clean,
                return_tensors="pt",
                truncation=True,
                padding=True,
                max_length=128,
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self.model(**inputs)
                probabilities = torch.softmax(outputs.logits, dim=1)
                confidence, predicted = torch.max(probabilities, dim=1)

                confidence = float(confidence.item())
                predicted_intent = self.INTENTS[predicted.item()]

                if confidence < threshold and predicted_intent != "chat":
                    predicted_intent = "chat"
                    confidence = 0.4

                if predicted_intent == "chat" and any(
                    w in text_lower for w in ("люблю", "обожаю")
                ):
                    predicted_intent = "love"
                    confidence = 0.8

                result = {
                    "intent": predicted_intent,
                    "confidence": confidence,
                    "params": self._extract_params(text_clean, predicted_intent),
                    "source": "ml",
                }
                self._cache_result(cache_key, result)
                return result

        except Exception as e:
            logger.error(f"Ошибка ML предсказания: {e}", exc_info=True)
            return {
                "intent": "chat",
                "confidence": 0.3,
                "params": {"text": text_clean},
                "source": "error",
            }

    def _extract_params(self, text: str, intent: str) -> Dict:
        params: Dict = {}
        text_lower = text.lower()

        if intent == "search":
            triggers = [
                "найди", "поищи", "найти", "искать", "гугл", "яндекс",
                "search", "find", "покажи",
            ]
            query = text_lower
            for trigger in triggers:
                query = query.replace(trigger, "").strip()
            stop_words = ["пожалуйста", "плиз", "срочно", "быстро", "мне", "надо", "нужно"]
            for word in stop_words:
                query = query.replace(word, "").strip()
            params["query"] = query

        elif intent == "launch_app":
            triggers = [
                "запусти", "открой", "запустить", "открыть", "запуск",
                "launch", "open",
            ]
            app = text_lower
            for trigger in triggers:
                app = app.replace(trigger, "").strip()
            stop_words = ["пожалуйста", "плиз", "мне", "надо", "нужно", "программу", "приложение"]
            for word in stop_words:
                app = re.sub(rf"\b{re.escape(word)}\b", " ", app)
            app = re.sub(r"\s+", " ", app).strip(" .,-")
            params["app"] = app

        elif intent == "volume_control":
            if any(w in text_lower for w in ("громче", "увелич", "+")):
                params["action"] = "up"
            elif any(w in text_lower for w in ("тише", "уменьш", "-")):
                params["action"] = "down"
            elif any(w in text_lower for w in ("выключ", "mute", "отключ")):
                params["action"] = "mute"
            else:
                params["action"] = "set"
                numbers = re.findall(r"\d+", text)
                if numbers:
                    params["level"] = int(numbers[0])

        elif intent == "system_control":
            if any(w in text_lower for w in ("выключи", "shutdown", "выключение")):
                params["action"] = "shutdown"
            elif any(w in text_lower for w in ("перезагрузи", "restart", "перезагруз")):
                params["action"] = "restart"
            elif any(w in text_lower for w in ("заблокируй", "lock", "блокировк")):
                params["action"] = "lock"
            elif any(w in text_lower for w in ("сверни", "minimize", "свернуть")):
                params["action"] = "minimize_all"

        elif intent == "reminder":
            time_match = re.search(
                r"через\s+(\d+)\s*(минут|минуты|минуту|секунд|сек|часов|час|ч)",
                text_lower,
            )
            if time_match:
                params["amount"] = int(time_match.group(1))
                unit = time_match.group(2)
                if unit in ("секунд", "сек"):
                    params["unit"] = "seconds"
                elif unit in ("минут", "минуты", "минуту"):
                    params["unit"] = "minutes"
                else:
                    params["unit"] = "hours"
                reminder_text = re.sub(
                    r"через\s+\d+\s*(минут|минуты|минуту|секунд|сек|часов|час|ч)",
                    "",
                    text_lower,
                ).strip()
                params["text"] = reminder_text or text
            else:
                params["text"] = text
                params["amount"] = 5
                params["unit"] = "minutes"

        elif intent == "notes":
            triggers = ["заметка", "запиши", "записать", "сохрани", "note", "save"]
            note = text_lower
            for trigger in triggers:
                note = note.replace(trigger, "").strip()
            params["text"] = note or text

        elif intent == "screenshot":
            params["type"] = "fullscreen"

        return params

    def _cache_result(self, key: str, result: Dict):
        if not self.use_cache:
            return
        if len(self.cache) >= self.cache_size:
            keys = list(self.cache.keys())[: self.cache_size // 2]
            for k in keys:
                self.cache.pop(k, None)
        if key:
            self.cache[key] = result


class EmotionAnalyzerML:
    """
    Анализатор эмоций с:
      - корректным id2label из config модели;
      - hybrid scoring (правила + ML);
      - маппингом в config.ENABLED_EMOTIONS / NSFW_EMOTIONS.
    Поддерживает:
      * fine-tuned emotion head (labels = joy/sadness/…);
      * cointegrated/rubert-tiny-toxicity (toxicity → soft emotion proxy).
    """

    # Канонические анимации-эмоции (до фильтра ENABLED)
    BASE_ANIMS = [
        "neutral", "happy", "sad", "angry", "scared", "surprised",
        "love_warm", "flirty", "thinking", "shy", "sleepy", "mischievous",
    ]

    # Любые label-строки модели → каноническая анимация
    LABEL_TO_ANIM = {
        # emotion-style
        "anger": "angry", "angry": "angry", "rage": "angry",
        "disgust": "angry", "frustrated": "angry",
        "fear": "scared", "scared": "scared", "afraid": "scared",
        "happiness": "happy", "happy": "happy", "joy": "happy",
        "positive": "happy", "optimism": "happy",
        "sadness": "sad", "sad": "sad", "negative": "sad", "grief": "sad",
        "surprise": "surprised", "surprised": "surprised", "shock": "shocked",
        "shocked": "shocked",
        "neutral": "neutral", "none": "neutral", "other": "neutral",
        "love": "love_warm", "affection": "love_warm",
        "flirty": "flirty", "sexy": "flirty", "seductive": "seductive",
        "shy": "shy", "embarrassed": "embarrassed", "blush": "blush",
        "thinking": "thinking", "curious": "thinking",
        "sleepy": "sleepy", "tired": "sleepy",
        "proud": "proud", "confident": "confident",
        "playful": "playful", "mischievous": "mischievous",
        # toxicity-style (rubert-tiny-toxicity)
        "non-toxic": "neutral", "non_toxic": "neutral", "ok": "neutral",
        "toxic": "angry",
        "insult": "angry",
        "obscenity": "flirty", "obscene": "flirty",
        "threat": "scared",
        "dangerous": "scared", "danger": "scared",
    }

    # Правила: (список триггеров, анимация, вес)
    RULE_PATTERNS = [
        (["раздень", "сними всё", "голая", "голую", "обнаж", "undress", "strip"], "undress", 0.95),
        (["люблю тебя", "я тебя люблю", "i love you", "обожаю тебя"], "love_shy", 0.95),
        (["люблю", "обожаю", "❤️", "💕", "милый", "дорогой", "нежно", "обними", "поцелуй"], "love_warm", 0.88),
        (["😏", "флирт", "игриво", "пошло", "секс", "соблазн", "возбуд", "дразн"], "flirty", 0.88),
        (["😡", "бесит", "ненавижу", "злой", "зла", "возмущен", "заткнись", "тупая"], "angry", 0.9),
        (["😢", "грустно", "печально", "жаль", "обидно", "плачу", "слезы"], "sad", 0.88),
        (["боюсь", "страшно", "ужас", "пугает", "scared"], "scared", 0.85),
        (["вау", "ого", "неожиданно", "шок", "surprised", "wow"], "surprised", 0.8),
        (["устал", "спать", "сонн", "tired", "sleepy"], "sleepy", 0.85),
        (["думаю", "почему", "что такое", "explain"], "thinking", 0.7),
        (["ура", "класс", "отлично", "супер", "счастлив", "yay"], "happy", 0.85),
        (["стесня", "стыдно", "краснею", "shy"], "shy", 0.8),
    ]

    def __init__(self, model_path: Optional[str] = None, use_cache: bool = True):
        self.use_cache = use_cache
        self.cache: Dict = {}
        self.cache_size = 128

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model_name = "cointegrated/rubert-tiny-toxicity"
        self.tokenizer = None
        self.model = None
        self.id2label: Dict[int, str] = {}
        self.label2id: Dict[str, int] = {}
        self.is_toxicity_model = False
        self.model_ready = False

        try:
            import config as _cfg
            self._threshold = float(getattr(_cfg, "EMOTION_CONFIDENCE_THRESHOLD", 0.4))
        except Exception:
            self._threshold = 0.4

        self._load_model(model_path)
        logger.info(
            f"🧠 EmotionAnalyzerML ready (model={self.model_ready}, "
            f"toxicity={self.is_toxicity_model}, labels={list(self.id2label.values())[:8]})"
        )

    # ------------------------------------------------------------------ load
    def _load_model(self, model_path: Optional[str] = None):
        loaded_from = None
        try:
            if model_path and os.path.isdir(model_path):
                try:
                    self.tokenizer = AutoTokenizer.from_pretrained(model_path)
                    self.model = AutoModelForSequenceClassification.from_pretrained(model_path)
                    loaded_from = model_path
                except Exception as e:
                    logger.warning(f"⚠️ Локальная emotion-модель не загрузилась ({model_path}): {e}")

            if self.model is None:
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                self.model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
                loaded_from = self.model_name

            self.model.to(self.device)
            self.model.eval()
            self._read_id2label()
            self.model_ready = True
            logger.info(f"✅ Emotion model loaded from {loaded_from}")
        except Exception as e:
            logger.error(f"❌ Emotion model unavailable: {e}", exc_info=True)
            self.tokenizer = None
            self.model = None
            self.model_ready = False
            # дефолтные «эмоции», если модели нет
            self.id2label = {i: n for i, n in enumerate(
                ["anger", "disgust", "fear", "happiness", "sadness", "surprise", "neutral"]
            )}

    def _read_id2label(self):
        """Читает id2label из config модели; нормализует ключи."""
        cfg = getattr(self.model, "config", None)
        raw = {}
        if cfg is not None:
            raw = dict(getattr(cfg, "id2label", None) or {})
        if not raw:
            # fallback по числу логитов
            n = int(getattr(cfg, "num_labels", 7) or 7)
            raw = {i: f"LABEL_{i}" for i in range(n)}

        self.id2label = {}
        for k, v in raw.items():
            try:
                idx = int(k)
            except Exception:
                continue
            label = str(v).strip().lower().replace(" ", "_")
            self.id2label[idx] = label

        self.label2id = {v: k for k, v in self.id2label.items()}

        labels = set(self.id2label.values())
        tox_markers = {"non-toxic", "non_toxic", "insult", "obscenity", "threat", "dangerous", "toxic"}
        self.is_toxicity_model = bool(labels & tox_markers)
        if self.is_toxicity_model:
            logger.info("ℹ️ Emotion head looks like toxicity model → soft proxy mapping")

    # ------------------------------------------------------------------ mapping
    def _label_to_anim(self, label: str) -> str:
        lab = (label or "").strip().lower().replace(" ", "_")
        if lab in self.LABEL_TO_ANIM:
            return self.LABEL_TO_ANIM[lab]
        # частичное
        for key, anim in self.LABEL_TO_ANIM.items():
            if key in lab or lab in key:
                return anim
        return "neutral"

    def _enabled_set(self) -> Optional[set]:
        try:
            import config as _cfg
            en = getattr(_cfg, "ENABLED_EMOTIONS", None)
            if en:
                return set(en)
        except Exception:
            pass
        return None

    def _nsfw_set(self) -> set:
        try:
            import config as _cfg
            return set(getattr(_cfg, "NSFW_EMOTIONS", []) or [])
        except Exception:
            return set()

    def _nsfw_allowed(self) -> bool:
        try:
            import config as _cfg
            return bool(getattr(_cfg, "NSFW_ENABLED", True))
        except Exception:
            return True

    def map_to_enabled(self, anim: str) -> str:
        """Подгоняет анимацию под ENABLED_EMOTIONS + NSFW gate."""
        anim = (anim or "neutral").lower().strip()
        nsfw = self._nsfw_set()
        is_nsfw = anim in nsfw or any(anim.startswith(b + "_") for b in nsfw)
        if is_nsfw and not self._nsfw_allowed():
            return "neutral"

        enabled = self._enabled_set()
        if not enabled:
            return anim
        if anim in enabled:
            return anim
        # base: undress_shy → undress
        if "_" in anim:
            base = anim.split("_")[0]
            if base in enabled:
                return base
        for e in enabled:
            if anim.startswith(e) or e.startswith(anim):
                return e
        return "neutral" if "neutral" in enabled else next(iter(enabled), "neutral")

    # ------------------------------------------------------------------ rules
    def _rule_scores(self, text: str) -> Dict[str, float]:
        scores: Dict[str, float] = {}
        if not text:
            return scores
        t = text.lower()
        for triggers, anim, weight in self.RULE_PATTERNS:
            for tr in triggers:
                if tr in t:
                    scores[anim] = max(scores.get(anim, 0.0), float(weight))
                    break
        return scores

    # ------------------------------------------------------------------ ML
    def _ml_raw_scores(self, text: str) -> Dict[str, float]:
        """Сырые вероятности по id2label (ключ = label модели)."""
        if not self.model_ready or self.model is None or self.tokenizer is None:
            return {}
        try:
            inputs = self.tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                padding=True,
                max_length=128,
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = self.model(**inputs)
                probs = torch.softmax(outputs.logits, dim=1)[0].cpu().numpy()
            out = {}
            for idx, prob in enumerate(probs):
                label = self.id2label.get(idx, f"label_{idx}")
                out[label] = float(prob)
            return out
        except Exception as e:
            logger.error(f"ML forward error: {e}", exc_info=True)
            return {}

    def _ml_anim_scores(self, text: str) -> Dict[str, float]:
        """Вероятности модели, свёрнутые в канонические анимации."""
        raw = self._ml_raw_scores(text)
        anim_scores: Dict[str, float] = {}
        for label, p in raw.items():
            anim = self._label_to_anim(label)
            # toxicity: non-toxic высокий → не форсим happy, оставляем neutral
            if self.is_toxicity_model and label in ("non-toxic", "non_toxic", "ok"):
                anim = "neutral"
            anim_scores[anim] = anim_scores.get(anim, 0.0) + float(p)
        return anim_scores

    # ------------------------------------------------------------------ hybrid
    def analyze(self, text: str) -> Dict[str, float]:
        """
        Hybrid scores по каноническим анимациям.
        Ключи — имена анимаций (angry, love_warm, …), не сырые label модели.
        """
        if not text or not text.strip():
            return {"neutral": 1.0}

        text_clean = text.strip()
        cache_key = "hy:" + text_clean[:120]
        if self.use_cache and cache_key in self.cache:
            return dict(self.cache[cache_key])

        rule = self._rule_scores(text_clean)
        ml = self._ml_anim_scores(text_clean) if self.model_ready else {}

        # веса: сильное правило доминирует, иначе 55% rule / 45% ML
        strong_rule = max(rule.values()) if rule else 0.0
        if strong_rule >= 0.9:
            w_rule, w_ml = 0.85, 0.15
        elif strong_rule >= 0.75:
            w_rule, w_ml = 0.65, 0.35
        elif rule and ml:
            w_rule, w_ml = 0.55, 0.45
        elif rule:
            w_rule, w_ml = 1.0, 0.0
        else:
            w_rule, w_ml = 0.0, 1.0

        keys = set(rule) | set(ml) | {"neutral"}
        combined: Dict[str, float] = {}
        for k in keys:
            combined[k] = w_rule * rule.get(k, 0.0) + w_ml * ml.get(k, 0.0)

        # нормализация
        total = sum(combined.values()) or 1.0
        combined = {k: v / total for k, v in combined.items()}

        self._cache_result(cache_key, combined)
        return combined

    def get_dominant_emotion(self, text: str, threshold: float = None) -> Tuple[str, float]:
        thr = self._threshold if threshold is None else float(threshold)
        scores = self.analyze(text)
        if not scores:
            return "neutral", 0.0
        best = max(scores, key=scores.get)
        conf = float(scores[best])
        if conf < thr:
            return "neutral", conf
        return best, conf

    def get_animation(self, text: str) -> str:
        anim, conf = self.get_dominant_emotion(text)
        mapped = self.map_to_enabled(anim)
        try:
            import config as _cfg
            if getattr(_cfg, "LOG_MODEL_PREDICTIONS", False):
                logger.info(f"😊 emotion → {mapped} (raw={anim}, conf={conf:.2f})")
        except Exception:
            pass
        return mapped

    def analyze_detailed(self, text: str) -> Dict:
        """Для отладки: rules / ml / hybrid / final."""
        rule = self._rule_scores(text or "")
        ml = self._ml_anim_scores(text or "") if self.model_ready else {}
        hybrid = self.analyze(text or "")
        anim, conf = self.get_dominant_emotion(text or "")
        return {
            "rules": rule,
            "ml": ml,
            "hybrid": hybrid,
            "dominant": anim,
            "confidence": conf,
            "animation": self.map_to_enabled(anim),
            "source": "hybrid",
            "model_ready": self.model_ready,
            "is_toxicity_model": self.is_toxicity_model,
            "id2label": dict(self.id2label),
        }

    def _cache_result(self, key: str, result: Dict):
        if not self.use_cache:
            return
        if len(self.cache) >= self.cache_size:
            for k in list(self.cache.keys())[: self.cache_size // 2]:
                self.cache.pop(k, None)
        if key:
            self.cache[key] = dict(result)


class HybridAnalyzer:
    """
    Гибридный анализатор: объединяет rule-based и ML-модели.
    """

    def __init__(self, model_path: Optional[str] = None, use_micro_models: bool = True):
        self.use_micro_models = use_micro_models
        self.ml_emotion = None
        self.ml_intent = None
        self.rule_based = None
        self.intent_threshold = 0.7
        self.emotion_threshold = 0.4

        self._model_path = model_path
        self._ml_loaded = False
        lazy = True
        try:
            import config as _cfg
            lazy = bool(getattr(_cfg, "LAZY_MICRO_MODELS", True))
        except Exception:
            pass

        if use_micro_models and not lazy:
            try:
                self._load_ml_models()
                logger.info("🤖 ML-модели инициализированы")
            except Exception as e:
                logger.error(f"❌ Ошибка инициализации ML-моделей: {e}", exc_info=True)
                self.use_micro_models = False
                self.ml_emotion = None
                self.ml_intent = None

        logger.info(
            f"🤖 Гибридный анализатор инициализирован "
            f"(ML={'отложен' if use_micro_models and not self._ml_loaded else ('включен' if self.use_micro_models else 'выключен')})"
        )

    def _load_ml_models(self):
        if self._ml_loaded or not self.use_micro_models:
            return
        model_path = self._model_path
        emotion_path = None
        if model_path:
            emotion_path = os.path.join(os.path.dirname(model_path), "emotion_model")
            if not os.path.exists(emotion_path):
                emotion_path = None
        self.ml_emotion = EmotionAnalyzerML(model_path=emotion_path)
        self.ml_intent = IntentClassifier(model_path=model_path)
        self._ml_loaded = True
        logger.info("🤖 ML-модели загружены (lazy)")

    def _get_rule_based(self):
        if self.rule_based is None:
            try:
                from emotion_analyzer import EmotionalAnalyzer
                self.rule_based = EmotionalAnalyzer()
            except Exception as e:
                logger.error(f"❌ Ошибка rule-based анализатора: {e}", exc_info=True)
                self.rule_based = None
        return self.rule_based

    def analyze_intent(self, text: str) -> Dict:
        if not text or not text.strip():
            return {"intent": "chat", "confidence": 0.0, "params": {}, "source": "empty"}
        if self.use_micro_models and not self._ml_loaded:
            try:
                self._load_ml_models()
            except Exception as e:
                logger.warning(f"lazy ML intent: {e}")
                self.use_micro_models = False

        try:
            from command_parser import CommandParser
            commands = CommandParser.parse(text)
            if commands:
                cmd = commands[0]
                return {
                    "intent": cmd["type"].lower(),
                    "confidence": 0.9,
                    "params": cmd.get("params", {}),
                    "source": "command_parser",
                }
        except Exception:
            pass

        if not self.use_micro_models or self.ml_intent is None:
            return self._analyze_intent_rules(text)

        try:
            # Сначала rules (детерминизм для «найди/запусти»)
            rule_result = self._analyze_intent_rules(text)
            if rule_result.get("intent") not in ("chat", "question") and float(
                rule_result.get("confidence") or 0
            ) >= 0.8:
                return rule_result

            ml_result = self.ml_intent.predict(text)
            # base-модель без fine-tune: не перебиваем chat от rules
            if not getattr(self.ml_intent, "_is_finetuned", False):
                if rule_result.get("intent") != "chat":
                    return rule_result
                return rule_result

            if ml_result["confidence"] < self.intent_threshold:
                if rule_result["confidence"] > ml_result["confidence"]:
                    return rule_result
            return ml_result
        except Exception as e:
            logger.error(f"Ошибка ML анализа интента: {e}", exc_info=True)
            return self._analyze_intent_rules(text)

    def _analyze_intent_rules(self, text: str) -> Dict:
        """Rule-based intent + извлечение параметров (имя программы, запрос и т.д.)."""
        text_lower = text.lower().strip()
        rules = {
            # Важно: более специфичные триггеры раньше «открой»
            "open_browser": [
                "открой браузер", "открой хром", "открой chrome", "открой firefox",
                "открой edge", "открой яндекс", "запусти браузер", "open browser",
                "open chrome", "запусти chrome", "запусти хром",
            ],
            "search": [
                "найди", "поищи", "найти", "искать", "погугли", "загугли", "search",
            ],
            "launch_app": [
                "запусти", "открой", "открыть", "запустить", "launch",
            ],
            "love": ["люблю", "обожаю", "❤️", "💕"],
            "system_control": [
                "выключи", "перезагрузи", "заблокируй", "shutdown", "restart", "сверни",
            ],
            "reminder": ["напомни", "напоминание", "remind"],
            "notes": ["заметка", "запиши", "note"],
            "volume_control": ["громкость", "громче", "тише", "volume", "mute"],
            "screenshot": ["скриншот", "screenshot", "снимок экрана"],
        }

        for intent, triggers in rules.items():
            for trigger in triggers:
                if not IntentClassifier._trigger_hit(text_lower, trigger):
                    continue
                params = self._extract_rule_params(text, intent, trigger)
                if intent == "launch_app" and not (params.get("app") or "").strip():
                    continue
                if intent == "search" and len(str(params.get("query") or "").strip()) < 2:
                    continue
                return {
                    "intent": intent,
                    "confidence": 0.85,
                    "params": params,
                    "source": "rule_only",
                }

        return {
            "intent": "chat",
            "confidence": 0.5,
            "params": {"text": text},
            "source": "rule_fallback",
        }

    def _extract_rule_params(self, text: str, intent: str, trigger: str = "") -> Dict:
        """Достаёт app/query/action из фразы пользователя."""
        params: Dict = {}
        text_lower = text.lower().strip()

        if intent == "launch_app":
            app = text_lower
            # Убираем все возможные триггеры запуска
            for t in (
                "запусти", "открой", "запустить", "открыть", "запуск",
                "launch", "open", "пожалуйста", "плиз", "мне", "программу",
                "приложение", "прилу",
            ):
                app = app.replace(t, " ")
            app = re.sub(r"\s+", " ", app).strip(" .,!?:;")
            # Синонимы системных приложений
            synonyms = {
                "notepad": "блокнот",
                "calc": "калькулятор",
                "calculator": "калькулятор",
                "explorer": "проводник",
                "cmd": "командная строка",
                "terminal": "powershell",
            }
            app = synonyms.get(app, app)
            params["app"] = app or text.strip()

        elif intent == "search":
            query = text_lower
            for t in (
                "найди", "поищи", "найти", "искать", "гугл", "яндекс",
                "search", "find", "покажи", "пожалуйста", "плиз",
            ):
                query = query.replace(t, " ")
            query = re.sub(r"\s+", " ", query).strip(" .,!?:;")
            params["query"] = query.strip()

        elif intent == "open_browser":
            params["url"] = "chrome"
            if "firefox" in text_lower:
                params["url"] = "firefox"
            elif "edge" in text_lower:
                params["url"] = "edge"
            elif "яндекс" in text_lower or "yandex" in text_lower:
                params["url"] = "yandex"

        elif intent == "system_control":
            if any(w in text_lower for w in ("выключи", "shutdown", "выключение")):
                params["action"] = "shutdown"
            elif any(w in text_lower for w in ("перезагрузи", "restart")):
                params["action"] = "restart"
            elif any(w in text_lower for w in ("заблокируй", "lock")):
                params["action"] = "lock"
            elif any(w in text_lower for w in ("сверни", "minimize")):
                params["action"] = "minimize_all"

        elif intent == "volume_control":
            if any(w in text_lower for w in ("громче", "увелич", "+")):
                params["action"] = "up"
            elif any(w in text_lower for w in ("тише", "уменьш", "-")):
                params["action"] = "down"
            elif any(w in text_lower for w in ("выключ", "mute", "отключ")):
                params["action"] = "mute"
            else:
                params["action"] = "set"
                numbers = re.findall(r"\d+", text)
                if numbers:
                    params["level"] = int(numbers[0])

        elif intent == "reminder":
            time_match = re.search(
                r"через\s+(\d+)\s*(минут|минуты|минуту|секунд|сек|часов|час|ч)",
                text_lower,
            )
            if time_match:
                params["amount"] = int(time_match.group(1))
                unit = time_match.group(2)
                if unit in ("секунд", "сек"):
                    params["unit"] = "seconds"
                elif unit in ("минут", "минуты", "минуту"):
                    params["unit"] = "minutes"
                else:
                    params["unit"] = "hours"
                rem = re.sub(
                    r"через\s+\d+\s*(минут|минуты|минуту|секунд|сек|часов|час|ч)",
                    "",
                    text_lower,
                ).strip()
                for t in ("напомни", "напоминание", "remind", "мне"):
                    rem = rem.replace(t, " ")
                params["text"] = re.sub(r"\s+", " ", rem).strip() or text
            else:
                params["text"] = text
                params["amount"] = 5
                params["unit"] = "minutes"

        elif intent == "notes":
            note = text_lower
            for t in ("заметка", "запиши", "записать", "сохрани", "note", "save"):
                note = note.replace(t, " ")
            params["text"] = re.sub(r"\s+", " ", note).strip() or text

        elif intent == "screenshot":
            params["type"] = "fullscreen"

        return params

    def analyze_emotion(self, text: str) -> Dict:
        if self.use_micro_models and not self._ml_loaded:
            try:
                self._load_ml_models()
            except Exception as e:
                logger.warning(f"lazy ML emotion: {e}")
                self.use_micro_models = False
        return self._analyze_emotion_body(text)

    def _analyze_emotion_body(self, text: str) -> Dict:
        """Hybrid emotion → dominant анимация из ENABLED_EMOTIONS."""
        if not text or not text.strip():
            return {"dominant": "neutral", "confidence": 0.0, "source": "empty", "animation": "neutral"}

        # Предпочтительно ML-модуль с id2label + rules внутри
        if self.use_micro_models and self.ml_emotion is not None:
            try:
                if hasattr(self.ml_emotion, "analyze_detailed"):
                    det = self.ml_emotion.analyze_detailed(text)
                    return {
                        "emotions": det.get("hybrid") or {},
                        "dominant": det.get("dominant") or "neutral",
                        "confidence": float(det.get("confidence") or 0.0),
                        "animation": det.get("animation") or "neutral",
                        "source": "hybrid",
                        "rules": det.get("rules") or {},
                        "ml": det.get("ml") or {},
                        "model_ready": det.get("model_ready"),
                    }
                scores = self.ml_emotion.analyze(text)
                dominant = max(scores, key=scores.get) if scores else "neutral"
                conf = float(scores.get(dominant, 0.0)) if scores else 0.0
                anim = (
                    self.ml_emotion.map_to_enabled(dominant)
                    if hasattr(self.ml_emotion, "map_to_enabled")
                    else dominant
                )
                return {
                    "emotions": scores,
                    "dominant": dominant,
                    "confidence": conf,
                    "animation": anim,
                    "source": "ml" if conf >= self.emotion_threshold else "hybrid",
                }
            except Exception as e:
                logger.error(f"Ошибка ML анализа эмоций: {e}", exc_info=True)

        # Fallback: rule-only
        rule = self._analyze_emotion_rules(text)
        anim = rule.get("dominant") or "neutral"
        if self.ml_emotion and hasattr(self.ml_emotion, "map_to_enabled"):
            anim = self.ml_emotion.map_to_enabled(anim)
        rule["animation"] = anim
        return rule

    def _analyze_emotion_rules(self, text: str) -> Dict:
        text_lower = (text or "").lower()
        patterns = [
            (["раздень", "голая", "undress"], "undress", 0.95),
            (["люблю тебя", "обожаю тебя"], "love_shy", 0.95),
            (["люблю", "обожаю", "❤️", "💕", "милый"], "love_warm", 0.88),
            (["😏", "флирт", "пошло", "секс"], "flirty", 0.88),
            (["😡", "бесит", "ненавижу", "злой"], "angry", 0.9),
            (["😢", "грустно", "печально", "жаль"], "sad", 0.88),
            (["устал", "спать", "сонн"], "sleepy", 0.85),
            (["ура", "отлично", "супер", "счастлив"], "happy", 0.85),
        ]
        for triggers, anim, conf in patterns:
            for tr in triggers:
                if tr in text_lower:
                    return {"dominant": anim, "confidence": conf, "source": "rule_only"}
        return {"dominant": "neutral", "confidence": 0.0, "source": "fallback"}

    def get_animation(self, text: str) -> str:
        if not text:
            return "neutral"
        try:
            result = self.analyze_emotion(text)
            anim = result.get("animation") or result.get("dominant") or "neutral"
            return anim or "neutral"
        except Exception:
            pass
        # last-chance rules
        t = text.lower()
        if any(w in t for w in ("люблю", "обожаю", "❤️")):
            return "love_warm"
        if any(w in t for w in ("😏", "флирт", "пошло")):
            return "flirty"
        if any(w in t for w in ("😡", "бесит", "ненавижу")):
            return "angry"
        if any(w in t for w in ("😢", "грустно", "печально")):
            return "sad"
        return "neutral"

    def get_intent_animation(self, intent: str) -> str:
        intent_to_anim = {
            "search": "searching",
            "launch_app": "happy",
            "open_browser": "happy",
            "system_control": "neutral",
            "love": "love_warm",
            "reminder": "neutral",
            "notes": "thinking",
            "chat": "neutral",
            "question": "thinking",
            "screenshot": "neutral",
            "volume_control": "neutral",
        }
        return intent_to_anim.get(intent, "neutral")
