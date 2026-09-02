# app_scanner.py
import os
import re
import sqlite3
import json
import threading
from pathlib import Path
import subprocess
import sys
import platform
from datetime import datetime
import shutil
import logging
import webbrowser
from typing import Optional, Dict, List, Tuple, Any

logger = logging.getLogger(__name__)

try:
    import winreg
    HAS_WINREG = True
except ImportError:
    HAS_WINREG = False

# ===== Лимиты сканирования (не ходим по всему диску на каждый find) =====
try:
    import config as _cfg
except Exception:
    _cfg = None

def _cfg_get(name, default):
    return getattr(_cfg, name, default) if _cfg is not None else default

SCAN_COOLDOWN_SEC = int(_cfg_get("APP_SCAN_COOLDOWN_SEC", 3600) or 3600)
SCAN_DIR_MAX_DEPTH = int(_cfg_get("APP_SCAN_DIR_MAX_DEPTH", 2) or 2)
SCAN_SHORTCUT_MAX_DEPTH = int(_cfg_get("APP_SCAN_SHORTCUT_MAX_DEPTH", 5) or 5)
FIND_LIVE_MAX_DEPTH = int(_cfg_get("APP_FIND_LIVE_MAX_DEPTH", 1) or 1)
FIND_NEGATIVE_CACHE_SEC = float(_cfg_get("APP_FIND_NEGATIVE_CACHE_SEC", 120) or 120)
ENABLE_LIVE_DISK_FIND = bool(_cfg_get("APP_ENABLE_LIVE_DISK_FIND", False))  # по умолчанию ВЫКЛ

# Каталоги, которые не обходим при os.walk
SKIP_DIR_NAMES = {
    "node_modules", ".git", ".svn", "__pycache__", "cache", "caches",
    "temp", "tmp", "log", "logs", "crashdumps", "winsxs",
    "windowsapps", "packagedata", "packages",
    "steamapps",  # слишком тяжёлый; steam лучше через ярлыки
}

# Жёсткий список корней для полного scan (без %APPDATA% целиком)
DEFAULT_SCAN_ROOTS = [
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs"),
]

# Пользовательские корни (только они допустимы для live-find, если включён)
DEFAULT_USER_ROOTS = [
    r"E:\AI",
    r"D:\AI",
    r"E:\Games",
    r"D:\Games",
    r"C:\Games",
]


class AppScanner:
    """Сканирует установленные программы и предоставляет API для их поиска и запуска"""
    
    def __init__(self, db_path="apps.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            timeout=30.0,
        )
        # WAL — защита от database is locked
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA busy_timeout=5000;")
        self.cursor = self.conn.cursor()
        self._init_db()
        self.last_scan = self._load_last_scan()
        self._scanning = False
        self._neg_cache = {}  # query_lower -> monotonic deadline
        
    def _init_db(self):
        # Основная таблица приложений
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS apps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                display_name TEXT,
                path TEXT,
                icon_path TEXT,
                publisher TEXT,
                version TEXT,
                install_date TEXT,
                source TEXT,
                category TEXT,
                usage_count INTEGER DEFAULT 0,
                last_used TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(name, path)
            )
        """)
        
        # ===== НОВАЯ ТАБЛИЦА: АЛИАСЫ =====
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alias TEXT NOT NULL UNIQUE,
                target TEXT NOT NULL,
                type TEXT CHECK(type IN ('app', 'file', 'folder', 'url', 'command')),
                description TEXT,
                usage_count INTEGER DEFAULT 0,
                last_used TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_apps_name ON apps(name)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_apps_display_name ON apps(display_name)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_apps_path ON apps(path)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_aliases_alias ON aliases(alias)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_aliases_type ON aliases(type)")
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        self.conn.commit()

    def _load_last_scan(self):
        try:
            row = self.cursor.execute(
                "SELECT value FROM meta WHERE key=?", ("last_scan",)
            ).fetchone()
            return row[0] if row else None
        except Exception:
            return None

    def _save_last_scan(self, iso: str):
        try:
            self.cursor.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                ("last_scan", iso),
            )
            self.conn.commit()
        except Exception as e:
            logger.debug(f"meta last_scan: {e}")
    
    # ===== СУЩЕСТВУЮЩИЕ МЕТОДЫ =====
    
    def scan_system(self, force=False):
        """Сканирует установленные программы (редко, с cooldown, в фоне)."""
        if self._scanning:
            return "Сканирование уже выполняется"

        if not force and self.last_scan:
            try:
                time_since = (datetime.now() - datetime.fromisoformat(self.last_scan)).total_seconds()
                if time_since < SCAN_COOLDOWN_SEC:
                    return f"Сканирование выполнялось {int(time_since/60)} минут назад"
            except Exception:
                pass

        self._scanning = True

        def _scan():
            try:
                logger.info("Начинаем сканирование системы...")
                apps = []
                apps.extend(self._scan_common_apps())
                logger.info(f"  системных: {len(apps)}")
                if HAS_WINREG and platform.system() == "Windows":
                    apps.extend(self._scan_registry())
                    logger.info(f"  после реестра: {len(apps)}")
                apps.extend(self._scan_shortcuts())
                apps.extend(self._scan_path())
                apps.extend(self._scan_user_shortcuts())
                apps.extend(self._scan_common_dirs())
                saved = 0
                for app in apps:
                    if self._save_app(app):
                        saved += 1
                iso = datetime.now().isoformat()
                self.last_scan = iso
                self._save_last_scan(iso)
                logger.info(f"Сканирование завершено: найдено {len(apps)}, сохранено {saved}")
            except Exception as e:
                logger.error(f"Ошибка сканирования: {e}")
            finally:
                self._scanning = False

        threading.Thread(target=_scan, daemon=True).start()
        return "Сканирование запущено в фоне..."
    
    def _scan_common_apps(self):
        """Сканирует стандартные приложения Windows."""
        apps = []
        
        # Стандартные приложения Windows
        windows_apps = {
            "блокнот": "notepad.exe",
            "калькулятор": "calc.exe",
            "проводник": "explorer.exe",
            "командная строка": "cmd.exe",
            "powershell": "powershell.exe",
            "диспетчер задач": "taskmgr.exe",
            "настройки": "ms-settings:",
            "wordpad": "write.exe",
            "панель управления": "control.exe",
            "снимок экрана": "snippingtool.exe",
            "экранная лупа": "magnify.exe",
            "экранная клавиатура": "osk.exe",
        }
        
        for display_name, exe in windows_apps.items():
            # Проверяем, есть ли в PATH
            path = shutil.which(exe)
            if path:
                apps.append({
                    "name": display_name,
                    "display_name": display_name,
                    "path": path,
                    "source": "system",
                    "category": "system"
                })
            else:
                # Проверяем в системных папках
                system_dirs = [
                    os.environ.get("SystemRoot", "C:\\Windows"),
                    os.environ.get("SystemRoot", "C:\\Windows") + "\\System32",
                    os.environ.get("ProgramFiles", "C:\\Program Files"),
                    os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
                ]
                for dir_path in system_dirs:
                    full_path = os.path.join(dir_path, exe)
                    if os.path.exists(full_path):
                        apps.append({
                            "name": display_name,
                            "display_name": display_name,
                            "path": full_path,
                            "source": "system",
                            "category": "system"
                        })
                        break
        
        return apps
    
    def _scan_registry(self):
        apps = []
        
        registry_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        
        for hkey, path in registry_paths:
            try:
                key = winreg.OpenKey(hkey, path)
                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        subkey = winreg.OpenKey(key, subkey_name)
                        
                        try:
                            display_name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                        except:
                            display_name = subkey_name
                        
                        if display_name and len(display_name) > 1:
                            path_value = ""
                            try:
                                path_value = winreg.QueryValueEx(subkey, "DisplayIcon")[0]
                                if path_value and path_value.endswith(","):
                                    path_value = path_value.rstrip(",")
                            except:
                                pass
                            
                            if not path_value:
                                try:
                                    path_value = winreg.QueryValueEx(subkey, "InstallLocation")[0]
                                except:
                                    pass
                            
                            # Если путь пустой, пытаемся найти .exe по имени
                            if not path_value:
                                exe_candidates = [
                                    f"C:\\Program Files\\{display_name}\\{display_name}.exe",
                                    f"C:\\Program Files (x86)\\{display_name}\\{display_name}.exe",
                                    f"C:\\Program Files\\{display_name}.exe",
                                ]
                                for candidate in exe_candidates:
                                    if os.path.exists(candidate):
                                        path_value = candidate
                                        break
                            
                            publisher = ""
                            try:
                                publisher = winreg.QueryValueEx(subkey, "Publisher")[0]
                            except:
                                pass
                            
                            version = ""
                            try:
                                version = winreg.QueryValueEx(subkey, "DisplayVersion")[0]
                            except:
                                pass
                            
                            category = self._guess_category(display_name)
                            
                            apps.append({
                                "name": self._normalize_name(display_name),
                                "display_name": display_name,
                                "path": path_value,
                                "publisher": publisher or "",
                                "version": version or "",
                                "source": "registry",
                                "category": category
                            })
                        
                        i += 1
                    except WindowsError:
                        break
                winreg.CloseKey(key)
            except Exception:
                pass
        
        return apps
    
    def _scan_common_dirs(self):
        """Сканирует ограниченный набор корней (без %APPDATA% целиком)."""
        apps = []
        roots = list(DEFAULT_SCAN_ROOTS)
        extra = _cfg_get("APP_SCAN_EXTRA_ROOTS", None)
        if isinstance(extra, (list, tuple)):
            roots.extend(extra)
        else:
            roots.extend(DEFAULT_USER_ROOTS)

        for dir_path in roots:
            if not dir_path or not os.path.isdir(dir_path):
                continue
            try:
                for root, dirs, files in os.walk(dir_path):
                    depth = root.replace(dir_path, "").count(os.sep)
                    if depth > SCAN_DIR_MAX_DEPTH:
                        dirs[:] = []
                        continue
                    # prune тяжёлые/бесполезные подпапки
                    dirs[:] = [
                        d for d in dirs
                        if d.lower() not in SKIP_DIR_NAMES and not d.startswith(".")
                    ]
                    for file in files:
                        fl = file.lower()
                        if not fl.endswith(".exe"):
                            continue
                        if "uninstall" in fl or fl.startswith("update"):
                            continue
                        name = os.path.splitext(file)[0]
                        if name.lower() in {
                            "conhost", "csrss", "winlogon", "services",
                            "lsass", "svchost", "dllhost", "rundll32",
                        }:
                            continue
                        full_path = os.path.join(root, file)
                        apps.append({
                            "name": self._normalize_name(name),
                            "display_name": name,
                            "path": full_path,
                            "source": "scan",
                            "category": self._guess_category(name),
                        })
            except Exception as e:
                logger.debug(f"scan dir {dir_path}: {e}")
        return apps
    
    def _scan_shortcuts(self):
        apps = []
        
        shortcut_dirs = [
            os.path.join(os.environ.get("ProgramData", "C:\\ProgramData"), "Microsoft\\Windows\\Start Menu\\Programs"),
            os.path.join(os.environ.get("APPDATA", ""), "Microsoft\\Windows\\Start Menu\\Programs"),
            os.path.join(os.environ.get("ALLUSERSPROFILE", "C:\\ProgramData"), "Microsoft\\Windows\\Start Menu\\Programs"),
        ]
        
        for dir_path in shortcut_dirs:
            if not os.path.exists(dir_path):
                continue
            
            for root, dirs, files in os.walk(dir_path):
                depth = root.replace(dir_path, "").count(os.sep)
                if depth > SCAN_SHORTCUT_MAX_DEPTH:
                    dirs[:] = []
                    continue
                dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIR_NAMES]
                for file in files:
                    if file.lower().endswith((".lnk", ".url")):
                        full_path = os.path.join(root, file)
                        name = os.path.splitext(file)[0]
                        apps.append({
                            "name": self._normalize_name(name),
                            "display_name": name,
                            "path": full_path,
                            "source": "shortcut",
                            "category": self._guess_category(name),
                        })
        
        return apps
    
    def _scan_user_shortcuts(self):
        apps = []
        
        desktop_paths = [
            os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"),
            os.path.join(os.environ.get("USERPROFILE", ""), "OneDrive", "Desktop"),
            os.path.join(os.environ.get("PUBLIC", "C:\\Users\\Public"), "Desktop"),
        ]
        
        for desktop in desktop_paths:
            if not os.path.exists(desktop):
                continue
            
            for file in os.listdir(desktop):
                if file.lower().endswith((".lnk", ".url", ".exe")):
                    full_path = os.path.join(desktop, file)
                    name = os.path.splitext(file)[0]
                    
                    app = {
                        "name": self._normalize_name(name),
                        "display_name": name,
                        "path": full_path,
                        "source": "desktop",
                        "category": self._guess_category(name)
                    }
                    apps.append(app)
        
        return apps
    
    def _scan_path(self):
        apps = []
        path_env = os.environ.get("PATH", "")
        
        for dir_path in path_env.split(os.pathsep):
            if not os.path.exists(dir_path):
                continue
            
            try:
                for file in os.listdir(dir_path):
                    if file.lower().endswith(".exe"):
                        full_path = os.path.join(dir_path, file)
                        name = os.path.splitext(file)[0]
                        
                        if name.lower() in ["conhost", "csrss", "winlogon", "services", "lsass", "svchost"]:
                            continue
                        
                        app = {
                            "name": self._normalize_name(name),
                            "display_name": name,
                            "path": full_path,
                            "source": "path",
                            "category": self._guess_category(name)
                        }
                        apps.append(app)
            except Exception:
                pass
        
        return apps
    
    def _guess_category(self, name):
        name_lower = name.lower()
        
        categories = {
            "browser": ["chrome", "firefox", "edge", "opera", "brave", "yandex", "safari", "vivaldi", "browser"],
            "office": ["word", "excel", "powerpoint", "outlook", "office", "libreoffice", "openoffice"],
            "code": ["visual studio", "vscode", "code", "pycharm", "intellij", "eclipse", "sublime", "atom", "github", "git"],
            "media": ["spotify", "vlc", "media player", "itunes", "winamp", "audacity", "photoshop", "gimp", "krita"],
            "game": ["steam", "game", "play", "minecraft", "league of legends", "dota", "csgo", "battle", "blizzard"],
            "social": ["discord", "telegram", "whatsapp", "skype", "zoom", "teams", "slack"],
            "system": ["task manager", "control panel", "cmd", "powershell", "terminal", "settings", "notepad", "calc", "explorer"],
            "ai": ["python", "conda", "jupyter", "tensorflow", "pytorch", "llm", "stable diffusion", "comfy"],
            "utility": ["7-zip", "winrar", "total commander", "everything", "process", "hwinfo", "cpu-z", "gpuz"]
        }
        
        for category, keywords in categories.items():
            for keyword in keywords:
                if keyword in name_lower:
                    return category
        
        return "other"
    
    def _normalize_name(self, name):
        if not name:
            return ""
        
        name = re.sub(r'\s*\([^)]*\)\s*', ' ', name)
        name = re.sub(r'\s+', ' ', name).strip()
        name = re.sub(r'[^\w\s\-\.]', '', name)
        
        return name
    
    def _save_app(self, app_data):
        try:
            now = datetime.now().isoformat()
            
            with self.lock:
                self.cursor.execute("""
                    INSERT OR REPLACE INTO apps 
                    (name, display_name, path, publisher, version, source, category, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    app_data.get("name", ""),
                    app_data.get("display_name", ""),
                    app_data.get("path", ""),
                    app_data.get("publisher", ""),
                    app_data.get("version", ""),
                    app_data.get("source", "manual"),
                    app_data.get("category", "other"),
                    now,
                    now
                ))
                self.conn.commit()
                return True
        except Exception as e:
            print(f"⚠️ Ошибка сохранения {app_data.get('name')}: {e}")
            return False
    
    # ===== НОВЫЕ МЕТОДЫ: АЛИАСЫ =====
    
    def add_alias(self, alias: str, target: str, type_: str = "app", description: str = "") -> bool:
        """
        Добавляет алиас для быстрого запуска.
        
        Args:
            alias: Имя для вызова (например, "конфи")
            target: Путь или команда (например, "E:\\AI\\Comfy Desktop\\Comfy Desktop.exe")
            type_: Тип ('app', 'file', 'folder', 'url', 'command')
            description: Описание (необязательно)
        """
        alias = alias.lower().strip()
        target = target.strip()
        
        if not alias or not target:
            logger.error("Alias и target не могут быть пустыми")
            return False
        
        # Если тип не указан, определяем автоматически
        if not type_ or type_ not in ('app', 'file', 'folder', 'url', 'command'):
            type_ = self._guess_alias_type(target)
        
        now = datetime.now().isoformat()
        
        try:
            with self.lock:
                self.cursor.execute("""
                    INSERT OR REPLACE INTO aliases 
                    (alias, target, type, description, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (alias, target, type_, description or "", now, now))
                self.conn.commit()
                logger.info(f"✅ Добавлен алиас: {alias} → {target} ({type_})")
                return True
        except Exception as e:
            logger.error(f"Ошибка добавления алиаса {alias}: {e}")
            return False
    
    def _guess_alias_type(self, target: str) -> str:
        """Автоматически определяет тип по цели."""
        target_lower = target.lower()
        
        # URL
        if target_lower.startswith(('http://', 'https://', 'www.')):
            return 'url'
        
        # Команда (с пробелами или без .exe)
        if ' ' in target and not os.path.exists(target):
            return 'command'
        
        # Проверяем существование
        if os.path.exists(target):
            if os.path.isdir(target):
                return 'folder'
            elif target_lower.endswith('.exe') or target_lower.endswith('.lnk'):
                return 'app'
            else:
                return 'file'
        
        # Если не существует, но похоже на путь с .exe
        if target_lower.endswith('.exe'):
            return 'app'
        
        return 'command'
    
    def resolve_alias(self, alias: str) -> Optional[Dict[str, Any]]:
        """
        Ищет алиас по имени.
        
        Returns:
            {"target": str, "type": str, "description": str} или None
        """
        alias = alias.lower().strip()
        if not alias:
            return None
        
        try:
            with self.lock:
                self.cursor.execute(
                    "SELECT target, type, description FROM aliases WHERE alias = ?",
                    (alias,)
                )
                row = self.cursor.fetchone()
                if row:
                    # Обновляем статистику использования
                    self.cursor.execute("""
                        UPDATE aliases 
                        SET usage_count = usage_count + 1, last_used = ?
                        WHERE alias = ?
                    """, (datetime.now().isoformat(), alias))
                    self.conn.commit()
                    
                    return {
                        "target": row[0],
                        "type": row[1],
                        "description": row[2] or ""
                    }
        except Exception as e:
            logger.error(f"Ошибка поиска алиаса {alias}: {e}")
        
        return None
    
    def has_alias(self, alias: str) -> bool:
        """Проверяет, существует ли алиас."""
        alias = alias.lower().strip()
        if not alias:
            return False
        try:
            with self.lock:
                self.cursor.execute(
                    "SELECT 1 FROM aliases WHERE alias = ?",
                    (alias,)
                )
                return self.cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Ошибка проверки алиаса {alias}: {e}")
            return False
    
    def launch_by_alias(self, alias: str) -> Tuple[bool, str]:
        """
        Запускает по алиасу.
        
        Returns:
            (success: bool, message: str)
        """
        resolved = self.resolve_alias(alias)
        if not resolved:
            return False, f"Алиас '{alias}' не найден"
        
        target = resolved["target"]
        type_ = resolved["type"]
        
        try:
            if type_ == "app":
                return self.launch_app(target)
            elif type_ == "folder":
                os.startfile(target)
                return True, f"📂 Открыта папка: {target}"
            elif type_ == "file":
                os.startfile(target)
                return True, f"📄 Открыт файл: {target}"
            elif type_ == "url":
                webbrowser.open(target)
                return True, f"🌐 Открыт URL: {target}"
            elif type_ == "command":
                # SAFE: без shell=True — argv через shlex, иначе инъекции
                import shlex
                try:
                    import config as _cfg
                    safe = bool(getattr(_cfg, "SAFE_MODE", True))
                except Exception:
                    safe = True
                if safe:
                    return False, "type=command запрещён в SAFE_MODE (shell). Смени тип на app/file."
                try:
                    argv = shlex.split(target, posix=False)
                except Exception:
                    argv = [target]
                if not argv:
                    return False, "пустая команда"
                subprocess.Popen(argv, shell=False)
                return True, f"⚡ Выполнено: {target}"
            else:
                return False, f"Неизвестный тип: {type_}"
        except Exception as e:
            return False, f"Ошибка запуска: {e}"
    
    def delete_alias(self, alias: str) -> bool:
        """Удаляет алиас."""
        alias = alias.lower().strip()
        try:
            with self.lock:
                self.cursor.execute("DELETE FROM aliases WHERE alias = ?", (alias,))
                self.conn.commit()
                return self.cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Ошибка удаления алиаса {alias}: {e}")
            return False
    
    def list_aliases(self, type_: Optional[str] = None) -> List[Dict[str, Any]]:
        """Возвращает список всех алиасов."""
        try:
            with self.lock:
                if type_:
                    self.cursor.execute(
                        "SELECT alias, target, type, description, usage_count, last_used FROM aliases WHERE type = ? ORDER BY alias",
                        (type_,)
                    )
                else:
                    self.cursor.execute(
                        "SELECT alias, target, type, description, usage_count, last_used FROM aliases ORDER BY alias"
                    )
                rows = self.cursor.fetchall()
                
                return [
                    {
                        "alias": row[0],
                        "target": row[1],
                        "type": row[2],
                        "description": row[3] or "",
                        "usage_count": row[4] or 0,
                        "last_used": row[5]
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Ошибка получения списка алиасов: {e}")
            return []
    
    def get_alias_stats(self) -> Dict[str, Any]:
        """Возвращает статистику по алиасам."""
        try:
            with self.lock:
                self.cursor.execute("SELECT COUNT(*) FROM aliases")
                total = self.cursor.fetchone()[0]
                
                self.cursor.execute(
                    "SELECT type, COUNT(*) FROM aliases GROUP BY type"
                )
                by_type = dict(self.cursor.fetchall())
                
                self.cursor.execute(
                    "SELECT SUM(usage_count) FROM aliases"
                )
                total_usage = self.cursor.fetchone()[0] or 0
                
                return {
                    "total": total,
                    "by_type": by_type,
                    "total_usage": total_usage
                }
        except Exception as e:
            logger.error(f"Ошибка получения статистики алиасов: {e}")
            return {"total": 0, "by_type": {}, "total_usage": 0}
    
    # ===== СУЩЕСТВУЮЩИЕ МЕТОДЫ (продолжение) =====
    
    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Поиск по запросу (сначала алиасы, потом приложения)."""
        if not query or not query.strip():
            return []
        
        query_lower = query.lower().strip()
        # Убираем лишние слова из запроса
        clean_words = ["запусти", "открой", "запустить", "открыть", "запуск", "open", "run", "launch"]
        for word in clean_words:
            query_lower = query_lower.replace(word, "").strip()
        
        with self.lock:
            results = []
            
            # Сначала ищем в алиасах
            self.cursor.execute("""
                SELECT alias, target, type, description, usage_count, last_used
                FROM aliases
                WHERE alias LIKE ? OR target LIKE ?
                ORDER BY 
                    CASE 
                        WHEN alias = ? THEN 0
                        WHEN alias LIKE ? THEN 1
                        ELSE 2
                    END,
                    usage_count DESC
                LIMIT ?
            """, (
                f"%{query_lower}%",
                f"%{query_lower}%",
                query_lower,
                f"{query_lower}%",
                limit
            ))
            alias_rows = self.cursor.fetchall()
            
            for row in alias_rows:
                results.append({
                    "type": "alias",
                    "alias": row[0],
                    "target": row[1],
                    "target_type": row[2],
                    "description": row[3] or "",
                    "usage_count": row[4] or 0,
                    "last_used": row[5]
                })
            
            # Если алиасов достаточно, не ищем в приложениях
            if len(results) >= limit:
                return results[:limit]
            
            # Потом в приложениях
            remaining = limit - len(results)
            self.cursor.execute("""
                SELECT id, name, display_name, path, publisher, version, category, usage_count, last_used
                FROM apps
                WHERE LOWER(name) LIKE ? OR LOWER(display_name) LIKE ? OR LOWER(path) LIKE ?
                ORDER BY 
                    CASE 
                        WHEN LOWER(name) = ? THEN 0
                        WHEN LOWER(display_name) = ? THEN 1
                        WHEN LOWER(name) LIKE ? THEN 2
                        WHEN LOWER(display_name) LIKE ? THEN 3
                        ELSE 4
                    END,
                    usage_count DESC
                LIMIT ?
            """, (
                f"%{query_lower}%",
                f"%{query_lower}%",
                f"%{query_lower}%",
                query_lower,
                query_lower,
                f"{query_lower}%",
                f"{query_lower}%",
                remaining
            ))
            app_rows = self.cursor.fetchall()
            
            for row in app_rows:
                results.append({
                    "type": "app",
                    "id": row[0],
                    "name": row[1],
                    "display_name": row[2],
                    "path": row[3],
                    "publisher": row[4] or "",
                    "version": row[5] or "",
                    "category": row[6] or "other",
                    "usage_count": row[7] or 0,
                    "last_used": row[8]
                })
            
            return results
    
    def find_best_match(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Быстрый поиск: alias → БД → системные имена → which.
        Полный обход Program Files на КАЖДЫЙ find ОТКЛЮЧЁН
        (см. APP_ENABLE_LIVE_DISK_FIND / APP_SCAN_EXTRA_ROOTS).
        """
        if not query or not query.strip():
            return None

        query_lower = query.lower().strip()
        for word in ("запусти", "открой", "запустить", "открыть", "запуск", "open", "run", "launch"):
            query_lower = query_lower.replace(word, "").strip()
        if not query_lower:
            return None

        # negative cache — не долбим диск по одним и тем же промахам
        import time as _time
        now = _time.monotonic()
        exp = self._neg_cache.get(query_lower)
        if exp and exp > now:
            return None
        # чистим просроченное
        if len(self._neg_cache) > 200:
            self._neg_cache = {k: v for k, v in self._neg_cache.items() if v > now}

        # 1) алиасы
        alias = self.resolve_alias(query_lower)
        if alias:
            return {
                "type": "alias",
                "alias": query_lower,
                "target": alias["target"],
                "target_type": alias["type"],
                "description": alias["description"],
            }

        # 2) БД (основной путь)
        results = self.search(query_lower, limit=10)
        if results:
            for app in results:
                if app.get("type") == "alias":
                    return app
                path = app.get("path") or ""
                path_lower = path.lower()
                if path and os.path.exists(path):
                    if path_lower.endswith(".exe") and "system32" not in path_lower:
                        return app
                    return app
            return results[0]

        # 3) известные системные
        system_apps = {
            "блокнот": "notepad.exe",
            "notepad": "notepad.exe",
            "калькулятор": "calc.exe",
            "calc": "calc.exe",
            "проводник": "explorer.exe",
            "explorer": "explorer.exe",
            "командная строка": "cmd.exe",
            "cmd": "cmd.exe",
            "powershell": "powershell.exe",
            "paint": "mspaint.exe",
            "паинт": "mspaint.exe",
            "wordpad": "wordpad.exe",
        }
        if query_lower in system_apps:
            path = shutil.which(system_apps[query_lower])
            if path:
                return {
                    "type": "app",
                    "name": query_lower,
                    "display_name": query_lower,
                    "path": path,
                    "category": "system",
                    "usage_count": 0,
                }

        # 4) which по имени.exe
        for cand in (query_lower, query_lower + ".exe", query_lower.replace(" ", "") + ".exe"):
            path = shutil.which(cand)
            if path and os.path.isfile(path):
                return {
                    "type": "app",
                    "name": self._normalize_name(os.path.splitext(os.path.basename(path))[0]),
                    "display_name": os.path.splitext(os.path.basename(path))[0],
                    "path": path,
                    "category": "path",
                    "usage_count": 0,
                }

        # 5) опциональный shallow live-find ТОЛЬКО по user-roots (не Program Files)
        if ENABLE_LIVE_DISK_FIND:
            hit = self._live_find_in_user_roots(query_lower)
            if hit:
                return hit

        self._neg_cache[query_lower] = now + FIND_NEGATIVE_CACHE_SEC
        return None

    def _live_find_in_user_roots(self, query_lower: str) -> Optional[Dict[str, Any]]:
        """Узкий live-поиск только в APP_SCAN_EXTRA_ROOTS / DEFAULT_USER_ROOTS."""
        roots = list(DEFAULT_USER_ROOTS)
        extra = _cfg_get("APP_SCAN_EXTRA_ROOTS", None)
        if isinstance(extra, (list, tuple)):
            roots = list(extra) + roots
        for dir_path in roots:
            if not dir_path or not os.path.isdir(dir_path):
                continue
            # не ходим в Program Files / Windows даже если кто-то добавил
            low = dir_path.lower().replace("/", "\\")
            if "program files" in low or "\\windows" in low or low.endswith("\\windows"):
                continue
            try:
                for root, dirs, files in os.walk(dir_path):
                    depth = root.replace(dir_path, "").count(os.sep)
                    if depth > FIND_LIVE_MAX_DEPTH:
                        dirs[:] = []
                        continue
                    dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIR_NAMES]
                    for file in files:
                        if not file.lower().endswith(".exe"):
                            continue
                        fl = file.lower()
                        if query_lower in fl or fl.replace(".exe", "") in query_lower:
                            full_path = os.path.join(root, file)
                            return {
                                "type": "app",
                                "name": self._normalize_name(os.path.splitext(file)[0]),
                                "display_name": os.path.splitext(file)[0],
                                "path": full_path,
                                "category": "live",
                                "usage_count": 0,
                            }
            except Exception as e:
                logger.debug(f"live find {dir_path}: {e}")
        return None
    
    def launch_app(self, query: str, add_to_history: bool = True) -> Tuple[bool, str]:
        """
        Запускает приложение по имени или пути.
        Сначала проверяет алиасы.
        """
        # Проверяем, может это прямой путь к файлу
        if os.path.exists(query):
            try:
                subprocess.Popen([query], shell=False)
                return True, f"Запущено: {os.path.basename(query)}"
            except Exception as e:
                return False, f"Ошибка запуска: {e}"
        
        # Проверяем, есть ли путь в памяти
        if query.lower().endswith(".exe"):
            clean_path = query.strip()
            if os.path.exists(clean_path):
                try:
                    subprocess.Popen([clean_path], shell=False)
                    return True, f"Запущено: {os.path.basename(clean_path)}"
                except Exception as e:
                    return False, f"Ошибка запуска: {e}"
        
        # Проверяем системные приложения
        system_apps = {
            "блокнот": "notepad.exe",
            "калькулятор": "calc.exe",
            "проводник": "explorer.exe",
            "командная строка": "cmd.exe",
            "powershell": "powershell.exe",
        }
        
        query_lower = query.lower().strip()
        if query_lower in system_apps:
            exe = system_apps[query_lower]
            path = shutil.which(exe)
            if path:
                try:
                    subprocess.Popen([path], shell=False)
                    return True, f"Запущено: {query}"
                except Exception as e:
                    return False, f"Ошибка запуска: {e}"
        
        # Ищем лучшее совпадение
        match = self.find_best_match(query)
        
        if not match:
            return False, f"Программа '{query}' не найдена"
        
        # Если это алиас
        if match.get("type") == "alias":
            return self.launch_by_alias(match["alias"])
        
        path = match.get("path")
        if not path:
            return False, f"Путь к программе не найден"
        
        if not os.path.exists(path):
            return False, f"Файл '{path}' не существует"
        
        try:
            if path.lower().endswith(".lnk"):
                os.startfile(path)
            else:
                subprocess.Popen([path], shell=False)
            
            if add_to_history and match.get("id"):
                with self.lock:
                    self.cursor.execute("""
                        UPDATE apps 
                        SET usage_count = usage_count + 1, last_used = ?
                        WHERE id = ?
                    """, (datetime.now().isoformat(), match["id"]))
                    self.conn.commit()
            
            return True, f"Запущено: {match.get('display_name') or match.get('name') or os.path.basename(path)}"
            
        except Exception as e:
            return False, f"Ошибка запуска: {e}"
    
    # ===== ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ ДЛЯ СТАТИСТИКИ =====
    
    def get_all_categories(self) -> Dict[str, int]:
        """Возвращает количество приложений по категориям."""
        with self.lock:
            self.cursor.execute("""
                SELECT category, COUNT(*) as count
                FROM apps
                GROUP BY category
                ORDER BY count DESC
            """)
            return dict(self.cursor.fetchall())
    
    def get_by_category(self, category: str, limit: int = 50) -> List[tuple]:
        """Возвращает приложения по категории."""
        with self.lock:
            self.cursor.execute("""
                SELECT id, name, display_name, path, usage_count
                FROM apps
                WHERE category = ?
                ORDER BY usage_count DESC, name ASC
                LIMIT ?
            """, (category, limit))
            return self.cursor.fetchall()
    
    def get_most_used(self, limit: int = 10) -> List[tuple]:
        """Возвращает самые используемые приложения."""
        with self.lock:
            self.cursor.execute("""
                SELECT id, name, display_name, path, usage_count
                FROM apps
                WHERE usage_count > 0
                ORDER BY usage_count DESC
                LIMIT ?
            """, (limit,))
            return self.cursor.fetchall()
    
    def get_installed_apps(self, limit: int = 20) -> List[tuple]:
        """Возвращает установленные приложения (из реестра)."""
        with self.lock:
            self.cursor.execute("""
                SELECT id, name, display_name, path, category, publisher, version
                FROM apps
                WHERE source = 'registry' OR source = 'manual'
                ORDER BY display_name ASC
                LIMIT ?
            """, (limit,))
            return self.cursor.fetchall()
    
    def add_manual_app(self, name: str, path: str, category: str = "other") -> bool:
        """Добавляет приложение вручную."""
        app = {
            "name": self._normalize_name(name),
            "display_name": name,
            "path": path,
            "source": "manual",
            "category": category
        }
        return self._save_app(app)
    
    def get_stats(self) -> Dict[str, Any]:
        """Возвращает полную статистику."""
        with self.lock:
            # Количество приложений
            self.cursor.execute("SELECT COUNT(*) FROM apps")
            total_apps = self.cursor.fetchone()[0]
            
            # Количество алиасов
            self.cursor.execute("SELECT COUNT(*) FROM aliases")
            total_aliases = self.cursor.fetchone()[0]
            
            # Категории
            self.cursor.execute("""
                SELECT category, COUNT(*) FROM apps GROUP BY category
            """)
            categories = dict(self.cursor.fetchall())
            
            # Типы алиасов
            self.cursor.execute("""
                SELECT type, COUNT(*) FROM aliases GROUP BY type
            """)
            alias_types = dict(self.cursor.fetchall())
            
            return {
                "total_apps": total_apps,
                "total_aliases": total_aliases,
                "categories": categories,
                "alias_types": alias_types,
                "db_path": self.db_path
            }
    
    def close(self):
        """Закрывает соединение с БД."""
        try:
            with self.lock:
                if self.conn:
                    self.conn.close()
                    self.conn = None
                    self.cursor = None
        except Exception as e:
            logger.warning(f"AppScanner.close: {e}")