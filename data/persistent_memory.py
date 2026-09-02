# persistent_memory.py
# ИСПРАВЛЕНО: WAL-режим SQLite + busy_timeout + единая обработка ошибок
import sqlite3
import threading
import datetime
import os
import base64
import re
import math
import logging
from collections import defaultdict
from datetime import timedelta
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


class PersistentMemory:
    def __init__(self, db_path="persistent_memory.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self.conn = None
        self.cursor = None
        self._connect()
        self._init_encryption()

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
            self.conn.execute("PRAGMA foreign_keys=ON;")
            self.cursor = self.conn.cursor()
            self._init_db()
            logger.info(f"PersistentMemory: WAL-режим включён ({self.db_path})")
        except Exception as e:
            logger.error(f"PersistentMemory: ошибка подключения: {e}", exc_info=True)
            raise

    def _init_db(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                access_count INTEGER DEFAULT 0,
                last_accessed TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(scope, category, key)
            )
        """)
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)")
        self.conn.commit()
        self._migrate_columns()

    def _migrate_columns(self):
        """pinned / importance / expires_at — безопасная миграция."""
        cols = {r[1] for r in self.cursor.execute("PRAGMA table_info(memories)").fetchall()}
        alters = []
        if "pinned" not in cols:
            alters.append("ALTER TABLE memories ADD COLUMN pinned INTEGER DEFAULT 0")
        if "importance" not in cols:
            alters.append("ALTER TABLE memories ADD COLUMN importance REAL DEFAULT 0.5")
        if "expires_at" not in cols:
            alters.append("ALTER TABLE memories ADD COLUMN expires_at TEXT")
        for sql in alters:
            try:
                self.cursor.execute(sql)
            except Exception as e:
                logger.debug(f"migrate: {e}")
        if alters:
            self.conn.commit()

    def _init_encryption(self):
        key_file = "secret.key"
        try:
            if os.path.exists(key_file):
                with open(key_file, "rb") as f:
                    self.cipher = Fernet(f.read())
            else:
                key = Fernet.generate_key()
                with open(key_file, "wb") as f:
                    f.write(key)
                self.cipher = Fernet(key)
        except Exception as e:
            logger.error(f"PersistentMemory: ошибка шифрования: {e}", exc_info=True)
            raise

    def _encrypt(self, text: str) -> str:
        if not text:
            return ""
        return base64.b64encode(self.cipher.encrypt(text.encode())).decode()

    def _decrypt(self, encrypted: str) -> str:
        if not encrypted:
            return ""
        return self.cipher.decrypt(base64.b64decode(encrypted)).decode()

    def add_memory(self, scope, category, key, value, confidence=1.0,
                   importance=0.5, pinned=False, expires_at=None):
        try:
            with self._lock:
                encrypted_value = self._encrypt(value)
                now = datetime.datetime.now().isoformat()
                # importance: fact/name ~0.9, casual ~0.3
                imp = float(importance)
                pin = 1 if pinned else 0
                self.cursor.execute("""
                    INSERT INTO memories
                    (scope, category, key, value, confidence, created_at, updated_at,
                     pinned, importance, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(scope, category, key) DO UPDATE SET
                        value=excluded.value,
                        confidence=excluded.confidence,
                        updated_at=excluded.updated_at,
                        importance=MAX(memories.importance, excluded.importance),
                        pinned=MAX(memories.pinned, excluded.pinned),
                        expires_at=COALESCE(excluded.expires_at, memories.expires_at)
                """, (scope, category, key, encrypted_value, confidence, now, now,
                      pin, imp, expires_at))
                self.conn.commit()
        except Exception as e:
            logger.error(f"PersistentMemory.add_memory: {e}", exc_info=True)
            try:
                self.conn.rollback()
            except Exception:
                pass

    def get_memory(self, scope, category, key):
        try:
            with self._lock:
                self.cursor.execute(
                    "SELECT value, confidence FROM memories WHERE scope=? AND category=? AND key=?",
                    (scope, category, key),
                )
                row = self.cursor.fetchone()
                if row:
                    return {"value": self._decrypt(row[0]), "confidence": row[1]}
                return None
        except Exception as e:
            logger.error(f"PersistentMemory.get_memory: {e}", exc_info=True)
            return None

    def search_memories(self, query, scope=None, limit=10):
        """Поиск с учётом pinned / importance; soft-forgotten (confidence=0) исключаются."""
        try:
            with self._lock:
                words = re.findall(r"\w+", (query or "").lower())
                now_iso = datetime.datetime.now().isoformat()
                # Базовый набор: не forgotten, не expired
                sql = """
                    SELECT id, scope, category, key, value, confidence,
                           COALESCE(pinned, 0), COALESCE(importance, 0.5),
                           expires_at, created_at, updated_at
                    FROM memories
                    WHERE COALESCE(confidence, 0) > 0.05
                      AND (expires_at IS NULL OR expires_at >= ?)
                """
                params = [now_iso]
                if scope:
                    if isinstance(scope, (list, tuple, set)):
                        scopes = [str(s) for s in scope if s]
                        if scopes:
                            sql += " AND scope IN ({})".format(
                                ",".join("?" * len(scopes))
                            )
                            params.extend(scopes)
                    else:
                        sql += " AND scope = ?"
                        params.append(scope)
                if words:
                    parts = []
                    for word in words:
                        parts.append("(LOWER(key) LIKE ? OR LOWER(value) LIKE ?)")
                        # value encrypted — LIKE по ciphertext бесполезен;
                        # матчим по key, value расшифруем ниже
                        params.extend([f"%{word}%", f"%{word}%"])
                    sql += " AND (" + " OR ".join(parts) + ")"
                sql += " ORDER BY COALESCE(pinned,0) DESC, COALESCE(importance,0.5) DESC, updated_at DESC"
                sql += " LIMIT ?"
                params.append(max(limit * 5, 30))  # берём с запасом, rank в python

                try:
                    self.cursor.execute(sql, params)
                    rows = self.cursor.fetchall()
                except Exception:
                    # fallback без pinned-колонок
                    self.cursor.execute(
                        "SELECT id, scope, category, key, value, confidence, "
                        "0, 0.5, NULL, created_at, updated_at FROM memories "
                        "WHERE confidence > 0.05 LIMIT ?",
                        (limit * 3,),
                    )
                    rows = self.cursor.fetchall()

                results = []
                for row in rows:
                    (_id, _scope, category, key, enc, confidence,
                     pinned, importance, expires_at, created_at, updated_at) = row
                    try:
                        value = self._decrypt(enc)
                    except Exception:
                        continue
                    text = (key + " " + value).lower()
                    if words:
                        tf = sum(text.count(w) for w in words) / (len(text.split()) + 1)
                        if tf <= 0 and not int(pinned or 0):
                            # key LIKE мог сработать на ciphertext — проверим вручную
                            if not any(w in text for w in words):
                                continue
                    else:
                        tf = 0.1
                    pin_boost = 0.35 if int(pinned or 0) else 0.0
                    imp = float(importance or 0.5)
                    conf = float(confidence or 0)
                    score = tf * 0.45 + imp * 0.25 + conf * 0.15 + pin_boost
                    results.append({
                        "id": _id,
                        "scope": _scope,
                        "category": category,
                        "key": key,
                        "value": value,
                        "confidence": conf,
                        "pinned": bool(int(pinned or 0)),
                        "importance": imp,
                        "score": score,
                        "created_at": created_at,
                        "updated_at": updated_at,
                    })
                results.sort(key=lambda x: (-int(x.get("pinned") or 0), -x.get("score", 0)))
                return results[:limit]
        except Exception as e:
            logger.error(f"PersistentMemory.search_memories: {e}", exc_info=True)
            return []


    def get_context_for_prompt(self, query, scope="global", limit=5, max_tokens=500):
        memories = self.search_memories(query, scope=scope, limit=limit)
        if not memories:
            return ""

        context_parts = ["\n=== ДОЛГОВРЕМЕННАЯ ПАМЯТЬ ===\n"]
        for mem in memories:
            pin = "📌 " if mem.get("pinned") else ""
            sc = mem.get("scope") or ""
            tag = f"{sc}/{mem['category']}" if sc else mem["category"]
            context_parts.append(
                f"{pin}[{tag}] {mem['key']}: {mem['value']} "
                f"(важность: {mem.get('importance', mem.get('confidence', 0)):.1f})"
            )

        full_text = "\n".join(context_parts)
        if len(full_text) > max_tokens * 4:
            full_text = full_text[: max_tokens * 4] + "... (обрезано)"

        return full_text

    def log_activity(self, activity_type, content=None, duration=None):
        try:
            with self._lock:
                self.cursor.execute("""
                    CREATE TABLE IF NOT EXISTS activity_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT,
                        hour INTEGER,
                        day_of_week INTEGER,
                        activity_type TEXT,
                        content TEXT,
                        duration INTEGER
                    )
                """)
                now = datetime.datetime.now()
                self.cursor.execute("""
                    INSERT INTO activity_log
                    (timestamp, hour, day_of_week, activity_type, content, duration)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (now.isoformat(), now.hour, now.weekday(), activity_type, content, duration))
                self.conn.commit()
        except Exception as e:
            logger.error(f"PersistentMemory.log_activity: {e}", exc_info=True)

    def get_behavior_profile(self, days=30):
        return {
            "peak_hours": [],
            "frequent_commands": [],
            "active_days": [],
            "total_activities": 0,
        }

    def get_contextual_suggestion(self):
        now = datetime.datetime.now()
        if 6 <= now.hour < 12:
            return "🌅 Доброе утро! Что будем искать сегодня?"
        if 18 <= now.hour < 23:
            return "🌙 Вечерняя активность. Есть что-то, что я могу для тебя сделать?"
        return None

    def clear_all(self):
        try:
            with self._lock:
                self.cursor.execute("DELETE FROM memories")
                self.conn.commit()
        except Exception as e:
            logger.error(f"PersistentMemory.clear_all: {e}", exc_info=True)

    def clear_scope(self, scope):
        try:
            with self._lock:
                self.cursor.execute("DELETE FROM memories WHERE scope = ?", (scope,))
                self.conn.commit()
        except Exception as e:
            logger.error(f"PersistentMemory.clear_scope: {e}", exc_info=True)

    def get_stats(self):
        try:
            with self._lock:
                self.cursor.execute("SELECT COUNT(*) FROM memories")
                total = self.cursor.fetchone()[0]
                self.cursor.execute(
                    "SELECT category, COUNT(*) FROM memories GROUP BY category"
                )
                by_category = dict(self.cursor.fetchall())
                return {"total": total, "by_category": by_category}
        except Exception as e:
            logger.error(f"PersistentMemory.get_stats: {e}", exc_info=True)
            return {"total": 0, "by_category": {}}

    def list_all(self, scope=None, category=None, limit=200):
        """Все записи памяти для UI (расшифрованные)."""
        try:
            with self._lock:
                sql = """
                    SELECT id, scope, category, key, value, confidence,
                           access_count, last_accessed, created_at, updated_at
                    FROM memories
                    WHERE 1=1
                """
                params = []
                if scope:
                    sql += " AND scope = ?"
                    params.append(scope)
                if category:
                    sql += " AND category = ?"
                    params.append(category)
                sql += " ORDER BY updated_at DESC LIMIT ?"
                params.append(int(limit))
                self.cursor.execute(sql, params)
                rows = self.cursor.fetchall()
                out = []
                for row in rows:
                    _id, sc, cat, key, val, conf, acc, last, created, updated = row
                    try:
                        val = self._decrypt(val)
                    except Exception:
                        pass
                    try:
                        key = self._decrypt(key) if key and key.startswith("gAAAA") else key
                    except Exception:
                        pass
                    out.append({
                        "id": _id,
                        "scope": sc,
                        "category": cat,
                        "key": key,
                        "value": val,
                        "confidence": conf,
                        "access_count": acc,
                        "last_accessed": last,
                        "created_at": created,
                        "updated_at": updated,
                    })
                return out
        except Exception as e:
            logger.error(f"list_all: {e}", exc_info=True)
            return []

    def list_categories(self):
        try:
            with self._lock:
                self.cursor.execute(
                    "SELECT category, COUNT(*) FROM memories GROUP BY category ORDER BY COUNT(*) DESC"
                )
                return [{"category": r[0], "count": r[1]} for r in self.cursor.fetchall()]
        except Exception as e:
            logger.error(f"list_categories: {e}")
            return []

    def delete_memory(self, memory_id: int) -> bool:
        try:
            with self._lock:
                self.cursor.execute("DELETE FROM memories WHERE id = ?", (int(memory_id),))
                self.conn.commit()
                return self.cursor.rowcount > 0
        except Exception as e:
            logger.error(f"delete_memory: {e}")
            return False

    def delete_by_category(self, category: str, scope: str = "global") -> int:
        try:
            with self._lock:
                self.cursor.execute(
                    "DELETE FROM memories WHERE category = ? AND scope = ?",
                    (category, scope),
                )
                self.conn.commit()
                return self.cursor.rowcount
        except Exception as e:
            logger.error(f"delete_by_category: {e}")
            return 0



    def get_memory_by_id(self, memory_id: int):
        try:
            with self._lock:
                self.cursor.execute(
                    "SELECT id, scope, category, key, value, confidence, "
                    "pinned, importance, expires_at, created_at, updated_at "
                    "FROM memories WHERE id=?",
                    (memory_id,),
                )
                row = self.cursor.fetchone()
                if not row:
                    return None
                return {
                    "id": row[0],
                    "scope": row[1],
                    "category": row[2],
                    "key": row[3],
                    "value": self._decrypt(row[4]),
                    "confidence": row[5],
                    "pinned": bool(row[6] or 0),
                    "importance": float(row[7] or 0.5),
                    "expires_at": row[8],
                    "created_at": row[9],
                    "updated_at": row[10],
                }
        except Exception as e:
            logger.error(f"get_memory_by_id: {e}")
            return None

    def set_pinned(self, memory_id: int, pinned: bool = True) -> bool:
        try:
            with self._lock:
                self.cursor.execute(
                    "UPDATE memories SET pinned=?, updated_at=? WHERE id=?",
                    (1 if pinned else 0, datetime.datetime.now().isoformat(), memory_id),
                )
                self.conn.commit()
                return self.cursor.rowcount > 0
        except Exception as e:
            logger.error(f"set_pinned: {e}")
            return False

    def set_importance(self, memory_id: int, importance: float) -> bool:
        try:
            with self._lock:
                self.cursor.execute(
                    "UPDATE memories SET importance=?, updated_at=? WHERE id=?",
                    (float(importance), datetime.datetime.now().isoformat(), memory_id),
                )
                self.conn.commit()
                return self.cursor.rowcount > 0
        except Exception as e:
            logger.error(f"set_importance: {e}")
            return False

    def forget_memory(self, memory_id: int) -> bool:
        """Soft-delete: confidence=0 — не попадает в prompt, запись остаётся."""
        try:
            with self._lock:
                self.cursor.execute(
                    "UPDATE memories SET confidence=0, importance=0, updated_at=? WHERE id=?",
                    (datetime.datetime.now().isoformat(), memory_id),
                )
                self.conn.commit()
                return self.cursor.rowcount > 0
        except Exception as e:
            logger.error(f"forget_memory: {e}")
            return False

    def purge_expired(self) -> int:
        """Удаляет записи с expires_at < now. Возвращает число удалённых."""
        try:
            with self._lock:
                now = datetime.datetime.now().isoformat()
                self.cursor.execute(
                    "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < ?",
                    (now,),
                )
                n = self.cursor.rowcount
                self.conn.commit()
                return n
        except Exception as e:
            logger.error(f"purge_expired: {e}")
            return 0

    def close(self):
        try:
            with self._lock:
                if self.conn:
                    self.conn.close()
                    self.conn = None
                    self.cursor = None
        except Exception as e:
            logger.warning(f"PersistentMemory.close: {e}")
