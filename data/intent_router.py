# intent_router.py — микро-модель только как ускоритель очевидных команд
"""
Основной путь команд: LLM → CommandParser → CommandExecutor.
Микро-модель (HybridAnalyzer) — только short-circuit для
высокоуверенных, полностью параметризованных action-интентов.

Использование из LMAssistant:
    router = IntentRouter(analyzer, intent_to_command_fn)
    decision = router.try_accelerate(user_message)
    if decision.should_execute:
        result = await executor.execute_async(decision.command)
        ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional
import logging

import config

logger = logging.getLogger(__name__)

# Интенты, которые МОЖНО выполнить без LLM (только при полной уверенности)
ACCELERABLE_INTENTS = frozenset({
    "search",
    "launch_app",
    "open_browser",
    "screenshot",
    "volume_control",
    "system_control",  # только lock / minimize_all — shutdown/restart без confirm не ускоряем
    "reminder",
    "notes",
})

# Опасные system_control — никогда не short-circuit
DANGEROUS_SYSTEM_ACTIONS = frozenset({"shutdown", "restart", "kill"})


@dataclass
class RouteDecision:
    """Результат маршрутизации одного user-сообщения."""
    should_execute: bool = False
    command: Optional[Dict[str, Any]] = None
    intent: Optional[str] = None
    confidence: float = 0.0
    source: str = "none"          # ml | rule | command_parser | none
    reason: str = ""              # почему ускорили / почему нет
    hint_for_llm: str = ""        # подсказка в system prompt, если не ускорили


class IntentRouter:
    """
    Решает: выполнить команду сразу или отдать в LLM.

    Порог по умолчанию выше, чем старый INTENT_CONFIDENCE_THRESHOLD,
    и обязательны непустые params для action-интентов.
    """

    def __init__(
        self,
        analyzer=None,
        intent_to_command: Optional[Callable[[str, Dict], Optional[Dict]]] = None,
        confidence_threshold: Optional[float] = None,
    ):
        self.analyzer = analyzer
        self._intent_to_command = intent_to_command
        # Жёстче, чем раньше: ускоритель, не центр
        self.threshold = float(
            confidence_threshold
            if confidence_threshold is not None
            else getattr(config, "INTENT_ACCELERATE_THRESHOLD", 0.88)
        )

    def try_accelerate(self, user_message: str) -> RouteDecision:
        """
        Пытается распознать очевидную команду.
        Возвращает RouteDecision; should_execute=True только при полной готовности.
        """
        text = (user_message or "").strip()
        if not text:
            return RouteDecision(reason="empty")

        # 1) Явные теги команд в сообщении пользователя — редко, но надёжно
        try:
            from command_parser import CommandParser
            cmds = CommandParser.parse(text)
            # Игнорируем только ANIM
            action_cmds = [c for c in cmds if c.get("type") and c["type"] != "ANIM"]
            if len(action_cmds) == 1:
                return RouteDecision(
                    should_execute=True,
                    command=action_cmds[0],
                    intent=action_cmds[0]["type"].lower(),
                    confidence=1.0,
                    source="command_parser",
                    reason="явный тег команды в сообщении",
                )
        except Exception as e:
            logger.debug(f"IntentRouter CommandParser: {e}")

        if not self.analyzer or not hasattr(self.analyzer, "analyze_intent"):
            return RouteDecision(reason="нет анализатора")

        try:
            result = self.analyzer.analyze_intent(text)
        except Exception as e:
            logger.error(f"IntentRouter analyze_intent: {e}")
            return RouteDecision(reason=f"ошибка анализа: {e}")

        if not result or not isinstance(result, dict):
            return RouteDecision(reason="пустой результат анализа")

        intent = (result.get("intent") or "chat").lower()
        confidence = float(result.get("confidence") or 0.0)
        params = result.get("params") or {}
        source = result.get("source") or "ml"

        # chat / question / love / flirty / undress → всегда в LLM
        if intent in ("chat", "question", "love", "flirty", "undress", "file_operation"):
            return RouteDecision(
                intent=intent,
                confidence=confidence,
                source=source,
                reason=f"интент «{intent}» идёт в LLM",
                hint_for_llm=self._hint(intent, confidence),
            )

        if intent not in ACCELERABLE_INTENTS:
            return RouteDecision(
                intent=intent,
                confidence=confidence,
                source=source,
                reason=f"интент «{intent}» не в списке ускоряемых",
                hint_for_llm=self._hint(intent, confidence),
            )

        if confidence < self.threshold:
            return RouteDecision(
                intent=intent,
                confidence=confidence,
                source=source,
                reason=f"уверенность {confidence:.2f} < порога {self.threshold}",
                hint_for_llm=self._hint(intent, confidence),
            )

        # Опасные system actions — только через LLM + confirm
        if intent == "system_control":
            action = (params.get("action") or "").lower()
            if action in DANGEROUS_SYSTEM_ACTIONS or not action:
                return RouteDecision(
                    intent=intent,
                    confidence=confidence,
                    source=source,
                    reason=f"system_control/{action or '?'} требует LLM+confirm",
                    hint_for_llm=self._hint(intent, confidence),
                )

        if not self._intent_to_command:
            return RouteDecision(
                intent=intent,
                confidence=confidence,
                source=source,
                reason="нет intent_to_command",
                hint_for_llm=self._hint(intent, confidence),
            )

        command = self._intent_to_command(intent, params)
        if not command:
            return RouteDecision(
                intent=intent,
                confidence=confidence,
                source=source,
                reason="неполные params (команда не собрана)",
                hint_for_llm=self._hint(intent, confidence),
            )

        # Доп. проверка: SEARCH/LAUNCH без содержимого не ускоряем
        if command["type"] == "SEARCH" and not str(command.get("params") or "").strip():
            return RouteDecision(
                intent=intent,
                confidence=confidence,
                source=source,
                reason="SEARCH без query",
                hint_for_llm=self._hint(intent, confidence),
            )
        if command["type"] == "LAUNCH" and not str(command.get("params") or "").strip():
            return RouteDecision(
                intent=intent,
                confidence=confidence,
                source=source,
                reason="LAUNCH без имени",
                hint_for_llm=self._hint(intent, confidence),
            )

        logger.info(
            f"⚡ Ускорение: {intent} conf={confidence:.2f} source={source} → {command['type']}"
        )
        return RouteDecision(
            should_execute=True,
            command=command,
            intent=intent,
            confidence=confidence,
            source=source,
            reason="высокая уверенность + полные params",
        )

    @staticmethod
    def _hint(intent: str, confidence: float) -> str:
        if not intent or intent in ("chat", "question"):
            return ""
        return (
            f"[ПОДСКАЗКА ИНТЕНТА] Возможно: {intent} "
            f"(уверенность {confidence:.0%}). "
            f"Если это действие — используй соответствующий тег команды."
        )
