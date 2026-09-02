# config.py — Полный файл конфигурации для Лисички
# ============================================================

import os
import re

# ============================================================
# ОПРЕДЕЛЕНИЕ БАЗОВЫХ ПУТЕЙ
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if os.path.basename(BASE_DIR) == "data":
    inner_data = os.path.join(BASE_DIR, "data")
    if os.path.exists(inner_data) and os.path.isdir(inner_data):
        DATA_DIR = inner_data
    else:
        DATA_DIR = BASE_DIR
else:
    possible_data = os.path.join(BASE_DIR, "data")
    if os.path.exists(possible_data) and os.path.isdir(possible_data):
        DATA_DIR = possible_data
    else:
        DATA_DIR = os.path.join(BASE_DIR, "data")

os.makedirs(DATA_DIR, exist_ok=True)

# ============================================================
# МИКРО-МОДЕЛИ - ПУТИ
# ============================================================

MODELS_DIR = os.path.join(DATA_DIR, "models")
os.makedirs(MODELS_DIR, exist_ok=True)


def _resolve_model_subdir(name: str) -> str:
    """
    Единый канонический путь: data/models/<name>
    Legacy fallback: data/<name> (если там есть веса, а в models/ пусто).
    """
    primary = os.path.join(MODELS_DIR, name)
    legacy = os.path.join(DATA_DIR, name)

    def _has_weights(p: str) -> bool:
        if not os.path.isdir(p):
            return False
        for f in ("config.json", "pytorch_model.bin", "model.safetensors",
                  "tf_model.h5", "intents.json"):
            if os.path.isfile(os.path.join(p, f)):
                return True
        try:
            return any(os.scandir(p))
        except Exception:
            return False

    if _has_weights(primary):
        return primary
    if _has_weights(legacy):
        print(f"⚠️ Модель {name}: legacy путь {legacy} → лучше перенести в {primary}")
        return legacy
    os.makedirs(primary, exist_ok=True)
    return primary


INTENT_MODEL_PATH = _resolve_model_subdir("intent_model")
EMOTION_MODEL_PATH = _resolve_model_subdir("emotion_model")

# ============================================================
# НАСТРОЙКИ МИКРО-МОДЕЛЕЙ
# ============================================================

# Ежедневный стабильный режим: микро-модели не в горячем пути.
USE_MICRO_MODELS = True
MICRO_MODEL_PATH = INTENT_MODEL_PATH
USE_HYBRID_ANALYZER = True
# Не грузить torch/микро-модели на старте — только при первом запросе.
LAZY_MICRO_MODELS = True
# Router может подсказывать intent, но не исполняет команды сам.
INTENT_ROUTER_ENABLED = False
INTENT_ROUTER_EXECUTE = False

INTENT_CONFIDENCE_THRESHOLD = 0.7
# Short-circuit микро-модели (ускоритель). Выше = реже обходим LLM.
# Основной путь команд: LLM → CommandParser → Executor.
INTENT_ACCELERATE_THRESHOLD = 0.92
EMOTION_CONFIDENCE_THRESHOLD = 0.4

ENABLE_MODEL_CACHE = True
MODEL_CACHE_SIZE = 100

LOG_MODEL_PREDICTIONS = True

# Не поднимать semantic/embeddings, пока в индексе мало чанков.
RAG_LAZY_EMBEDDINGS = True
RAG_MIN_CHUNKS_FOR_SEMANTIC = 8

# ============================================================
# API НАСТРОЙКИ
# ============================================================

API_URL = "http://26.26.15.18:1234/v1"
# Запуск GUI не ждёт этот адрес. Если молчит — команды работают, чат без модели.
LLM_PING_TIMEOUT = 1.5
LLM_CONNECT_TIMEOUT = 3
LLM_TIMEOUT = 300
LLM_SOCK_READ_TIMEOUT = 300
API_KEY = "not-needed"
MODEL_NAME = "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive"
FAST_MODEL = "qwen3-vl-8b-instruct-abliterated-v2.0"

TEMPERATURE = 0.4
MAX_TOKENS = 1000
CHAT_HISTORY_TURNS = 6
CHAT_HISTORY_CHARS = 360
CHAT_USER_CHARS = 800
CHAT_MAX_SENTENCES = 3

# ============================================================
# СИСТЕМНЫЙ ПРОМПТ
# ============================================================

# Запасной промпт. Личность — personas/characters/<ACTIVE_CHARACTER>.md
SYSTEM_PROMPT = """Ты виртуальный ассистент. Имя, внешность, характер и манеру речи бери из активного файла персонажа.

Правила:
1. В каждом ответе ровно один тег [ANIM:имя] в начале.
2. Поиск в интернете — только через [SEARCH запрос]. Не выдумывай результаты и ссылки.
3. Запуск программ — [LAUNCH название].
4. Опасные действия (удаление, shutdown, kill) — только с confirm.

Команды: [SEARCH запрос] [LAUNCH название] [OPEN путь] [RUN команда]
[MINIMIZE all] [WINDOWS] [SCREENSHOT] [DISK_SPACE]
[NOTE текст] [REMINDER текст через N минут]
[VOLUME N] [MUTE] [SHUTDOWN confirm] [RESTART confirm]

Анимации: neutral, happy, happy_big, thinking, searching, angry, idle, dance, sad, cry,
love, love_warm, love_shy, blush, flirty, teasing, undress, undress_shy, sleepy, tired, playful.
"""

# Модульный промпт (prompt_builder.py при старте собирает полный)
USE_MODULAR_PROMPT = True
BASE_SYSTEM_PROMPT = SYSTEM_PROMPT


# ============================================================
# ПУТИ И ФАЙЛЫ
# ============================================================

DB_PATH = os.path.join(DATA_DIR, "assistant_memory.db")
PERSISTENT_MEMORY_DB = os.path.join(DATA_DIR, "persistent_memory.db")
REMINDER_DB_PATH = os.path.join(DATA_DIR, "reminders.db")
ADVANCED_RAG_DB = os.path.join(DATA_DIR, "advanced_rag.db")
APP_SCANNER_DB = os.path.join(DATA_DIR, "apps.db")

FRAMES_DIR = os.path.join(DATA_DIR, "frames")
FILES_DIR = os.path.join(DATA_DIR, "files")
SCREENSHOTS_DIR = os.path.join(FILES_DIR, "screenshots")
DOWNLOADS_DIR = os.path.join(FILES_DIR, "downloads")
NOTES_DIR = os.path.join(FILES_DIR, "notes")
DOCUMENTS_DIR = os.path.join(FILES_DIR, "documents")
SAVE_DIR = SCREENSHOTS_DIR
NOTES_FILE = os.path.join(NOTES_DIR, "notes.md")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
TEMP_DIR = os.path.join(DATA_DIR, "temp")

for path in [
    FRAMES_DIR, FILES_DIR, SCREENSHOTS_DIR, DOWNLOADS_DIR,
    NOTES_DIR, DOCUMENTS_DIR, SAVE_DIR, LOGS_DIR, TEMP_DIR, MODELS_DIR,
]:
    os.makedirs(path, exist_ok=True)

VOSK_MODEL_PATH = os.path.join(DATA_DIR, "vosk-model-small-ru-0.22")

# ============================================================
# RAG НАСТРОЙКИ
# ============================================================

RAG_AUTO_INDEX = False
# --- Персонажи / пользователь (плагины) ---
# personas/characters/*.md  и  personas/users/*.md
PERSONA_DIR = "personas"
ACTIVE_CHARACTER = "лисичка"   # имя файла без .md
ACTIVE_USER = "default"
RAG_DOCS_EXTRA = []            # доп. md в RAG
# RAG_DOCS собирается character_manager при старте; legacy:
RAG_DOCS = []
RAG_EXTRA_DIRS = ["rag_docs"]

ADVANCED_RAG_ENABLED = True
# nomic-embed-text-v1.5 → обычно 768; при другом embedder подстрой
ADVANCED_RAG_DIMENSION = 768
RAG_CONTEXT_TIMEOUT = 5.0  # hybrid чуть дольше keyword

# hybrid = keyword + FAISS (рекомендуется при живом /v1/embeddings)
RAG_HYBRID_MODE = True
RAG_DEFAULT_MODE = "hybrid"  # keyword | semantic | hybrid
RAG_MIN_SIMILARITY = 0.22
RAG_CHUNK_SIZE = 350
RAG_OVERLAP = 60
RAG_CACHE_SIZE = 1500

# Отдельная embedding-модель (НЕ chat!). LM Studio: nomic-embed-text-…
EMBEDDING_MODEL = "text-embedding-nomic-embed-text-v1.5"
EMBEDDING_TIMEOUT = 6.0

# Не дергать RAG на коротких репликах
RAG_SKIP_SHORT_QUERY = True
RAG_MIN_QUERY_CHARS = 12
RAG_MIN_QUERY_WORDS = 2
RAG_CONTEXT_LIMIT = 4
RAG_MAX_CONTEXT_CHARS = 2200
# RRF: semantic чуть сильнее (LIKE шумит), имена всё равно поднимает keyword
RAG_RRF_K = 60
RAG_RRF_WEIGHT_KEYWORD = 0.45
RAG_RRF_WEIGHT_SEMANTIC = 1.0
MEMORY_CONTEXT_LIMIT = 5

# ============================================================
# АВТО-СООБЩЕНИЯ (ОБНОВЛЕНО)
# ============================================================

ENABLE_AUTO_GREETING = False
GREETING_INTERVAL_MIN = 180          # Минимальный интервал (сек)
GREETING_INTERVAL_MAX = 420          # Максимальный интервал (сек) ~7 мин
GREETING_NSFW_CHANCE = 0.35          # Шанс NSFW (0-1)

# НОВЫЕ ПАРАМЕТРЫ ДЛЯ LLM ГЕНЕРАЦИИ
GREETING_USE_LLM = False             # простой = шаблон из карточки, не 35B
GREETING_MAX_RETRIES = 15.0          # Таймаут в секундах
GREETING_TEMPERATURE = 0.9           # Креативность (0-1)
GREETING_MAX_TOKENS = 60             # Максимум токенов

# ============================================================
# НАСТРОЕНИЕ
# ============================================================

TIME_AWARE_ENABLED = True
TIME_AWARE_IN_GREETINGS = True
# границы суток по местным часам ПК
TIME_HOURS = {"morning": 6, "day": 11, "evening": 18, "late": 23}

# Анимации по времени суток (утро→happy_big, ночь→sleepy/idle)
TIME_BASED_ANIMS = True
TIME_BASED_ANIM_MAP = {
    "morning": "happy_big",
    "day": "happy",
    "evening": "idle",
    "night": "sleepy",
}

# Память анимаций: повтор фраз («спасибо»×3 → love_warm)
MEMORY_ANIMS = True

MOOD_HOLD_SECONDS = 900
MOOD_PLAYFUL_HOLD_SECONDS = 1200
MOOD_PLAYFUL_NSFW_CHANCE = 0.65

# ============================================================
# NSFW НАСТРОЙКИ
# ============================================================

NSFW_ENABLED = True
NSFW_FREQUENCY = 0.65
NSFW_EMOTIONS_WEIGHT = 1.0

NSFW_EMOTIONS = [
    "undress", "undress_happy", "undress_sly", "undress_love",
    "undress_shy", "undress_playful", "undress_seductive",
    "undress_teasing", "undress_mischievous",
    "seductive", "seductive_happy",
    "flirty", "flirty_happy",
    "teasing", "teasing_sly",
    "dominant", "dominant_happy", "dominant_sly",
    "submissive", "submissive_happy", "submissive_shy",
    "lingerie", "lingerie_happy",
    "bath", "bath_shy", "bath_happy",
    "bed", "bed_love", "bed_shy",
    "naked", "naked_shy"
]

ENABLED_EMOTIONS = [
    "neutral", "neutral_happy", "neutral_sad", "neutral_angry", "neutral_love",
    "happy", "happy_big", "happy_sly", "happy_love",
    "thinking", "thinking_happy", "thinking_sad", "thinking_angry", "thinking_love",
    "searching", "searching_happy", "searching_sad", "searching_angry",
    "pointing", "pointing_happy", "pointing_angry", "pointing_love",
    "angry", "angry_frustrated", "angry_sad", "angry_angry",
    "love", "love_warm", "love_shy", "love_happy", "love_sad", "love_sly",
    "idle", "idle_sad", "idle_happy", "idle_angry", "idle_sly",
    "dance", "dance_happy", "dance_sly", "dance_love",
    "undress", "undress_happy", "undress_sly", "undress_love",
    "undress_shy", "undress_playful", "undress_seductive",
    "undress_teasing", "undress_mischievous",
    "seductive", "seductive_happy",
    "flirty", "flirty_happy",
    "teasing", "teasing_sly",
    "dominant", "dominant_happy", "dominant_sly",
    "submissive", "submissive_happy", "submissive_shy",
    "lingerie", "lingerie_happy",
    "bath", "bath_shy", "bath_happy",
    "bed", "bed_love", "bed_shy",
    "naked", "naked_shy",
    "blush", "blush_shy", "blush_happy",
    "cry", "cry_sad", "cry_angry",
    "surprised", "surprised_happy", "surprised_shocked",
    "shocked", "scared",
    "sly", "sly_happy", "sly_mischievous",
    "sleepy", "tired", "sick",
    "proud", "proud_happy", "proud_confident",
    "embarrassed",
    "jealous", "jealous_angry", "jealous_sad",
    "mischievous", "mischievous_happy", "mischievous_sly",
    "innocent",
    "confident", "confident_happy", "confident_dominant",
    "shy", "shy_happy", "shy_blush",
    "playful", "playful_happy", "playful_mischievous",
    "giggling", "pouting", "smirking"
]

# ============================================================
# БЕЗОПАСНОСТЬ
# ============================================================

SAFE_MODE = True
HARD_SANDBOX = True  # запрет System32/Windows даже вне ALLOWED_DIRS
LLM_CIRCUIT_FAILS = 3
LLM_CIRCUIT_COOLDOWN = 120  # сек offline-режим lifecycle
GREETING_LLM_TIMEOUT = 60.0

# Первая загрузка большой модели в LM Studio / Ollama может занять минуты.
LLM_TIMEOUT = 300.0          # весь запрос, сек
LLM_CONNECT_TIMEOUT = 90.0   # установка соединения
LLM_SOCK_READ_TIMEOUT = 300.0

RUN_WHITELIST = [
    "notepad.exe", "explorer.exe", "chrome.exe", "msedge.exe",
    "firefox.exe", "calc.exe", "cmd.exe", "powershell.exe"
]
ALLOWED_DIRS = [
    r"C:\Users",
    r"E:\AI",
    r"E:\Games",
    r"D:\asistent\data",
    FILES_DIR,
]
REQUIRE_CONFIRM_FOR = ["DELETE", "SHUTDOWN", "RESTART", "KILL", "EMPTY RECYCLE"]
LOG_LEVEL = "INFO"
LOG_FILE = "assistant.log"

# ============================================================
# ПОИСК
# ============================================================

ENABLE_INTERNET = True

# Экран: ручная команда «посмотри». Автослежение выкл.
SCREEN_VISION_ENABLED = True
SCREEN_VISION_AUTO = False
SCREEN_ALLOWED_MONITORS = None  # None = все; иначе [0, 1] слева направо
SCREEN_VISION_AUTO_INTERVAL = 60
SCREEN_VISION_MAX_SIDE = 1600
SCREEN_VISION_MODEL = "qwen3-vl-8b-instruct-abliterated-v2.0"
SCREEN_OCR_ENABLED = True
SCREEN_OCR_ENGINE = "auto"       # auto | rapidocr | tesseract | easyocr
SCREEN_OCR_LANG = "rus+eng"      # tesseract: rus+eng
SCREEN_OCR_LANGS = ["ru", "en"]  # easyocr
SCREEN_OCR_MIN_SCORE = 0.45      # отбросить слабые куски RapidOCR
SCREEN_OCR_PSM = 6               # tesseract: 6 = блок текста
SCREEN_OCR_OEM = 3               # tesseract LSTM
SCREEN_OCR_MAX_CHARS = 3500
SCREEN_OCR_JPEG_QUALITY = 90     # выше = мельче шрифт читается лучше
SCREEN_FOCUS_DEFAULT = "all"     # all | left | center | right | primary | active
SEARCH_ENGINE = "google"
SEARCH_SAFE_MODE = "off"
SEARCH_NUM_RESULTS = 10
SEARCH_CACHE_TTL = 3600
SEARCH_OPEN_BROWSER = True
USE_ASSISTANT_BROWSER = False

# ============================================================
# БРАУЗЕР
# ============================================================

DEFAULT_BROWSER = "chrome"
BROWSER_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# ============================================================
# УПРАВЛЕНИЕ ПК
# ============================================================

ENABLE_PC_CONTROL = True

# ============================================================
# АНАЛИЗ ПОВЕДЕНИЯ
# ============================================================

BEHAVIOR_ANALYSIS_ENABLED = True
BEHAVIOR_ANALYSIS_DAYS = 30

# ============================================================
# АНАЛИЗ ЭКРАНА
# ============================================================

SCREEN_ANALYSIS_ENABLED = True
SCREEN_ANALYSIS_MODEL = None

# ============================================================
# СИСТЕМНЫЙ МОНИТОР
# ============================================================

ENABLE_SYSTEM_MONITOR = False
MONITOR_INTERVAL = 60
CPU_THRESHOLD = 85
RAM_THRESHOLD = 85
DISK_THRESHOLD = 8
PROCESS_THRESHOLD = 300

# ============================================================
# ПАМЯТЬ
# ============================================================

MAX_MEMORIES_IN_CONTEXT = 5

# ============================================================
# ИНТЕРФЕЙС
# ============================================================

AVATAR_SIZE = 302
SHOW_AVATAR = True
ANIMATION_SPEED = 80
DEFAULT_ANIMATION = "happy"
ENABLE_STREAMING = True
FONT_SIZE = 12
SHOW_TYPING_INDICATOR = True
THEME = "dark"

# ============================================================
# ХРОМАКЕЙ
# ============================================================

CHROMA_KEY_ENABLED = True
CHROMA_KEY_COLOR = "#00FF00"
CHROMA_KEY_TOLERANCE = 45
CHROMA_KEY_SOFTNESS = 28

# ============================================================
# ГОЛОС
# ============================================================

ENABLE_VOICE_INPUT = False
ENABLE_VOICE_OUTPUT = True

# push = кнопка 🎤 (нажал — сказал)
# wake = всегда слушает, команда после кодового слова (как Алиса/Siri)
VOICE_INPUT_MODE = "push"
WAKE_WORD = "лисичка"  # можно сменить в настройках

VOICE_RECOGNITION_ENGINE = "vosk"
GOOGLE_SPEECH_API_KEY = ""
VOICE_LANGUAGE = "ru-RU"
VOICE_INPUT_DEVICE = None

# silero | edge-tts | pyttsx3 | openai | custom
VOICE_SYNTHESIS_ENGINE = "silero"
# Silero: xenia (моложе) | kseniya | baya | aidar | eugene
# Edge: ru-RU-SvetlanaNeural
VOICE_NAME = "xenia"
SILERO_SPEAKER = "xenia"
SILERO_SAMPLE_RATE = 48000  # 8000 | 24000 | 48000
VOICE_SPEED = 8   # чуть быстрее — «живее» для персонажа
VOICE_VOLUME = 1.0
VOICE_GENDER = "female"
VOICE_OUTPUT_DEVICE = None
VOICE_BUTTON_TEXT = "🎤"

# ============================================================
# VOSK
# ============================================================

VOSK_MODEL_PATH = os.path.join(DATA_DIR, "vosk-model-small-ru-0.22")

# ============================================================
# СТРИМИНГ
# ============================================================

ENABLE_STREAMING = True

def frame_emotion_stats():
    """Сверка списка эмоций и файлов в frames/. Кадры можно догенерировать позже."""
    listed = [str(x).lower() for x in (ENABLED_EMOTIONS or [])]
    nsfw = [str(x).lower() for x in (NSFW_EMOTIONS or [])]
    on_disk = set()
    try:
        if os.path.isdir(FRAMES_DIR):
            for _root, _dirs, files in os.walk(FRAMES_DIR):
                for f in files:
                    fl = f.lower()
                    if not fl.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".webm", ".mp4")):
                        continue
                    stem = os.path.splitext(f)[0]
                    stem = re.sub(r"_(sprite|strip)_\d+(x\d+)?$", "", stem, flags=re.I)
                    stem = re.sub(r"_\d+$", "", stem)
                    on_disk.add(stem.lower())
    except Exception:
        pass
    ready = [n for n in listed if n in on_disk]
    missing = [n for n in listed if n not in on_disk]
    nsfw_ready = [n for n in nsfw if n in on_disk]
    return {
        "listed": len(listed),
        "ready": len(ready),
        "missing": missing,
        "nsfw_listed": len(nsfw),
        "nsfw_ready": len(nsfw_ready),
        "files": len(on_disk),
    }


def print_banner():
    """Печатать ПОСЛЕ settings.json, иначе цифры врут."""
    who = str(globals().get("ACTIVE_CHARACTER") or "персонаж")
    st = frame_emotion_stats()
    miss = st["missing"]
    miss_s = ", ".join(miss[:8]) + ("…" if len(miss) > 8 else "")
    print("=" * 70)
    print(f"🎭 КОНФИГУРАЦИЯ — {who}")
    print("=" * 70)
    print(f"📁 BASE_DIR: {BASE_DIR}")
    print(f"📁 DATA_DIR: {DATA_DIR}")
    print(f"📁 MODELS_DIR: {MODELS_DIR}")
    print("=" * 70)
    print(f"🤖 USE_MICRO_MODELS: {USE_MICRO_MODELS}")
    print(f"📁 INTENT_MODEL: {INTENT_MODEL_PATH}")
    print(f"📁 EMOTION_MODEL: {EMOTION_MODEL_PATH}")
    print(f"🎯 INTENT_THRESHOLD: {INTENT_CONFIDENCE_THRESHOLD}")
    print(f"😊 EMOTION_THRESHOLD: {EMOTION_CONFIDENCE_THRESHOLD}")
    print("=" * 70)
    print(f"🔞 NSFW_ENABLED: {NSFW_ENABLED}  freq={NSFW_FREQUENCY}")
    print(f"🎭 Имена в коде: {st['listed']} | файлов в frames/: {st['files']} | совпало: {st['ready']}")
    print(f"🎭 NSFW в коде: {st['nsfw_listed']} | файлов NSFW-имён: {st['nsfw_ready']}")
    if miss:
        print(f"🎭 Нет кадра ({len(miss)}): {miss_s}")
    print(f"🌡️ TEMPERATURE: {TEMPERATURE}")
    print(f"🧠 MODEL_NAME: {MODEL_NAME}")
    print(f"👁 SCREEN_VISION_MODEL: {globals().get('SCREEN_VISION_MODEL', '')}")
    print("=" * 70)
    print(f"📚 RAG_DOCS: {RAG_DOCS}")
    print(f"🔊 VOICE in={ENABLE_VOICE_INPUT} out={ENABLE_VOICE_OUTPUT} wake={WAKE_WORD!r}")
    print(f"🛡️ SAFE_MODE={SAFE_MODE} PC={ENABLE_PC_CONTROL} NET={ENABLE_INTERNET}")
    print(f"💬 AUTO_GREETING={ENABLE_AUTO_GREETING} LLM={GREETING_USE_LLM}")
    print("=" * 70)