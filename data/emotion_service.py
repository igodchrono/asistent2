# emotion_service.py — ЕДИНЫЙ путь эмоций/анимаций
"""
Один анализатор на всё приложение:
  GUI, AnimationSelector, LMAssistant → get_shared_analyzer()

Порядок:
  1) HybridAnalyzer (ML + правила + id2label), если USE_MICRO_MODELS
  2) rule-based EmotionalAnalyzer
  3) None (neutral)

Не создавать второй HybridAnalyzer в GUI — только этот модуль.
"""
from __future__ import annotations

from typing import Any, Optional
import logging

import config

logger = logging.getLogger(__name__)

_shared: Optional[Any] = None
_init_done = False


def get_shared_analyzer(force_reload: bool = False):
    """Singleton-анализатор. Повторные вызовы дешёвые."""
    global _shared, _init_done
    if _shared is not None and not force_reload:
        return _shared
    if _init_done and not force_reload:
        return _shared

    _init_done = True
    use_micro = bool(getattr(config, "USE_MICRO_MODELS", False))
    use_hybrid = bool(getattr(config, "USE_HYBRID_ANALYZER", True))
    lazy = bool(getattr(config, "LAZY_MICRO_MODELS", True))

    if use_micro and use_hybrid:
        try:
            from micro_models import HybridAnalyzer
            model_path = getattr(config, "MICRO_MODEL_PATH", None) or getattr(
                config, "INTENT_MODEL_PATH", None
            )
            _shared = HybridAnalyzer(
                model_path=model_path,
                use_micro_models=True,
            )
            logger.info(
                "emotion_service: HybridAnalyzer (единый%s)"
                % (", lazy-ready" if lazy else ", load-now")
            )
            return _shared
        except Exception as e:
            logger.warning(f"emotion_service: HybridAnalyzer недоступен: {e}")

    try:
        from emotion_analyzer import EmotionalAnalyzer
        _shared = EmotionalAnalyzer()
        logger.info("emotion_service: rule-based EmotionalAnalyzer")
        return _shared
    except Exception as e:
        logger.error(f"emotion_service: нет анализатора: {e}")
        _shared = None
        return None


def resolve_animation(text: str, intent: Optional[str] = None) -> str:
    """Единая точка выбора анимации по тексту (учитывает ENABLED_EMOTIONS)."""
    analyzer = get_shared_analyzer()
    if not analyzer:
        return "neutral"
    try:
        # Hybrid / EmotionAnalyzerML
        if hasattr(analyzer, "analyze_emotion"):
            result = analyzer.analyze_emotion(text or "")
            anim = result.get("animation") or result.get("dominant")
            if anim:
                return str(anim)
        if hasattr(analyzer, "get_animation"):
            anim = analyzer.get_animation(text or "")
            if anim:
                return str(anim)
        if hasattr(analyzer, "analyze_full_context"):
            emotion, _ = analyzer.analyze_full_context(text or "")
            if emotion and hasattr(analyzer, "get_animation"):
                return str(analyzer.get_animation(emotion) or "neutral")
    except Exception as e:
        logger.debug(f"resolve_animation: {e}")
    return "neutral"


def resolve_intent_animation(intent: Optional[str]) -> str:
    analyzer = get_shared_analyzer()
    if analyzer and intent and hasattr(analyzer, "get_intent_animation"):
        try:
            return str(analyzer.get_intent_animation(intent) or "neutral")
        except Exception:
            pass
    return "neutral"
