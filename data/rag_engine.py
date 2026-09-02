# rag_engine.py
"""
Универсальный RAG-движок для Лисички.
Поддерживает два режима:
1. Keyword-поиск (SQLite LIKE) — быстрый, без API
2. Семантический поиск (FAISS + эмбеддинги) — точный
"""

import aiohttp
import aiosqlite
import asyncio
import json
import os
import re
import hashlib
import sqlite3
import threading
from typing import List, Dict, Optional, Tuple, Union, Any
from datetime import datetime
from pathlib import Path

import numpy as np
import faiss

from utils import run_in_executor, rag_semaphore, api_semaphore, api_rate_limiter, task_pool, logger

import config


class RAGEngine:
    """
    Универсальный RAG-движок.
    - Режим 'keyword': быстрый поиск по ключевым словам (SQLite LIKE)
    - Режим 'semantic': точный семантический поиск (FAISS + эмбеддинги)
    """
    
    # Режимы поиска
    MODE_KEYWORD = "keyword"
    MODE_SEMANTIC = "semantic"
    MODE_HYBRID = "hybrid"  # Комбинированный
    
    def __init__(
        self,
        db_path: Optional[str] = None,
        api_url: Optional[str] = None,
        model_name: Optional[str] = None,
        dimension: int = 512,
        chunk_size: int = 500,
        overlap: int = 50
    ):
        # Пути
        self.db_path = db_path or getattr(config, "ADVANCED_RAG_DB", "rag.db")
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.dimension = dimension or getattr(config, "ADVANCED_RAG_DIMENSION", 512)
        
        # API настройки
        self.api_url = (api_url or config.API_URL or "").rstrip("/")
        # ВАЖНО: для /embeddings — отдельная модель, не chat
        self.model_name = (
            model_name
            or getattr(config, "EMBEDDING_MODEL", None)
            or getattr(config, "MODEL_NAME", None)
            or "text-embedding-nomic-embed-text-v1.5"
        )
        self.embed_timeout = float(getattr(config, "EMBEDDING_TIMEOUT", 6.0) or 6.0)

        # Режим: hybrid если RAG_HYBRID_MODE или RAG_DEFAULT_MODE=hybrid
        _pref = (getattr(config, "RAG_DEFAULT_MODE", "keyword") or "keyword").lower()
        if getattr(config, "RAG_HYBRID_MODE", False):
            _pref = "hybrid"
        if _pref == "semantic" and getattr(config, "ADVANCED_RAG_ENABLED", False):
            self.default_mode = self.MODE_SEMANTIC
        elif _pref == "hybrid" and getattr(config, "ADVANCED_RAG_ENABLED", False):
            self.default_mode = self.MODE_HYBRID
        else:
            self.default_mode = self.MODE_KEYWORD
        self._lazy_embeddings = bool(getattr(config, "RAG_LAZY_EMBEDDINGS", True))
        self._min_chunks_semantic = int(getattr(config, "RAG_MIN_CHUNKS_FOR_SEMANTIC", 8) or 8)
        
        # Состояние
        self._initialized = False
        self._lock = asyncio.Lock()
        self._embedding_cache: Dict[str, np.ndarray] = {}
        self._cache_size = 1000
        
        # FAISS индекс (только для семантического режима)
        self.index: Optional[faiss.Index] = None
        self.chunks: List[Dict] = []
        
        # Инициализация
        self._init_db_sync()
        self._load_existing_chunks_sync()
        if self._lazy_embeddings and len(self.chunks) < self._min_chunks_semantic:
            if self.default_mode in (self.MODE_SEMANTIC, self.MODE_HYBRID):
                logger.info(
                    f"RAG: чанков {len(self.chunks)} < {self._min_chunks_semantic} "
                    "→ keyword-only (embeddings отложены)"
                )
                self.default_mode = self.MODE_KEYWORD
        self._initialized = True
        
        logger.info(f"RAGEngine инициализирован | БД: {self.db_path} | "
                   f"Режим: {self.default_mode} | Чанков: {len(self.chunks)}")
    
    # ================================================================
    # 1. ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ
    # ================================================================
    
    def _init_db_sync(self):
        """Синхронная инициализация БД (универсальная схема)."""
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Основная таблица чанков
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT NOT NULL,
                source TEXT NOT NULL,
                chunk_index INTEGER,
                content TEXT NOT NULL,
                content_hash TEXT,
                embedding_vector TEXT,
                created_at TEXT,
                updated_at TEXT,
                version INTEGER DEFAULT 1
            )
        """)
        
        # Индексы для быстрого поиска
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_doc_id ON chunks(doc_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_source ON chunks(source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_content_hash ON chunks(content_hash)")
        
        # Таблица документов (метаданные)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL,
                file_path TEXT,
                file_size INTEGER,
                file_mtime REAL,
                total_chunks INTEGER,
                indexed_at TEXT,
                UNIQUE(doc_id, source)
            )
        """)
        
        conn.commit()
        conn.close()
    
    def _load_existing_chunks_sync(self):
        """Загрузка существующих чанков в FAISS (если есть эмбеддинги)."""
        self.chunks = []
        embeddings = []
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, doc_id, source, chunk_index, content, embedding_vector
                FROM chunks
                ORDER BY id
            """)
            rows = cursor.fetchall()
            conn.close()
            
            for row in rows:
                _id, doc_id, source, chunk_idx, content, emb_json = row
                self.chunks.append({
                    "id": _id,
                    "doc_id": doc_id,
                    "source": source,
                    "chunk_index": chunk_idx,
                    "content": content
                })
                
                if emb_json:
                    emb = np.array(json.loads(emb_json), dtype=np.float32)
                    embeddings.append(emb)
            
            # Инициализируем FAISS индекс
            if embeddings:
                base = faiss.IndexFlatIP(self.dimension)
                self.index = faiss.IndexIDMap2(base)
                vectors = np.vstack(embeddings).astype(np.float32)
                # ids from chunks order — reload assigns sequential if missing
                ids = np.arange(len(embeddings), dtype=np.int64)
                # better: use DB ids if available in self.chunks
                if self.chunks and all(c.get('id') is not None for c in self.chunks[:len(embeddings)]):
                    ids = np.array([c['id'] for c in self.chunks[:len(embeddings)]], dtype=np.int64)
                self.index.add_with_ids(vectors, ids)
                logger.info(f"Загружено {len(embeddings)} чанков в FAISS")
            else:
                base = faiss.IndexFlatIP(self.dimension)
                self.index = faiss.IndexIDMap2(base)
                
        except Exception as e:
            logger.error(f"Ошибка загрузки чанков: {e}")
            base = faiss.IndexFlatIP(self.dimension)
            self.index = faiss.IndexIDMap2(base)
    
    # ================================================================
    # 2. РАБОТА С ЭМБЕДДИНГАМИ
    # ================================================================
    
    def _random_vector(self) -> np.ndarray:
        """Создаёт нормализованный случайный вектор (fallback)."""
        vec = np.random.randn(self.dimension).astype(np.float32)
        norm = np.linalg.norm(vec) + 1e-8
        return vec / norm
    
    def _resize_vector(self, emb: np.ndarray) -> np.ndarray:
        """Изменяет размер вектора до нужной размерности."""
        if len(emb) < self.dimension:
            return np.pad(emb, (0, self.dimension - len(emb)))
        return emb[:self.dimension]
    
    def _get_cache_key(self, text: str) -> str:
        """Генерирует ключ для кэша эмбеддингов."""
        return hashlib.md5(text[:200].encode()).hexdigest()
    
    async def _get_embedding_async(self, text: str) -> Optional[np.ndarray]:
        """
        Эмбеддинг через /v1/embeddings.
        При ошибке — None (НЕ random vector: он портит FAISS ranking).
        """
        if not text or len(text.strip()) < 3:
            return None

        cache_key = self._get_cache_key(text)
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]

        text = text[:1500]
        api_key = getattr(config, "API_KEY", "not-needed") or "not-needed"

        async with api_semaphore:
            await api_rate_limiter.acquire()
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": self.model_name,
                    "input": text,
                    "encoding_format": "float",
                }
                try:
                    async with session.post(
                        f"{self.api_url}/embeddings",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=self.embed_timeout),
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            embedding = (data.get("data") or [{}])[0].get("embedding") or []
                            if embedding:
                                emb = np.array(embedding, dtype=np.float32)
                                # авто-подстройка dimension при первом успешном embed
                                if not getattr(self, "_dim_locked", False):
                                    if len(emb) != self.dimension:
                                        logger.info(
                                            f"RAG dimension {self.dimension} → {len(emb)} (from embedder)"
                                        )
                                        self.dimension = int(len(emb))
                                    self._dim_locked = True
                                if len(emb) != self.dimension:
                                    emb = self._resize_vector(emb)
                                # L2-нормализация для IndexFlatIP / cosine-like
                                n = float(np.linalg.norm(emb) + 1e-9)
                                emb = emb / n
                                if len(self._embedding_cache) < self._cache_size:
                                    self._embedding_cache[cache_key] = emb
                                return emb
                        body = await response.text()
                        logger.warning(f"Эмбеддинг HTTP {response.status}: {body[:120]}")
                except asyncio.TimeoutError:
                    logger.warning(f"Таймаут эмбеддинга ({self.embed_timeout}с) — semantic skip")
                except Exception as e:
                    logger.error(f"Ошибка эмбеддинга: {e}")
        return None
    
    # ================================================================
    # 3. РАЗБИВКА НА ЧАНКИ
    # ================================================================
    
    def _chunk_text(self, text: str, chunk_size: Optional[int] = None, 
                   overlap: Optional[int] = None) -> List[str]:
        """Разбивка текста на чанки с перекрытием."""
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return []
        
        chunk_size = chunk_size or self.chunk_size
        overlap = overlap or self.overlap
        
        words = text.split()
        chunks = []
        step = chunk_size - overlap
        
        for i in range(0, len(words), step):
            chunk = ' '.join(words[i:i + chunk_size])
            if chunk and len(chunk) > 30:
                chunks.append(chunk)
        
        return chunks
    
    # ================================================================
    # 4. ИНДЕКСАЦИЯ ДОКУМЕНТОВ
    # ================================================================
    

    def _faiss_ensure(self) -> None:
        """Создаёт пустой IndexIDMap2, если индекса ещё нет."""
        if self.index is None:
            base = faiss.IndexFlatIP(int(self.dimension))
            self.index = faiss.IndexIDMap2(base)

    def _faiss_remove_doc(self, doc_id: str) -> None:
        """
        Удаляет из FAISS все векторы чанков данного doc_id.
        IndexIDMap2.remove_ids; meta в self.chunks тоже чистим.
        """
        if self.index is None:
            self.chunks = [c for c in self.chunks if c.get("doc_id") != doc_id]
            return
        ids = [int(c["id"]) for c in self.chunks if c.get("doc_id") == doc_id and c.get("id") is not None]
        self.chunks = [c for c in self.chunks if c.get("doc_id") != doc_id]
        if not ids:
            return
        try:
            id_arr = np.array(ids, dtype=np.int64)
            self.index.remove_ids(id_arr)
        except Exception as e:
            logger.warning(f"FAISS remove_ids doc={doc_id}: {e} — rebuild on next full load")
            # fallback: soft — search просто не найдёт старые meta

    async def add_document_async(
        self,
        text: str,
        doc_id: str,
        source: str,
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None,
        use_embeddings: Optional[bool] = None
    ) -> Tuple[int, str]:
        """
        Добавление документа в индекс.
        
        Args:
            text: Текст документа
            doc_id: Уникальный ID документа
            source: Источник (имя файла)
            chunk_size: Размер чанка
            overlap: Перекрытие
            use_embeddings: Использовать эмбеддинги (если None — по default_mode)
        """
        if not text or len(text.strip()) < 10:
            return 0, "Документ слишком короткий"
        
        use_embeddings = use_embeddings if use_embeddings is not None else (
            self.default_mode in (self.MODE_SEMANTIC, self.MODE_HYBRID)
        )
        
        chunks = self._chunk_text(text, chunk_size, overlap)
        if not chunks:
            return 0, "Не удалось разбить на чанки"
        
        now = datetime.now().isoformat()
        content_hash = hashlib.md5(text[:1000].encode()).hexdigest()
        
        # Получаем эмбеддинги (если нужно)
        embeddings = []
        if use_embeddings:
            embed_tasks = [self._get_embedding_async(chunk) for chunk in chunks]
            embeddings = await asyncio.gather(*embed_tasks)
        
        # Сохраняем в БД
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as conn:
                # Удаляем старые чанки этого документа
                await conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
                
                for i, chunk in enumerate(chunks):
                    emb = embeddings[i] if embeddings else None
                    emb_json = json.dumps(emb.tolist()) if emb is not None else None
                    
                    await conn.execute("""
                        INSERT INTO chunks 
                        (doc_id, source, chunk_index, content, content_hash, embedding_vector, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        doc_id,
                        source,
                        i,
                        chunk,
                        content_hash,
                        emb_json,
                        now,
                        now
                    ))
                
                # Обновляем метаданные документа
                await conn.execute("""
                    INSERT OR REPLACE INTO documents 
                    (doc_id, source, total_chunks, indexed_at)
                    VALUES (?, ?, ?, ?)
                """, (doc_id, source, len(chunks), now))
                
                await conn.commit()
        
        # Обновляем FAISS: incremental IndexIDMap (без полной перестройки)
        if embeddings and any(e is not None for e in embeddings):
            self._faiss_remove_doc(doc_id)
            # id чанков из БД после insert
            async with aiosqlite.connect(self.db_path) as conn:
                cursor = await conn.execute(
                    "SELECT id, doc_id, source, chunk_index, content, embedding_vector "
                    "FROM chunks WHERE doc_id = ? ORDER BY chunk_index",
                    (doc_id,),
                )
                rows = await cursor.fetchall()

            ids = []
            vecs = []
            for row in rows:
                _id, doc_id2, source2, chunk_idx, content, emb_json = row
                # обновить/добавить meta
                meta = {
                    "id": _id,
                    "doc_id": doc_id2,
                    "source": source2,
                    "chunk_index": chunk_idx,
                    "content": content,
                }
                # убрать старые записи этого id
                self.chunks = [c for c in self.chunks if c.get("id") != _id and c.get("doc_id") != doc_id]
                self.chunks.append(meta)
                if emb_json:
                    emb = np.array(json.loads(emb_json), dtype=np.float32)
                    emb = self._resize_vector(emb)
                    n = np.linalg.norm(emb) + 1e-8
                    emb = emb / n
                    vecs.append(emb)
                    ids.append(_id)

            if vecs:
                self._faiss_ensure()
                vectors = np.vstack(vecs).astype(np.float32)
                id_arr = np.array(ids, dtype=np.int64)
                self.index.add_with_ids(vectors, id_arr)

        logger.info(f"Индексировано {len(chunks)} чанков из {source}")
        return len(chunks), f"Индексировано {len(chunks)} чанков из {source}"
    
    # ================================================================
    # 5. ПОИСК
    # ================================================================
    
    async def search_async(
        self, 
        query: str, 
        limit: int = 5,
        mode: Optional[str] = None,
        min_similarity: float = 0.3
    ) -> List[Dict]:
        """
        Асинхронный поиск.
        
        Args:
            query: Поисковый запрос
            limit: Количество результатов
            mode: 'keyword', 'semantic', 'hybrid' (или None — default_mode)
            min_similarity: Минимальное сходство (для семантического поиска)
        """
        mode = mode or self.default_mode
        if (
            getattr(self, "_lazy_embeddings", True)
            and len(self.chunks) < int(getattr(self, "_min_chunks_semantic", 8) or 8)
            and mode in (self.MODE_SEMANTIC, self.MODE_HYBRID)
        ):
            mode = self.MODE_KEYWORD
        if mode == self.MODE_SEMANTIC:
            return await self._search_semantic_async(query, limit, min_similarity)
        elif mode == self.MODE_KEYWORD:
            return await self._search_keyword_async(query, limit)
        elif mode == self.MODE_HYBRID:
            return await self._search_hybrid_async(query, limit, min_similarity)
        else:
            return await self._search_keyword_async(query, limit)
    
    # --- 5.1 Семантический поиск (FAISS) ---
    
    @run_in_executor
    def _search_faiss(self, query_emb: np.ndarray, limit: int) -> List[Dict]:
        """Поиск в FAISS (IndexIDMap2 → indices = chunk id)."""
        if self.index is None or self.index.ntotal == 0:
            return []
        
        k = min(limit, self.index.ntotal)
        query_emb = query_emb.reshape(1, -1).astype(np.float32)
        distances, indices = self.index.search(query_emb, k)
        
        by_id = {int(c["id"]): c for c in self.chunks if c.get("id") is not None}
        results = []
        for idx, dist in zip(indices[0], distances[0]):
            if idx is None or int(idx) < 0:
                continue
            chunk = by_id.get(int(idx))
            if not chunk:
                continue
            results.append({
                "id": chunk["id"],
                "doc_id": chunk["doc_id"],
                "source": chunk["source"],
                "chunk_index": chunk["chunk_index"],
                "content": chunk["content"],
                "similarity": float(dist)
            })
        return results
    
    async def _search_semantic_async(self, query: str, limit: int, min_similarity: float) -> List[Dict]:
        """Семантический поиск."""
        if not query or not query.strip():
            return []
        
        async with rag_semaphore:
            query_emb = await self._get_embedding_async(query)
            if query_emb is None or query_emb.size == 0:
                return []
            
            results = await self._search_faiss(query_emb, limit)
            
            # Фильтруем по минимальному сходству
            return [r for r in results if r.get("similarity", 0) >= min_similarity]
    
    # --- 5.2 Поиск по ключевым словам (улучшенный ranking) ---

    # Источники персонажа / пользователя — выше приоритет
    _PRIORITY_SOURCES = (
        "персонаж_лисичка", "о_пользователе", "character", "user", "persona",
    )
    # Стоп-слова (рус + eng) — не участвуют в score
    _STOP_WORDS = frozenset({
        "и", "в", "на", "с", "по", "для", "не", "что", "это", "как", "а", "то",
        "от", "из", "к", "у", "о", "же", "бы", "ли", "или", "но", "да", "нет",
        "the", "a", "an", "of", "to", "in", "on", "for", "is", "and", "or",
        "лисичка", "хозяин", "пожалуйста", "плиз",
    })

    def _keyword_score(
        self, words: List[str], content: str, source: str, chunk_index: int
    ) -> float:
        """
        BM25-подобное ранжирование без idf-корпуса:
        - покрытие уникальных токенов запроса
        - частота (с насыщением)
        - бонус за совпадение в начале чанка
        - бонус приоритетным source (персонаж / пользователь)
        - лёгкий штраф за очень длинные чанки
        """
        if not words or not content:
            return 0.0

        text_lower = content.lower()
        tokens = re.findall(r"\w+", text_lower)
        if not tokens:
            return 0.0
        n = len(tokens)
        token_set = set(tokens)

        covered = 0
        tf_sum = 0.0
        for w in words:
            cnt = text_lower.count(w)
            if cnt > 0:
                covered += 1
                # насыщение tf: 1 + log
                tf_sum += 1.0 + (0.0 if cnt <= 1 else min(2.5, 0.7 * (cnt ** 0.5)))

        if covered == 0:
            return 0.0

        coverage = covered / len(words)
        # длина: предпочитаем средние чанки
        length_norm = 1.0 / (1.0 + abs(n - 80) / 120.0)

        head = " ".join(tokens[:40])
        head_hits = sum(1 for w in words if w in head)
        head_bonus = 0.15 * (head_hits / len(words))

        source_l = (source or "").lower()
        src_bonus = 0.0
        for p in self._PRIORITY_SOURCES:
            if p in source_l:
                src_bonus = 0.25
                break
        # первые чанки документа чуть важнее (введение / заголовки)
        if chunk_index == 0:
            src_bonus += 0.08

        score = (0.45 * coverage) + (0.30 * (tf_sum / (len(words) + 1))) + (
            0.10 * length_norm
        ) + head_bonus + src_bonus
        return float(score)

    async def _search_keyword_async(self, query: str, limit: int) -> List[Dict]:
        """Поиск по ключевым словам (SQLite LIKE) + улучшенный ranking."""
        if not query or not query.strip():
            return []

        raw_words = re.findall(r"\w+", query.lower())
        words = [w for w in raw_words if len(w) > 1 and w not in self._STOP_WORDS]
        if not words:
            words = [w for w in raw_words if len(w) > 1] or raw_words
        if not words:
            return []

        # Уникальные, порядок сохранён
        seen = set()
        uniq_words: List[str] = []
        for w in words:
            if w not in seen:
                seen.add(w)
                uniq_words.append(w)
        words = uniq_words

        async with self._lock:
            async with aiosqlite.connect(self.db_path) as conn:
                conditions = " OR ".join(["LOWER(content) LIKE ?" for _ in words])
                params = [f"%{w}%" for w in words]
                cursor = await conn.execute(
                    f"SELECT id, doc_id, source, chunk_index, content "
                    f"FROM chunks WHERE {conditions}",
                    params,
                )
                rows = await cursor.fetchall()

        scored = []
        for row in rows:
            _id, doc_id, source, chunk_idx, content = row
            score = self._keyword_score(words, content or "", source or "", int(chunk_idx or 0))
            if score < 0.08:
                continue
            scored.append({
                "id": _id,
                "doc_id": doc_id,
                "source": source,
                "chunk_index": chunk_idx,
                "content": content,
                "score": score,
                "similarity": score,  # единообразие с semantic
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]
    
    # --- 5.3 Гибридный поиск ---
    
    async def _search_hybrid_async(self, query: str, limit: int, min_similarity: float) -> List[Dict]:
        """
        Hybrid: keyword + semantic с Reciprocal Rank Fusion (устойчивее сырых score).
        Если semantic пустой (нет embed) — чистый keyword.
        """
        k = float(getattr(config, "RAG_RRF_K", 60) or 60)
        w_kw = float(getattr(config, "RAG_RRF_WEIGHT_KEYWORD", 0.45) or 0.0)
        w_sem = float(getattr(config, "RAG_RRF_WEIGHT_SEMANTIC", 1.0) or 0.0)
        keyword_results = await self._search_keyword_async(query, max(limit * 3, 8))
        semantic_results = await self._search_semantic_async(query, max(limit * 3, 8), min_similarity)

        ranks: Dict[Any, Dict] = {}
        for i, r in enumerate(keyword_results):
            rid = r.get("id")
            if rid is None:
                continue
            entry = ranks.setdefault(rid, {**r, "rank": 0.0, "sources": []})
            entry["rank"] += w_kw / (k + i + 1)
            entry["sources"].append("kw")
            entry["score"] = max(float(entry.get("score") or 0), float(r.get("score") or 0))

        for i, r in enumerate(semantic_results):
            rid = r.get("id")
            if rid is None:
                continue
            sim = float(r.get("similarity") or 0)
            if sim < min_similarity:
                continue
            entry = ranks.setdefault(rid, {**r, "rank": 0.0, "sources": []})
            entry["rank"] += w_sem / (k + i + 1)
            entry["sources"].append("sem")
            entry["similarity"] = max(float(entry.get("similarity") or 0), sim)

        results = sorted(ranks.values(), key=lambda x: x["rank"], reverse=True)
        return results[:limit]

    # ================================================================
    # 6. ПОЛУЧЕНИЕ КОНТЕКСТА ДЛЯ ПРОМПТА
    # ================================================================

    async def get_context_async(
        self,
        query: str,
        limit: int = 4,
        max_chars: int = 1800,
        mode: Optional[str] = None,
        min_similarity: float = 0.12,
    ) -> str:
        """
        Контекст для system prompt (hybrid/keyword/semantic).
        Короткие реплики пропускаем — не засоряем prompt.
        """
        q = (query or "").strip()
        if getattr(config, "RAG_SKIP_SHORT_QUERY", True):
            min_c = int(getattr(config, "RAG_MIN_QUERY_CHARS", 12) or 12)
            min_w = int(getattr(config, "RAG_MIN_QUERY_WORDS", 2) or 2)
            if len(q) < min_c or len(q.split()) < min_w:
                return ""

        mode = mode or self.default_mode
        min_similarity = float(
            min_similarity
            if min_similarity is not None
            else getattr(config, "RAG_MIN_SIMILARITY", 0.22)
        )
        limit = int(limit or getattr(config, "RAG_CONTEXT_LIMIT", 4) or 4)
        max_chars = int(max_chars or getattr(config, "RAG_MAX_CONTEXT_CHARS", 2200) or 2200)

        results = await self.search_async(
            query, limit=limit, mode=mode, min_similarity=min_similarity
        )
        if not results:
            return ""

        # Дедуп по source+началу контента
        seen = set()
        parts = ["\n=== КОНТЕКСТ ИЗ ПАМЯТИ / ДОКУМЕНТОВ ===\n"]
        total = 0
        used = 0

        for res in results:
            score = float(res.get("similarity") or res.get("score") or 0)
            # для keyword порог мягче
            floor = min_similarity if mode == self.MODE_SEMANTIC else min(
                min_similarity, 0.10
            )
            if score < floor:
                continue

            content = (res.get("content") or "").strip()
            if not content:
                continue
            # обрезка слишком длинного чанка
            if len(content) > 700:
                content = content[:700].rstrip() + "…"

            src = res.get("source") or "?"
            key = (src, content[:80])
            if key in seen:
                continue
            seen.add(key)

            piece = f"• [{src}]\n{content}\n"
            if total + len(piece) > max_chars:
                break
            parts.append(piece)
            total += len(piece)
            used += 1
            if used >= limit:
                break

        return "\n".join(parts) if used > 0 else ""
    
    # ================================================================
    # 7. ИНДЕКСАЦИЯ ФАЙЛОВ
    # ================================================================
    
    async def index_file_async(self, file_path: str, max_chars: int = 50000) -> Tuple[int, str]:
        """
        Индексирует файл асинхронно.
        """
        if not os.path.isfile(file_path):
            return 0, f"Файл не найден: {file_path}"
        
        ext = os.path.splitext(file_path)[1].lower()
        content = ""
        
        try:
            if ext in (".txt", ".md", ".py", ".js", ".json", ".csv", ".log",
                       ".html", ".css", ".sql", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf"):
                import aiofiles
                async with aiofiles.open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = await f.read(max_chars)
            
            elif ext == ".pdf":
                try:
                    import PyPDF2
                    with open(file_path, "rb") as f:
                        reader = PyPDF2.PdfReader(f)
                        for page in reader.pages:
                            content += (page.extract_text() or "") + "\n"
                            if len(content) > max_chars:
                                break
                except Exception as e:
                    return 0, f"PDF error: {e}"
            
            elif ext == ".docx":
                try:
                    from docx import Document
                    doc = Document(file_path)
                    content = "\n".join(p.text for p in doc.paragraphs)
                except Exception as e:
                    return 0, f"DOCX error: {e}"
            
            elif ext in (".xlsx", ".xls"):
                try:
                    import openpyxl
                    wb = openpyxl.load_workbook(file_path, data_only=True)
                    for sheet in wb.worksheets:
                        content += f"\n=== {sheet.title} ===\n"
                        for row in sheet.iter_rows(values_only=True):
                            content += " | ".join([str(c) if c is not None else "" for c in row]) + "\n"
                except Exception as e:
                    return 0, f"XLSX error: {e}"
            
            else:
                return 0, f"Неподдерживаемый тип: {ext}"
        
        except Exception as e:
            return 0, str(e)
        
        if not content:
            return 0, "Файл пуст"
        
        doc_id = hashlib.md5((file_path + str(os.path.getmtime(file_path))).encode()).hexdigest()[:16]
        source = os.path.basename(file_path)
        
        return await self.add_document_async(content, doc_id, source)
    
    async def index_directory_async(
        self,
        dir_path: str,
        extensions: Optional[set] = None,
        max_chars: int = 50000,
        recursive: bool = True
    ) -> List[Tuple[str, int, str]]:
        """
        Индексирует все файлы в директории.
        """
        if extensions is None:
            extensions = {".md", ".txt", ".pdf", ".docx", ".py", ".json", ".csv", ".log", ".html", ".css", ".sql"}
        
        dir_path = Path(dir_path)
        if not dir_path.is_dir():
            return []
        
        results = []
        pattern = "**/*" if recursive else "*"
        
        for f in sorted(dir_path.glob(pattern)):
            if f.is_file() and f.suffix.lower() in extensions:
                try:
                    n, msg = await self.index_file_async(str(f), max_chars)
                    results.append((str(f), n, msg))
                    if n > 0:
                        logger.info(f"Индексирован: {f.name} ({n} чанков)")
                except Exception as e:
                    logger.error(f"Ошибка индексации {f.name}: {e}")
                    results.append((str(f), 0, str(e)))
        
        return results
    
    async def auto_index_from_config_async(self):
        """
        Автоматическая индексация из конфига.
        """
        if not getattr(config, "RAG_AUTO_INDEX", True):
            return []
        
        base_dirs = [
            Path.cwd(),
            Path(__file__).resolve().parent,
        ]
        results = []
        
        # Индексация отдельных файлов
        try:
            await self.prune_inactive_personas_async()
        except Exception as e:
            logger.warning(f"RAG prune personas: {e}")

        docs = getattr(config, "RAG_DOCS", [])
        for name in docs:
            found = None
            for base in base_dirs:
                candidate = base / name
                if candidate.is_file():
                    found = str(candidate)
                    break
            
            if found:
                n, msg = await self.index_file_async(found)
                results.append((found, n, msg))
                logger.info(f"RAG: {msg}")
            else:
                results.append((name, 0, "не найден"))
                logger.warning(f"RAG файл не найден: {name}")
        
        # Индексация директорий
        for d in getattr(config, "RAG_EXTRA_DIRS", []):
            dir_found = None
            for base in base_dirs:
                candidate = base / d
                if candidate.is_dir():
                    dir_found = candidate
                    break
            
            if dir_found:
                for path, n, msg in await self.index_directory_async(str(dir_found)):
                    results.append((path, n, msg))
                    if n > 0:
                        logger.info(f"RAG: {msg}")
            else:
                try:
                    (Path.cwd() / d).mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass
        
        return results
    
    # ================================================================
    # 8. УПРАВЛЕНИЕ ДАННЫМИ
    # ================================================================
    
    async def prune_inactive_personas_async(self) -> int:
        """Убрать из индекса чужие карточки персонажей."""
        try:
            import character_manager as cm
            keep = set()
            for p in (cm.get_active_character_path(), cm.get_active_user_path()):
                if p:
                    keep.add(p.name.lower())
                    keep.add(p.stem.lower())
            active = str(getattr(config, "ACTIVE_CHARACTER", "") or "").lower()
            if active:
                keep.add(active)
                keep.add(f"персонаж_{active}")
        except Exception:
            keep = set()
        removed = 0
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as conn:
                cur = await conn.execute("SELECT DISTINCT source FROM chunks")
                rows = await cur.fetchall()
                for (src,) in rows:
                    base = (src or "").replace("\\", "/").split("/")[-1].lower()
                    stem = base[:-3] if base.endswith(".md") else base
                    is_card = (
                        base.startswith("персонаж_")
                        or stem in ("лисичка", "мила", "раиса", "мороз", "шип")
                        or "characters" in (src or "").lower()
                    )
                    if not is_card:
                        continue
                    if stem in keep or base in keep:
                        continue
                    await conn.execute("DELETE FROM chunks WHERE source = ?", (src,))
                    await conn.execute("DELETE FROM documents WHERE source = ?", (src,))
                    removed += 1
                if removed:
                    await conn.commit()
            if removed:
                def _keep_src(src: str) -> bool:
                    base = (src or "").replace("\\", "/").split("/")[-1].lower()
                    stem = base[:-3] if base.endswith(".md") else base
                    is_card = base.startswith("персонаж_") or stem in (
                        "лисичка", "мила", "раиса", "мороз", "шип",
                    )
                    if not is_card:
                        return True
                    return stem in keep or base in keep
                self.chunks = [c for c in self.chunks if _keep_src(c.get("source") or "")]
        if removed:
            logger.info(f"RAG: сняты чужие карточки ({removed})")
        return removed

    async def delete_document_async(self, doc_id: str) -> bool:
        """Удаляет документ из индекса."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as conn:
                await conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
                await conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
                await conn.commit()
            
            self.chunks = [c for c in self.chunks if c["doc_id"] != doc_id]
            
            # Перестраиваем FAISS
            self.index = faiss.IndexFlatIP(self.dimension)
            if self.chunks:
                async with aiosqlite.connect(self.db_path) as conn:
                    cursor = await conn.execute(
                        "SELECT embedding_vector FROM chunks ORDER BY id"
                    )
                    rows = await cursor.fetchall()
                    embeddings = []
                    for row in rows:
                        if row[0]:
                            emb = np.array(json.loads(row[0]), dtype=np.float32)
                            embeddings.append(emb)
                    
                    if embeddings:
                        vectors = np.vstack(embeddings)
                        self.index.add(vectors)
            
            logger.info(f"Документ {doc_id} удалён")
            return True
    
    async def clear_all_async(self) -> bool:
        """Очищает весь индекс."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as conn:
                await conn.execute("DELETE FROM chunks")
                await conn.execute("DELETE FROM documents")
                await conn.commit()
            
            self.chunks = []
            self.index = faiss.IndexFlatIP(self.dimension)
            self._embedding_cache.clear()
            
            logger.info("Весь RAG индекс очищен")
            return True
    
    def get_stats(self) -> Dict:
        """Возвращает статистику индекса."""
        return {
            "total_chunks": len(self.chunks),
            "faiss_size": self.index.ntotal if self.index else 0,
            "cache_size": len(self._embedding_cache),
            "db_path": self.db_path,
            "dimension": self.dimension,
            "default_mode": self.default_mode
        }
    
    def close(self):
        """Закрытие ресурсов."""
        self._embedding_cache.clear()
        logger.info("RAGEngine закрыт")
    
    # ================================================================
    # 9. СОВМЕСТИМОСТЬ СО СТАРЫМ КОДОМ
    # ================================================================
    
    # Алиасы для обратной совместимости
    async def search(self, query: str, limit: int = 5) -> List[Dict]:
        """Алиас для search_async (совместимость)."""
        return await self.search_async(query, limit)
    
    async def get_context(self, query: str, limit: int = 4) -> str:
        """Алиас для get_context_async (совместимость)."""
        return await self.get_context_async(query, limit)
    
    def auto_index_from_config(self):
        """Синхронная обёртка (совместимость)."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.auto_index_from_config_async())
        except RuntimeError:
            asyncio.run(self.auto_index_from_config_async())