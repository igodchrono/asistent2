# memory_manager.py
import sqlite3
import datetime
import threading
import logging

logger = logging.getLogger(__name__)


class MemoryManager:
    def __init__(self, db_path="assistant_memory.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.conn = None
        self.cursor = None
        self._connect()

    def _connect(self):
        """Подключение с WAL-режимом (безопасно для параллельных чтений/записей)."""
        try:
            self.conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0,
            )
            # WAL — ключевое исправление конфликтов записи
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.execute("PRAGMA synchronous=NORMAL;")
            self.conn.execute("PRAGMA busy_timeout=5000;")
            self.conn.execute("PRAGMA foreign_keys=ON;")
            self.cursor = self.conn.cursor()
            self._init_schema()
            logger.info(f"MemoryManager: WAL-режим включён ({self.db_path})")
        except Exception as e:
            logger.error(f"MemoryManager: ошибка подключения к БД: {e}", exc_info=True)
            raise

    def _init_schema(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                role TEXT,
                content TEXT
            )
        """)
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(timestamp)"
        )
        cols = {r[1] for r in self.cursor.execute("PRAGMA table_info(messages)").fetchall()}
        if "character" not in cols:
            try:
                self.cursor.execute(
                    "ALTER TABLE messages ADD COLUMN character TEXT DEFAULT 'лисичка'"
                )
            except Exception as e:
                logger.debug(f"messages.character migrate: {e}")
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_character ON messages(character)"
        )
        self.conn.commit()

    def add_message(self, role, content, character=None):
        if not role or content is None:
            return
        try:
            with self.lock:
                timestamp = datetime.datetime.now().isoformat()
                ch = (character or "лисичка").strip() or "лисичка"
                self.cursor.execute(
                    "INSERT INTO messages (timestamp, role, content, character) "
                    "VALUES (?, ?, ?, ?)",
                    (timestamp, str(role), str(content), ch),
                )
                self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"MemoryManager.add_message: {e}", exc_info=True)
            try:
                self.conn.rollback()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"MemoryManager.add_message (unexpected): {e}", exc_info=True)

    def get_recent_history(self, limit=20, character=None):
        try:
            with self.lock:
                if character:
                    self.cursor.execute(
                        "SELECT role, content FROM messages "
                        "WHERE character = ? "
                        "ORDER BY timestamp DESC LIMIT ?",
                        (str(character), int(limit)),
                    )
                else:
                    self.cursor.execute(
                        "SELECT role, content FROM messages ORDER BY timestamp DESC LIMIT ?",
                        (int(limit),),
                    )
                rows = self.cursor.fetchall()
            return [{"role": row[0], "content": row[1]} for row in reversed(rows)]
        except Exception as e:
            logger.error(f"MemoryManager.get_recent_history: {e}", exc_info=True)
            return []

    def search_history(self, keyword):
        if not keyword:
            return []
        try:
            with self.lock:
                self.cursor.execute(
                    "SELECT content FROM messages WHERE content LIKE ?",
                    ("%" + str(keyword) + "%",),
                )
                return [row[0] for row in self.cursor.fetchall()]
        except Exception as e:
            logger.error(f"MemoryManager.search_history: {e}", exc_info=True)
            return []

    def close(self):
        try:
            with self.lock:
                if self.conn:
                    self.conn.close()
                    self.conn = None
                    self.cursor = None
        except Exception as e:
            logger.warning(f"MemoryManager.close: {e}")
