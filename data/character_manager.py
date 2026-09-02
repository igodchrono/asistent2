# character_manager.py
# «Плагины» персонажа и профиля пользователя из папки personas/
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from utils import logger
except Exception:
    import logging
    logger = logging.getLogger("character_manager")

import config

# personas/
#   characters/<имя>/
#       <имя>.md      — лист
#       images/       — кадры (можно россыпью, без подпапок)
#       memory/       — память только этого персонажа
#   users/*.md
DEFAULT_SUBDIRS = ("characters", "users")

CHARACTER_TEMPLATE = """# Персонаж: {name}

## Значок
🎭

## Анимации запрещены
undress, naked, seductive

## Анимация вместо запрещённой
neutral

## Кто она
- Имя: {name}
- Возраст: 18
- Сущность: виртуальный ассистент
- Обращение к пользователю: «ты»

## Внешность
Опиши внешность здесь. Это канон: модель не должна выдумывать другой вид.

## Характер
Дружелюбная, игривая, немного дерзкая.

## Как говорит
Короткие живые фразы, эмодзи по делу. Не канцелярит.

## Примеры тона
**Пользователь:** привет
**{name}:** Привет! Чем помочь?

## Блок для system prompt
Ты — {name}. Держи характер, манеру речи и внешность из этого файла.

## Простой
[ANIM:idle] {name}: ты там?
[ANIM:sleepy] ночь: ещё не сплю.

## Триггеры эмоций
поплачь = cry
поспи = sleepy
бесит = angry
"""

_SECTION_ALIASES = {
    "кто она": "identity",
    "кто он": "identity",
    "кто это": "identity",
    "имя": "identity",
    "возраст / вид": "identity",
    "возраст": "identity",
    "вид": "identity",
    "внешность": "appearance",
    "внешность (канон по референсу)": "appearance",
    "характер": "personality",
    "как говорит": "speech",
    "речь": "speech",
    "манера": "speech",
    "манера письма": "speech",
    "примеры тона": "examples",
    "примеры": "examples",
    "блок для system prompt": "compact",
    "system prompt": "compact",
    "как обращаться": "address",
    "предпочтения": "prefs",
    "что важно помнить": "notes",
    "значок": "icon",
    "иконка": "icon",
    "emoji": "icon",
    "анимации запрещены": "anim_ban",
    "запрет анимаций": "anim_ban",
    "анимация вместо запрещённой": "anim_fallback",
    "анимация запасная": "anim_fallback",
    "папка кадров": "frames_dir",
    "кадры": "frames_dir",
    "frames": "frames_dir",
    "папка спрайтов": "frames_dir",
    "простой": "idle",
    "автосообщения": "idle",
    "скука": "idle",
    "idle": "idle",
    "фразы простоя": "idle",
    "триггеры эмоций": "triggers",
    "триггеры": "triggers",
    "эмоции слова": "triggers",
}

_card_cache: Dict[str, Tuple[float, str]] = {}

USER_TEMPLATE = """# Пользователь: {name}

## Как обращаться
{name}

## Предпочтения
...

## Что важно помнить
...
"""


def persona_root() -> Path:
    root = getattr(config, "PERSONA_DIR", None)
    if root:
        p = Path(root)
        if not p.is_absolute():
            base = Path(getattr(config, "DATA_DIR", None) or getattr(config, "BASE_DIR", Path.cwd()))
            p = base / p
        return p
    base = Path(getattr(config, "DATA_DIR", None) or getattr(config, "BASE_DIR", Path.cwd()))
    return base / "personas"


def ensure_persona_dirs() -> Path:
    root = persona_root()
    (root / "characters").mkdir(parents=True, exist_ok=True)
    (root / "users").mkdir(parents=True, exist_ok=True)
    return root


def _list_md(folder: Path) -> List[Dict[str, str]]:
    if not folder.is_dir():
        return []
    items = []
    for f in sorted(folder.glob("*.md")):
        items.append({
            "id": f.stem,
            "name": f.stem,
            "path": str(f.resolve()),
            "filename": f.name,
        })
    return items


def character_pack_dir(name: Optional[str] = None) -> Path:
    who = _safe_stem(name or getattr(config, "ACTIVE_CHARACTER", None) or "лисичка")
    return persona_root() / "characters" / who


def _card_in_pack(pack: Path) -> Optional[Path]:
    if not pack.is_dir():
        return None
    for cand in (
        pack / f"{pack.name}.md",
        pack / "character.md",
        pack / "персонаж.md",
        pack / "лист.md",
    ):
        if cand.is_file():
            return cand.resolve()
    mds = sorted(pack.glob("*.md"))
    return mds[0].resolve() if mds else None


def list_characters() -> List[Dict[str, str]]:
    ensure_persona_dirs()
    folder = persona_root() / "characters"
    items = []
    seen = set()
    if folder.is_dir():
        for child in sorted(folder.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                card = _card_in_pack(child)
                if card:
                    seen.add(child.name.lower())
                    items.append({
                        "id": child.name,
                        "name": child.name,
                        "path": str(card),
                        "filename": card.name,
                        "pack": str(child.resolve()),
                    })
        for f in sorted(folder.glob("*.md")):
            if f.stem.lower() in seen:
                continue
            items.append({
                "id": f.stem,
                "name": f.stem,
                "path": str(f.resolve()),
                "filename": f.name,
                "pack": "",
            })
    return items


def list_users() -> List[Dict[str, str]]:
    ensure_persona_dirs()
    return _list_md(persona_root() / "users")


def _resolve_md(kind: str, active_id: Optional[str]) -> Optional[Path]:
    """kind: characters | users"""
    ensure_persona_dirs()
    folder = persona_root() / kind
    if not active_id:
        return None
    # id без расширения или с .md
    stem = active_id[:-3] if active_id.lower().endswith(".md") else active_id
    if kind == "characters":
        pack_card = _card_in_pack(folder / stem)
        if pack_card:
            return pack_card
    candidate = folder / f"{stem}.md"
    if candidate.is_file():
        return candidate.resolve()
    # прямое имя файла в DATA_DIR (обратная совместимость)
    for base in (
        Path(getattr(config, "DATA_DIR", ".") or "."),
        Path(getattr(config, "BASE_DIR", ".") or "."),
        Path.cwd(),
    ):
        legacy = base / active_id
        if legacy.is_file():
            return legacy.resolve()
        legacy2 = base / f"{stem}.md"
        if legacy2.is_file():
            return legacy2.resolve()
    return None


def get_active_character_path() -> Optional[Path]:
    return _resolve_md("characters", getattr(config, "ACTIVE_CHARACTER", None) or "лисичка")


def get_active_user_path() -> Optional[Path]:
    return _resolve_md("users", getattr(config, "ACTIVE_USER", None) or "default")


def _stem(path_or_name: str) -> str:
    return Path(str(path_or_name)).stem.lower()


def _is_character_card(path_or_name: str) -> bool:
    p = Path(str(path_or_name))
    name = p.name.lower()
    if "characters" in [x.lower() for x in p.parts]:
        return True
    if name.startswith("персонаж_") or name in ("лисичка.md", "мила.md", "раиса.md"):
        return True
    return False


def build_rag_docs() -> List[str]:
    """Только активный персонаж + активный пользователь. Чужие карточки не индексировать."""
    docs: List[str] = []
    active = str(getattr(config, "ACTIVE_CHARACTER", "") or "лисичка").lower()
    ch = get_active_character_path()
    us = get_active_user_path()
    if ch:
        docs.append(str(ch))
    if us:
        docs.append(str(us))
    for extra in getattr(config, "RAG_DOCS_EXTRA", None) or []:
        if not extra:
            continue
        if _is_character_card(extra) and _stem(extra) not in {active, f"персонаж_{active}"}:
            continue
        if extra not in docs:
            docs.append(extra)
    return docs



_BAKED_MARKERS = ("Персонаж (файл", "Имя: Лисичка", "Обращение к пользователю: **«хозяин»**")


def prompt_looks_baked(text: str) -> bool:
    s = text or ""
    return any(m in s for m in _BAKED_MARKERS)


def base_rules_prompt() -> str:
    """Правила ассистента без карточки персонажа."""
    raw = getattr(config, "BASE_SYSTEM_PROMPT", None) or ""
    cur = getattr(config, "SYSTEM_PROMPT", "") or ""
    if raw and not prompt_looks_baked(raw):
        return raw
    if cur and not prompt_looks_baked(cur):
        return cur
    return (
        "Ты виртуальный ассистент. Имя, внешность, характер и манеру речи "
        "бери из активного файла персонажа.\n"
        "Правила: один [ANIM] в начале; поиск только через [SEARCH]; "
        "опасные действия только с confirm."
    )


def scrub_baked_prompt_from_config() -> None:
    cur = getattr(config, "SYSTEM_PROMPT", "") or ""
    if prompt_looks_baked(cur):
        config.SYSTEM_PROMPT = base_rules_prompt()
        logger.info("SYSTEM_PROMPT: убрана запечённая карточка персонажа")


def assembled_prompt_preview(character_id: Optional[str] = None) -> str:
    """Что реально уйдёт в модель: карточка выбранного персонажа + правила."""
    old = getattr(config, "ACTIVE_CHARACTER", None)
    try:
        if character_id:
            config.ACTIVE_CHARACTER = character_id
        card = build_character_prompt_block(1800)
        rules = base_rules_prompt()
        return ((card + "\n\n") if card else "") + rules
    finally:
        if character_id is not None:
            try:
                config.ACTIVE_CHARACTER = old
            except Exception:
                pass


def apply_to_config() -> List[str]:
    """Обновить config.RAG_DOCS под активные файлы. Вернуть список docs."""
    try:
        apply_character_paths()
    except Exception as e:
        logger.warning(f"pack paths: {e}")
    try:
        scrub_baked_prompt_from_config()
    except Exception as e:
        logger.warning(f"scrub prompt: {e}")
    docs = build_rag_docs()
    try:
        config.RAG_DOCS = docs
    except Exception:
        pass
    logger.info(f"Persona RAG_DOCS: {docs}")
    return docs


def ensure_character_pack(name: str) -> Path:
    """characters/<имя>/{лист.md, images/, memory/}"""
    ensure_persona_dirs()
    pack = character_pack_dir(name)
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "images").mkdir(exist_ok=True)
    (pack / "memory").mkdir(exist_ok=True)
    card = _card_in_pack(pack)
    if card is None:
        card = pack / f"{pack.name}.md"
        card.write_text(CHARACTER_TEMPLATE.format(name=name or pack.name), encoding="utf-8")
    readme = pack / "README.txt"
    if not readme.exists():
        readme.write_text(
            "Лист персонажа: %s.md\n"
            "Картинки: папка images/ (можно все файлы россыпью)\n"
            "Память: папка memory/ (чат и факты только этого персонажа)\n"
            % pack.name,
            encoding="utf-8",
        )
    return pack


def create_character(name: str) -> Path:
    pack = ensure_character_pack(name)
    card = _card_in_pack(pack)
    return card if card else pack / f"{pack.name}.md"


def create_user(name: str) -> Path:
    ensure_persona_dirs()
    safe = _safe_stem(name) or "user"
    path = persona_root() / "users" / f"{safe}.md"
    if not path.exists():
        path.write_text(USER_TEMPLATE.format(name=name or safe), encoding="utf-8")
    return path


def _safe_stem(name: str) -> str:
    s = (name or "").strip()
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    s = s.strip(". ")
    return s[:80]


def migrate_legacy_files() -> Tuple[Optional[Path], Optional[Path]]:
    """
    Если в корне лежат старые о_пользователе.md / персонаж_*.md —
    скопировать в personas/ при отсутствии.
    """
    ensure_persona_dirs()
    bases = [
        Path(getattr(config, "DATA_DIR", ".") or "."),
        Path(getattr(config, "BASE_DIR", ".") or "."),
        Path.cwd(),
    ]
    char_dst = persona_root() / "characters" / "лисичка.md"
    user_dst = persona_root() / "users" / "default.md"
    char_src = user_src = None
    for base in bases:
        for name in ("персонаж_лисичка.md", "персонаж.md", "character.md"):
            p = base / name
            if p.is_file():
                char_src = p
                break
        for name in ("о_пользователе.md", "пользователь.md", "user.md"):
            p = base / name
            if p.is_file():
                user_src = p
                break
    if char_src and not char_dst.exists():
        char_dst.write_text(char_src.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        logger.info(f"Persona: скопирован персонаж → {char_dst}")
    if user_src and not user_dst.exists():
        user_dst.write_text(user_src.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        logger.info(f"Persona: скопирован пользователь → {user_dst}")
    if not char_dst.exists() and not (persona_root() / "characters" / "лисичка").is_dir():
        create_character("лисичка")
    if not user_dst.exists():
        create_user("default")
    wrap_loose_character_cards()
    return get_active_character_path(), user_dst if user_dst.exists() else get_active_user_path()


def wrap_loose_character_cards() -> None:
    """characters/имя.md → characters/имя/имя.md + images + memory."""
    folder = persona_root() / "characters"
    if not folder.is_dir():
        return
    for f in list(folder.glob("*.md")):
        pack = folder / f.stem
        if pack.is_dir() and (pack / f.name).is_file():
            try:
                f.unlink()
            except Exception:
                pass
            continue
        pack.mkdir(parents=True, exist_ok=True)
        dest = pack / f.name
        if not dest.exists():
            try:
                dest.write_text(f.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
                f.unlink()
            except Exception as e:
                logger.warning(f"wrap {f}: {e}")
                continue
        (pack / "images").mkdir(exist_ok=True)
        (pack / "memory").mkdir(exist_ok=True)
        logger.info(f"Persona pack: {pack}")


def read_preview(path: Optional[Path], max_chars: int = 800) -> str:
    if not path or not path.is_file():
        return "(файл не найден)"
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if len(text) > max_chars:
            return text[:max_chars] + "\n…"
        return text
    except Exception as e:
        return f"(ошибка чтения: {e})"


def parse_md_sections(text: str) -> Dict[str, str]:
    """Разбивает markdown персонажа на секции по заголовкам ##."""
    sections: Dict[str, List[str]] = {}
    current = "intro"
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        m = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
        if m:
            title = m.group(1).strip().lower()
            title = re.sub(r"\s+", " ", title)
            current = _SECTION_ALIASES.get(title, title)
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items() if "".join(v).strip()}


def _trim_block(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _read_mtime_text(path: Path) -> Tuple[float, str]:
    stat = path.stat()
    return stat.st_mtime, path.read_text(encoding="utf-8", errors="ignore")


def build_character_prompt_block(max_chars: int = 1600) -> str:
    """
    Карточка активного персонажа для system prompt.
    Источник — personas/characters/<ACTIVE_CHARACTER>.md
    """
    path = get_active_character_path()
    if not path or not path.is_file():
        return ""
    try:
        mtime, raw = _read_mtime_text(path)
    except Exception as e:
        logger.warning(f"character card read: {e}")
        return ""

    cache_key = f"char:{path}:{max_chars}"
    hit = _card_cache.get(cache_key)
    if hit and hit[0] == mtime:
        return hit[1]

    sections = parse_md_sections(raw)
    parts: List[str] = []

    compact = sections.get("compact") or ""
    identity = sections.get("identity") or ""
    appearance = sections.get("appearance") or ""
    personality = sections.get("personality") or ""
    speech = sections.get("speech") or ""

    name = path.stem
    parts.append(
        f"ЗАМОК РОЛИ. Ты только {name}. Чужое имя (Qwen, Лиса, другой персонаж) запрещено.\n"
        f"Ответ: 1–3 коротких предложения в манере карточки. Без markdown-списков, "
        f"без простыни, без «я языковая модель»."
    )
    parts.append(f"Персонаж (файл {name}.md) — держись этого канона.")

    if compact:
        parts.append(_trim_block(compact, 420))
    if identity:
        parts.append("Кто ты:\n" + _trim_block(identity, 380))
    if appearance:
        parts.append("Внешность (канон, не выдумывай другой вид):\n" + _trim_block(appearance, 420))
    if personality:
        parts.append("Характер:\n" + _trim_block(personality, 380))
    if speech:
        parts.append("Манера речи:\n" + _trim_block(speech, 320))
    examples = sections.get("examples") or ""
    if examples:
        parts.append("Примеры тона (копируй ритм, не дословно):\n" + _trim_block(examples, 420))

    block = "\n\n".join(p for p in parts if p and p.strip())
    block = _trim_block(block, max_chars)
    _card_cache[cache_key] = (mtime, block)
    return block


def build_character_examples(max_chars: int = 700) -> str:
    path = get_active_character_path()
    if not path or not path.is_file():
        return ""
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    examples = parse_md_sections(raw).get("examples") or ""
    if not examples:
        return ""
    return "Примеры тона персонажа:\n" + _trim_block(examples, max_chars)


def build_user_prompt_block(max_chars: int = 400) -> str:
    path = get_active_user_path()
    if not path or not path.is_file():
        return ""
    try:
        mtime, raw = _read_mtime_text(path)
    except Exception:
        return ""
    cache_key = f"user:{path}:{max_chars}"
    hit = _card_cache.get(cache_key)
    if hit and hit[0] == mtime:
        return hit[1]
    sections = parse_md_sections(raw)
    bits = []
    for key, title in (
        ("address", "Как обращаться к хозяину"),
        ("prefs", "Предпочтения хозяина"),
        ("notes", "Важно помнить"),
    ):
        if sections.get(key):
            bits.append(f"{title}:\n" + _trim_block(sections[key], 180))
    block = _trim_block("\n\n".join(bits), max_chars)
    _card_cache[cache_key] = (mtime, block)
    return block


def _active_sections() -> Dict[str, str]:
    path = get_active_character_path()
    if not path or not path.is_file():
        return {}
    try:
        return parse_md_sections(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}


def character_frames_dir() -> Path:
    """Папка кадров активного персонажа.

    В карточке:
      ## Папка кадров
      Heson
      или frames/Heson
    Если папки нет — data/frames (общая).
    """
    import os
    data = Path(getattr(config, "DATA_DIR", None) or getattr(config, "BASE_DIR", Path.cwd()))
    shared = Path(getattr(config, "FRAMES_DIR", None) or (data / "frames"))
    raw = (_active_sections().get("frames_dir") or "").strip()
    line = ""
    for ln in raw.splitlines():
        s = ln.strip().lstrip("-").strip().strip("`")
        if s and not s.startswith("#"):
            line = s
            break
    who = str(getattr(config, "ACTIVE_CHARACTER", "") or "").strip()
    candidates = []
    if line:
        pth = Path(line)
        if pth.is_absolute():
            candidates.append(pth)
        else:
            candidates.append(data / line)
            candidates.append(shared / line)
            if line.lower().startswith("frames/"):
                candidates.append(data / line)
            else:
                candidates.append(shared / line)
    if who:
        pack = character_pack_dir(who)
        candidates.append(pack / "images")
        candidates.append(pack / "frames")
        candidates.append(pack)
        candidates.append(shared / who)
        candidates.append(data / "frames" / who)
    def _has_img(folder: Path) -> bool:
        if not folder.is_dir():
            return False
        exts = {".png", ".jpg", ".jpeg", ".webp"}
        try:
            for f in folder.rglob("*"):
                if f.is_file() and f.suffix.lower() in exts:
                    return True
        except Exception:
            return False
        return False

    seen = []
    for c in candidates:
        try:
            c = c.resolve()
        except Exception:
            continue
        if c in seen:
            continue
        seen.append(c)
        if _has_img(c):
            return c
    return shared


def character_memory_dir(name: Optional[str] = None) -> Path:
    pack = ensure_character_pack(name or getattr(config, "ACTIVE_CHARACTER", None) or "лисичка")
    mem = pack / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    return mem


def apply_character_paths(name: Optional[str] = None) -> Path:
    """FRAMES + базы памяти активного персонажа."""
    who = name or getattr(config, "ACTIVE_CHARACTER", None) or "лисичка"
    pack = ensure_character_pack(who)
    frames = character_frames_dir()
    mem = character_memory_dir(who)
    try:
        config.FRAMES_DIR = str(frames)
        config.CHARACTER_PACK_DIR = str(pack)
        config.CHARACTER_IMAGES_DIR = str(pack / "images")
        config.DB_PATH = str(mem / "chat.db")
        config.PERSISTENT_MEMORY_DB = str(mem / "persistent.db")
    except Exception as e:
        logger.warning(f"apply_character_paths: {e}")
    logger.info(f"Persona pack={pack} frames={frames} memory={mem}")
    return pack


def character_icon() -> str:
    raw = (_active_sections().get("icon") or "").strip()
    for line in raw.splitlines():
        s = line.strip().lstrip("-").strip()
        if s:
            return s.split()[0]
    who = str(getattr(config, "ACTIVE_CHARACTER", "") or "").lower()
    return {"лисичка": "🦊", "мила": "🧒", "раиса": "🧶"}.get(who, "🎭")


def character_display_name() -> str:
    who = str(getattr(config, "ACTIVE_CHARACTER", "") or "персонаж")
    ident = _active_sections().get("identity") or ""
    m = re.search(r"(?im)имя:\s*([^\n(]+)", ident)
    if m:
        name = m.group(1).strip()
        name = re.split(r"[,(]", name)[0].strip()
    else:
        name = who[:1].upper() + who[1:]
    return f"{character_icon()} {name}".strip()


def character_anim_ban() -> set:
    raw = _active_sections().get("anim_ban") or ""
    names = re.findall(r"[a-z][a-z0-9_]+", raw.lower())
    return set(names)


def character_anim_fallback() -> str:
    raw = (_active_sections().get("anim_fallback") or "").strip().lower()
    m = re.search(r"[a-z][a-z0-9_]+", raw)
    return m.group(0) if m else "neutral"


def character_short_name() -> str:
    who = str(getattr(config, "ACTIVE_CHARACTER", None) or "персонаж")
    return who




def character_emotion_triggers():
    """Фразы из карточки: «поплачь = cry». Без имён в коде."""
    raw = (_active_sections().get("triggers") or "").strip()
    out = []
    for ln in raw.splitlines():
        s = ln.strip().lstrip("-").strip()
        if not s or s.startswith("#"):
            continue
        m = re.split(r"\s*(?:=|->|:|—|–)\s*", s, maxsplit=1)
        if len(m) != 2:
            continue
        phrase, anim = m[0].strip().lower(), m[1].strip().lower()
        anim = re.sub(r"[^a-z0-9_]+", "", anim.split()[0] if anim else "")
        if phrase and anim:
            out.append((phrase, anim))
    return out


def greeting_system_prompt(extra: str = "") -> str:
    who = character_short_name()
    card = build_character_prompt_block(900)
    bits = [
        card or f"Ты — {who}. Держи характер из карточки.",
        "Сейчас пишешь ОДНО короткое авто-сообщение (до 25 слов), не диалог.",
        "Без [SEARCH]/[LAUNCH], без списков, без чужого имени.",
    ]
    if extra:
        bits.append(extra.strip())
    return "\n".join(bits)


def vision_system_prompt(addon: str = "") -> str:
    who = character_short_name()
    return (
        f"Ты {who}. Смотришь на скриншот. "
        + (addon or "")
        + " Ответ 1–3 коротких предложения. Без чужого имени персонажа."
    )


_IDLE_SKIP = (
    "строки для", "система берёт", "система берет", "автосообщен",
    "метк", "фильтр",
)
_IDLE_TAG_RE = re.compile(
    r"^(?:\[ANIM:([^\]]+)\]\s*)?"
    r"(?:[a-zа-яё0-9_]+(?:\s+[a-zа-яё0-9_]+){0,3}\s*:\s*)?",
    re.I,
)


def _clean_idle_line(raw: str) -> str:
    s = (raw or "").strip().lstrip("-").strip()
    if not s or s.startswith("#"):
        return ""
    low = s.lower()
    if any(x in low for x in _IDLE_SKIP):
        return ""
    anim = ""
    m = re.match(r"^\[ANIM:([^\]]+)\]\s*", s, re.I)
    if m:
        anim = m.group(1).strip()
        s = s[m.end():].strip()
    # срезать служебные ярлыки: "angry rude:", "morning утро:", "sleepy:"
    s = re.sub(
        r"^(?:night|late|morning|day|evening|night|sad|angry|rude|tired|"
        r"sleepy|happy|playful|pouting|idle|neutral|"
        r"ночь|утро|день|вечер|грусть|злость)\s*"
        r"(?:[a-zа-яё]+\s*){0,3}:\s*",
        "",
        s,
        flags=re.I,
    )
    s = s.strip()
    if not s:
        return ""
    return (f"[ANIM:{anim}] " if anim else "") + s


def _idle_lines_from_card() -> list:
    raw = (_active_sections().get("idle") or "").strip()
    out = []
    for ln in raw.splitlines():
        cleaned = _clean_idle_line(ln)
        if cleaned:
            out.append((ln, cleaned))
    return out


def greeting_templates(mood: int = 0, time_period: str = "", user_mood: str = "", self_mood: str = ""):
    """Фразы простоя из карточки. В чат уходит только реплика, не ярлыки."""
    who = character_short_name()
    period = (time_period or "").lower()
    um = (user_mood or "").lower()
    sm = (self_mood or "").lower()
    custom = _idle_lines_from_card()
    keys = [k for k in (period, um, sm) if k]
    picked = []
    generic = []
    for raw, cleaned in custom:
        low = raw.lower()
        if keys and any(k in low for k in keys):
            picked.append(cleaned)
        elif not re.search(r"\b(night|late|morning|evening|sad|angry|rude|tired|sleepy)\b", low):
            generic.append(cleaned)
    pool = picked or generic
    if pool:
        return pool

    night = period in ("night", "evening", "ночь", "вечер")
    user_sad = um in ("sad", "angry", "tired", "грусть", "злость")
    if mood >= 2:
        anim = "pouting"
        lines = [
            f"[ANIM:{anim}] {who}: долго молчишь.",
            f"[ANIM:angry] Эй. Я ещё здесь.",
        ]
    elif night or sm in ("sleepy", "tired"):
        lines = [
            f"[ANIM:sleepy] Тихо. Я ещё не сплю.",
            f"[ANIM:tired] Ночь. Напиши, если надо.",
        ]
    elif user_sad:
        lines = [
            f"[ANIM:sad] Если тяжело — скажи. Я рядом.",
            f"[ANIM:neutral] Молчать тоже можно. Я тут.",
        ]
    elif mood == 1:
        lines = [
            f"[ANIM:playful] Скучно. Есть дело?",
            f"[ANIM:idle] Ты там?",
        ]
    else:
        lines = [
            f"[ANIM:idle] Ты ещё там?",
            f"[ANIM:neutral] Я рядом.",
        ]
    return lines


def clip_character_reply(text: str, max_sentences: int = 3) -> str:
    """Отрезать простыню до показа в чат."""
    raw = (text or "").strip()
    if not raw:
        return raw
    import re
    parts = re.split(r"(?<=[.!?…])\s+", raw)
    keep = [p for p in parts if p.strip()][: max(1, max_sentences)]
    out = " ".join(keep).strip()
    return out or raw
