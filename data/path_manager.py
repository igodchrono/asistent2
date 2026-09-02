# path_manager.py
"""
Менеджер путей для Лисички.
Автоматически определяет структуру проекта:
D:\asistent\
├── python\          # Портативный Python
└── data\            # Основные файлы проекта
"""

import os
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

# Пытаемся импортировать dotenv, если нет - создаём заглушку
try:
    from dotenv import load_dotenv
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False
    def load_dotenv(*args, **kwargs):
        return False


class PathManager:
    """Централизованное управление всеми путями в проекте."""
    
    _instance = None
    _initialized = False
    _paths: Dict[str, str] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        # ОПРЕДЕЛЯЕМ СТРУКТУРУ ПРОЕКТА
        self._detect_project_structure()
        
        # Загружаем .env
        self._load_env()
        
        # Настраиваем пути
        self._setup_paths()
        
        # Создаём директории
        self._create_directories()
        
        # Выводим информацию
        self._print_info()
    
    def _detect_project_structure(self):
        """
        Автоматически определяет структуру проекта.
        Ищет:
        1. Папку data рядом с исполняемым файлом
        2. Папку python рядом с data
        """
        # Определяем базовую директорию
        if getattr(sys, 'frozen', False):
            # Если запущено как .exe
            base_dir = Path(sys.executable).parent
        else:
            # Если запущено как скрипт
            base_dir = Path(__file__).resolve().parent
        
        # Проверяем, не находимся ли мы уже в data
        if base_dir.name == "data":
            self._data_dir = base_dir
            self._base_dir = base_dir.parent
        else:
            # Ищем data рядом
            possible_data = base_dir / "data"
            if possible_data.exists() and possible_data.is_dir():
                self._data_dir = possible_data
                self._base_dir = base_dir
            else:
                # Ищем data в родительской директории
                possible_data = base_dir.parent / "data"
                if possible_data.exists() and possible_data.is_dir():
                    self._data_dir = possible_data
                    self._base_dir = base_dir.parent
                else:
                    # Используем текущую директорию как data
                    self._data_dir = base_dir
                    self._base_dir = base_dir.parent
        
        # Определяем python директорию
        possible_python = self._base_dir / "python"
        if possible_python.exists() and possible_python.is_dir():
            self._python_dir = possible_python
        else:
            self._python_dir = None
        
        # Определяем путь к python.exe
        if self._python_dir:
            self._python_exe = self._python_dir / "python.exe"
            if not self._python_exe.exists():
                self._python_exe = self._python_dir / "bin" / "python.exe"
                if not self._python_exe.exists():
                    self._python_exe = None
        else:
            self._python_exe = None
    
    def _load_env(self):
        """Загружает переменные окружения из .env."""
        # Ищем .env в data директории
        env_paths = [
            self._data_dir / ".env",
            self._base_dir / ".env",
            Path.home() / ".asistent" / ".env",
            Path(os.getenv("ASISTENT_ENV", "")) if os.getenv("ASISTENT_ENV") else None,
        ]
        
        for env_path in env_paths:
            if env_path and env_path.exists():
                if HAS_DOTENV:
                    load_dotenv(env_path)
                print(f"✅ Загружен .env: {env_path}")
                return
        
        # Если .env не найден, создаём
        default_env = self._data_dir / ".env"
        if not default_env.exists():
            self._create_default_env(default_env)
        
        if HAS_DOTENV:
            load_dotenv(default_env)
        print(f"✅ Создан и загружен .env: {default_env}")
    
    def _create_default_env(self, path: Path):
        """Создаёт .env файл с настройками по умолчанию."""
        default_content = f'''# .env - Настройки Лисички
# ============================

# Структура проекта (определена автоматически)
PROJECT_ROOT={self._data_dir}
PYTHON_PATH={self._python_exe if self._python_exe else ""}

# Пути внутри data
SAVE_DIR={self._data_dir}/sav
LOGS_DIR={self._data_dir}/logs
FRAMES_DIR={self._data_dir}/frames
TEMP_DIR={self._data_dir}/temp
NOTES_FILE={self._data_dir}/notes.md

# Базы данных
MEMORY_DB={self._data_dir}/assistant_memory.db
PERSISTENT_MEMORY_DB={self._data_dir}/persistent_memory.db
REMINDER_DB={self._data_dir}/reminders.db
DOCUMENT_RAG_DB={self._data_dir}/document_rag.db
ADVANCED_RAG_DB={self._data_dir}/advanced_rag.db
APP_SCANNER_DB={self._data_dir}/apps.db

# Модели
VOSK_MODEL_PATH={self._data_dir}/vosk-model-small-ru-0.22

# Браузер
DEFAULT_BROWSER=chrome
BROWSER_PATH=C:/Program Files/Google/Chrome/Application/chrome.exe

# API (LM Studio)
API_URL=http://26.26.15.18:1234/v1
API_KEY=not-needed
MODEL_NAME=qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive

# Голос
VOICE_NAME=ru-RU-SvetlanaNeural
VOICE_LANGUAGE=ru-RU

# Безопасность
SAFE_MODE=true
ALLOWED_DIRS={self._data_dir},~/Downloads,~/Documents
'''
        try:
            path.write_text(default_content, encoding="utf-8")
            print(f"📄 Создан .env: {path}")
        except Exception as e:
            print(f"⚠️ Не удалось создать .env: {e}")
    
    def _expand(self, path: str) -> str:
        """Разворачивает ~ и переменные окружения в пути."""
        if not path:
            return ""
        
        # Разворачиваем ~
        path = os.path.expanduser(path)
        
        # Разворачиваем переменные окружения
        path = os.path.expandvars(path)
        
        # Нормализуем путь
        path = os.path.normpath(path)
        
        return path
    
    def _setup_paths(self):
        """Инициализирует все пути."""
        
        # Базовые пути
        data_dir = str(self._data_dir)
        
        # --- ОСНОВНЫЕ ПУТИ ---
        self._paths = {
            # Структура проекта
            "BASE_DIR": str(self._base_dir),
            "DATA_DIR": data_dir,
            "PYTHON_DIR": str(self._python_dir) if self._python_dir else "",
            "PYTHON_EXE": str(self._python_exe) if self._python_exe else "",
            
            # Поддиректории внутри data
            "SAVE_DIR": self._expand(self._get_env("SAVE_DIR", os.path.join(data_dir, "sav"))),
            "LOGS_DIR": self._expand(self._get_env("LOGS_DIR", os.path.join(data_dir, "logs"))),
            "FRAMES_DIR": self._expand(self._get_env("FRAMES_DIR", os.path.join(data_dir, "frames"))),
            "TEMP_DIR": self._expand(self._get_env("TEMP_DIR", os.path.join(data_dir, "temp"))),
            
            # Файлы
            "NOTES_FILE": self._expand(self._get_env("NOTES_FILE", os.path.join(data_dir, "notes.md"))),
            
            # Базы данных
            "MEMORY_DB": self._expand(self._get_env("MEMORY_DB", os.path.join(data_dir, "assistant_memory.db"))),
            "PERSISTENT_MEMORY_DB": self._expand(self._get_env("PERSISTENT_MEMORY_DB", os.path.join(data_dir, "persistent_memory.db"))),
            "REMINDER_DB": self._expand(self._get_env("REMINDER_DB", os.path.join(data_dir, "reminders.db"))),
            "DOCUMENT_RAG_DB": self._expand(self._get_env("DOCUMENT_RAG_DB", os.path.join(data_dir, "document_rag.db"))),
            "ADVANCED_RAG_DB": self._expand(self._get_env("ADVANCED_RAG_DB", os.path.join(data_dir, "advanced_rag.db"))),
            "APP_SCANNER_DB": self._expand(self._get_env("APP_SCANNER_DB", os.path.join(data_dir, "apps.db"))),
            
            # Модели
            "VOSK_MODEL_PATH": self._expand(self._get_env("VOSK_MODEL_PATH", os.path.join(data_dir, "vosk-model-small-ru-0.22"))),
            
            # Браузер
            "BROWSER_PATH": self._expand(self._get_env("BROWSER_PATH", "C:/Program Files/Google/Chrome/Application/chrome.exe")),
            "DEFAULT_BROWSER": self._get_env("DEFAULT_BROWSER", "chrome"),
            
            # API
            "API_URL": self._get_env("API_URL", "http://26.26.15.18:1234/v1"),
            "API_KEY": self._get_env("API_KEY", "not-needed"),
            "MODEL_NAME": self._get_env("MODEL_NAME", "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive"),
            
            # Голос
            "VOICE_NAME": self._get_env("VOICE_NAME", "ru-RU-SvetlanaNeural"),
            "VOICE_LANGUAGE": self._get_env("VOICE_LANGUAGE", "ru-RU"),
            
            # Безопасность
            "SAFE_MODE": self._get_env("SAFE_MODE", "true").lower() == "true",
            "ALLOWED_DIRS": self._get_env("ALLOWED_DIRS", f"{data_dir},~/Downloads,~/Documents"),
        }
        
        # Разворачиваем ALLOWED_DIRS в список
        allowed_dirs_str = self._paths.get("ALLOWED_DIRS", "")
        if isinstance(allowed_dirs_str, str):
            self._paths["ALLOWED_DIRS_LIST"] = [
                self._expand(d.strip()) for d in allowed_dirs_str.split(",") if d.strip()
            ]
        else:
            self._paths["ALLOWED_DIRS_LIST"] = []
    
    def _get_env(self, key: str, default: str = "") -> str:
        """Получает значение из переменных окружения."""
        value = os.getenv(key, default)
        return value if value is not None else default
    
    def _create_directories(self):
        """Создаёт все необходимые директории."""
        dirs_to_create = [
            self._paths.get("SAVE_DIR"),
            self._paths.get("LOGS_DIR"),
            self._paths.get("FRAMES_DIR"),
            self._paths.get("TEMP_DIR"),
            self._paths.get("DATA_DIR"),
        ]
        
        for dir_path in dirs_to_create:
            if dir_path:
                try:
                    Path(dir_path).mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    print(f"⚠️ Не удалось создать директорию {dir_path}: {e}")
    
    def _print_info(self):
        """Выводит информацию о структуре проекта."""
        print("\n" + "=" * 60)
        print("📂 СТРУКТУРА ПРОЕКТА (определена автоматически)")
        print("=" * 60)
        print(f"   Базовый путь:   {self._base_dir}")
        print(f"   Data:           {self._data_dir}")
        print(f"   Python:         {self._python_dir if self._python_dir else '❌ не найден'}")
        print(f"   Python.exe:     {self._python_exe if self._python_exe else '❌ не найден'}")
        print("=" * 60)
    
    # ===== ГЕТТЕРЫ =====
    
    def get_base_dir(self) -> str:
        return str(self._base_dir)
    
    def get_data_dir(self) -> str:
        return str(self._data_dir)
    
    def get_python_dir(self) -> Optional[str]:
        return str(self._python_dir) if self._python_dir else None
    
    def get_python_exe(self) -> Optional[str]:
        return str(self._python_exe) if self._python_exe else None
    
    def get_save_dir(self) -> str:
        return self._paths["SAVE_DIR"]
    
    def get_logs_dir(self) -> str:
        return self._paths["LOGS_DIR"]
    
    def get_frames_dir(self) -> str:
        return self._paths["FRAMES_DIR"]
    
    def get_temp_dir(self) -> str:
        return self._paths["TEMP_DIR"]
    
    def get_notes_file(self) -> str:
        return self._paths["NOTES_FILE"]
    
    def get_memory_db(self) -> str:
        return self._paths["MEMORY_DB"]
    
    def get_persistent_memory_db(self) -> str:
        return self._paths["PERSISTENT_MEMORY_DB"]
    
    def get_reminder_db(self) -> str:
        return self._paths["REMINDER_DB"]
    
    def get_document_rag_db(self) -> str:
        return self._paths["DOCUMENT_RAG_DB"]
    
    def get_advanced_rag_db(self) -> str:
        return self._paths["ADVANCED_RAG_DB"]
    
    def get_app_scanner_db(self) -> str:
        return self._paths["APP_SCANNER_DB"]
    
    def get_vosk_model_path(self) -> str:
        return self._paths["VOSK_MODEL_PATH"]
    
    def get_browser_path(self) -> str:
        return self._paths["BROWSER_PATH"]
    
    def get_default_browser(self) -> str:
        return self._paths["DEFAULT_BROWSER"]
    
    def get_api_url(self) -> str:
        return self._paths["API_URL"]
    
    def get_api_key(self) -> str:
        return self._paths["API_KEY"]
    
    def get_model_name(self) -> str:
        return self._paths["MODEL_NAME"]
    
    def get_voice_name(self) -> str:
        return self._paths["VOICE_NAME"]
    
    def get_voice_language(self) -> str:
        return self._paths["VOICE_LANGUAGE"]
    
    def get_safe_mode(self) -> bool:
        return self._paths["SAFE_MODE"]
    
    def get_allowed_dirs(self) -> List[str]:
        return self._paths["ALLOWED_DIRS_LIST"]
    
    def get_path(self, key: str) -> Optional[str]:
        return self._paths.get(key)
    
    def get_all_paths(self) -> Dict[str, str]:
        return dict(self._paths)
    
    def resolve(self, path: str) -> str:
        if not path:
            return ""
        path = os.path.expanduser(path)
        path = os.path.expandvars(path)
        return os.path.normpath(path)
    
    def join(self, *parts) -> str:
        if not parts:
            return ""
        first = self.resolve(parts[0]) if parts else ""
        rest = [str(p) for p in parts[1:]]
        return os.path.normpath(os.path.join(first, *rest))


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР
# ============================================================

path_manager = PathManager()


# ============================================================
# УТИЛИТЫ
# ============================================================

def expand_path(path: str) -> str:
    return path_manager.resolve(path)


def join_paths(*parts) -> str:
    return path_manager.join(*parts)


def ensure_dir(path: str) -> bool:
    try:
        Path(expand_path(path)).mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False


# ============================================================
# ПРОВЕРКА
# ============================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("📂 ВСЕ ПУТИ")
    print("=" * 60)
    
    pm = PathManager()
    
    for key, value in pm.get_all_paths().items():
        if key.endswith("_LIST"):
            continue
        if isinstance(value, str) and len(value) < 200:
            print(f"  {key:25} = {value}")
        elif isinstance(value, list):
            print(f"  {key:25} = {value}")
        else:
            print(f"  {key:25} = {type(value).__name__}")
    
    print("\n" + "=" * 60)
    print("✅ ALLOWED_DIRS:")
    for d in pm.get_allowed_dirs():
        print(f"  • {d}")