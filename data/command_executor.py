# command_executor.py — единый исполнитель команд (sync + async)
# Безопасность: whitelist RUN, confirm для опасных, проверка ALLOWED_DIRS
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import re
import shlex
import os
import webbrowser
from urllib.parse import quote_plus, urljoin
from typing import Dict, Any, Optional, List, Tuple

from system_controller import SystemController
from app_scanner import AppScanner
from notes_manager import NotesManager
from persistent_memory import PersistentMemory
from reminder_manager import ReminderManager

import config

logger = logging.getLogger(__name__)

# Критичные процессы — не убивать даже с confirm
PROTECTED_PROCESSES = frozenset({
    "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
    "lsass.exe", "smss.exe", "system", "system idle process",
    "svchost.exe", "csrss", "lsass", "winlogon",
})

# Всегда запрещённые корни (даже если попали в ALLOWED_DIRS по ошибке)
FORBIDDEN_PATH_PREFIXES = (
    r"C:\Windows\System32",
    r"C:\Windows\SysWOW64",
    r"C:\Windows\WinSxS",
    r"C:\Program Files\Windows Defender",
    r"C:\$Recycle.Bin",
)

# Запрещённые шаблоны в RUN
RUN_DENY_PATTERNS = (
    r"\bformat\b", r"\bdel\s+/[sqf]", r"\brm\s+-rf\b", r"\brmdir\s+/s",
    r"\bshutdown\b", r"\breboot\b", r"reg\s+delete", r"net\s+user",
    r"powershell\s+-enc", r"powershell\s+-e\b", r"frombase64",
    r"invoke-expression", r"iex\s*\(", r"curl\s+.+\|\s*sh",
    r"wget\s+.+\|\s*sh",
)


class CommandExecutor:
    """
    Единая точка выполнения команд.
    - execute() / execute_async()
    Опасные операции всегда требуют confirm; RUN — whitelist в SAFE_MODE.
    """

    def __init__(self):
        self.system = SystemController()
        self.app_scanner = AppScanner() if getattr(config, "APP_SCANNER_AVAILABLE", True) else None
        self.reminder_manager = ReminderManager()
        self.notes = NotesManager()
        self.persistent_memory = PersistentMemory()
        self._alert_callback = None

        self.system_apps = {
            "блокнот": "notepad.exe",
            "блакнот": "notepad.exe",
            "notepad": "notepad.exe",
            "notepad.exe": "notepad.exe",
            "калькулятор": "calc.exe",
            "проводник": "explorer.exe",
            "командная строка": "cmd.exe",
            "powershell": "powershell.exe",
            "диспетчер задач": "taskmgr.exe",
        }

    def set_alert_callback(self, callback):
        self._alert_callback = callback

    # ------------------------------------------------------------------
    # Безопасность
    # ------------------------------------------------------------------

    def _require_confirm(self, confirm: bool, label: str) -> Optional[str]:
        """Опасные команды всегда требуют confirm (независимо от SAFE_MODE)."""
        if confirm:
            return None
        return f"⚠️ Требуется подтверждение: {label}"

    def _path_allowed(self, path: str) -> bool:
        """
        Жёсткий sandbox + realpath (path traversal):
        - пустой / null → False
        - realpath должен остаться внутри ALLOWED_DIRS
        - FORBIDDEN / Windows → всегда False
        """
        if not path or not str(path).strip():
            return False
        raw = str(path).strip()
        if "\x00" in raw:
            return False
        try:
            expanded = os.path.expanduser(raw)
            # realpath резолвит .. и симлинки
            norm = os.path.normcase(os.path.realpath(os.path.abspath(expanded)))
        except Exception:
            return False

        for bad in FORBIDDEN_PATH_PREFIXES:
            try:
                b = os.path.normcase(os.path.realpath(os.path.abspath(bad)))
                if norm == b or norm.startswith(b + os.sep):
                    return False
            except Exception:
                continue

        if getattr(config, "HARD_SANDBOX", True):
            try:
                windir = os.path.normcase(
                    os.path.realpath(os.path.abspath(os.environ.get("SystemRoot", r"C:\Windows")))
                )
                if norm == windir or norm.startswith(windir + os.sep):
                    return False
            except Exception:
                pass

        dirs = list(getattr(config, "ALLOWED_DIRS", None) or [])
        safe = bool(getattr(config, "SAFE_MODE", True))
        hard = bool(getattr(config, "HARD_SANDBOX", True))

        if (safe or hard) and not dirs:
            try:
                dirs = [getattr(config, "DATA_DIR", os.path.dirname(os.path.abspath(__file__)))]
            except Exception:
                dirs = [os.path.dirname(os.path.abspath(__file__))]

        if not dirs:
            return not (safe or hard)

        for d in dirs:
            try:
                base = os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(str(d)))))
                if norm == base or norm.startswith(base + os.sep):
                    return True
            except Exception:
                continue
        return False


    def _run_allowed(self, command: str) -> Tuple[bool, str]:
        """
        SAFE_MODE: разрешён только exe из RUN_WHITELIST.
        Проверка по argv[0] (shlex), НЕ по подстроке `w_base in low`
        (иначе `evil.exe notepad` / `cmd /c ...` обходили whitelist).
        """
        cmd = (command or "").strip()
        if not cmd:
            return False, "пустая команда"
        low = cmd.lower()
        for pat in RUN_DENY_PATTERNS:
            if re.search(pat, low, re.I):
                return False, "запрещённый шаблон в команде"

        # Разбор аргументов: Windows-friendly
        try:
            parts = shlex.split(cmd, posix=False)
        except ValueError:
            parts = cmd.split()
        if not parts:
            return False, "пустая команда"

        exe = os.path.basename(parts[0]).lower()
        if exe.endswith('"') or exe.startswith('"'):
            exe = exe.strip('"')

        if getattr(config, "SAFE_MODE", True):
            whitelist = [w.lower() for w in (getattr(config, "RUN_WHITELIST", None) or [])]
            if not whitelist:
                return False, "RUN_WHITELIST пуст — RUN заблокирован в SAFE_MODE"

            allowed_names = set()
            for w in whitelist:
                base = os.path.basename(w.lower().strip())
                allowed_names.add(base)
                if base.endswith(".exe"):
                    allowed_names.add(base[:-4])
                else:
                    allowed_names.add(base + ".exe")

            if exe not in allowed_names:
                return False, f"«{exe}» нет в RUN_WHITELIST"

            # В SAFE_MODE запрещаем цепочки: cmd /c, powershell -c с произвольным хвостом
            # если exe — cmd/powershell, разрешаем только без опасных флагов
            dangerous_flags = ("/c", "-c", "-command", "-enc", "-e", "-encodedcommand")
            if exe in ("cmd.exe", "cmd", "powershell.exe", "powershell", "pwsh.exe", "pwsh"):
                rest_low = " ".join(parts[1:]).lower()
                for fl in dangerous_flags:
                    if fl in rest_low.split() or rest_low.strip().startswith(fl):
                        return False, f"запрещены флаги запуска через {exe} ({fl})"

        return True, "ok"


    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def execute(self, command: Dict[str, Any]) -> Optional[str]:
        """Синхронное выполнение."""
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(asyncio.run, self.execute_async(command))
                    return fut.result(timeout=120)

            return asyncio.run(self.execute_async(command))
        except Exception as e:
            logger.error(f"Ошибка execute({command.get('type')}): {e}")
            return f"⚠️ Ошибка: {e}"

    async def execute_async(self, command: Dict[str, Any]) -> Optional[str]:
        """Асинхронное выполнение."""
        cmd_type = command.get("type")
        params = command.get("params")

        try:
            try:
                from commands import execute_tag
                routed = execute_tag(cmd_type, params)
            except Exception:
                routed = None
            if routed:
                return routed

            if cmd_type == "SEARCH":
                return await self._search_async(params)
            if cmd_type == "LAUNCH":
                return await self._launch_async(params)
            if cmd_type == "OPEN":
                return await self._open_async(params)
            if cmd_type == "RUN":
                return await self._run_async(params)
            if cmd_type == "WRITE":
                return self._write(params)
            if cmd_type == "NOTEPAD":
                return self._notepad(params)
            if cmd_type == "MINIMIZE":
                return self._minimize(params)
            if cmd_type == "MAXIMIZE":
                return self._maximize(params)
            if cmd_type == "SWITCH":
                return self._switch(params)
            if cmd_type == "CLOSE_WINDOW":
                return self._close_window(params)
            if cmd_type == "CLOSE_TAB":
                return self._close_tab(params if isinstance(params, int) else 1)
            if cmd_type == "CLOSE_ALL_TABS":
                return self._close_all_tabs()
            if cmd_type == "WINDOWS":
                return self._windows()
            if cmd_type == "PROCESSES":
                return self._processes()
            if cmd_type == "KILL":
                return self._kill(params or {})
            if cmd_type == "SCREENSHOT":
                return await self._screenshot_async()
            if cmd_type == "DESKTOP":
                return self._desktop()
            if cmd_type == "LOCK":
                return self._lock()
            if cmd_type == "SHUTDOWN":
                return self._shutdown(params or {})
            if cmd_type == "RESTART":
                return self._restart(params or {})
            if cmd_type == "VOLUME":
                return await self._volume_async(params)
            if cmd_type == "VOLUME_UP":
                return await self._volume_up_async()
            if cmd_type == "VOLUME_DOWN":
                return await self._volume_down_async()
            if cmd_type == "MUTE":
                return await self._mute_async()
            if cmd_type == "UNMUTE":
                return await self._unmute_async()
            if cmd_type == "MONITOR_OFF":
                return self._monitor_off()
            if cmd_type == "CLIPBOARD_GET":
                return self._clipboard_get()
            if cmd_type == "CLIPBOARD_SET":
                return self._clipboard_set(params)
            if cmd_type == "CLIPBOARD_APPEND":
                return self._clipboard_append(params)
            if cmd_type == "NOTE_ADD":
                return self.notes.add(params or "")
            if cmd_type == "NOTE_LIST":
                return self.notes.list_notes()
            if cmd_type == "NOTE_SEARCH":
                return self.notes.search(params or "")
            if cmd_type == "NOTE_CLEAR":
                return self.notes.clear((params or {}).get("confirm", False))
            if cmd_type == "REMINDER":
                return self._reminder(params or {})
            if cmd_type == "TIMER":
                return self._reminder(params or {})
            if cmd_type == "REMINDER_LIST":
                return self._reminder_list()
            if cmd_type == "REMINDER_DELETE":
                return self._reminder_delete(params)
            if cmd_type == "REMINDER_HISTORY":
                return self._reminder_history()
            if cmd_type == "READ_SCREEN":
                return self._read_screen()
            if cmd_type == "SCREEN_ANALYSIS":
                return self._screen_analysis(params or "Что на экране?")
            if cmd_type == "DISK_SPACE":
                return await self._disk_space_async()
            if cmd_type == "CREATE_FOLDER":
                return await self._create_folder_async(params)
            if cmd_type == "COPY":
                return await self._copy_async(params or {})
            if cmd_type == "MOVE":
                return await self._move_async(params or {})
            if cmd_type == "DELETE":
                return await self._delete_async(params or {})
            if cmd_type == "RENAME":
                return await self._rename_async(params or {})
            if cmd_type == "EMPTY_RECYCLE":
                return self._empty_recycle(params or {})
            if cmd_type == "ANIM":
                return None
            # ===== НОВЫЕ КОМАНДЫ ДЛЯ АЛИАСОВ =====
            if cmd_type == "REMEMBER_ALIAS":
                return await self._remember_alias_async(params)
            if cmd_type == "ALIAS_LIST":
                return await self._alias_list_async(params)
            if cmd_type == "ALIAS_DELETE":
                return await self._alias_delete_async(params)
            if cmd_type == "REMEMBER_APP":
                return await self._remember_app_async(params)
            logger.warning(f"Неизвестная команда: {cmd_type}")
            return None
        except Exception as e:
            logger.error(f"Ошибка команды {cmd_type}: {e}")
            return f"⚠️ Ошибка: {e}"

    def execute_all(self, commands: List[Dict[str, Any]]) -> List[str]:
        results = []
        for cmd in commands:
            r = self.execute(cmd)
            if r:
                results.append(r)
        return results

    async def execute_all_async(self, commands: List[Dict[str, Any]]) -> List[str]:
        results = []
        for cmd in commands:
            r = await self.execute_async(cmd)
            if r:
                results.append(r)
        return results

    # ------------------------------------------------------------------
    # Внутренние проверки
    # ------------------------------------------------------------------

    def _check_pc(self) -> bool:
        if not getattr(config, "ENABLE_PC_CONTROL", True):
            logger.warning("Управление ПК отключено")
            return False
        return True

    # ------------------------------------------------------------------
    # SEARCH
    # ------------------------------------------------------------------

    async def _search_async(self, params: str) -> str:
        if not getattr(config, "ENABLE_INTERNET", True):
            return "🌐 Поиск отключён"

        q = (params or "").strip()
        q = q.strip("«»\"'“”").strip()
        q = re.sub(r'^[«»"“”\']+|[«»"“”\']+$', "", q).strip()
        bad = (
            not q
            or len(q) < 2
            or "уже выполнен" in q.lower()
            or q.lower() in ("(уже выполнен)", "уже выполнен", "none", "null", "n/a")
        )
        if bad:
            return "⚠️ Поиск пропущен: запрос пустой"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._search_two_tabs, q)

    def _search_intent(self, q: str) -> str:
        t = (q or "").lower()
        if any(w in t for w in ("картин", "кортин", "фото", "изображен", "images", "pics")):
            return "images"
        if any(w in t for w in ("видео", "youtube", "ютуб", "ролик")):
            return "video"
        return "web"

    def _search_page_url(self, q: str, intent: str) -> str:
        engine = (getattr(config, "SEARCH_ENGINE", "google") or "google").lower()
        enc = quote_plus(q)
        if intent == "images":
            if engine == "yandex":
                return f"https://yandex.ru/images/search?text={enc}"
            if engine == "bing":
                return f"https://www.bing.com/images/search?q={enc}"
            return f"https://www.google.com/search?tbm=isch&q={enc}"
        if intent == "video":
            return f"https://www.youtube.com/results?search_query={enc}"
        if engine == "yandex":
            return f"https://yandex.ru/search/?text={enc}"
        if engine == "duckduckgo":
            return f"https://duckduckgo.com/?q={enc}"
        if engine == "bing":
            return f"https://www.bing.com/search?q={enc}"
        return f"https://www.google.com/search?q={enc}"

    def _fetch_best_result(self, q: str, intent: str) -> Optional[str]:
        """Первая внешняя ссылка из HTML DuckDuckGo (без ключа API)."""
        if intent == "images":
            return None
        try:
            import urllib.request
            url = "https://html.duckduckgo.com/html/?q=" + quote_plus(q)
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 LisichkaSearch/1.0"},
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            hrefs = re.findall(
                r'(?:class="result__a"[^>]*href="|uddg=)([^"&]+)',
                html,
                flags=re.I,
            )
            if not hrefs:
                hrefs = re.findall(r'href="(https?://[^"]+)"', html)
            skip = (
                "duckduckgo.com", "google.com/search", "yandex.",
                "bing.com/search", "javascript:",
            )
            for h in hrefs:
                try:
                    from urllib.parse import unquote
                    h = unquote(h)
                except Exception:
                    pass
                if not h.startswith("http"):
                    continue
                if any(s in h.lower() for s in skip):
                    continue
                return h
        except Exception as e:
            logger.debug(f"best result: {e}")
        return None

    def _open_in_selected_browser(self, url: str) -> bool:
        if not url:
            return False
        path = (getattr(config, "BROWSER_PATH", "") or "").strip()
        try:
            if path and os.path.isfile(path):
                subprocess.Popen(
                    [path, url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
        except Exception as e:
            logger.debug(f"browser path: {e}")
        try:
            webbrowser.open_new_tab(url)
            return True
        except Exception as e:
            logger.warning(f"webbrowser: {e}")
            return False

    def _search_two_tabs(self, q: str) -> str:
        intent = self._search_intent(q)
        search_url = self._search_page_url(q, intent)
        best = self._fetch_best_result(q, "web")

        opened = []
        if getattr(config, "SEARCH_OPEN_BROWSER", True):
            if self._open_in_selected_browser(search_url):
                opened.append("поиск")
            if best and self._open_in_selected_browser(best):
                opened.append("лучший результат")
        else:
            return f"🔍 Поиск собран, браузер выключен: {q}"

        if intent == "images":
            return f"🔍 Поиск картинок открыт: {q}"
        if best and "лучший результат" in opened:
            return f"🔍 Поиск и лучший результат: {best[:80]}"
        return f"🔍 Открыт поиск: {q}"

    # ------------------------------------------------------------------
    # LAUNCH / OPEN / RUN (с поддержкой алиасов)
    # ------------------------------------------------------------------

    async def _launch_async(self, params: str) -> str:
        """Запуск с поддержкой алиасов."""
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        
        if not params or not params.strip():
            return "❌ Не указано имя программы"
        
        params_clean = params.strip()
        params_lower = params_clean.lower()
        
        # ===== СНАЧАЛА ПРОВЕРЯЕМ АЛИАСЫ =====
        if self.app_scanner:
            resolved = self.app_scanner.resolve_alias(params_lower)
            if resolved:
                ok, msg = self.app_scanner.launch_by_alias(params_lower)
                return f"🚀 {msg}" if ok else f"❌ {msg}"
        
        # Проверяем системные приложения
        if params_lower in self.system_apps:
            exe = self.system_apps[params_lower]
            path = shutil.which(exe)
            if not path:
                system_dirs = [
                    os.environ.get("SystemRoot", "C:\\Windows"),
                    os.environ.get("SystemRoot", "C:\\Windows") + "\\System32",
                ]
                for dir_path in system_dirs:
                    full_path = os.path.join(dir_path, exe)
                    if os.path.exists(full_path):
                        path = full_path
                        break
            
            if path:
                try:
                    subprocess.Popen([path], shell=False)
                    return f"🚀 Запущено: {params_clean}"
                except Exception as e:
                    return f"❌ Ошибка запуска: {e}"
            else:
                return f"❌ Программа '{params_clean}' не найдена"
        
        if not self.app_scanner:
            return "❌ Сканер приложений недоступен"
        
        ok, msg = self.app_scanner.launch_app(params_clean)
        return f"🚀 {msg}" if ok else f"❌ {msg}"

    async def _open_async(self, params: str) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        p = (params or "").strip()
        if not p or p.lower() in ("путь", "path", "файл", "название"):
            return "❌ Не указано что открыть"
        
        # ===== ПРОВЕРЯЕМ АЛИАСЫ =====
        if self.app_scanner:
            resolved = self.app_scanner.resolve_alias(p.lower())
            if resolved:
                ok, msg = self.app_scanner.launch_by_alias(p.lower())
                return f"📂 {msg}" if ok else f"❌ {msg}"
        
        if p.startswith(("http://", "https://", "www.")):
            ok, msg = await self.system.open_url_async(p)
            return f"🌐 {msg}" if ok else f"❌ {msg}"
        
        p_lower = p.lower()
        if p_lower in self.system_apps:
            return await self._launch_async(p)
        
        result = await self.system.run_command_async(f"start {p}")
        return f"📂 {result}"

    async def _run_async(self, params: str) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        if not params or not params.strip():
            return "❌ Не указана команда"
        ok, reason = self._run_allowed(params)
        if not ok:
            logger.warning(f"RUN заблокирован: {reason} | cmd={params[:80]}")
            return f"⛔ RUN запрещён: {reason}"
        return await self.system.run_command_async(params or "")

    # ------------------------------------------------------------------
    # WRITE
    # ------------------------------------------------------------------

    def _write(self, params) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"

        path = ""
        content = ""

        if isinstance(params, dict):
            path = params.get("path", "")
            content = params.get("content", "")
        elif isinstance(params, str):
            match = re.search(
                r'path[:=]\s*["\']?(.+?)["\']?\s+(?:content[:=]\s*["\']?(.+?)["\']?)?$',
                params,
                re.I,
            )
            if match:
                path = match.group(1).strip()
                content = match.group(2).strip() if match.group(2) else ""
            else:
                lines = params.strip().split("\n")
                if len(lines) >= 2:
                    path = lines[0].strip()
                    content = "\n".join(lines[1:]).strip()
                else:
                    return "❌ Неверный формат: укажите путь и содержимое"

        if not path:
            return "❌ Не указан путь к файлу"
        if not self._path_allowed(path):
            return f"⛔ Путь вне ALLOWED_DIRS: {path}"

        ok, msg = (
            SystemController.write_text_file(path, content)
            if hasattr(SystemController, "write_text_file")
            else (False, "не реализовано")
        )
        return f"📝 {msg}" if ok else f"❌ {msg}"

    def _notepad(self, params) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        
        content = ""
        if isinstance(params, dict):
            content = params.get("content", "")
        elif isinstance(params, str):
            content = params
        
        if hasattr(SystemController, "open_notepad_with_text"):
            return SystemController.open_notepad_with_text(content)
        return "📂 Блокнот"

    # ===== НОВЫЕ МЕТОДЫ ДЛЯ АЛИАСОВ =====

    async def _remember_alias_async(self, params: Dict) -> str:
        """Запоминает алиас."""
        if not self.app_scanner:
            return "❌ Сканер приложений недоступен"
        
        alias = params.get('alias', '').strip()
        target = params.get('target', '').strip()
        type_ = params.get('type', '').strip().lower()
        
        if not alias or not target:
            return "❌ Укажите имя и цель"
        
        # Если тип не указан, определяем автоматически
        if not type_ or type_ not in ('app', 'file', 'folder', 'url', 'command'):
            if target.startswith(('http://', 'https://', 'www.')):
                type_ = 'url'
            elif os.path.exists(target):
                if os.path.isdir(target):
                    type_ = 'folder'
                elif target.lower().endswith('.exe') or target.lower().endswith('.lnk'):
                    type_ = 'app'
                else:
                    type_ = 'file'
            else:
                type_ = 'command'
        
        # Добавляем также в apps, если это программа
        if type_ == 'app' and (target.lower().endswith('.exe') or target.lower().endswith('.lnk')):
            self.app_scanner.add_manual_app(alias, target, "alias")
        
        ok = self.app_scanner.add_alias(alias, target, type_)
        if ok:
            type_names = {
                'app': 'программу',
                'file': 'файл',
                'folder': 'папку',
                'url': 'сайт',
                'command': 'команду'
            }
            type_name = type_names.get(type_, type_)
            return f"✅ Запомнила, хозяин! {type_name} «{alias}» → {target}"
        return "❌ Не удалось запомнить алиас"

    async def _alias_list_async(self, params: Dict) -> str:
        """Показывает список алиасов."""
        if not self.app_scanner:
            return "❌ Сканер приложений недоступен"
        
        type_ = params.get('type') if params else None
        aliases = self.app_scanner.list_aliases(type_)
        
        if not aliases:
            return "📋 Алиасов пока нет. Используйте: запомни алиас имя цель"
        
        lines = ["📋 Алиасы:"]
        type_names = {
            'app': '🚀',
            'file': '📄',
            'folder': '📂',
            'url': '🌐',
            'command': '⚡'
        }
        
        for a in aliases:
            icon = type_names.get(a['type'], '•')
            usage = f" (использовано {a['usage_count']} раз)" if a['usage_count'] else ""
            desc = f" — {a['description']}" if a['description'] else ""
            lines.append(f"  {icon} {a['alias']} → {a['target']}{desc}{usage}")
        
        return "\n".join(lines)

    async def _alias_delete_async(self, alias: str) -> str:
        """Удаляет алиас."""
        if not self.app_scanner:
            return "❌ Сканер приложений недоступен"
        
        alias = alias.strip()
        if self.app_scanner.delete_alias(alias):
            return f"🗑️ Алиас «{alias}» удалён"
        return f"❌ Алиас «{alias}» не найден"

    async def _remember_app_async(self, params: Dict) -> str:
        """Обратная совместимость: запоминает программу."""
        if not self.app_scanner:
            return "❌ Сканер приложений недоступен"
        
        name = params.get('name', '').strip()
        path = params.get('path', '').strip()
        
        if not name or not path:
            return "❌ Укажите имя и путь"
        
        self.app_scanner.add_manual_app(name, path, "alias")
        self.app_scanner.add_alias(name, path, "app")
        return f"✅ Запомнена программа: {name} → {path}"

    # ------------------------------------------------------------------
    # Остальные методы (без изменений)
    # ------------------------------------------------------------------

    def _minimize(self, params: str) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        if (params or "").lower() == "all":
            return SystemController.minimize_all_windows() if hasattr(SystemController, "minimize_all_windows") else "Свёрнуто"
        return SystemController.minimize_window_by_title(params) if hasattr(SystemController, "minimize_window_by_title") else "Свёрнуто"

    def _maximize(self, params: str) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return SystemController.maximize_window_by_title(params) if hasattr(SystemController, "maximize_window_by_title") else "Развёрнуто"

    def _switch(self, params: str) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return SystemController.switch_to_window(params) if hasattr(SystemController, "switch_to_window") else "Переключено"

    def _close_window(self, params: str) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return SystemController.close_window_by_title(params) if hasattr(SystemController, "close_window_by_title") else "Закрыто"

    def _close_tab(self, count: int = 1) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return SystemController.close_browser_tabs(count) if hasattr(SystemController, "close_browser_tabs") else "Вкладка закрыта"

    def _close_all_tabs(self) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return SystemController.close_all_browser_tabs() if hasattr(SystemController, "close_all_browser_tabs") else "Вкладки закрыты"

    def _windows(self) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return SystemController.list_windows() if hasattr(SystemController, "list_windows") else "Нет данных"

    def _processes(self) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return SystemController.list_top_processes() if hasattr(SystemController, "list_top_processes") else "Нет данных"

    def _kill(self, params: Dict) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        name = (params.get("name") or "").strip()
        if not name:
            return "❌ Не указан процесс"
        base = os.path.basename(name).lower()
        if base in PROTECTED_PROCESSES or name.lower() in PROTECTED_PROCESSES:
            return f"⛔ Защищённый процесс нельзя завершить: {name}"
        confirm = bool(params.get("confirm", False))
        msg = self._require_confirm(confirm, f"[KILL {name} confirm]")
        if msg:
            return msg
        return (
            SystemController.kill_process(name, True)
            if hasattr(SystemController, "kill_process")
            else f"Завершён: {name}"
        )

    async def _screenshot_async(self) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        ok, path = await self.system.take_screenshot_async()
        return f"📸 {path}" if ok else f"❌ {path}"

    def _desktop(self) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return SystemController.show_desktop() if hasattr(SystemController, "show_desktop") else "Рабочий стол"

    def _lock(self) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return SystemController.lock_pc() if hasattr(SystemController, "lock_pc") else "ПК заблокирован"

    def _shutdown(self, params: Dict) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        # Всегда нужен явный confirm — LLM/микромодель не могут «тихо» выключить ПК
        confirm = bool((params or {}).get("confirm", False))
        msg = self._require_confirm(confirm, "[SHUTDOWN confirm]")
        if msg:
            return msg
        if not getattr(config, "ENABLE_PC_CONTROL", True):
            return "⛔ Управление ПК отключено"
        logger.warning("SHUTDOWN confirmed — выключение ПК")
        return (
            SystemController.shutdown_pc(True)
            if hasattr(SystemController, "shutdown_pc")
            else "Выключение…"
        )

    def _restart(self, params: Dict) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        confirm = bool((params or {}).get("confirm", False))
        msg = self._require_confirm(confirm, "[RESTART confirm]")
        if msg:
            return msg
        if not getattr(config, "ENABLE_PC_CONTROL", True):
            return "⛔ Управление ПК отключено"
        logger.warning("RESTART confirmed — перезагрузка ПК")
        return (
            SystemController.restart_pc(True)
            if hasattr(SystemController, "restart_pc")
            else "Перезагрузка…"
        )

    async def _volume_async(self, level) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        try:
            level = int(level)
        except (TypeError, ValueError):
            return "⚠️ Неверный уровень громкости"
        return await self.system.set_volume_async(level)

    async def _volume_up_async(self) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return await self.system.volume_up_async()

    async def _volume_down_async(self) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return await self.system.volume_down_async()

    async def _mute_async(self) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return await self.system.mute_async()

    async def _unmute_async(self) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return await self.system.unmute_async()

    def _monitor_off(self) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return SystemController.monitor_off() if hasattr(SystemController, "monitor_off") else "Монитор выключен"

    def _clipboard_get(self) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return SystemController.clipboard_get() if hasattr(SystemController, "clipboard_get") else ""

    def _clipboard_set(self, text: str) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return SystemController.clipboard_set(text) if hasattr(SystemController, "clipboard_set") else "OK"

    def _clipboard_append(self, text: str) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return SystemController.clipboard_append(text) if hasattr(SystemController, "clipboard_append") else "OK"

    # ------------------------------------------------------------------
    # Напоминания
    # ------------------------------------------------------------------

    def _reminder(self, params: Dict) -> str:
        text = params.get("text", "")
        amount = int(params.get("amount", 0) or 0)
        unit = (params.get("unit") or "секунд").lower()
        if any(x in unit for x in ("мин", "min")):
            seconds = amount * 60
        elif any(x in unit for x in ("час", "hour")):
            seconds = amount * 3600
        else:
            seconds = amount
        rid = self.reminder_manager.add_reminder(text, seconds)
        return f"⏰ Напоминание установлено: «{text}» через {amount} {unit} (ID {rid})"

    def _reminder_list(self) -> str:
        reminders = self.reminder_manager.get_reminders()
        if reminders:
            return "📋 Активные напоминания:\n" + "\n".join(reminders)
        return "📋 Активных напоминаний нет"

    def _reminder_delete(self, rid) -> str:
        try:
            rid = int(rid)
        except (TypeError, ValueError):
            return "❌ Неверный ID"
        if self.reminder_manager.remove_reminder(rid):
            return f"🗑️ Напоминание {rid} удалено"
        return f"❌ Напоминание {rid} не найдено"

    def _reminder_history(self) -> str:
        history = self.reminder_manager.get_reminders_history(10)
        if history:
            lines = ["📋 История напоминаний:"]
            for row in history:
                status = "✅" if row[4] else "⏳"
                lines.append(f"  {status} ID:{row[0]} {row[1]} ({row[2][:16]})")
            return "\n".join(lines)
        return "📋 История напоминаний пуста"

    def _read_screen(self) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return SystemController.read_screen_text() if hasattr(SystemController, "read_screen_text") else "Недоступно"

    def _screen_analysis(self, question: str) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return SystemController.take_screenshot_and_analyze(question) if hasattr(SystemController, "take_screenshot_and_analyze") else "Недоступно"

    async def _disk_space_async(self) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        return await self.system.get_disk_space_async()

    async def _create_folder_async(self, path: str) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        ok, msg = await self.system.create_folder_async(path or "")
        return msg

    async def _copy_async(self, params: Dict) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        src, dst = params.get("src", ""), params.get("dst", "")
        if not self._path_allowed(src) or not self._path_allowed(dst):
            return "⛔ Путь вне ALLOWED_DIRS"
        ok, msg = await self.system.copy_file_async(src, dst)
        return msg

    async def _move_async(self, params: Dict) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        src, dst = params.get("src", ""), params.get("dst", "")
        if not self._path_allowed(src) or not self._path_allowed(dst):
            return "⛔ Путь вне ALLOWED_DIRS"
        ok, msg = await self.system.move_file_async(src, dst)
        return msg

    async def _delete_async(self, params: Dict) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        path = (params or {}).get("path", "")
        if not path:
            return "❌ Не указан путь"
        if not self._path_allowed(path):
            return f"⛔ Путь вне ALLOWED_DIRS: {path}"
        confirm = bool((params or {}).get("confirm", False))
        msg = self._require_confirm(confirm, f"[DELETE {path} confirm]")
        if msg:
            return msg
        ok, msg = await self.system.delete_file_async(path)
        return msg

    async def _rename_async(self, params: Dict) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        old, new = params.get("old", ""), params.get("new", "")
        if not self._path_allowed(old) or not self._path_allowed(new):
            return "⛔ Путь вне ALLOWED_DIRS"
        if hasattr(self.system, "move_file_async"):
            ok, msg = await self.system.move_file_async(old, new)
            return msg
        return "Переименовано"

    def _empty_recycle(self, params: Dict) -> str:
        if not self._check_pc():
            return "⛔ Управление ПК отключено"
        confirm = bool((params or {}).get("confirm", False))
        msg = self._require_confirm(confirm, "[EMPTY RECYCLE confirm]")
        if msg:
            return msg
        return (
            SystemController.empty_recycle_bin(True)
            if hasattr(SystemController, "empty_recycle_bin")
            else "Корзина очищена"
        )

    def close(self):
        try:
            self.reminder_manager.close()
        except Exception:
            pass
        try:
            self.persistent_memory.close()
        except Exception:
            pass
        if self.app_scanner:
            try:
                self.app_scanner.close()
            except Exception:
                pass