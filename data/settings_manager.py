# settings_manager.py — пользовательские настройки в settings.json поверх config.py
# ИСПРАВЛЕНО: единый источник правды, нет рассинхрона config ↔ settings
from __future__ import annotations

import json
import os
import re
import logging
from typing import Any, Dict, Set

logger = logging.getLogger(__name__)

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

# Ключи, которые GUI / пользователь может менять.
# Всё остальное всегда берётся из config.py (defaults).
USER_KEYS: Set[str] = {
    # API и модель
    "API_URL",
    "API_KEY",
    "MODEL_NAME",
    "SYSTEM_PROMPT",
    "TEMPERATURE",
    "MAX_TOKENS",
    # RAG / embeddings
    "ADVANCED_RAG_ENABLED",
    "ADVANCED_RAG_DIMENSION",
    "RAG_HYBRID_MODE",
    "RAG_DEFAULT_MODE",
    "RAG_MIN_SIMILARITY",
    "RAG_CONTEXT_TIMEOUT",
    "RAG_CONTEXT_LIMIT",
    "RAG_MAX_CONTEXT_CHARS",
    "RAG_SKIP_SHORT_QUERY",
    "RAG_MIN_QUERY_CHARS",
    "RAG_MIN_QUERY_WORDS",
    "RAG_CHUNK_SIZE",
    "RAG_OVERLAP",
    "RAG_CACHE_SIZE",
    "EMBEDDING_MODEL",
    "EMBEDDING_TIMEOUT",
    "MEMORY_CONTEXT_LIMIT",
    "RAG_AUTO_INDEX",
    "USE_MICRO_MODELS",
    "USE_HYBRID_ANALYZER",
    "LAZY_MICRO_MODELS",
    "INTENT_ROUTER_ENABLED",
    "INTENT_ROUTER_EXECUTE",
    "INTENT_ACCELERATE_THRESHOLD",
    
    # Интерфейс
    "AVATAR_SIZE",
    "ANIMATION_SPEED",
    "DEFAULT_ANIMATION",
    "ENABLED_EMOTIONS",
    
    # Интернет и управление ПК
    "ENABLE_INTERNET",
    "ENABLE_PC_CONTROL",
    "SAFE_MODE",
    
    # Поиск
    "SEARCH_ENGINE",
    "SEARCH_SAFE_MODE",
    "SEARCH_OPEN_BROWSER",
    "SEARCH_NUM_RESULTS",
    "SEARCH_WEB_MIN_SCORE",
    
    # Браузер
    "DEFAULT_BROWSER",
    "BROWSER_PATH",
    
    # NSFW
    "NSFW_ENABLED",
    "NSFW_FREQUENCY",
    
    # Голос (STT)
    "ENABLE_VOICE_INPUT",
    "ENABLE_VOICE_OUTPUT",
    "VOICE_RECOGNITION_ENGINE",
    "GOOGLE_SPEECH_API_KEY",
    "VOICE_LANGUAGE",
    "VOICE_INPUT_DEVICE",
    "VOICE_OUTPUT_DEVICE",
    "VOICE_INPUT_MODE",
    "WAKE_WORD",
    "ACTIVE_CHARACTER",
    "ACTIVE_USER",
    "PERSONA_DIR",
    
    # Голос (TTS)
    "VOICE_SYNTHESIS_ENGINE",
    "VOICE_NAME",
    "SILERO_SPEAKER",
    "VOICE_SPEED",
    "VOICE_VOLUME",
    "VOICE_GENDER",
    "VOICE_TTS_MODEL",
    "VOICE_TTS_API_KEY",
    "VOICE_TTS_API_URL",
    
    # Стриминг
    "ENABLE_STREAMING",
    
    # Авто-сообщения
    "ENABLE_AUTO_GREETING",
    "GREETING_INTERVAL_MIN",
    "GREETING_INTERVAL_MAX",
    "GREETING_NSFW_CHANCE",
    "GREETING_USE_LLM",
    "GREETING_MAX_RETRIES",
    "GREETING_TEMPERATURE",
    "GREETING_MAX_TOKENS",
    "TIME_AWARE_ENABLED",
    "TIME_AWARE_IN_GREETINGS",
    "TIME_BASED_ANIMS",
    "TIME_BASED_ANIM_MAP",
    "MEMORY_ANIMS",
    "SHOW_AVATAR",
    "SCREEN_OCR_ENABLED",
    "SCREEN_OCR_ENGINE",
    "SCREEN_OCR_LANG",
    "SCREEN_OCR_MIN_SCORE",
    "SCREEN_VISION_ENABLED",
    "SCREEN_VISION_AUTO",
    "SCREEN_VISION_AUTO_INTERVAL",
    "SCREEN_VISION_MAX_SIDE",
    "SCREEN_VISION_MODEL",
    "SCREEN_FOCUS_DEFAULT",
    "CHAT_MAX_SENTENCES",
    "FAST_MODEL",
}


def load_settings() -> Dict[str, Any]:
    """
    Читает settings.json.
    При ошибке возвращает пустой dict (не падает).
    """
    if not os.path.isfile(SETTINGS_FILE):
        logger.debug(f"settings.json не найден: {SETTINGS_FILE}")
        return {}
    
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        if not isinstance(data, dict):
            logger.warning("settings.json: корневой объект не dict — игнорируем")
            return {}
        
        logger.debug(f"Загружено {len(data)} настроек из {SETTINGS_FILE}")
        return data
    
    except json.JSONDecodeError as e:
        logger.error(f"settings.json: невалидный JSON — {e}")
        return {}
    except Exception as e:
        logger.error(f"settings.json: ошибка чтения — {e}", exc_info=True)
        return {}


def save_settings(data: Dict[str, Any]) -> bool:
    """
    Сохраняет только разрешённые ключи.
    Мержит с уже существующим файлом, чтобы не терять настройки.
    Возвращает True при успехе.
    """
    if not data:
        logger.warning("Попытка сохранить пустые настройки")
        return False
    
    try:
        # Создаём директорию, если нужно
        settings_dir = os.path.dirname(SETTINGS_FILE)
        if settings_dir:
            os.makedirs(settings_dir, exist_ok=True)
        
        # Загружаем текущие настройки
        current = load_settings()
        
        # Обновляем только разрешённые ключи
        saved_keys = []
        for key, value in data.items():
            if not isinstance(key, str):
                continue
            ok = (
                key in USER_KEYS
                or key.startswith(("VOICE_", "SEARCH_", "NSFW_", "GREETING_", "SCREEN_", "SHOW_", "CHAT_", "ENABLE_", "API_", "MODEL_"))
                or bool(re.match(r"^[A-Z][A-Z0-9_]+$", key))
            )
            if not ok:
                continue
            try:
                json.dumps(value)
            except TypeError:
                value = str(value)
            current[key] = value
            saved_keys.append(key)
        
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_FILE)
        print(f"💾 settings.json ({len(saved_keys)} ключей) -> {SETTINGS_FILE}")
        
        logger.info(f"settings.json: сохранено {len(saved_keys)} ключей")
        logger.debug(f"Сохранённые ключи: {', '.join(saved_keys[:10])}")
        return True
    
    except Exception as e:
        logger.error(f"settings.json: ошибка записи — {e}", exc_info=True)
        return False


def apply_to_config(config_module) -> Dict[str, Any]:
    """
    Накладывает settings.json поверх defaults из config.py.
    config.py всегда остаётся источником значений по умолчанию.
    Возвращает словарь реально применённых ключей.
    """
    data = load_settings()
    if not data:
        logger.info("Нет пользовательских настроек для применения")
        return {}
    
    applied: Dict[str, Any] = {}
    skipped: Dict[str, Any] = {}
    
    for key, value in data.items():
        # Проверяем, разрешён ли ключ
        if key not in USER_KEYS and not key.startswith(("VOICE_", "SEARCH_", "NSFW_", "GREETING_", "WAKE_", "SILERO_", "ACTIVE_", "PERSONA_", "RAG_", "SCREEN_", "SHOW_", "CHAT_")):
            skipped[key] = value
            continue
        
        try:
            setattr(config_module, key, value)
            applied[key] = value
        except Exception as e:
            logger.warning(f"Не удалось применить настройку {key}: {e}")
            skipped[key] = value
    
    if applied:
        logger.info(f"✅ settings.json: применено {len(applied)} настроек")
        logger.debug(f"Применённые ключи: {', '.join(list(applied.keys())[:10])}")
    
    if skipped:
        logger.debug(f"Пропущенные ключи: {', '.join(list(skipped.keys())[:10])}")
    
    return applied


def snapshot_from_config(config_module) -> Dict[str, Any]:
    """
    Снимок текущих значений USER_KEYS из config (для GUI / отладки).
    """
    out: Dict[str, Any] = {}
    for key in USER_KEYS:
        if hasattr(config_module, key):
            out[key] = getattr(config_module, key)
    return out


def get_effective(key: str, config_module, default: Any = None) -> Any:
    """
    Единая точка чтения настройки:
    1. settings.json (если есть)
    2. config.py
    3. default
    """
    settings = load_settings()
    if key in settings:
        return settings[key]
    if hasattr(config_module, key):
        return getattr(config_module, key)
    return default


def reset_to_defaults(config_module) -> bool:
    """
    Сбрасывает все пользовательские настройки.
    Удаляет settings.json и перезагружает config.
    """
    try:
        if os.path.exists(SETTINGS_FILE):
            os.remove(SETTINGS_FILE)
            logger.info(f"settings.json удалён: {SETTINGS_FILE}")
        
        # Перезагружаем config (применяем defaults)
        import importlib
        importlib.reload(config_module)
        
        logger.info("Настройки сброшены к значениям по умолчанию")
        return True
    
    except Exception as e:
        logger.error(f"Ошибка сброса настроек: {e}", exc_info=True)
        return False


def get_settings_info() -> Dict[str, Any]:
    """
    Возвращает информацию о текущих настройках.
    """
    info = {
        "settings_file": SETTINGS_FILE,
        "file_exists": os.path.exists(SETTINGS_FILE),
        "user_keys_count": len(USER_KEYS),
        "user_keys": sorted(list(USER_KEYS)),
    }
    
    if os.path.exists(SETTINGS_FILE):
        try:
            stat = os.stat(SETTINGS_FILE)
            info["file_size"] = stat.st_size
            info["modified"] = stat.st_mtime
        except Exception:
            pass
        
        settings = load_settings()
        info["settings_count"] = len(settings)
    
    return info


# ============================================================
# КОНСОЛЬНАЯ УТИЛИТА
# ============================================================

if __name__ == "__main__":
    print("=" * 70)
    print("⚙️ МЕНЕДЖЕР НАСТРОЕК")
    print("=" * 70)
    
    info = get_settings_info()
    print(f"\n📁 Файл: {info['settings_file']}")
    print(f"📄 Существует: {info['file_exists']}")
    print(f"📊 Ключей: {info['user_keys_count']}")
    
    if info.get('settings_count'):
        print(f"📝 Загружено настроек: {info['settings_count']}")
    
    print("\n🔑 Доступные ключи:")
    for key in info['user_keys'][:15]:
        print(f"   • {key}")
    if len(info['user_keys']) > 15:
        print(f"   ... и ещё {len(info['user_keys']) - 15} ключей")

def get_setting(key: str, default: Any = None) -> Any:
    """
    Единая точка чтения настройки:
    1) settings.json (если ключ есть)
    2) иначе config.py
    3) иначе default
    """
    data = load_settings()
    if key in data:
        return data[key]
    try:
        import config as _cfg
        if hasattr(_cfg, key):
            return getattr(_cfg, key)
    except Exception:
        pass
    return default


def reload_config(config_module=None) -> Dict[str, Any]:
    """Перечитать settings.json и наложить на config. Для GUI после Save."""
    if config_module is None:
        import config as config_module
    return apply_to_config(config_module)
