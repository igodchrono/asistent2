# screen_watch.py — ручной «посмотри на экран» + реакция по содержимому
from __future__ import annotations

import base64
import io
import os
import re
import time
from typing import Optional, Tuple

import config

LOOK_RE = re.compile(
    r"(?i)("
    r"посмотри\s+на\s+экран|глянь\s+на\s+экран|смотри\s+на\s+экран|"
    r"что\s+(ты\s+)?(вид[еи]шь|видишь|видешь)\s+на\s+экране|"
    r"что\s+(у\s+меня\s+)?на\s+экране|что\s+там\s+на\s+экране|"
    r"что\s+открыто|опиши\s+(мне\s+)?экран|покажи\s+что\s+на\s+экране|"
    r"что\s+я\s+смотрю|что\s+у\s+меня\s+открыто|"
    r"посмотри\s+сюда|посмотри\s+что\s+тут|"
    r"look\s+at\s+(the\s+)?screen|what('?s| is) on (my )?screen|"
    r"(левый|правый|средний|центр(альный)?|основной|главный|активный|этот|текущий)\s+(монитор|экран)|"
    r"(монитор|экран)\s*(№|#|number)?\s*\d+|"
    r"(первый|второй|третий|четвёртый|четвертый)\s+(монитор|экран)|"
    r"все\s+(мониторы|экраны)|"
    r"повнимательн|ещё раз посмотр|еще раз посмотр|"
    r"назван\w*\s+файл|прочитай\s+назван|список\s+файл|"
    r"что\s+там\s+(за\s+)?файл|"
    r"какой\s+текст|что\s+написано|прочитай\s+текст|скопируй\s+текст|"
    r"проанализ\w*\s+(мой\s+)?(экран|скрин|скриншот)|"
    r"проанализ\w*\s+(его|её|этот|тот|скрин|скриншот)|"
    r"разбери\s+(мой\s+)?(экран|скрин|скриншот)|"
    r"что\s+на\s+скрине|опиши\s+скрин|"
    r"analyze\s+(my\s+)?(screen|screenshot)"
    r")"
)
LOOK_SHORT = re.compile(r"(?i)^\s*(посмотри|глянь|смотри|look|проанализируй|разбери)\s*[.!?…]*\s*$")
LOOK_BLOCK = re.compile(
    r"(?i)(найди|нади|поищи|открой|запусти|скачай|включи|выключи)"
)

SCENE_TO_ANIM = {
    "cats": "happy",
    "cute": "happy_big",
    "meme": "giggling",
    "funny": "playful",
    "hentai": "flirty",
    "nsfw": "seductive",
    "porn": "seductive",
    "nude": "flirty",
    "code": "thinking",
    "terminal": "thinking_sad",
    "error": "shocked",
    "comfy": "searching_happy",
    "image_gen": "searching",
    "folder": "pointing",
    "files": "idle",
    "work": "idle",
    "docs": "thinking",
    "tax": "tired",
    "news_sad": "sad",
    "sad": "cry_sad",
    "game": "playful_happy",
    "video": "idle_happy",
    "chat": "shy_happy",
    "desktop": "idle_sly",
    "empty": "sleepy",
}

VISION_ADDON = """
На вложении скриншот. Это не рассказ и не инвентаризация стола.
Пиши как живой персонаж: одна реплика 1–2 предложения.
Можно подколоть или коротко назвать ОДНО главное, что видно (окно, игра, папка).
Нельзя: «сидит за столом», список ярлыков, перечисление всех окон, «на диске D», простыня.
Первая строка служебная и не для голоса: [SCENE:метка] [ANIM:кадр]
SCENE: cats,cute,meme,funny,hentai,nsfw,folder,files,code,error,work,game,video,chat,desktop,empty
ANIM по картинке, не thinking по привычке.
Без паролей. Имена файлов только если они крупно видны.
"""


def strip_vision_meta(text: str) -> str:
    s = text or ""
    s = re.sub(r"\[SCENE:[^\]]*\]", "", s, flags=re.I)
    s = re.sub(r"\[OCR[^\]]*\]", "", s, flags=re.I)
    s = re.sub(r"\n{2,}", "\n", s).strip()
    return s

TEXT_HINTS = [
    (re.compile(r"(?i)(comfy|генерац|очередь задач|изображен|нейросет)", re.I), "searching_happy"),
    (re.compile(r"(?i)(папк|проводн|диск [a-z]|explorer|файлов)", re.I), "pointing"),
    (re.compile(r"(?i)(ошибк|traceback|exception|crash)", re.I), "shocked"),
    (re.compile(r"(?i)(кот|кошк|puppy|мил)", re.I), "happy"),
    (re.compile(r"(?i)(hentai|хентай|18\+|nude|порн)", re.I), "flirty"),
    (re.compile(r"(?i)(steam|игр[аыуе]|gameplay)", re.I), "playful"),
    (re.compile(r"(?i)(youtube|ютуб|видео)", re.I), "idle_happy"),
    (re.compile(r"(?i)(груст|печал)", re.I), "sad"),
]


def extract_anim(reply: str) -> Optional[str]:
    if not reply:
        return None
    m = re.search(r"\[ANIM:\s*([a-zA-Z0-9_]+)\]", reply, re.I)
    return m.group(1).lower() if m else None


def infer_anim_from_text(text: str) -> Optional[str]:
    t = text or ""
    for rx, anim in TEXT_HINTS:
        if rx.search(t):
            return anim
    return None


def is_look_command(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if LOOK_SHORT.match(t):
        return True
    if LOOK_BLOCK.search(t) and not re.search(r"(?i)экран", t):
        return False
    return bool(LOOK_RE.search(t))


def scene_to_anim(scene: str) -> Optional[str]:
    if not scene:
        return None
    key = scene.strip().lower().strip("[]")
    key = key.replace("scene:", "")
    return SCENE_TO_ANIM.get(key)


def extract_scene(reply: str) -> Tuple[Optional[str], Optional[str]]:
    if not reply:
        return None, None
    m = re.search(r"\[SCENE:\s*([a-zA-Z0-9_]+)\]", reply, re.I)
    scene = m.group(1).lower() if m else None
    return scene, scene_to_anim(scene or "")


def _grab_pil(max_side: int = 1280) -> Optional[bytes]:
    return _grab_region(None, max_side=max_side)


def list_monitors() -> list:
    """[{index, left, top, right, bottom, width, height, primary}, ...] слева направо."""
    mons = []
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        user32 = ctypes.windll.user32
        MONITORINFOF_PRIMARY = 1
        found = []

        def _cb(hmon, hdc, lprect, lparam):
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                r = info.rcMonitor
                found.append({
                    "hmon": int(hmon),
                    "left": int(r.left),
                    "top": int(r.top),
                    "right": int(r.right),
                    "bottom": int(r.bottom),
                    "width": int(r.right - r.left),
                    "height": int(r.bottom - r.top),
                    "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
                })
            return 1

        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM
        )
        user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(_cb), 0)
        found.sort(key=lambda m: (m["left"], m["top"]))
        for i, m in enumerate(found):
            m["index"] = i
            mons.append(m)
    except Exception:
        mons = []
    return mons


def _active_monitor(mons: list) -> Optional[dict]:
    if not mons:
        return None
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return next((m for m in mons if m.get("primary")), mons[0])
        MONITOR_DEFAULTTONEAREST = 2
        hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        for m in mons:
            if m.get("hmon") == int(hmon):
                return m
    except Exception:
        pass
    return next((m for m in mons if m.get("primary")), mons[0])


_ORD = {
    "перв": 0, "1": 0, "один": 0,
    "втор": 1, "2": 1, "два": 1,
    "трет": 2, "3": 2, "три": 2,
    "четв": 3, "4": 3,
}


def parse_monitor_focus(text: str, mons: Optional[list] = None) -> Tuple[str, Optional[int]]:
    """
    ('all'| 'primary'| 'active'| 'index', index_or_None)
    index — после сортировки слева направо, 0 = самый левый.
    """
    t = (text or "").lower().replace("ё", "е")
    mons = mons if mons is not None else list_monitors()
    n = len(mons)

    if re.search(r"(все|оба|три)\s+(монитор|экран)", t) or "все экраны" in t:
        return "all", None
    if re.search(r"(активн|текущ|этот|этого|сфокусир|передн)", t):
        return "active", None
    if re.search(r"(основн|главн|primary)", t):
        return "primary", None

    if re.search(r"\bлев", t):
        return "index", 0
    if re.search(r"\bправ", t):
        return "index", max(0, n - 1) if n else 0
    if re.search(r"(средн|центр|центральн|middle)", t):
        return "index", n // 2 if n else 0

    m = re.search(r"(?:монитор|экран)\s*(?:№|#|number)?\s*(\d+)", t)
    if m:
        i = int(m.group(1)) - 1
        return "index", max(0, min(i, n - 1)) if n else i

    for stem, idx in _ORD.items():
        if re.search(rf"{stem}\w*\s+(монитор|экран)", t):
            return "index", min(idx, n - 1) if n else idx
    default = str(getattr(config, "SCREEN_FOCUS_DEFAULT", "all") or "all").lower()
    if default in ("left", "левый"):
        return "index", 0
    if default in ("right", "правый"):
        return "index", max(0, n - 1) if n else 0
    if default in ("center", "middle", "центр", "средний"):
        return "index", n // 2 if n else 0
    if default in ("primary", "основной"):
        return "primary", None
    if default in ("active", "активный"):
        return "active", None
    return "all", None


_last_focus = None


def allowed_monitor_indices(mons: Optional[list] = None) -> Optional[list]:
    raw = getattr(config, "SCREEN_ALLOWED_MONITORS", None)
    if raw is None or raw == "" or raw == "all":
        return None
    if isinstance(raw, str):
        parts = [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]
        raw = parts
    out = []
    for x in raw:
        try:
            out.append(int(x))
        except Exception:
            continue
    n = len(mons or [])
    if n:
        out = [i for i in out if 0 <= i < n]
    return out or None


def resolve_monitor(text: str) -> Tuple[Optional[dict], str]:
    """Монитор или None (=все). Подпись для промпта."""
    global _last_focus
    mons = list_monitors()
    kind, idx = parse_monitor_focus(text, mons)
    explicit = re.search(
        r"(лев|прав|средн|центр|центральн|активн|основн|все\s+(монитор|экран)|монитор\s*\d)",
        (text or "").lower(),
    )
    if explicit:
        _last_focus = (kind, idx)
    elif re.search(r"(?i)(этот экран|этот монитор|тот же|ещ[её] раз|снова туда)", text or ""):
        if _last_focus is not None:
            kind, idx = _last_focus

    if not mons:
        return None, "весь виртуальный рабочий стол"
    if kind == "primary":
        mon = next((m for m in mons if m.get("primary")), mons[0])
        return _clamp_allowed(mon, f"основной монитор ({mon['width']}x{mon['height']})", mons)
    if kind == "active":
        mon = _active_monitor(mons)
        return _clamp_allowed(mon, f"активный монитор #{(mon or {}).get('index', 0)+1}", mons)
    if kind == "index" and idx is not None and 0 <= idx < len(mons):
        mon = mons[idx]
        if idx == 0:
            side = "левый"
        elif idx == len(mons) - 1:
            side = "правый"
        else:
            side = "средний"
        label = f"{side} монитор #{idx+1} из {len(mons)} ({mon['width']}x{mon['height']})"
        return _clamp_allowed(mon, label, mons)
    return _clamp_allowed(None, f"все {len(mons)} монитора сразу", mons)


def _clamp_allowed(mon, label, mons):
    allow = allowed_monitor_indices(mons)
    if allow is None:
        return mon, label
    if mon is not None and int(mon.get("index", -1)) in allow:
        return mon, label
    for m in mons or []:
        if int(m.get("index", -1)) in allow:
            return m, f"разрешённый монитор #{m['index']+1} ({m['width']}x{m['height']})"
    return None, "нет разрешённых мониторов"


def _grab_region(mon: Optional[dict], max_side: int = 1280) -> Optional[bytes]:
    try:
        from PIL import ImageGrab, Image
    except Exception:
        return None
    try:
        full = ImageGrab.grab(all_screens=True)
    except TypeError:
        full = ImageGrab.grab()
    if full.mode != "RGB":
        full = full.convert("RGB")
    if mon:
        # ImageGrab all_screens: начало кадра = min left/top виртуального стола
        mons = list_monitors()
        if mons:
            vx = min(m["left"] for m in mons)
            vy = min(m["top"] for m in mons)
        else:
            vx = vy = 0
        x1 = mon["left"] - vx
        y1 = mon["top"] - vy
        x2 = mon["right"] - vx
        y2 = mon["bottom"] - vy
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(full.width, x2), min(full.height, y2)
        if x2 > x1 and y2 > y1:
            full = full.crop((x1, y1, x2, y2))
    w, h = full.size
    scale = min(1.0, float(max_side) / max(w, h))
    if scale < 1.0:
        full = full.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.BILINEAR)
    buf = io.BytesIO()
    q = int(getattr(config, "SCREEN_OCR_JPEG_QUALITY", 90) or 90)
    full.save(buf, format="JPEG", quality=max(60, min(95, q)), optimize=True)
    return buf.getvalue()


def _ocr_pytesseract(path: str) -> str:
    import pytesseract
    from PIL import Image
    lang = getattr(config, "SCREEN_OCR_LANG", "rus+eng")
    psm = int(getattr(config, "SCREEN_OCR_PSM", 6) or 6)
    oem = int(getattr(config, "SCREEN_OCR_OEM", 3) or 3)
    img = Image.open(path)
    cfg = f"--oem {oem} --psm {psm}"
    return (pytesseract.image_to_string(img, lang=lang, config=cfg) or "").strip()


def _ocr_rapidocr(path: str) -> str:
    from rapidocr_onnxruntime import RapidOCR
    engine = getattr(_ocr_rapidocr, "_eng", None)
    if engine is None:
        try:
            engine = RapidOCR(text_score=float(getattr(config, "SCREEN_OCR_MIN_SCORE", 0.45)))
        except TypeError:
            engine = RapidOCR()
        _ocr_rapidocr._eng = engine
    result, _ = engine(path)
    if not result:
        return ""
    min_s = float(getattr(config, "SCREEN_OCR_MIN_SCORE", 0.45) or 0)
    lines = []
    for row in result:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        text = str(row[1]).strip()
        score = 1.0
        if len(row) >= 3:
            try:
                score = float(row[2])
            except Exception:
                score = 1.0
        if text and score >= min_s:
            lines.append(text)
    return "\n".join(lines).strip()


def _ocr_easyocr(path: str) -> str:
    import easyocr
    reader = getattr(_ocr_easyocr, "_r", None)
    if reader is None:
        langs = list(getattr(config, "SCREEN_OCR_LANGS", ["ru", "en"]))
        reader = easyocr.Reader(langs, gpu=True)
        _ocr_easyocr._r = reader
    min_s = float(getattr(config, "SCREEN_OCR_MIN_SCORE", 0.45) or 0)
    rows = reader.readtext(path, detail=1)
    out = []
    for row in rows:
        try:
            text = str(row[1]).strip()
            score = float(row[2]) if len(row) > 2 else 1.0
        except Exception:
            continue
        if text and score >= min_s:
            out.append(text)
    return "\n".join(out).strip()


def _ocr_usable(txt: str) -> bool:
    if not txt or len(txt.strip()) < 3:
        return False
    cyr = len(re.findall(r"[А-Яа-яЁё]", txt))
    lat = len(re.findall(r"[A-Za-z]", txt))
    if cyr >= 6:
        return True
    if re.search(r"https?://|www\.|Google|YouTube|Gmail", txt):
        return True
    if lat > 30 and cyr < 4:
        return False
    return True


def ocr_image(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    if not getattr(config, "SCREEN_OCR_ENABLED", True):
        return ""
    lang = str(getattr(config, "SCREEN_OCR_LANG", "")).lower()
    auto = (_ocr_pytesseract, _ocr_rapidocr, _ocr_easyocr) if "rus" in lang else (
        _ocr_rapidocr, _ocr_pytesseract, _ocr_easyocr
    )
    order = {
        "rapidocr": (_ocr_rapidocr,),
        "tesseract": (_ocr_pytesseract,),
        "easyocr": (_ocr_easyocr,),
        "auto": auto,
    }
    key = str(getattr(config, "SCREEN_OCR_ENGINE", "auto") or "auto").lower()
    for fn in order.get(key, order["auto"]):
        try:
            txt = fn(path)
            if txt and _ocr_usable(txt):
                return txt
        except Exception:
            continue
    return ""


def ocr_via_vl(jpeg_path: str) -> str:
    """Текст с кадра через VL-модель (использует основную модель)."""
    if not jpeg_path or not os.path.isfile(jpeg_path):
        return ""
    import json
    import urllib.request
    model = getattr(config, "MODEL_NAME", "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive")
    b64 = jpeg_b64(jpeg_path)
    if not b64 or not model:
        return ""
    url = str(getattr(config, "API_URL", "")).rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": 800,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "На картинке скриншот монитора. Перепиши только то, что РЕАЛЬНО видно: "
                            "вкладки, чат, кнопки, часы. Русский оставляй русским. "
                            "Если изображения нет — ответь ровно NO_IMAGE. "
                            "Не пиши чужие рассказы и не выдумывай документы."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            }
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {getattr(config, 'API_KEY', 'lm-studio')}",
        },
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    txt = str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    dbg = os.path.join(getattr(config, "DATA_DIR", "."), "cache", "vl_ocr_debug.txt")
    try:
        with open(dbg, "w", encoding="utf-8") as f:
            f.write(f"model={model}\njpeg={jpeg_path}\nchars={len(txt)}\n---\n{txt[:2000]}\n")
    except Exception:
        pass
    if not txt or re.search(r"NO_IMAGE", txt, re.I):
        return ""
    if re.search(r"(?i)реалити|расшифровк\w+ огромн", txt) and not re.search(
        r"(?i)youtube|google|grok|лисичк|gmail|блокнот", txt
    ):
        return ""
    return txt


def last_ocr_text() -> str:
    p = os.path.join(getattr(config, "DATA_DIR", "."), "cache", "screen_last_ocr.txt")
    try:
        with open(p, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def capture_jpeg(max_side: int = 1280, text: str = "") -> Optional[str]:
    """Путь к jpeg. text — фраза хозяина, чтобы выбрать монитор."""
    mon, label = resolve_monitor(text or "")
    cap_side = max(
        int(max_side or 1280),
        int(getattr(config, "SCREEN_VISION_MAX_SIDE", 1600) or 1600),
    )
    raw = _grab_region(mon, max_side=cap_side)
    if not raw:
        return None
    out_dir = os.path.join(getattr(config, "DATA_DIR", "."), "cache")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "screen_last.jpg")
    with open(path, "wb") as f:
        f.write(raw)
    try:
        with open(os.path.join(out_dir, "screen_last.txt"), "w", encoding="utf-8") as f:
            f.write(label)
    except Exception:
        pass
    ocr_txt = ocr_image(path)
    limit = int(getattr(config, "SCREEN_OCR_MAX_CHARS", 3500) or 3500)
    if len(ocr_txt) > limit:
        ocr_txt = ocr_txt[:limit] + "\n…"
    try:
        with open(os.path.join(out_dir, "screen_last_ocr.txt"), "w", encoding="utf-8") as f:
            f.write(ocr_txt)
    except Exception:
        pass
    return path


def jpeg_b64(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return None


def user_content_with_image(text: str, jpeg_path: str) -> object:
    b64 = jpeg_b64(jpeg_path)
    if not b64:
        return text
    return [
        {
            "type": "text",
            "text": (text or "Что у меня на экране? Реагируй на картинку.")
            + "\n(во вложении скриншот выбранного монитора или всех, если не уточнил)",
        },
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        },
    ]


_last_auto = 0.0


def auto_due() -> bool:
    if not getattr(config, "SCREEN_VISION_AUTO", False):
        return False
    if not getattr(config, "SCREEN_VISION_ENABLED", True):
        return False
    interval = float(getattr(config, "SCREEN_VISION_AUTO_INTERVAL", 60) or 60)
    global _last_auto
    now = time.time()
    if now - _last_auto < interval:
        return False
    _last_auto = now
    return True