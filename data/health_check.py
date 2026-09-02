# health_check.py — простой health-check при старте Лисички
"""
Проверяет:
- доступность API (LM Studio / OpenAI-совместимый)
- наличие микро-моделей (intent + emotion)
- папку frames и хотя бы одну анимацию
- ключевые БД и директории
- голос (опционально)
"""

from __future__ import annotations

import os
import sys
import time
import logging
from typing import Dict, List, Tuple, Any, Optional

logger = logging.getLogger(__name__)


def _ok(msg: str) -> Tuple[bool, str]:
    return True, f"✅ {msg}"


def _warn(msg: str) -> Tuple[bool, str]:
    return False, f"⚠️ {msg}"


def _fail(msg: str) -> Tuple[bool, str]:
    return False, f"❌ {msg}"


def check_api(timeout: float = 4.0) -> Tuple[bool, str]:
    """Проверка доступности LLM API."""
    try:
        import config
        import requests

        url = getattr(config, "API_URL", "").rstrip("/")
        key = getattr(config, "API_KEY", "not-needed")
        if not url:
            return _fail("API_URL пустой")

        headers = {"Authorization": f"Bearer {key}"}
        r = requests.get(f"{url}/models", headers=headers, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            models = data.get("data") or data.get("models") or []
            names = [m.get("id") or m.get("name") or "?" for m in models[:5]]
            extra = f" ({', '.join(names)})" if names else ""
            return _ok(f"API доступен{extra}")
        return _warn(f"API ответил {r.status_code}")
    except Exception as e:
        return _fail(f"API недоступен: {e}")


def check_models() -> Tuple[bool, str]:
    """Проверка микро-моделей (intent + emotion)."""
    try:
        import config

        intent = getattr(config, "INTENT_MODEL_PATH", "")
        emotion = getattr(config, "EMOTION_MODEL_PATH", "")
        missing = []

        def _has_model(path: str) -> bool:
            if not path or not os.path.isdir(path):
                return False
            files = os.listdir(path)
            has_cfg = any(f in files for f in ("config.json", "tokenizer_config.json"))
            has_weights = any(
                f.endswith((".bin", ".safetensors")) or f == "pytorch_model.bin"
                for f in files
            )
            return has_cfg and has_weights

        if not _has_model(intent):
            missing.append("intent_model")
        if not _has_model(emotion):
            missing.append("emotion_model")

        if not missing:
            return _ok("Микро-модели на месте (intent + emotion)")
        if getattr(config, "USE_MICRO_MODELS", False):
            return _warn(f"Нет моделей: {', '.join(missing)} → fallback на правила")
        return _ok("Микро-модели не используются (USE_MICRO_MODELS=False)")
    except Exception as e:
        return _fail(f"Проверка моделей: {e}")


def check_frames() -> Tuple[bool, str]:
    """Проверка папки frames и наличия хотя бы одной анимации/статики."""
    try:
        import config

        frames = getattr(config, "FRAMES_DIR", "")
        if not frames or not os.path.isdir(frames):
            return _warn(f"Папка frames не найдена: {frames}")

        categories = ["basic", "thinking", "searching", "idle", "dance", "nsfw", "extra", "pointing"]
        found_emotions = set()
        total_files = 0

        for cat in categories:
            path = os.path.join(frames, cat)
            if not os.path.isdir(path):
                continue
            for f in os.listdir(path):
                if f.lower().endswith((".png", ".jpg", ".jpeg")):
                    total_files += 1
                    base = os.path.splitext(f)[0]
                    # убираем _sprite_N / _strip_NxM
                    import re
                    base = re.sub(r"_(sprite|strip)_\d+(x\d+)?", "", base)
                    found_emotions.add(base)

        if total_files == 0:
            return _warn("В frames/ нет изображений — будет заглушка")
        return _ok(f"Frames: {total_files} файлов, эмоций ~{len(found_emotions)}")
    except Exception as e:
        return _fail(f"Проверка frames: {e}")


def check_databases() -> Tuple[bool, str]:
    """Проверка ключевых БД и директорий."""
    try:
        import config

        paths = {
            "DATA_DIR": getattr(config, "DATA_DIR", ""),
            "MEMORY_DB": getattr(config, "DB_PATH", ""),
            "PERSISTENT": getattr(config, "PERSISTENT_MEMORY_DB", ""),
            "RAG": getattr(config, "ADVANCED_RAG_DB", ""),
            "APPS": getattr(config, "APP_SCANNER_DB", ""),
            "LOGS": getattr(config, "LOGS_DIR", ""),
            "SAVE": getattr(config, "SAVE_DIR", ""),
        }
        problems = []
        for name, p in paths.items():
            if not p:
                problems.append(f"{name}=пусто")
                continue
            if name.endswith("_DB") or name in ("MEMORY_DB", "PERSISTENT", "RAG", "APPS"):
                # БД может ещё не существовать — это нормально
                parent = os.path.dirname(p) or "."
                if not os.path.isdir(parent):
                    try:
                        os.makedirs(parent, exist_ok=True)
                    except Exception:
                        problems.append(f"{name} parent")
            else:
                if not os.path.isdir(p):
                    try:
                        os.makedirs(p, exist_ok=True)
                    except Exception:
                        problems.append(name)

        if problems:
            return _warn(f"Проблемы путей: {', '.join(problems)}")
        return _ok("Директории и пути БД в порядке")
    except Exception as e:
        return _fail(f"Проверка БД: {e}")


def check_voice() -> Tuple[bool, str]:
    """Лёгкая проверка голосовых настроек (не блокирует)."""
    try:
        import config

        parts = []
        if getattr(config, "ENABLE_VOICE_INPUT", False):
            vosk = getattr(config, "VOSK_MODEL_PATH", "")
            if vosk and os.path.isdir(vosk):
                parts.append("Vosk OK")
            else:
                parts.append("Vosk модель не найдена (будет Google/fallback)")
        else:
            parts.append("STT выключен")

        engine = getattr(config, "VOICE_SYNTHESIS_ENGINE", "edge-tts")
        if getattr(config, "ENABLE_VOICE_OUTPUT", False):
            parts.append(f"TTS={engine}")
        else:
            parts.append("TTS выключен")

        return _ok("Голос: " + ", ".join(parts))
    except Exception as e:
        return _warn(f"Голос: {e}")


def check_pc_control() -> Tuple[bool, str]:
    try:
        import config
        if not getattr(config, "ENABLE_PC_CONTROL", True):
            return _ok("Управление ПК отключено")
        # лёгкая проверка
        try:
            import pyautogui  # noqa: F401
            import psutil  # noqa: F401
            return _ok("ПК-контроль: зависимости на месте")
        except ImportError as e:
            return _warn(f"ПК-контроль: не хватает пакета ({e})")
    except Exception as e:
        return _warn(f"ПК-контроль: {e}")


def run_health_check(verbose: bool = True) -> Dict[str, Any]:
    """
    Запускает все проверки.
    Возвращает dict: {ok: bool, checks: [(name, ok, msg), ...], summary: str}
    """
    checks_spec = [
        ("API", check_api),
        ("Models", check_models),
        ("Frames", check_frames),
        ("Paths/DB", check_databases),
        ("Voice", check_voice),
        ("PC Control", check_pc_control),
    ]

    results: List[Tuple[str, bool, str]] = []
    all_ok = True

    if verbose:
        print("\n" + "=" * 60)
        print("🩺 HEALTH-CHECK ЛИСИЧКИ")
        print("=" * 60)

    for name, fn in checks_spec:
        try:
            ok, msg = fn()
        except Exception as e:
            ok, msg = False, f"❌ {name}: {e}"
        results.append((name, ok, msg))
        if not ok and not msg.startswith("⚠️"):
            all_ok = False
        if verbose:
            print(f"  {msg}")

    critical_fail = any(
        (not ok) and msg.startswith("❌") for _, ok, msg in results
    )

    if verbose:
        print("=" * 60)
        if critical_fail:
            print("❌ Есть критические проблемы — ассистент может работать нестабильно")
        elif not all_ok:
            print("⚠️ Есть предупреждения, но можно запускать")
        else:
            print("✅ Всё в порядке, можно работать")
        print("=" * 60 + "\n")

    return {
        "ok": not critical_fail,
        "all_green": all_ok and not critical_fail,
        "checks": results,
        "summary": "ok" if not critical_fail else "critical",
    }


if __name__ == "__main__":
    # Для ручного запуска: python health_check.py
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    run_health_check(verbose=True)
