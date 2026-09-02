# chat_settings.py — смена настроек фразой в чате
from __future__ import annotations

import re
from typing import Any, Optional, Tuple

import config

BOOL_ON = re.compile(r"(?i)^\s*(вкл|включи|включить|да|true|on|1)\s*$")
BOOL_OFF = re.compile(r"(?i)^\s*(выкл|выключи|выключить|нет|false|off|0)\s*$")

# фраза-кусок → (ключ config, тип)
ALIASES = [
    (r"порог ocr|ocr min|min_score|чувствительн\w* ocr", "SCREEN_OCR_MIN_SCORE", "float"),
    (r"движок ocr|ocr engine", "SCREEN_OCR_ENGINE", "str"),
    (r"язык ocr|ocr lang", "SCREEN_OCR_LANG", "str"),
    (r"лимит ocr|max_chars", "SCREEN_OCR_MAX_CHARS", "int"),
    (r"монитор по умолчанию|фокус монитора", "SCREEN_FOCUS_DEFAULT", "str"),
    (r"ocr|распознаван\w* текста", "SCREEN_OCR_ENABLED", "bool"),
    (r"просмотр экрана|смотреть экран|screen vision", "SCREEN_VISION_ENABLED", "bool"),
    (r"автопросмотр|авто.?слежен", "SCREEN_VISION_AUTO", "bool"),
    (r"автосообщен|авто.?привет|пнуть когда молчу", "ENABLE_AUTO_GREETING", "bool"),
    (r"llm.?привет|автосообщен\w* с llm|привет через llm", "GREETING_USE_LLM", "bool"),
    (r"nsfw|пошл", "NSFW_ENABLED", "bool"),
    (r"интернет", "ENABLE_INTERNET", "bool"),
    (r"управлен\w* пк|пк.?контрол", "ENABLE_PC_CONTROL", "bool"),
    (r"голос на вход|микрофон|stt", "ENABLE_VOICE_INPUT", "bool"),
    (r"голос на выход|озвучк|tts", "ENABLE_VOICE_OUTPUT", "bool"),
    (r"микро.?модел", "USE_MICRO_MODELS", "bool"),
    (r"безопасн\w* режим|safe mode", "SAFE_MODE", "bool"),
    (r"открывать браузер", "SEARCH_OPEN_BROWSER", "bool"),
    (r"температур", "TEMPERATURE", "float"),
    (r"частот\w* nsfw|nsfw frequency", "NSFW_FREQUENCY", "float"),
    (r"браузер по умолчанию", "DEFAULT_BROWSER", "str"),
    (r"поисковик|search engine", "SEARCH_ENGINE", "str"),
    (r"быстр\w* модель|fast model|модель для экрана", "FAST_MODEL", "str"),
    (r"модель для зрения|vision model", "SCREEN_VISION_MODEL", "str"),
    (r"модель(?!и)", "MODEL_NAME", "str"),
    (r"сторона кадра|max_side", "SCREEN_VISION_MAX_SIDE", "int"),
    (r"интервал авто.?мин", "GREETING_INTERVAL_MIN", "int"),
    (r"интервал авто.?макс", "GREETING_INTERVAL_MAX", "int"),
]


SHOW_RE = re.compile(
    r"(?i)^\s*(покажи|выведи|какие)\s+(настройк|параметр|ocr|конфиг)"
)
SET_RE = re.compile(
    r"(?i)^\s*(?:лисичка[,\s]+)?("
    r"включи|выключи|поставь|установи|смени|измени|сделай|"
    r"переключи|выставь"
    r")\s+(.+)$"
)


def _parse_bool(chunk: str) -> Optional[bool]:
    if BOOL_ON.search(chunk) or re.search(r"(?i)\bвключи", chunk):
        return True
    if BOOL_OFF.search(chunk) or re.search(r"(?i)\bвыключи", chunk):
        return False
    return None


def _parse_value(kind: str, raw: str) -> Any:
    raw = raw.strip(" .!?,")
    if kind == "bool":
        v = _parse_bool(raw)
        return v
    if kind == "float":
        m = re.search(r"(\d+[.,]\d+|\d+)", raw.replace(",", "."))
        return float(m.group(1)) if m else None
    if kind == "int":
        m = re.search(r"(\d+)", raw)
        return int(m.group(1)) if m else None
    if kind == "str":
        raw = re.sub(r"(?i)^(на|в|как|равн[оа]|это)\s+", "", raw).strip()
        aliases = {
            "средний": "center", "центр": "center", "центральный": "center",
            "левый": "left", "правый": "right",
            "активный": "active", "основной": "primary", "все": "all",
            "гугл": "google", "яндекс": "yandex",
            "хром": "chrome", "хрома": "chrome",
        }
        key = raw.lower()
        if key in aliases:
            return aliases[key]
        for a, v in aliases.items():
            if a in key:
                return v
        return raw.strip()
    return raw


def _match_alias(text: str) -> Optional[Tuple[str, str]]:
    for rx, key, kind in ALIASES:
        if re.search(rx, text, re.I):
            return key, kind
    return None


def format_value(v: Any) -> str:
    if v is True:
        return "вкл"
    if v is False:
        return "выкл"
    return str(v)


def show_settings() -> str:
    keys = [
        "SCREEN_OCR_ENABLED", "SCREEN_OCR_ENGINE", "SCREEN_OCR_LANG",
        "SCREEN_OCR_MIN_SCORE", "SCREEN_VISION_ENABLED", "SCREEN_VISION_AUTO",
        "SCREEN_FOCUS_DEFAULT", "SCREEN_VISION_MAX_SIDE",
        "ENABLE_AUTO_GREETING", "NSFW_ENABLED", "NSFW_FREQUENCY",
        "ENABLE_INTERNET", "ENABLE_PC_CONTROL", "SAFE_MODE",
        "TEMPERATURE", "MODEL_NAME", "FAST_MODEL", "SCREEN_VISION_MODEL",
        "SEARCH_ENGINE", "DEFAULT_BROWSER",
        "ENABLE_VOICE_INPUT", "ENABLE_VOICE_OUTPUT",
    ]
    lines = ["⚙️ Настройки:"]
    for k in keys:
        lines.append(f"  {k} = {format_value(getattr(config, k, '—'))}")
    return "\n".join(lines)


def list_api_models() -> str:
    import urllib.request
    import json
    base = str(getattr(config, "API_URL", "") or "").rstrip("/")
    if base.endswith("/v1"):
        url = base + "/models"
    else:
        url = base + "/v1/models"
    configured = getattr(config, "MODEL_NAME", "")
    lines = [f"в settings/config: {configured}", f"API: {url}"]
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {getattr(config, 'API_KEY', 'lm-studio')}"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        ids = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
        if not ids:
            lines.append("API не вернул список моделей (ничего не загружено?)")
        else:
            lines.append("загружено в сервере:")
            for i in ids:
                mark = " ← сейчас в настройках" if i == configured else ""
                lines.append(f"  - {i}{mark}")
            if configured not in ids:
                lines.append(f"⚠ {configured} нет среди загруженных")
    except Exception as e:
        lines.append(f"не достучалась до API: {e}")
    return "\n".join(lines)


def apply(key: str, value: Any) -> str:
    setattr(config, key, value)
    try:
        from settings_manager import USER_KEYS, load_settings, save_settings
        if isinstance(USER_KEYS, set):
            USER_KEYS.add(key)
        data = load_settings()
        data[key] = value
        save_settings(data)
    except Exception:
        try:
            import json
            import os
            path = os.path.join(getattr(config, "DATA_DIR", "."), "settings.json")
            cur = {}
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    cur = json.load(f) or {}
            cur[key] = value
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cur, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return f"✅ {key} = {format_value(value)}"


def try_chat_setting(text: str) -> Optional[str]:
    t = (text or "").strip()
    if not t:
        return None
    if SHOW_RE.search(t) or re.search(r"(?i)^\s*настройки\s*[?]?\s*$", t):
        return show_settings()
    if re.search(r"(?i)(какая модель|какие модели|покажи модели|модель в api)", t):
        return list_api_models()

    # включи OCR / выключи автосообщения
    m = re.match(
        r"(?i)^\s*(?:лисичка[,\s]+)?(включи|выключи|поставь|установи|смени|выставь)\s+(.+)$",
        t,
    )
    if not m:
        return None
    verb, rest = m.group(1).lower(), m.group(2).strip()
    hit = _match_alias(rest)
    if not hit:
        return None
    key, kind = hit
    if kind == "bool" and verb in ("включи", "выключи"):
        val = verb.startswith("вкл")
    else:
        val = _parse_value(kind, rest)
        if kind == "bool" and val is None:
            val = verb.startswith("вкл")
    if val is None:
        return f"Не поняла значение для {key}"
    if key == "SCREEN_OCR_ENGINE":
        allowed = {"auto", "rapidocr", "tesseract", "easyocr"}
        v = str(val).lower()
        if v not in allowed:
            return "Движок OCR: auto / rapidocr / tesseract / easyocr"
        val = v
    return apply(key, val)
