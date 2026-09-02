# reminder_manager.py
# ИСПРАВЛЕНО: WAL-режим SQLite + busy_timeout + единая обработка ошибок
import sqlite3
import threading
import time
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class ReminderManager:
    def __init__(self, db_path="reminders.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.running = True
        self.callback = None
        self.reminders = []
        self.conn = None
        self.cursor = None
        self._connect()
        self._load_reminders()

    def _connect(self):
        try:
            self.conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0,
            )
            # WAL — защита от database is locked
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.execute("PRAGMA synchronous=NORMAL;")
            self.conn.execute("PRAGMA busy_timeout=5000;")
            self.cursor = self.conn.cursor()
            self._init_db()
            logger.info(f"ReminderManager: WAL-режим включён ({self.db_path})")
        except Exception as e:
            logger.error(f"ReminderManager: ошибка подключения: {e}", exc_info=True)
            raise

    def _init_db(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                trigger_at TEXT NOT NULL,
                seconds INTEGER,
                is_active INTEGER DEFAULT 1,
                is_done INTEGER DEFAULT 0
            )
        """)
        self.conn.commit()

    def _load_reminders(self):
        try:
            self.cursor.execute("""
                SELECT id, text, trigger_at, seconds
                FROM reminders
                WHERE is_active = 1 AND is_done = 0
            """)
            rows = self.cursor.fetchall()

            for row in rows:
                try:
                    trigger_at = datetime.fromisoformat(row[2])
                    now = datetime.now()
                    if trigger_at > now:
                        seconds = (trigger_at - now).total_seconds()
                        self.reminders.append({
                            "id": row[0],
                            "text": row[1],
                            "time": trigger_at.timestamp(),
                            "seconds": seconds,
                            "db_id": row[0],
                        })
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка загрузки напоминания: {e}")
        except Exception as e:
            logger.error(f"ReminderManager._load_reminders: {e}", exc_info=True)

    def set_callback(self, callback):
        self.callback = callback

    def add_reminder(self, text, seconds):
        try:
            with self.lock:
                trigger_at = datetime.now() + timedelta(seconds=seconds)

                self.cursor.execute("""
                    INSERT INTO reminders (text, created_at, trigger_at, seconds, is_active)
                    VALUES (?, ?, ?, ?, 1)
                """, (text, datetime.now().isoformat(), trigger_at.isoformat(), seconds))
                self.conn.commit()

                reminder_id = self.cursor.lastrowid

                reminder = {
                    "id": reminder_id,
                    "text": text,
                    "time": time.time() + seconds,
                    "seconds": seconds,
                    "db_id": reminder_id,
                }
                self.reminders.append(reminder)
                return reminder_id
        except Exception as e:
            logger.error(f"ReminderManager.add_reminder: {e}", exc_info=True)
            try:
                self.conn.rollback()
            except Exception:
                pass
            return -1

    def get_reminders(self):
        try:
            with self.lock:
                if not self.reminders:
                    return []
                now = time.time()
                result = []
                for r in self.reminders:
                    remaining = max(0, int(r["time"] - now))
                    result.append(f"ID: {r['id']} | {r['text']} (через {remaining} сек)")
                return result
        except Exception as e:
            logger.error(f"ReminderManager.get_reminders: {e}", exc_info=True)
            return []

    def remove_reminder(self, reminder_id):
        try:
            with self.lock:
                self.cursor.execute("""
                    UPDATE reminders SET is_active = 0 WHERE id = ?
                """, (reminder_id,))
                self.conn.commit()

                before = len(self.reminders)
                self.reminders = [r for r in self.reminders if r["id"] != reminder_id]
                return len(self.reminders) < before
        except Exception as e:
            logger.error(f"ReminderManager.remove_reminder: {e}", exc_info=True)
            return False

    def check_reminders(self):
        now = time.time()
        to_remove = []

        try:
            with self.lock:
                for r in self.reminders:
                    if now >= r["time"]:
                        text = f"⏰ НАПОМИНАНИЕ: {r['text']}"

                        self.cursor.execute("""
                            UPDATE reminders SET is_done = 1 WHERE id = ?
                        """, (r.get("db_id", r["id"]),))
                        self.conn.commit()

                        if self.callback:
                            try:
                                self.callback(text)
                            except Exception as cb_err:
                                logger.error(f"Reminder callback error: {cb_err}")

                        to_remove.append(r)

                for r in to_remove:
                    self.reminders.remove(r)
        except Exception as e:
            logger.error(f"ReminderManager.check_reminders: {e}", exc_info=True)

    def get_reminders_history(self, limit=20):
        try:
            self.cursor.execute("""
                SELECT id, text, created_at, trigger_at, is_done
                FROM reminders
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"ReminderManager.get_reminders_history: {e}", exc_info=True)
            return []

    def stop(self):
        self.running = False

    def close(self):
        try:
            with self.lock:
                if self.conn:
                    self.conn.close()
                    self.conn = None
                    self.cursor = None
        except Exception as e:
            logger.warning(f"ReminderManager.close: {e}")
