# -*- coding: utf-8 -*-
"""Переиндексация RAG (hybrid/FAISS). Запуск из data/:
   ..\\python\\python.exe reindex_rag.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from settings_manager import apply_to_config
apply_to_config(config)

try:
    import character_manager as _p
    _p.apply_to_config()
except Exception as e:
    print("persona:", e)

from rag_engine import RAGEngine

async def main():
    rag = RAGEngine(
        db_path=getattr(config, "ADVANCED_RAG_DB", "advanced_rag.db"),
        dimension=int(getattr(config, "ADVANCED_RAG_DIMENSION", 768) or 768),
    )
    print("mode:", rag.default_mode)
    print("embed model:", rag.model_name)
    print("dim:", rag.dimension)
    print("Indexing from config...")
    await rag.auto_index_from_config_async()
    st = rag.get_stats()
    print("stats:", st)
    # smoke search
    ctx = await rag.get_context_async(
        "что любит хозяин и кто такая лисичка",
        limit=4,
        mode=rag.default_mode,
    )
    print("--- context sample ---")
    print(ctx[:800] if ctx else "(empty)")
    rag.close()

if __name__ == "__main__":
    asyncio.run(main())
