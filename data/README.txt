Пункты 2–4. Скопируй файлы в D:\asistent\data\ поверх существующих.

Файлы:
  assistant_core.py
  gui.py
  micro_models.py
  emotion_service.py
  rag_engine.py
  config.py

settings.json — добавь ключи (если нет):
  "LAZY_MICRO_MODELS": true,
  "RAG_LAZY_EMBEDDINGS": true,
  "RAG_MIN_CHUNKS_FOR_SEMANTIC": 8

voice_controller.py в этом наборе нет (полный файл не был в локальной копии).
Правка вручную, в __init__ VoiceController:

Было:
        if eng in ("silero", "silero-tts", "silero_tts"):
            self.preload_silero_async()

Стало:
        if (
            getattr(config, "ENABLE_VOICE_OUTPUT", False)
            and eng in ("silero", "silero-tts", "silero_tts")
        ):
            self.preload_silero_async()

Что изменилось:
2) Старт легче: микро-модели грузятся при первом запросе, RAG без embeddings
   пока чанков мало, Silero не грузится при выключенном TTS.
3) ANIM: тег модели важнее selector/GUI. GUI больше не угадывает анимацию
   по ключевым словам ответа и не ставит анимацию до стрима.
4) Интенты: граница слова + для search/launch нужен объект
   («найди в себе силы» / голое «открой» не ускоряются).
