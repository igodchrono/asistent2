# system_controller.py - ИСПРАВЛЕННЫЙ
import asyncio
import subprocess
import os
import shutil
import platform
import time
import sys
from typing import Tuple, Optional, Dict, List, Any
from pathlib import Path
import aiofiles
import aiohttp
from utils import run_in_executor, fs_semaphore, task_pool, logger


class SystemController:
    """
    Асинхронный фасад для работы с операционной системой.
    Все блокирующие операции выполняются в отдельных потоках.
    """
    
    def __init__(self):
        self._browser_path = None
        self._default_browser = "chrome"
        self._allowed_dirs = []
        self._init_config()
    
    def _init_config(self):
        try:
            import config
            self._browser_path = getattr(config, "BROWSER_PATH", None)
            self._default_browser = getattr(config, "DEFAULT_BROWSER", "chrome")
            self._allowed_dirs = getattr(config, "ALLOWED_DIRS", [])
        except ImportError:
            pass
    
    def _is_allowed(self, path: str) -> bool:
        """Проверяет, разрешён ли доступ к пути (нормализованные abs paths)."""
        if not self._allowed_dirs:
            return True
        if not path:
            return False
        try:
            norm = os.path.normcase(os.path.abspath(os.path.expanduser(path)))
        except Exception:
            return False
        for d in self._allowed_dirs:
            try:
                base = os.path.normcase(os.path.abspath(d))
                if norm == base or norm.startswith(base + os.sep):
                    return True
            except Exception:
                continue
        return False
    
    # ===== ПРОЦЕССЫ =====
    
    @staticmethod
    @run_in_executor
    def _run_subprocess(cmd: list, timeout: int = 30) -> Tuple[int, str, str]:
        """Запуск процесса в отдельном потоке."""
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=(platform.system() == "Windows" and len(cmd) == 1)
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            return proc.returncode, stdout or "", stderr or ""
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return -1, "", "Таймаут"
    
    async def run_command_async(self, command: str, timeout: int = 30) -> str:
        """Асинхронный запуск команды. Whitelist проверяет CommandExecutor."""
        if not command or not str(command).strip():
            return "Пустая команда"
        async with fs_semaphore:
            if platform.system() == "Windows":
                cmd = ["cmd", "/c", command]
            else:
                cmd = ["sh", "-c", command]

            returncode, stdout, stderr = await self._run_subprocess(cmd, timeout)

            if returncode == 0:
                return stdout.strip() or "Команда выполнена"
            return stderr.strip() or f"Ошибка: {returncode}"
    
    @staticmethod
    @run_in_executor
    def _list_processes() -> List[Dict]:
        """Список процессов (синхронный)."""
        try:
            import psutil
            processes = []
            for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                try:
                    info = p.info
                    processes.append({
                        'pid': info['pid'],
                        'name': info['name'],
                        'cpu': info.get('cpu_percent', 0),
                        'memory': info.get('memory_percent', 0)
                    })
                except:
                    continue
            return sorted(processes, key=lambda x: x['cpu'], reverse=True)
        except ImportError:
            return []
    
    async def get_processes_async(self, limit: int = 15) -> List[Dict]:
        """Асинхронное получение списка процессов."""
        procs = await self._list_processes()
        return procs[:limit]
    
    @staticmethod
    @run_in_executor
    def _kill_process(name: str) -> Tuple[bool, str]:
        """Завершение процесса (синхронный)."""
        try:
            import psutil
            killed = []
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    if p.info['name'] and name.lower() in p.info['name'].lower():
                        p.kill()
                        killed.append(p.info['name'])
                except:
                    continue
            
            if killed:
                return True, f"Завершены процессы: {', '.join(killed)}"
            return False, f"Процесс {name} не найден"
        except ImportError:
            return False, "psutil не установлен"
    
    async def kill_process_async(self, name: str) -> Tuple[bool, str]:
        """Асинхронное завершение процесса."""
        async with fs_semaphore:
            return await self._kill_process(name)
    
    # ===== ФАЙЛОВАЯ СИСТЕМА =====
    
    @staticmethod
    @run_in_executor
    def _read_file(path: str) -> str:
        """Синхронное чтение файла."""
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    
    async def read_file_async(self, path: str) -> str:
        """Асинхронное чтение файла."""
        if not self._is_allowed(path):
            raise PermissionError(f"Доступ запрещён: {path}")
        async with aiofiles.open(path, 'r', encoding='utf-8') as f:
            return await f.read()
    
    @staticmethod
    @run_in_executor
    def _write_file(path: str, content: str, overwrite: bool = True) -> Tuple[bool, str]:
        """Синхронная запись файла."""
        if not overwrite and os.path.exists(path):
            return False, "Файл уже существует"
        
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True, f"Записано: {path}"
    
    async def write_file_async(self, path: str, content: str, overwrite: bool = True) -> Tuple[bool, str]:
        """Асинхронная запись файла."""
        if not self._is_allowed(path):
            return False, f"Доступ запрещён: {path}"
        async with fs_semaphore:
            return await self._write_file(path, content, overwrite)
    
    @staticmethod
    @run_in_executor
    def _delete_file(path: str) -> Tuple[bool, str]:
        """Синхронное удаление файла/директории."""
        if not os.path.exists(path):
            return False, f"Не существует: {path}"
        
        if os.path.isfile(path):
            os.remove(path)
        else:
            shutil.rmtree(path)
        return True, f"Удалено: {path}"
    
    async def delete_file_async(self, path: str) -> Tuple[bool, str]:
        """Асинхронное удаление файла/директории."""
        if not self._is_allowed(path):
            return False, f"Доступ запрещён: {path}"
        async with fs_semaphore:
            return await self._delete_file(path)
    
    @staticmethod
    @run_in_executor
    def _copy_file(src: str, dst: str) -> Tuple[bool, str]:
        """Синхронное копирование."""
        shutil.copy2(src, dst)
        return True, f"Скопировано: {src} → {dst}"
    
    async def copy_file_async(self, src: str, dst: str) -> Tuple[bool, str]:
        """Асинхронное копирование."""
        if not self._is_allowed(src) or not self._is_allowed(dst):
            return False, "Доступ запрещён"
        async with fs_semaphore:
            return await self._copy_file(src, dst)
    
    @staticmethod
    @run_in_executor
    def _move_file(src: str, dst: str) -> Tuple[bool, str]:
        """Синхронное перемещение."""
        shutil.move(src, dst)
        return True, f"Перемещено: {src} → {dst}"
    
    async def move_file_async(self, src: str, dst: str) -> Tuple[bool, str]:
        """Асинхронное перемещение."""
        if not self._is_allowed(src) or not self._is_allowed(dst):
            return False, "Доступ запрещён"
        async with fs_semaphore:
            return await self._move_file(src, dst)
    
    @staticmethod
    @run_in_executor
    def _create_folder(path: str) -> Tuple[bool, str]:
        """Синхронное создание папки."""
        os.makedirs(path, exist_ok=True)
        return True, f"Папка создана: {path}"
    
    async def create_folder_async(self, path: str) -> Tuple[bool, str]:
        """Асинхронное создание папки."""
        if not self._is_allowed(path):
            return False, f"Доступ запрещён: {path}"
        async with fs_semaphore:
            return await self._create_folder(path)
    
    @staticmethod
    @run_in_executor
    def _get_disk_space(drive: Optional[str] = None) -> str:
        """Синхронное получение информации о диске."""
        d = drive or ("C:\\" if platform.system() == "Windows" else "/")
        total, used, free = shutil.disk_usage(d)
        return f"{d}: Всего {total//2**30} ГБ, занято {used//2**30} ГБ, свободно {free//2**30} ГБ"
    
    async def get_disk_space_async(self, drive: Optional[str] = None) -> str:
        """Асинхронное получение информации о диске."""
        return await self._get_disk_space(drive)
    
    @staticmethod
    @run_in_executor
    def _list_directory(path: str) -> List[Dict]:
        """Синхронный список файлов в директории."""
        result = []
        for item in os.listdir(path):
            full = os.path.join(path, item)
            try:
                stat = os.stat(full)
                result.append({
                    "name": item,
                    "path": full,
                    "is_dir": os.path.isdir(full),
                    "size": stat.st_size if not os.path.isdir(full) else 0,
                    "modified": stat.st_mtime
                })
            except:
                pass
        return result
    
    async def list_directory_async(self, path: str) -> List[Dict]:
        """Асинхронный список файлов в директории."""
        if not self._is_allowed(path):
            raise PermissionError(f"Доступ запрещён: {path}")
        return await self._list_directory(path)
    
    # ===== БРАУЗЕР =====

       # ===== БРАУЗЕР =====

    @staticmethod
    def open_url_in_browser(url: str) -> Tuple[bool, str]:
        """
        Открыть URL во ВКЛАДКЕ существующего браузера, а не новым окном/процессом.
        Chrome/Edge/Brave: --new-tab (переиспользует уже запущенный процесс).
        """
        import webbrowser
        try:
            import config as _cfg
            browser_path = getattr(_cfg, "BROWSER_PATH", None)
            default_browser = (getattr(_cfg, "DEFAULT_BROWSER", "") or "").lower()
        except Exception:
            browser_path = None
            default_browser = ""

        if not url:
            return False, "Пустой URL"
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        def _chromium_args(exe: str, link: str) -> list:
            name = os.path.basename(exe).lower()
            # вкладка в уже открытом окне
            if any(x in name for x in ("chrome", "msedge", "edge", "brave", "opera", "yandex", "chromium")):
                return [exe, "--new-tab", link]
            if "firefox" in name:
                return [exe, "-new-tab", link]
            return [exe, link]

        try:
            if browser_path and os.path.isfile(browser_path):
                args = _chromium_args(browser_path, url)
                # Не ждём завершения: chrome сразу отдаёт управление уже работающему процессу
                subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
                return True, f"Вкладка: {url[:80]}"

            # Без BROWSER_PATH — системный обработчик (обычно та же вкладка/окно)
            if platform.system() == "Windows":
                try:
                    # start передаёт URL shell — открывает в default browser как вкладку
                    subprocess.Popen(
                        ["cmd", "/c", "start", "", url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        shell=False,
                    )
                    return True, f"Вкладка: {url[:80]}"
                except Exception:
                    pass

            webbrowser.open(url, new=2)  # new=2 → новая вкладка, если поддерживается
            return True, f"Вкладка: {url[:80]}"
        except Exception as e:
            logger.error(f"open_url_in_browser: {e}")
            try:
                webbrowser.open(url, new=2)
                return True, f"Открыто (fallback): {url[:80]}"
            except Exception as e2:
                return False, str(e2)

    @staticmethod
    @run_in_executor
    def _open_url_browser(browser_path: str, url: str) -> Tuple[bool, str]:
        return SystemController.open_url_in_browser(url)

    async def open_url_async(self, url: str) -> Tuple[bool, str]:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        return await self._open_url_browser(self._browser_path, url)

    # ===== ПОИСК =====

    _IMAGE_HINTS = (
        "картинк", "фото", "изображен", "рисунок", "арт", "обои",
        "wallpaper", "image", "picture", "photo", "pics", "meme",
        "мем", "скрин", "gif", "гиф", "аватар", "иллюстрац", "кортинк",
    )

    # Домены, которые почти никогда не нужны как «лучший результат»
    _JUNK_DOMAINS = (
        "zhihu.com", "baidu.com", "csdn.net", "jianshu.com", "sohu.com",
        "alibaba.com", "aliexpress.com", "quora.com",
        "facebook.com/login", "instagram.com",
        "doubleclick.", "googlesyndication.", "taboola.", "outbrain.",
        "spam", "malware", "casino", "porn", "xxx",
        "accounts.google.", "login.live.", "chrome.google.com/webstore",
    )

    # Хорошие хосты для картинок
    _IMAGE_GOOD_HOSTS = (
        "pinterest.", "imgur.", "deviantart.", "artstation.", "pixiv.",
        "wallhaven.", "unsplash.", "flickr.", "gettyimages.", "shutterstock.",
        "freepik.", "pexels.", "pixabay.", "wallpaper", "wallpapers",
        "yandex.ru/images", "images.google", "bing.com/images",
        "joyreactor.", "reactor.cc", "vk.com/photo", "vk.com/album",
        "iaaa.org", "wikimedia.org", "upload.wikimedia",
        "pinimg.com", "i.redd.it", "preview.redd.it",
        "cdn.", "staticflickr.", "live.staticflickr",
    )

    # Видео-сайты — плохо как 2-я вкладка для «картинки …»
    _VIDEO_BAD_HOSTS = (
        "youtube.com", "youtu.be", "rutube.ru", "vimeo.com", "twitch.tv",
        "tiktok.com", "vk.com/video", "dailymotion.com", "boosty.to",
        "animego.", "anime1.", "anilibria.", "yummyani", "jut.su",
        "anistar.", "anime", "kinopoisk.", "ivi.ru", "okko.tv",
        "netflix.", "shikimori.", "myanimelist.", "watch", "streaming",
    )

    @staticmethod
    def detect_search_intent(query: str) -> str:
        q = (query or "").lower()
        for hint in SystemController._IMAGE_HINTS:
            if hint in q:
                return "images"
        return "web"

    @staticmethod
    def build_search_page_url(query: str, engine: Optional[str] = None, intent: str = "web") -> str:
        import urllib.parse
        try:
            import config as _cfg
            engine = (engine or getattr(_cfg, "SEARCH_ENGINE", "google") or "google").lower()
            safe = str(getattr(_cfg, "SEARCH_SAFE_MODE", "off")).lower()
        except Exception:
            engine = (engine or "google").lower()
            safe = "off"

        q = urllib.parse.quote_plus((query or "").strip())
        safe_on = safe in ("on", "moderate", "strict", "true", "1")

        if intent == "images":
            if engine == "yandex":
                return f"https://yandex.ru/images/search?text={q}"
            if engine == "bing":
                return f"https://www.bing.com/images/search?q={q}"
            if engine in ("duckduckgo", "ddg"):
                return f"https://duckduckgo.com/?q={q}&iax=images&ia=images"
            sp = "&safe=active" if safe_on else "&safe=off"
            return f"https://www.google.com/search?tbm=isch&q={q}{sp}"

        if engine == "yandex":
            return f"https://yandex.ru/search/?text={q}"
        if engine == "bing":
            return f"https://www.bing.com/search?q={q}"
        if engine in ("duckduckgo", "ddg"):
            return f"https://duckduckgo.com/?q={q}"
        sp = "&safe=active" if safe_on else "&safe=off"
        return f"https://www.google.com/search?q={q}{sp}"

    @staticmethod
    def _is_junk_url(url: str) -> bool:
        u = (url or "").lower()
        return any(j in u for j in SystemController._JUNK_DOMAINS)

    # стоп-слова запроса (не дают очков совпадения)
    _QUERY_STOP = frozenset({
        "найди", "найти", "поиск", "поискать", "ищу", "открой", "открыть",
        "покажи", "показать", "скачай", "скачать", "пожалуйста", "мне",
        "в", "на", "и", "или", "про", "для", "это", "как", "что", "где",
        "the", "a", "an", "of", "in", "on", "for", "to", "and", "or",
        "картинки", "картинка", "фото", "image", "images", "video", "видео",
        "сайт", "страницу", "ссылку", "google", "яндекс", "yandex", "bing",
    })

    # если в запросе есть бренд/сайт — сильно предпочитаем его домен
    _SITE_HINTS = (
        ("youtube", ("youtube.com", "youtu.be")),
        ("ютуб", ("youtube.com", "youtu.be")),
        ("youtu", ("youtube.com", "youtu.be")),
        ("вики", ("wikipedia.org")),
        ("wikipedia", ("wikipedia.org")),
        ("википеди", ("wikipedia.org")),
        ("github", ("github.com")),
        ("habr", ("habr.com")),
        ("rutube", ("rutube.ru")),
        ("vk", ("vk.com", "vk.ru")),
        ("вконтакте", ("vk.com", "vk.ru")),
        ("twitch", ("twitch.tv")),
        ("reddit", ("reddit.com")),
        ("steam", ("steampowered.com", "store.steampowered.com")),
    )

    @staticmethod
    def _score_result(query: str, result: Dict, intent: str = "web") -> float:
        """
        Релевантность результата запросу.
        Высокий score → можно открывать 2-й вкладкой.
        Низкий → только страница поиска.
        """
        import re
        from urllib.parse import urlparse

        q_raw = (query or "").lower().strip()
        stop = SystemController._QUERY_STOP
        tokens = [
            t for t in re.split(r"[\s\-_,.!?]+", q_raw)
            if len(t) > 1 and t not in stop
        ]
        if not tokens and q_raw:
            tokens = [q_raw]

        # синонимы: кошек/кот ↔ cat/neko — чтобы «кошек» не терялся за «аниме»
        _SYN = {
            "кошек": ("кот", "кошка", "кошки", "cat", "cats", "neko", "kitty"),
            "кошка": ("кот", "кошек", "cat", "neko"),
            "кот": ("кошка", "кошек", "cat", "neko"),
            "cat": ("кошка", "кот", "кошек", "neko"),
            "аниме": ("anime", "аниме"),
            "anime": ("аниме", "anime"),
        }
        expanded = list(tokens)
        for tok in tokens:
            for syn in _SYN.get(tok, ()):
                if syn not in expanded:
                    expanded.append(syn)

        title = (result.get("title") or "").lower()
        snippet = (result.get("snippet") or result.get("body") or "").lower()
        url = (result.get("url") or result.get("href") or "").lower()

        if SystemController._is_junk_url(url):
            return -100.0

        try:
            host = urlparse(url).netloc.lower()
            if host.startswith("www."):
                host = host[4:]
        except Exception:
            host = ""

        score = 0.0
        matched = 0
        content_tokens = [t for t in tokens if t not in ("аниме", "anime", "арт", "art")]
        for tok in expanded:
            hit = False
            if tok in title:
                score += 4.0 if tok in tokens else 2.0
                hit = True
            if tok in snippet:
                score += 1.5 if tok in tokens else 0.8
                hit = True
            if tok in url:
                score += 2.0 if tok in tokens else 1.0
                hit = True
            if tok in host or host.startswith(tok + "."):
                score += 5.0
                hit = True
            if hit and tok in tokens:
                matched += 1

        # доля покрытых токенов запроса (главный фильтр контекста)
        if tokens:
            coverage = matched / len(tokens)
            score += coverage * 6.0
            if coverage < 0.34 and len(tokens) >= 2:
                score -= 4.0  # почти не пересекается с запросом
            if coverage >= 0.8:
                score += 3.0
            # важные слова (кошек и т.п.) обязательны: «аниме» без «кошек» — мало
            if content_tokens:
                content_hits = sum(
                    1 for t in content_tokens
                    if t in title or t in snippet or t in url
                    or any(s in title or s in url for s in _SYN.get(t, ()))
                )
                if content_hits == 0 and len(content_tokens) >= 1:
                    score -= 10.0

        # точная фраза (2+ слова) в title
        meaningful = " ".join(tokens[:6])
        if len(tokens) >= 2 and meaningful in title:
            score += 5.0
        if len(tokens) >= 2 and meaningful in snippet:
            score += 2.0

        # подсказки сайтов из запроса
        for hint, domains in SystemController._SITE_HINTS:
            if hint in q_raw:
                if any(d in host or d in url for d in domains):
                    score += 12.0
                else:
                    score -= 3.0  # просили youtube, а открыли не youtube

        if intent == "images":
            is_img_host = any(h in url for h in SystemController._IMAGE_GOOD_HOSTS)
            is_img_file = bool(re.search(r"\.(jpg|jpeg|png|gif|webp|bmp)(\?|$)", url))
            if is_img_host:
                score += 8.0
            if is_img_file:
                score += 10.0
            if any(w in title for w in ("фото", "картин", "image", "photo", "wallpaper", "арт", "drawing")):
                score += 2.0
            # видео / аниме-стриминг при запросе картинок — почти дисквалификация
            if any(h in url or h in host for h in SystemController._VIDEO_BAD_HOSTS):
                score -= 20.0
            if any(w in url for w in ("/watch", "/video", "/episode", "/series", "/stream")):
                score -= 12.0
            if any(w in url for w in ("/question/", "/answer/", "/article/", "/blog/", "/post/")):
                score -= 5.0
            # без признаков картинки — сильно режем (чтобы не открыть «аниме сайт»)
            if not is_img_host and not is_img_file:
                score -= 10.0
            if any(w in title for w in ("什么", "如何", "为什么", "怎么样", "知乎")):
                score -= 10.0
        else:
            if any(h in url for h in ("wikipedia.org", "habr.com", "github.com", "docs.")):
                score += 1.5
            if re.search(r"\.(jpg|jpeg|png|gif)(\?|$)", url):
                score -= 1.0
            # чужой язык в title при русском запросе
            if re.search(r"[а-яё]", q_raw) and re.search(r"[\u4e00-\u9fff]", title):
                score -= 8.0

        return score

    @staticmethod
    def pick_best_result(
        query: str, results: List[Dict], intent: str = "web", min_score: float = 4.0
    ) -> Optional[Dict]:
        """
        Вторая вкладка только при уверенном score.
        Без «слабого fallback» — иначе открывается случайный мусор.
        """
        if not results:
            return None
        scored = []
        for r in results:
            url = r.get("url") or r.get("href") or ""
            if not str(url).startswith("http"):
                continue
            if SystemController._is_junk_url(url):
                continue
            s = SystemController._score_result(query, r, intent)
            scored.append((s, r))
            logger.debug(
                f"SEARCH score={s:.1f} title={(r.get('title') or '')[:50]!r} url={url[:70]!r}"
            )
        if not scored:
            return None
        scored.sort(key=lambda x: x[0], reverse=True)
        best_s, best_r = scored[0]
        # относительный отрыв от 2-го места
        if len(scored) > 1 and best_s < scored[1][0] + 0.5 and best_s < min_score + 2:
            # неоднозначно — лучше только поиск
            if best_s < min_score:
                logger.info(
                    f"SEARCH skip 2nd tab: ambiguous best score={best_s:.1f} min={min_score}"
                )
                return None
        if best_s < min_score:
            logger.info(
                f"SEARCH skip 2nd tab: best score={best_s:.1f} < min={min_score} "
                f"title={(best_r.get('title') or '')[:60]!r}"
            )
            return None
        logger.info(
            f"SEARCH best score={best_s:.1f} title={(best_r.get('title') or '')[:60]!r}"
        )
        return best_r

    @staticmethod
    @run_in_executor
    def _search_duckduckgo(query: str, num_results: int = 8, intent: str = "web") -> List[Dict]:
        try:
            from duckduckgo_search import DDGS
            results = []
            with DDGS() as ddgs:
                if intent == "images":
                    try:
                        for r in ddgs.images(query, max_results=num_results, region="ru-ru"):
                            # Для картинок предпочитаем страницу-источник, иначе прямую картинку
                            page = r.get("url") or ""
                            img = r.get("image") or r.get("thumbnail") or ""
                            url = page or img
                            if not url:
                                continue
                            if SystemController._is_junk_url(url):
                                continue
                            results.append({
                                "url": url,
                                "title": r.get("title", "") or r.get("source", ""),
                                "snippet": r.get("source", ""),
                                "image": img or url,
                            })
                    except Exception as e:
                        logger.error(f"DDG images: {e}")
                if not results:
                    for r in ddgs.text(query, max_results=num_results, region="ru-ru"):
                        href = r.get("href") or r.get("link") or ""
                        if not href or SystemController._is_junk_url(href):
                            continue
                        results.append({
                            "url": href,
                            "title": r.get("title", ""),
                            "snippet": r.get("body", ""),
                        })
            return results
        except ImportError:
            logger.error("duckduckgo_search не установлен")
            return []
        except Exception as e:
            logger.error(f"Ошибка поиска DDG: {e}")
            return []

    async def search_async(
        self, query: str, num_results: int = 8, intent: Optional[str] = None
    ) -> List[Dict]:
        if intent is None:
            intent = self.detect_search_intent(query)
        try:
            import config as _cfg
            num_results = int(getattr(_cfg, "SEARCH_NUM_RESULTS", num_results) or num_results)
        except Exception:
            pass
        results = await self._search_duckduckgo(query, num_results, intent)
        if not results:
            results = await self._search_http_async(query, num_results)
        return results

    @staticmethod
    async def _search_http_async(query: str, num_results: int = 8) -> List[Dict]:
        import urllib.parse
        import re
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://www.bing.com/search?q={urllib.parse.quote_plus(query)}"
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    )
                }
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status != 200:
                        return []
                    html = await response.text()
                    results = []
                    matches = re.findall(
                        r'<li class="b_algo".*?<h2[^>]*>\s*'
                        r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                        html, re.DOTALL | re.IGNORECASE,
                    )
                    if not matches:
                        matches = re.findall(
                            r'<a href="(https?://[^"]+)"[^>]*>([^<]{5,120})</a>', html
                        )
                    for href, title in matches[: num_results * 2]:
                        if any(x in href for x in ("bing.com", "microsoft.com", "javascript:")):
                            continue
                        if SystemController._is_junk_url(href):
                            continue
                        clean = re.sub(r"<[^>]+>", "", title).strip()
                        if not clean:
                            continue
                        results.append({"url": href, "title": clean[:120], "snippet": ""})
                        if len(results) >= num_results:
                            break
                    return results
        except Exception as e:
            logger.error(f"Ошибка HTTP поиска: {e}")
        return []

    async def search_and_open_best_async(self, query: str) -> Dict[str, Any]:
        """
        1) Вкладка поисковика
        2) Вторая вкладка — только если результат реально релевантный
           (иначе Zhihu/мусор не откроется)
        """
        try:
            import config as _cfg
            open_browser = getattr(_cfg, "SEARCH_OPEN_BROWSER", True)
            engine = getattr(_cfg, "SEARCH_ENGINE", "google")
        except Exception:
            open_browser = True
            engine = "google"

        intent = self.detect_search_intent(query)
        search_page = self.build_search_page_url(query, engine=engine, intent=intent)

        # картинки: только Images-поиск, без 2-й вкладки (SERP хрупкий)
        if intent == "images":
            logger.info(f"SEARCH images-only page q={query!r} engine={engine}")
            if open_browser:
                await self.open_url_async(search_page)
            return {
                "status": "success",
                "intent": "images",
                "search_page": search_page,
                "best_url": "",
                "best_title": "",
                "results_count": 0,
            }

        results = await self.search_async(query, intent=intent)
        logger.info(f"SEARCH results={len(results or [])} intent={intent} q={query!r}")

        min_score = 4.0
        try:
            import config as _cfg2
            min_score = float(getattr(_cfg2, "SEARCH_WEB_MIN_SCORE", 4.0) or 4.0)
        except Exception:
            min_score = 4.0
        best = self.pick_best_result(query, results, intent=intent, min_score=min_score)

        if open_browser:
            await self.open_url_async(search_page)
            await asyncio.sleep(0.55)
            if best:
                best_url = best.get("url") or best.get("image") or ""
                if best_url and not self._is_junk_url(best_url):
                    if best_url.rstrip("/") != search_page.rstrip("/"):
                        await self.open_url_async(best_url)
                        return {
                            "status": "success",
                            "intent": intent,
                            "search_page": search_page,
                            "best_url": best_url,
                            "best_title": best.get("title", ""),
                            "results_count": len(results or []),
                        }
                    logger.info("best_url == search_page — 2-я вкладка пропущена")
                else:
                    logger.info(f"best отклонён: {best_url!r}")
            else:
                logger.info("SEARCH: только страница поиска")

        return {
            "status": "search_only" if not best else "success",
            "intent": intent,
            "search_page": search_page,
            "best_url": (best or {}).get("url", "") if best else "",
            "best_title": (best or {}).get("title", "") if best else "",
            "results_count": len(results) if results else 0,
        }

    @staticmethod
    def search_and_open_best(query: str) -> Dict[str, Any]:
        """Синхронная версия для CommandExecutor."""
        try:
            import config as _cfg
            open_browser = getattr(_cfg, "SEARCH_OPEN_BROWSER", True)
            engine = getattr(_cfg, "SEARCH_ENGINE", "google")
            num = int(getattr(_cfg, "SEARCH_NUM_RESULTS", 8) or 8)
        except Exception:
            open_browser = True
            engine = "google"
            num = 8

        intent = SystemController.detect_search_intent(query)
        search_page = SystemController.build_search_page_url(
            query, engine=engine, intent=intent
        )

        if intent == "images":
            if open_browser:
                SystemController.open_url_in_browser(search_page)
            return {
                "status": "success",
                "intent": "images",
                "search_page": search_page,
                "best_url": "",
                "best_title": "",
                "results_count": 0,
            }

        if open_browser:
            SystemController.open_url_in_browser(search_page)
            time.sleep(0.8)

        results: List[Dict] = []
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                if intent == "images":
                    try:
                        for r in ddgs.images(query, max_results=num, region="ru-ru"):
                            page = r.get("url") or ""
                            img = r.get("image") or ""
                            url = page or img
                            if not url or SystemController._is_junk_url(url):
                                continue
                            results.append({
                                "url": url,
                                "title": r.get("title", "") or r.get("source", ""),
                                "snippet": r.get("source", ""),
                                "image": img or url,
                            })
                    except Exception:
                        pass
                if not results:
                    for r in ddgs.text(query, max_results=num, region="ru-ru"):
                        href = r.get("href") or ""
                        if not href or SystemController._is_junk_url(href):
                            continue
                        results.append({
                            "url": href,
                            "title": r.get("title", ""),
                            "snippet": r.get("body", ""),
                        })
        except Exception as e:
            logger.error(f"search_and_open_best DDG: {e}")

        min_score = 5.0 if intent == "images" else 4.0
        best = SystemController.pick_best_result(
            query, results, intent=intent, min_score=min_score
        )
        if best and open_browser:
            best_url = best.get("url") or best.get("image") or ""
            if best_url and not SystemController._is_junk_url(best_url):
                SystemController.open_url_in_browser(best_url)
                return {
                    "status": "success",
                    "intent": intent,
                    "search_page": search_page,
                    "best_url": best_url,
                    "best_title": best.get("title", ""),
                    "results_count": len(results),
                }

        return {
            "status": "search_only",
            "intent": intent,
            "search_page": search_page,
            "best_url": "",
            "best_title": "",
            "results_count": len(results),
        }

    # ===== СКРИНШОТЫ =====
    
    @staticmethod
    @run_in_executor
    def _take_screenshot(save_dir: str) -> Tuple[bool, str]:
        """Синхронное создание скриншота."""
        try:
            from PIL import ImageGrab
            os.makedirs(save_dir, exist_ok=True)
            filename = f"screenshot_{int(time.time())}.png"
            path = os.path.join(save_dir, filename)
            ImageGrab.grab().save(path)
            return True, path
        except ImportError:
            return False, "Pillow не установлен"
        except Exception as e:
            return False, str(e)
    
    async def take_screenshot_async(self, save_dir: Optional[str] = None) -> Tuple[bool, str]:
        """Асинхронное создание скриншота."""
        if save_dir is None:
            try:
                import config
                save_dir = config.SAVE_DIR
            except:
                save_dir = os.getcwd()
        
        async with fs_semaphore:
            return await self._take_screenshot(save_dir)
    
    # ===== СИСТЕМНАЯ ИНФОРМАЦИЯ =====
    
    @staticmethod
    @run_in_executor
    def _get_system_stats() -> Dict:
        """Синхронное получение системной статистики."""
        try:
            import psutil
            return {
                "cpu_percent": psutil.cpu_percent(interval=0.5),
                "cpu_count": psutil.cpu_count(),
                "memory": {
                    "total": psutil.virtual_memory().total // (1024**3),
                    "available": psutil.virtual_memory().available // (1024**3),
                    "percent": psutil.virtual_memory().percent
                },
                "disk": {
                    "total": psutil.disk_usage('/').total // (1024**3),
                    "used": psutil.disk_usage('/').used // (1024**3),
                    "free": psutil.disk_usage('/').free // (1024**3),
                    "percent": psutil.disk_usage('/').percent
                },
                "processes": len(psutil.pids()),
                "boot_time": psutil.boot_time()
            }
        except ImportError:
            return {"error": "psutil не установлен"}
        except Exception as e:
            return {"error": str(e)}
    
    async def get_system_stats_async(self) -> Dict:
        """Асинхронное получение системной статистики."""
        return await self._get_system_stats()
    
    # ===== ОКНА (Windows) =====
    
    @staticmethod
    @run_in_executor
    def _get_windows() -> List[Dict]:
        """Синхронное получение списка окон."""
        try:
            import pygetwindow as gw
            windows = []
            for w in gw.getAllWindows():
                if w.title:
                    windows.append({
                        "title": w.title,
                        "x": w.left,
                        "y": w.top,
                        "width": w.width,
                        "height": w.height,
                        "is_active": w.isActive,
                        "is_minimized": w.isMinimized
                    })
            return windows
        except ImportError:
            return []
    
    async def get_windows_async(self, limit: int = 25) -> List[Dict]:
        """Асинхронное получение списка окон."""
        windows = await self._get_windows()
        return windows[:limit]
    
    @staticmethod
    @run_in_executor
    def _activate_window(title: str) -> Tuple[bool, str]:
        """Синхронная активация окна."""
        try:
            import pygetwindow as gw
            wins = gw.getWindowsWithTitle(title)
            if wins:
                wins[0].activate()
                return True, f"Активировано: {wins[0].title}"
            return False, f"Окно не найдено: {title}"
        except ImportError:
            return False, "pygetwindow не установлен"
    
    async def activate_window_async(self, title: str) -> Tuple[bool, str]:
        """Асинхронная активация окна."""
        return await self._activate_window(title)
    
    # ===== ГРОМКОСТЬ (Windows) =====
    
    @staticmethod
    @run_in_executor
    def _set_volume(level: int) -> str:
        """Синхронная установка громкости."""
        try:
            import pyautogui
            # Неидеально, но работает
            for _ in range(20):
                pyautogui.press('volumedown')
            for _ in range(level // 5):
                pyautogui.press('volumeup')
            return f"Громкость ~{level}%"
        except ImportError:
            return "pyautogui не установлен"
    
    async def set_volume_async(self, level: int) -> str:
        """Асинхронная установка громкости."""
        return await self._set_volume(level)
    
    @staticmethod
    @run_in_executor
    def _volume_up() -> str:
        try:
            import pyautogui
            pyautogui.press('volumeup', presses=3)
            return "Громкость +"
        except ImportError:
            return "pyautogui не установлен"
    
    async def volume_up_async(self) -> str:
        return await self._volume_up()
    
    @staticmethod
    @run_in_executor
    def _volume_down() -> str:
        try:
            import pyautogui
            pyautogui.press('volumedown', presses=3)
            return "Громкость -"
        except ImportError:
            return "pyautogui не установлен"
    
    async def volume_down_async(self) -> str:
        return await self._volume_down()
    
    @staticmethod
    @run_in_executor
    def _mute() -> str:
        try:
            import pyautogui
            pyautogui.press('volumemute')
            return "Звук выключен"
        except ImportError:
            return "pyautogui не установлен"
    
    async def mute_async(self) -> str:
        return await self._mute()
    
    @staticmethod
    @run_in_executor
    def _unmute() -> str:
        try:
            import pyautogui
            pyautogui.press('volumemute')
            return "Звук включён"
        except ImportError:
            return "pyautogui не установлен"
    
    async def unmute_async(self) -> str:
        return await self._unmute()
    
    # ===== ПИТАНИЕ =====
    
    @staticmethod
    @run_in_executor
    def _lock_pc() -> str:
        try:
            import pyautogui
            pyautogui.hotkey('win', 'l')
            return "ПК заблокирован"
        except ImportError:
            return "pyautogui не установлен"
    
    async def lock_pc_async(self) -> str:
        return await self._lock_pc()
    


    # ===== ОКНА (расширенные sync + async) =====

    @staticmethod
    @run_in_executor
    def _minimize_all_windows() -> str:
        try:
            import pyautogui
            pyautogui.hotkey("win", "d")
            return "Все окна свёрнуты (рабочий стол)"
        except Exception:
            try:
                import pygetwindow as gw
                for w in gw.getAllWindows():
                    try:
                        if w.title and not w.isMinimized:
                            w.minimize()
                    except Exception:
                        pass
                return "Окна свёрнуты"
            except Exception as e2:
                return f"Ошибка: {e2}"

    async def minimize_all_windows_async(self) -> str:
        return await self._minimize_all_windows()

    @staticmethod
    def minimize_all_windows() -> str:
        try:
            import pyautogui
            pyautogui.hotkey("win", "d")
            return "Все окна свёрнуты (рабочий стол)"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    @run_in_executor
    def _minimize_window_by_title(title: str) -> str:
        try:
            import pygetwindow as gw
            wins = gw.getWindowsWithTitle(title)
            if not wins:
                wins = [w for w in gw.getAllWindows() if title.lower() in (w.title or "").lower()]
            if wins:
                wins[0].minimize()
                return f"Свёрнуто: {wins[0].title}"
            return f"Окно не найдено: {title}"
        except Exception as e:
            return f"Ошибка: {e}"

    async def minimize_window_async(self, title: str) -> str:
        return await self._minimize_window_by_title(title)

    @staticmethod
    def minimize_window_by_title(title: str) -> str:
        try:
            import pygetwindow as gw
            wins = gw.getWindowsWithTitle(title) or [
                w for w in gw.getAllWindows() if title.lower() in (w.title or "").lower()
            ]
            if wins:
                wins[0].minimize()
                return f"Свёрнуто: {wins[0].title}"
            return f"Окно не найдено: {title}"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    @run_in_executor
    def _maximize_window_by_title(title: str) -> str:
        try:
            import pygetwindow as gw
            wins = gw.getWindowsWithTitle(title) or [
                w for w in gw.getAllWindows() if title.lower() in (w.title or "").lower()
            ]
            if wins:
                wins[0].maximize()
                return f"Развёрнуто: {wins[0].title}"
            return f"Окно не найдено: {title}"
        except Exception as e:
            return f"Ошибка: {e}"

    async def maximize_window_async(self, title: str) -> str:
        return await self._maximize_window_by_title(title)

    @staticmethod
    def maximize_window_by_title(title: str) -> str:
        try:
            import pygetwindow as gw
            wins = gw.getWindowsWithTitle(title) or [
                w for w in gw.getAllWindows() if title.lower() in (w.title or "").lower()
            ]
            if wins:
                wins[0].maximize()
                return f"Развёрнуто: {wins[0].title}"
            return f"Окно не найдено: {title}"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    def switch_to_window(title: str) -> str:
        try:
            import pygetwindow as gw
            wins = gw.getWindowsWithTitle(title) or [
                w for w in gw.getAllWindows() if title.lower() in (w.title or "").lower()
            ]
            if wins:
                w = wins[0]
                if w.isMinimized:
                    w.restore()
                w.activate()
                return f"Активировано: {w.title}"
            return f"Окно не найдено: {title}"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    def close_window_by_title(title: str) -> str:
        try:
            import pygetwindow as gw
            wins = gw.getWindowsWithTitle(title) or [
                w for w in gw.getAllWindows() if title.lower() in (w.title or "").lower()
            ]
            if wins:
                title0 = wins[0].title
                wins[0].close()
                return f"Закрыто: {title0}"
            return f"Окно не найдено: {title}"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    def close_browser_tabs(count: int = 1) -> str:
        try:
            import pyautogui
            for _ in range(max(1, int(count))):
                pyautogui.hotkey("ctrl", "w")
            return f"Закрыто вкладок: {count}"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    def close_all_browser_tabs() -> str:
        try:
            import pyautogui
            pyautogui.hotkey("ctrl", "shift", "w")
            return "Все вкладки закрыты"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    def list_windows() -> str:
        try:
            import pygetwindow as gw
            titles = [w.title for w in gw.getAllWindows() if w.title and w.title.strip()]
            if not titles:
                return "Окон не найдено"
            lines = ["  • " + t for t in titles[:30]]
            return "Открытые окна:\n" + "\n".join(lines)
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    def list_top_processes() -> str:
        try:
            import psutil
            procs = []
            for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
                try:
                    procs.append(p.info)
                except Exception:
                    continue
            procs.sort(key=lambda x: x.get("cpu_percent") or 0, reverse=True)
            lines = []
            for info in procs[:15]:
                lines.append(
                    f"  {info.get('name','?'):30} PID {info.get('pid')} "
                    f"CPU {info.get('cpu_percent',0):.1f}% MEM {info.get('memory_percent',0):.1f}%"
                )
            return "Топ процессов:\n" + "\n".join(lines)
        except Exception as e:
            return f"Ошибка: {e}"


    @staticmethod
    def kill_process(name: str, confirm: bool = False) -> str:
        try:
            import psutil
            killed = []
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    if p.info["name"] and name.lower() in p.info["name"].lower():
                        p.kill()
                        killed.append(p.info["name"])
                except Exception:
                    continue
            if killed:
                return f"Завершены: {', '.join(set(killed))}"
            return f"Процесс «{name}» не найден"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    def show_desktop() -> str:
        try:
            import pyautogui
            pyautogui.hotkey("win", "d")
            return "Рабочий стол"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    def lock_pc() -> str:
        try:
            import pyautogui
            pyautogui.hotkey("win", "l")
            return "ПК заблокирован"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    def shutdown_pc(confirm: bool = False) -> str:
        if not confirm:
            return "⚠️ Нужно подтверждение"
        try:
            import subprocess, platform
            if platform.system() == "Windows":
                subprocess.Popen(["shutdown", "/s", "/t", "5"])
            else:
                subprocess.Popen(["shutdown", "-h", "+1"])
            return "Выключение через 5 сек…"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    def restart_pc(confirm: bool = False) -> str:
        if not confirm:
            return "⚠️ Нужно подтверждение"
        try:
            import subprocess, platform
            if platform.system() == "Windows":
                subprocess.Popen(["shutdown", "/r", "/t", "5"])
            else:
                subprocess.Popen(["shutdown", "-r", "+1"])
            return "Перезагрузка через 5 сек…"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    def monitor_off() -> str:
        try:
            import ctypes
            ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
            return "Монитор выключен"
        except Exception as e:
            return f"Ошибка: {e}"

    # ===== БУФЕР ОБМЕНА =====

    @staticmethod
    def clipboard_get() -> str:
        try:
            import pyperclip
            return pyperclip.paste() or "(пусто)"
        except Exception:
            try:
                from PyQt5.QtWidgets import QApplication
                app = QApplication.instance()
                if app:
                    return app.clipboard().text() or "(пусто)"
            except Exception:
                pass
            return "Буфер недоступен"

    @staticmethod
    def clipboard_set(text: str) -> str:
        try:
            import pyperclip
            pyperclip.copy(text or "")
            return "Буфер обновлён"
        except Exception:
            try:
                from PyQt5.QtWidgets import QApplication
                app = QApplication.instance()
                if app:
                    app.clipboard().setText(text or "")
                    return "Буфер обновлён"
            except Exception as e:
                return f"Ошибка: {e}"
            return "Буфер недоступен"

    @staticmethod
    def clipboard_append(text: str) -> str:
        current = SystemController.clipboard_get()
        if current in ("(пусто)", "Буфер недоступен"):
            current = ""
        return SystemController.clipboard_set((current or "") + (text or ""))

    # ===== БЛОКНОТ / ФАЙЛЫ =====

    @staticmethod
    def open_empty_notepad() -> str:
        try:
            import subprocess, platform
            if platform.system() == "Windows":
                subprocess.Popen(["notepad.exe"])
            else:
                subprocess.Popen(["xdg-open", "/tmp/note.txt"])
            return "Блокнот открыт"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    def open_notepad_with_text(content: str) -> str:
        try:
            import tempfile, subprocess, platform, os
            fd, path = tempfile.mkstemp(suffix=".txt", prefix="lisichka_")
            os.close(fd)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content or "")
            if platform.system() == "Windows":
                subprocess.Popen(["notepad.exe", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return f"Блокнот: {path}"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    def write_text_file(path: str, content: str):
        try:
            import os
            # Проверка ALLOWED_DIRS
            try:
                import config as _cfg
                dirs = getattr(_cfg, "ALLOWED_DIRS", None) or []
                if dirs:
                    norm = os.path.normcase(os.path.abspath(os.path.expanduser(path)))
                    ok = False
                    for d in dirs:
                        base = os.path.normcase(os.path.abspath(d))
                        if norm == base or norm.startswith(base + os.sep):
                            ok = True
                            break
                    if not ok:
                        return False, f"Доступ запрещён: {path}"
            except Exception:
                pass
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content or "")
            return True, f"Записано: {path}"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def open_file_or_url(path: str) -> str:
        try:
            import os, subprocess, platform
            if path.startswith(("http://", "https://")):
                ok, msg = SystemController.open_url_in_browser(path)
                return msg
            if platform.system() == "Windows":
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", path])
            return f"Открыто: {path}"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    def empty_recycle_bin(confirm: bool = False) -> str:
        if not confirm:
            return "⚠️ Нужно подтверждение"
        try:
            import ctypes
            ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)
            return "Корзина очищена"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    def read_screen_text() -> str:
        try:
            from PIL import ImageGrab
            try:
                import pytesseract
                img = ImageGrab.grab()
                text = pytesseract.image_to_string(img, lang="rus+eng")
                return text.strip() or "(текст не распознан)"
            except ImportError:
                return "pytesseract не установлен — OCR недоступен"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    def take_screenshot_and_analyze(question: str = "") -> str:
        try:
            from PIL import ImageGrab
            import os, time
            try:
                import config as _cfg
                save_dir = getattr(_cfg, "SAVE_DIR", ".")
            except Exception:
                save_dir = "."
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(save_dir, f"screen_{int(time.time())}.png")
            ImageGrab.grab().save(path)
            return f"Скриншот сохранён: {path}. Вопрос: {question or '—'}"
        except Exception as e:
            return f"Ошибка: {e}"

    @staticmethod
    def take_screenshot() -> str:
        try:
            from PIL import ImageGrab
            import os, time
            try:
                import config as _cfg
                save_dir = getattr(_cfg, "SAVE_DIR", ".")
            except Exception:
                save_dir = "."
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(save_dir, f"screenshot_{int(time.time())}.png")
            ImageGrab.grab().save(path)
            return f"📸 {path}"
        except Exception as e:
            return f"❌ {e}"

    @staticmethod
    def run_command(command: str) -> str:
        try:
            import subprocess, platform
            if platform.system() == "Windows":
                proc = subprocess.run(
                    ["cmd", "/c", command],
                    capture_output=True, text=True, timeout=30
                )
            else:
                proc = subprocess.run(
                    ["sh", "-c", command],
                    capture_output=True, text=True, timeout=30
                )
            if proc.returncode == 0:
                return (proc.stdout or "OK").strip()
            return (proc.stderr or f"Код {proc.returncode}").strip()
        except Exception as e:
            return f"Ошибка: {e}"

    async def minimize_all_async(self) -> str:
        return await self._minimize_all_windows()

    async def switch_to_window_async(self, title: str) -> str:
        return await self._activate_window(title)

    async def lock_async(self) -> str:
        return await self._lock_pc()

    def close(self):
        """Закрытие ресурсов."""
        pass
