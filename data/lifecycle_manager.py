# lifecycle_manager.py - ИСПРАВЛЕННЫЙ (авто-сообщения работают)
import threading
import time
import random
import logging
import asyncio
import re
from typing import Callable, Optional, Dict, Any

import config

logger = logging.getLogger(__name__)


class LifecycleManager:
    """
    Управление жизненным циклом ассистента.
    - Мониторинг системы (CPU/RAM/Disk)
    - Авто-сообщения при длительном простое
    """
    
    def __init__(self, executor):
        self.executor = executor
        self._stop_event = threading.Event()
        self._monitor_thread = None
        self._greeting_thread = None
        self._screen_thread = None
        self._greeting_mood = 0
        self._last_user_activity = time.time()
        self._assistant = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Статистика
        self._greeting_count = 0
        self._llm_generated_count = 0
        self._nsfw_count = 0
        
        # Кэш для шаблонов
        self._greeting_cache = []
        self._max_cache_size = 20

        # Circuit breaker для LLM (API offline → только шаблоны)
        self._llm_fail_count = 0
        self._llm_circuit_open_until = 0.0  # time.time() until
        self._llm_fail_threshold = int(getattr(config, "LLM_CIRCUIT_FAILS", 3) or 3)
        self._llm_circuit_cooldown = float(getattr(config, "LLM_CIRCUIT_COOLDOWN", 120) or 120)
        
        logger.info("LifecycleManager инициализирован")
    
    def set_assistant(self, assistant):
        """Устанавливает ссылку на ассистента для генерации LLM."""
        self._assistant = assistant
        # Сохраняем ссылку на event loop
        if assistant:
            try:
                self._loop = asyncio.get_running_loop()
                logger.info("Event loop сохранён из running loop")
            except RuntimeError:
                logger.info("Event loop ещё не запущен, будет установлен позже")
    
    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """Устанавливает event loop для потокобезопасных вызовов."""
        self._loop = loop
        logger.info("Event loop установлен")
    
    def start(self):
        """Запускает фоновые процессы. Можно вызывать повторно после смены настроек."""
        if getattr(config, 'ENABLE_SYSTEM_MONITOR', False):
            self._start_monitor()

        enabled = bool(getattr(config, 'ENABLE_AUTO_GREETING', False))
        alive = bool(self._greeting_thread and self._greeting_thread.is_alive())
        if enabled and not alive:
            if getattr(self, '_stop_event', None) is not None and self._stop_event.is_set():
                self._stop_event = threading.Event()
            self._start_greeting()
            print(f"🔄 Авто-сообщения ВКЛ, интервал {getattr(config,'GREETING_INTERVAL_MIN',180)}-{getattr(config,'GREETING_INTERVAL_MAX',420)} сек")
        elif not enabled:
            print("🔄 Авто-сообщения ВЫКЛ (ENABLE_AUTO_GREETING=False) — поток не запущен")
        elif alive:
            print("🔄 Авто-сообщения: поток уже работает")

        auto_screen = bool(getattr(config, "SCREEN_VISION_AUTO", False)) and bool(
            getattr(config, "SCREEN_VISION_ENABLED", True)
        )
        screen_alive = bool(self._screen_thread and self._screen_thread.is_alive())
        if auto_screen and not screen_alive:
            if getattr(self, "_stop_event", None) is not None and self._stop_event.is_set():
                self._stop_event = threading.Event()
            self._start_screen_watch()
            print(
                f"👁 Автопросмотр экрана ВКЛ, интервал "
                f"{int(getattr(config,'SCREEN_VISION_AUTO_INTERVAL', 60))} сек"
            )
        elif not auto_screen:
            print("👁 Автопросмотр экрана ВЫКЛ")
        elif screen_alive:
            print("👁 Автопросмотр: поток уже работает")

        logger.info("LifecycleManager запущен (greeting=%s alive=%s)", enabled, alive)
    
    def stop(self):
        """Останавливает все фоновые процессы."""
        self._stop_event.set()
        
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2)
        
        if self._greeting_thread and self._greeting_thread.is_alive():
            self._greeting_thread.join(timeout=2)
        if self._screen_thread and self._screen_thread.is_alive():
            self._screen_thread.join(timeout=2)
        
        logger.info(f"LifecycleManager остановлен. Статистика: {self.get_stats()}")
    
    def update_activity(self):
        """Обновляет время последней активности пользователя."""
        self._last_user_activity = time.time()
        self._greeting_mood = 0
        ctx = getattr(self._assistant, "context", None) if self._assistant else None
        if ctx is not None and hasattr(ctx, "touch_activity"):
            ctx.touch_activity()
        logger.debug("Активность пользователя обновлена")
    
    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику работы."""
        return {
            "total_greetings": self._greeting_count,
            "llm_generated": self._llm_generated_count,
            "nsfw_percentage": (self._nsfw_count / max(1, self._greeting_count)) * 100,
            "cache_size": len(self._greeting_cache),
        }
    
    # ================================================================
    # СИСТЕМНЫЙ МОНИТОР
    # ================================================================
    
    def _start_monitor(self):
        """Запускает мониторинг системы в отдельном потоке."""
        def monitor_loop():
            last_check = 0
            last_alert = ""
            interval = getattr(config, "MONITOR_INTERVAL", 60)
            
            while not self._stop_event.is_set():
                now = time.time()
                if now - last_check >= interval:
                    try:
                        from system_controller import SystemController
                        alerts = SystemController.check_system_alerts(
                            cpu_threshold=getattr(config, "CPU_THRESHOLD", 85),
                            ram_threshold=getattr(config, "RAM_THRESHOLD", 85),
                            disk_threshold=getattr(config, "DISK_THRESHOLD", 8)
                        )
                        if alerts:
                            alert_text = " | ".join(alerts)
                            if alert_text != last_alert:
                                last_alert = alert_text
                                self._send_alert(alert_text)
                        else:
                            last_alert = ""
                        last_check = now
                    except Exception as e:
                        logger.error(f"Ошибка мониторинга: {e}")
                
                self._stop_event.wait(5)
        
        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("Системный монитор запущен")
    
    def _send_alert(self, message: str):
        """Потокобезопасная отправка системного алерта."""
        if self.executor and hasattr(self.executor, '_alert_callback'):
            cb = self.executor._alert_callback
            if cb:
                cb(f"⚠️ СИСТЕМА: {message}")
    
    # ================================================================
    # АВТО-СООБЩЕНИЯ
    # ================================================================
    
    def _start_greeting(self):
        """Запускает монитор авто-сообщений в отдельном потоке."""
        if self._greeting_thread and self._greeting_thread.is_alive():
            return
        def greeting_loop():
            last_greeting = 0
            
            # Берём интервалы из настроек
            min_interval = getattr(config, "GREETING_INTERVAL_MIN", 180)
            max_interval = getattr(config, "GREETING_INTERVAL_MAX", 300)
            try:
                from time_context import greeting_interval_factor, time_bucket
                fac = greeting_interval_factor(time_bucket())
                min_interval = int(min_interval * fac)
                max_interval = int(max_interval * fac)
            except Exception:
                pass
            next_interval = random.randint(min_interval, max(min_interval + 1, max_interval))
            
            logger.info(f"Авто-сообщения: интервал {min_interval}-{max_interval} сек")
            
            while not self._stop_event.is_set():
                now = time.time()
                silent_for = now - self._last_user_activity
                
                # Проверяем, пора ли отправлять сообщение
                if silent_for >= next_interval and (now - last_greeting) >= next_interval:
                    # Определяем настроение
                    nsfw_chance = getattr(config, "GREETING_NSFW_CHANCE", 0.2)
                    
                    ctx = getattr(self._assistant, "context", None) if self._assistant else None
                    if ctx is not None and hasattr(ctx, "tick_silence"):
                        selfm = ctx.tick_silence(silent_for)
                        if selfm in ("hurt",):
                            mood = 2
                        elif selfm in ("playful",) and random.random() < nsfw_chance:
                            mood = 1
                            self._nsfw_count += 1
                        else:
                            mood = 0
                    elif self._greeting_mood >= 2:
                        mood = 2
                        self._nsfw_count += 1
                    elif random.random() < nsfw_chance:
                        mood = 1
                        self._greeting_mood = max(self._greeting_mood, 1)
                        self._nsfw_count += 1
                    else:
                        mood = 0
                        self._greeting_mood = min(self._greeting_mood + 1, 2)
                    
                    # Генерируем и отправляем сообщение
                    logger.info(f"Отправка авто-сообщения (mood={mood}, тишина={silent_for:.0f}с)")
                    self._send_greeting(mood)
                    self._greeting_count += 1
                    
                    last_greeting = now
                    next_interval = random.randint(min_interval, max_interval)
                    
                    # Сбрасываем накопленную обиду после отправки
                    if self._greeting_mood >= 2:
                        self._greeting_mood = 1
                
                self._stop_event.wait(5)  # Проверяем каждые 5 секунд
        
        self._greeting_thread = threading.Thread(target=greeting_loop, daemon=True)
        self._greeting_thread.start()
        logger.info(f"Монитор приветствий запущен")

    def _start_screen_watch(self):
        if self._screen_thread and self._screen_thread.is_alive():
            return

        def screen_loop():
            print("👁 поток автопросмотра запущен")
            first = True
            while not self._stop_event.is_set():
                interval = 3 if first else max(15, int(getattr(config, "SCREEN_VISION_AUTO_INTERVAL", 60) or 60))
                first = False
                if self._stop_event.wait(interval):
                    break
                if not getattr(config, "SCREEN_VISION_AUTO", False):
                    continue
                if not getattr(config, "SCREEN_VISION_ENABLED", True):
                    continue
                if time.time() - self._last_user_activity < 2:
                    print("👁 пропуск: хозяин только что писал")
                    continue
                try:
                    print("👁 смотрю экран…")
                    self._peek_screen()
                except Exception as e:
                    print(f"👁 ошибка: {e}")
                    logger.error("screen watch: %s", e)

        self._screen_thread = threading.Thread(target=screen_loop, daemon=True)
        self._screen_thread.start()

    def _peek_screen(self):
        if not self._assistant:
            print("👁 нет assistant")
            return
        try:
            from screen_watch import (
                capture_jpeg,
                extract_scene,
                extract_anim,
                infer_anim_from_text,
                VISION_ADDON,
            )
        except Exception as e:
            logger.error("screen_watch import: %s", e)
            return
        hide = getattr(self._assistant, "hide_for_screenshot", None)
        show = getattr(self._assistant, "show_after_screenshot", None)
        path = None
        try:
            if callable(hide):
                hide()
                time.sleep(0.15)
            path = capture_jpeg()
        finally:
            if callable(show):
                show()
        if not path:
            return
        nsfw_ok = bool(getattr(config, "NSFW_ENABLED", False))
        last = getattr(self, "_last_screen_anim", "")
        user = (
            "Автовзгляд на экран. Не описывай интерьер. "
            "Одна короткая реплика в характере про главное на экране. "
            "Без списка окон. [ANIM:…] по картинке."
        )
        if last:
            user += f" Прошлый кадр был {last} — если экран другой, смени ANIM."
        if not nsfw_ok:
            user += " Без пошлости, даже если на экране 18+ — скажи мягко и смени тему."

        msg = self._vision_react_threadsafe(path, user)
        if not msg:
            return
        try:
            from screen_watch import strip_vision_meta
            msg = strip_vision_meta(msg)
        except Exception:
            import re as _re
            msg = _re.sub(r"\[SCENE:[^\]]*\]", "", msg)
        scene, scene_anim = extract_scene(msg)
        tag_anim = extract_anim(msg)
        text_anim = infer_anim_from_text(msg)
        anim = tag_anim or text_anim or scene_anim or "idle"
        if anim == "thinking" and text_anim and text_anim != "thinking":
            anim = text_anim
        if not re.search(r"\[ANIM:", msg, re.I):
            msg = f"[ANIM:{anim}] {msg}"
        else:
            msg = re.sub(r"\[ANIM:\s*\w+\]", f"[ANIM:{anim}]", msg, count=1, flags=re.I)
        self._last_screen_anim = anim
        print(f"👁 scene={scene} anim={anim} (tag={tag_anim} text={text_anim} scene_map={scene_anim})")
        self._deliver_greeting(msg)

    def _vision_model(self) -> str:
        name = (getattr(config, "SCREEN_VISION_MODEL", "") or "").strip()
        if name:
            return name
        main = (getattr(config, "MODEL_NAME", "") or "").strip()
        return main or "local"

    def _vision_react_threadsafe(self, jpeg_path: str, user_text: str) -> Optional[str]:
        try:
            from screen_watch import user_content_with_image, VISION_ADDON
        except Exception as e:
            print(f"👁 нет screen_watch: {e}")
            return None

        async def _run() -> Optional[str]:
            import aiohttp
            api_url = (getattr(config, "API_URL", "") or "").rstrip("/")
            api_key = getattr(config, "API_KEY", "not-needed") or "not-needed"
            model = self._vision_model()
            print(f"👁 VL модель: {model}")
            if not api_url:
                return None
            try:
                from character_manager import vision_system_prompt
                vis = vision_system_prompt(VISION_ADDON)
            except Exception:
                vis = "Смотришь на скриншот. Ответ 1–3 коротких предложения."
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": vis,
                    },
                    {"role": "user", "content": user_content_with_image(user_text, jpeg_path)},
                ],
                "temperature": 0.7,
                "max_tokens": 180,
                "stream": False,
            }
            timeout = aiohttp.ClientTimeout(total=90, sock_connect=20, sock_read=70)
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{api_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                    timeout=timeout,
                ) as resp:
                    if resp.status != 200:
                        txt = await resp.text()
                        print(f"👁 HTTP {resp.status}: {txt[:200]}")
                        return None
                    data = await resp.json()
                    return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

        try:
            text = asyncio.run(_run())
        except Exception as e:
            print(f"👁 peek fail: {e}")
            logger.error("vision peek: %s", e)
            return None
        if not text or len(text.strip()) < 3:
            print("👁 пустой ответ VL")
            return None
        return text.strip()

    def _llm_circuit_ok(self) -> bool:
        return time.time() >= float(getattr(self, "_llm_circuit_open_until", 0) or 0)

    def _llm_circuit_trip(self, reason: str = ""):
        self._llm_fail_count = int(getattr(self, "_llm_fail_count", 0) or 0) + 1
        thr = int(getattr(self, "_llm_fail_threshold", 3) or 3)
        if self._llm_fail_count >= thr:
            cool = float(getattr(self, "_llm_circuit_cooldown", 120) or 120)
            self._llm_circuit_open_until = time.time() + cool
            self._llm_fail_count = 0
            logger.warning(f"LLM circuit OPEN {cool:.0f}s ({reason})")


    def _llm_post_sync(self, messages, max_tokens=60, temperature=0.9, timeout=45.0, model=None):
        """Прямой HTTP, без GUI-loop. Иначе привет всегда падает в шаблон."""
        import json
        import urllib.request
        api_url = (getattr(config, "API_URL", "") or "").rstrip("/")
        api_key = getattr(config, "API_KEY", "not-needed") or "not-needed"
        model = model or (getattr(config, "MODEL_NAME", "") or "local")
        if not api_url:
            print("💬 LLM greeting: нет API_URL")
            return None
        payload = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{api_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=float(timeout)) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            msg = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            return str(msg).strip() or None
        except Exception as e:
            print(f"💬 LLM greeting HTTP: {e}")
            return None

    def _send_greeting(self, mood: int):
        """
        Генерирует и отправляет авто-сообщение.
        Вызывается из фонового потока.
        """
        use_llm = getattr(config, 'GREETING_USE_LLM', True)
        msg = None
        
        # Пробуем LLM только если circuit closed
        if use_llm and self._assistant and self._llm_circuit_ok():
            print("💬 автосообщение через ИИ…")
            msg = self._generate_greeting_with_llm_threadsafe(mood)
            if not msg:
                print("💬 ИИ не ответил — будет шаблон")
        elif use_llm and not self._llm_circuit_ok():
            print("💬 ИИ временно отключён (ошибки подряд) — шаблон")
            if msg:
                self._llm_generated_count += 1
                self._llm_fail_count = 0
                logger.debug(f"Сгенерировано через LLM (mood={mood}): {msg[:50]}...")
        
        # Если LLM не сработал, пробуем кэш
        if not msg:
            cached = self._get_cached_greeting()
            if cached:
                msg = cached
                logger.debug(f"Использован кэш: {cached[:50]}...")
        
        # Если ничего нет — используем шаблоны
        if not msg:
            msg = self._get_greeting_message(mood)
            logger.debug(f"Использован шаблон (mood={mood}): {msg[:50]}...")
        
        # Отправляем сообщение
        if msg:
            self._deliver_greeting(msg)
        else:
            logger.warning("Не удалось сгенерировать авто-сообщение")
    
    def _generate_greeting_with_llm_threadsafe(self, mood: int) -> Optional[str]:
        """
        Лёгкий completion БЕЗ send_message_async:
        не пишет историю, не парсит команды, не трогает executor.
        """
        timeout = float(getattr(config, "GREETING_LLM_TIMEOUT", 45.0) or 45.0)

        snap = self._greeting_context(mood)
        period = snap["period"]
        um = snap["user_mood"]
        sm = snap["self_mood"]
        if mood >= 2:
            tone, anim = "коротко, задето молчанием, без эссе", "pouting"
        elif period in ("night", "evening"):
            tone, anim = "тихо, ночь, без бодрости", "sleepy"
        elif um in ("sad", "angry", "tired"):
            tone, anim = "спокойно, без шуток про настроение", "sad"
        elif mood == 1:
            tone, anim = "легко, коротко", "playful"
        else:
            tone, anim = "спокойно, скучает одним предложением", "idle"

        try:
            from character_manager import greeting_system_prompt
            system = greeting_system_prompt()
        except Exception:
            system = (
                "Пиши одно короткое сообщение (15–30 слов) в характере персонажа. "
                "Без тегов команд, без [ANIM], без кавычек, без списков."
            )
        user = (
            f"Тон: {tone}. "
            f"Время: {period or 'день'}. "
            f"Настроение пользователя: {um or 'неизвестно'}. "
            f"Твоё настроение: {sm or 'neutral'}. "
            f"Пользователь молчит — одна короткая реплика в своём характере."
        )
        try:
            from time_context import get_greeting_hint, format_clock
            if getattr(config, "TIME_AWARE_IN_GREETINGS", True):
                user = user + f" Часы: {format_clock()}. {get_greeting_hint()}"
        except Exception:
            pass

        async def _lite_completion() -> Optional[str]:
            import aiohttp
            api_url = (getattr(config, "API_URL", "") or "").rstrip("/")
            api_key = getattr(config, "API_KEY", "not-needed") or "not-needed"
            model = getattr(config, "MODEL_NAME", "") or "local"
            if not api_url:
                return None
            max_tokens = int(getattr(config, "GREETING_MAX_TOKENS", 60) or 60)
            temp = float(getattr(config, "GREETING_TEMPERATURE", 0.9) or 0.9)
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temp,
                "max_tokens": max_tokens,
                "stream": False,
            }
            timeout = aiohttp.ClientTimeout(total=min(
                float(getattr(config, "GREETING_LLM_TIMEOUT", 8.0) or 8.0), 12.0
            ))
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{api_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                    timeout=timeout,
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(f"API {resp.status}: {body[:120]}")
                    data = await resp.json()
                    choices = data.get("choices") or []
                    if not choices:
                        return None
                    msg = (choices[0].get("message") or {}).get("content") or ""
                    return str(msg).strip()

        try:
            response = self._llm_post_sync(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=int(getattr(config, "GREETING_MAX_TOKENS", 60) or 60),
                temperature=float(getattr(config, "GREETING_TEMPERATURE", 0.9) or 0.9),
                timeout=timeout,
            )
            if not response and self._loop and not self._loop.is_closed():
                future = asyncio.run_coroutine_threadsafe(_lite_completion(), self._loop)
                response = future.result(timeout=timeout)
            if not response:
                return None
            response = re.sub(r"\[ANIM:\w+\]", "", response, flags=re.I)
            response = re.sub(r"\[[A-Z_][^\]]*\]", "", response)
            response = re.sub(r"[<>]", "", response).strip()
            response = re.sub(r'^[\s"«»]+|[\s"«»]+$', "", response)
            if response and len(response) > 5:
                self._cache_greeting(response)
                return f"[ANIM:{anim}] {response}"
            logger.warning(f"LLM greeting слишком короткий: {response!r}")
            return None
        except asyncio.TimeoutError:
            logger.warning("Таймаут LLM greeting")
            self._llm_circuit_trip("timeout")
        except asyncio.CancelledError:
            logger.debug("LLM greeting отменён")
        except RuntimeError as e:
            if "closed" in str(e).lower():
                logger.debug("Event loop закрыт")
            else:
                logger.error(f"LLM greeting RuntimeError: {e}")
                self._llm_circuit_trip(str(e)[:80])
        except Exception as e:
            logger.error(f"LLM greeting ошибка: {e}", exc_info=True)
            self._llm_circuit_trip(str(e)[:80])
        return None


    def _cache_greeting(self, message: str):
        """Кэширует успешно сгенерированное сообщение."""
        if len(self._greeting_cache) >= self._max_cache_size:
            self._greeting_cache.pop(0)
        self._greeting_cache.append(message)
        logger.debug(f"Кэш обновлён (размер: {len(self._greeting_cache)})")
    
    def _get_cached_greeting(self) -> Optional[str]:
        """Возвращает случайное сообщение из кэша."""
        if self._greeting_cache:
            return random.choice(self._greeting_cache)
        return None
    
    def _greeting_context(self, mood: int = 0) -> dict:
        try:
            from scene_state import get_scene_state
            snap = get_scene_state(getattr(self, "_assistant", None))
            if mood >= 2 and snap.get("self_mood") in ("neutral", "idle", ""):
                snap["self_mood"] = "pouting"
            return snap
        except Exception:
            return {"period": "day", "user_mood": "neutral", "self_mood": "idle", "character": ""}

    def _get_greeting_message(self, mood: int) -> str:
        snap = self._greeting_context(mood)
        try:
            from character_manager import greeting_templates
            templates = greeting_templates(
                mood,
                time_period=snap["period"],
                user_mood=snap["user_mood"],
                self_mood=snap["self_mood"],
            )
        except Exception:
            templates = ["[ANIM:idle] Ты ещё там?"]
        return random.choice(templates) if templates else "[ANIM:idle] …"
    
    def _deliver_greeting(self, message: str):
        """
        Доставляет сообщение в GUI.
        Вызывается из фонового потока.
        """
        if not self.executor:
            logger.warning("Нет executor для доставки сообщения")
            return
        
        # Получаем callback из reminder_manager
        if hasattr(self.executor, 'reminder_manager'):
            callback = getattr(self.executor.reminder_manager, 'callback', None)
            if callback:
                try:
                    # Вызываем callback (потокобезопасно через Qt сигналы)
                    anim = "idle"
                    try:
                        ast = getattr(self, "_assistant", None)
                        sel = getattr(ast, "anim_selector", None) if ast else None
                        if sel:
                            anim = sel.select(text=message, user_text=message) or "idle"
                    except Exception:
                        anim = "idle"
                    if anim and "[ANIM:" not in (message or ""):
                        message = f"[ANIM:{anim}]\n{message}"
                    callback(message)
                    logger.info(f"✅ Авто-сообщение доставлено [{anim}]: {message[:50]}...")
                except Exception as e:
                    logger.error(f"Ошибка доставки авто-сообщения: {e}")
            else:
                logger.warning(f"Нет callback для доставки, сообщение: {message[:50]}...")
        else:
            logger.warning(f"Нет reminder_manager, сообщение: {message[:50]}...")