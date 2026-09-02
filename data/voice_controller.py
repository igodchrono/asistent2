# voice_controller.py
# TTS: edge-tts | silero (офлайн) | pyttsx3 | openai | custom HTTP API
# Silero: xenia / kseniya / baya — русские женские, полностью офлайн после 1-й загрузки
import asyncio
import tempfile
import os
import time
import re
import json
import threading
from typing import Optional, Callable, Dict, List

import pygame
import speech_recognition as sr

from utils import voice_semaphore, task_pool, logger
import config

try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False
    logger.warning("edge-tts не установлен")


class VoiceController:
    """
    Асинхронный контроллер голоса.
    STT: vosk | google
    TTS: edge-tts | silero | pyttsx3 | openai | custom
    """

    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.microphone = None

        # устройства и vosk — ДО _setup_microphone
        self._input_device = getattr(config, "VOICE_INPUT_DEVICE", None)
        self._output_device = getattr(config, "VOICE_OUTPUT_DEVICE", None)
        self.vosk_model_path = getattr(config, "VOSK_MODEL_PATH", None)
        self._vosk_model = None

        self._setup_microphone()

        self.voice = getattr(config, "VOICE_NAME", "ru-RU-SvetlanaNeural")
        self.rate = getattr(config, "VOICE_SPEED", 0)
        self.volume = float(getattr(config, "VOICE_VOLUME", 1.0))
        self.language = getattr(config, "VOICE_LANGUAGE", "ru-RU")

        self._tts_stop = asyncio.Event()
        self._tts_paused = False
        self.is_listening = False
        self.is_recording = False
        self.callback: Optional[Callable] = None
        self._listener_task: Optional[asyncio.Task] = None
        self.avatar_window = None

        try:
            pygame.mixer.init()
        except Exception as e:
            logger.warning(f"Ошибка pygame: {e}")
        try:
            self._apply_output_device()
        except Exception:
            pass

        # Silero TTS (ленивая загрузка)
        self._silero_model = None
        self._silero_sample_rate = int(getattr(config, "SILERO_SAMPLE_RATE", 48000) or 48000)
        self._silero_speaker = (
            getattr(config, "SILERO_SPEAKER", None)
            or getattr(config, "VOICE_NAME", "xenia")
            or "xenia"
        )
        self._silero_lock = threading.Lock()
        self._silero_loading = False
        self._silero_load_error = None

        eng = (getattr(config, "VOICE_SYNTHESIS_ENGINE", "") or "").lower()
        if eng in ("silero", "silero-tts", "silero_tts"):
            self.preload_silero_async()

        logger.info(
            f"VoiceController инициализирован "
            f"(TTS={getattr(config, 'VOICE_SYNTHESIS_ENGINE', 'edge-tts')}, "
            f"STT={getattr(config, 'VOICE_RECOGNITION_ENGINE', 'vosk')}, "
            f"mode={getattr(config, 'VOICE_INPUT_MODE', 'push')}, "
            f"mic={self._input_device})"
        )

    def apply_settings(self):
        """Перечитать настройки из config (после сохранения в GUI)."""
        self.voice = getattr(config, "VOICE_NAME", self.voice)
        self.rate = getattr(config, "VOICE_SPEED", self.rate)
        self.volume = float(getattr(config, "VOICE_VOLUME", self.volume))
        self.language = getattr(config, "VOICE_LANGUAGE", self.language)
        self._silero_speaker = (
            getattr(config, "SILERO_SPEAKER", None) or self.voice or "xenia"
        )
        self._silero_sample_rate = int(
            getattr(config, "SILERO_SAMPLE_RATE", self._silero_sample_rate) or 48000
        )
        self.vosk_model_path = getattr(config, "VOSK_MODEL_PATH", self.vosk_model_path)

        new_in = getattr(config, "VOICE_INPUT_DEVICE", None)
        new_out = getattr(config, "VOICE_OUTPUT_DEVICE", None)
        if new_in != self._input_device:
            self._input_device = new_in
            self._setup_microphone()
        self._output_device = new_out
        self._apply_output_device()

        logger.info(
            f"Voice settings applied: engine={getattr(config, 'VOICE_SYNTHESIS_ENGINE', '?')}, "
            f"mode={getattr(config, 'VOICE_INPUT_MODE', 'push')}, "
            f"wake={getattr(config, 'WAKE_WORD', '')!r}, "
            f"mic={self._input_device}, out={self._output_device}, "
            f"voice={self.voice}, rate={self.rate}"
        )

    def set_avatar_window(self, avatar_window):
        self.avatar_window = avatar_window
        logger.info("Avatar window установлен")

    def _setup_microphone(self):
        try:
            device_index = getattr(self, "_input_device", None)
            if device_index is None:
                device_index = getattr(config, "VOICE_INPUT_DEVICE", None)
            # settings.json может хранить строку
            if device_index is not None and device_index != "":
                try:
                    device_index = int(device_index)
                except (TypeError, ValueError):
                    device_index = None
            if device_index is not None:
                self.microphone = sr.Microphone(device_index=device_index)
                logger.info(f"Микрофон: device_index={device_index}")
            else:
                self.microphone = sr.Microphone()
                logger.info("Микрофон: системный по умолчанию")

            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.8)
                logger.info("Микрофон настроен (noise adjust)")
        except Exception as e:
            logger.error(f"Ошибка микрофона: {e}", exc_info=True)
            self.microphone = None

    def _apply_output_device(self):
        """Попытка выбрать устройство вывода для pygame (Windows часто ограничен)."""
        try:
            idx = self._output_device
            if idx is None or idx == "":
                return
            idx = int(idx)
            # pygame 2: quit + init with device
            if pygame.mixer.get_init():
                pygame.mixer.quit()
            # devicename через SDL — не всегда работает; пробуем
            pygame.mixer.init()
            logger.info(f"Output device hint={idx} (pygame использует default, если недоступно)")
        except Exception as e:
            logger.debug(f"output device: {e}")
            try:
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
            except Exception:
                pass

    @staticmethod
    def list_input_devices():
        """Список микрофонов [{index, name}, ...]."""
        try:
            names = sr.Microphone.list_microphone_names() or []
            return [{"index": i, "name": n} for i, n in enumerate(names)]
        except Exception as e:
            logger.error(f"list_input_devices: {e}")
            return []

    @staticmethod
    def list_output_devices():
        """Список устройств вывода (через pyaudio, если есть)."""
        devices = [{"index": None, "name": "(системный по умолчанию)"}]
        try:
            import pyaudio
            pa = pyaudio.PyAudio()
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if int(info.get("maxOutputChannels") or 0) > 0:
                    devices.append({
                        "index": i,
                        "name": info.get("name") or f"Device {i}",
                    })
            pa.terminate()
        except Exception as e:
            logger.debug(f"list_output_devices: {e}")
        return devices

    def set_callback(self, callback: Callable[[str], None]):
        self.callback = callback

    # ===== РАСПОЗНАВАНИЕ (STT) =====

    async def listen_async(
        self, timeout: int = 5, phrase_time_limit: int = 10
    ) -> Optional[str]:
        if not self.microphone:
            logger.warning("Микрофон не настроен")
            return None

        loop = asyncio.get_running_loop()
        self.is_recording = True
        try:
            text = await loop.run_in_executor(
                None, self._listen_sync, timeout, phrase_time_limit
            )
            return text
        finally:
            self.is_recording = False

    def _listen_sync(self, timeout: int, phrase_time_limit: int) -> Optional[str]:
        try:
            with self.microphone as source:
                logger.info("Слушаю...")
                audio = self.recognizer.listen(
                    source, timeout=timeout, phrase_time_limit=phrase_time_limit
                )
                logger.info("Обработка...")

                engine = getattr(config, "VOICE_RECOGNITION_ENGINE", "vosk")

                if engine == "google":
                    api_key = getattr(config, "GOOGLE_SPEECH_API_KEY", "") or ""
                    if api_key:
                        try:
                            text = self.recognizer.recognize_google_cloud(
                                audio,
                                credentials_json=api_key,
                                language=self.language,
                            )
                        except Exception as e:
                            logger.warning(f"Google Cloud ошибка: {e}")
                            text = self.recognizer.recognize_google(
                                audio, language=self.language
                            )
                    else:
                        text = self.recognizer.recognize_google(
                            audio, language=self.language
                        )

                elif engine == "vosk":
                    try:
                        import vosk

                        if not self.vosk_model_path or not os.path.exists(
                            self.vosk_model_path
                        ):
                            logger.warning("Vosk модель не найдена, использую Google")
                            text = self.recognizer.recognize_google(
                                audio, language=self.language
                            )
                        else:
                            if self._vosk_model is None:
                                self._vosk_model = vosk.Model(self.vosk_model_path)
                                logger.info("Vosk model loaded (cached)")
                            rec = vosk.KaldiRecognizer(self._vosk_model, 16000)
                            rec.AcceptWaveform(audio.get_wav_data())
                            result = json.loads(rec.FinalResult())
                            text = result.get("text", "")
                            if not text:
                                text = self.recognizer.recognize_google(
                                    audio, language=self.language
                                )
                    except ImportError:
                        logger.warning("Vosk не установлен")
                        text = self.recognizer.recognize_google(
                            audio, language=self.language
                        )
                    except Exception as e:
                        logger.error(f"Vosk ошибка: {e}")
                        text = self.recognizer.recognize_google(
                            audio, language=self.language
                        )
                else:
                    text = self.recognizer.recognize_google(
                        audio, language=self.language
                    )

                logger.info(f"Распознано: {text}")
                return text

        except sr.WaitTimeoutError:
            logger.debug("Таймаут")
            return None
        except sr.UnknownValueError:
            logger.debug("Не распознано")
            return None
        except Exception as e:
            logger.error(f"Ошибка распознавания: {e}")
            return None

    def _normalize_wake(self, s: str) -> str:
        s = (s or "").lower().strip()
        # упрощение: ё→е, лишние пробелы
        s = s.replace("ё", "е")
        s = re.sub(r"[^a-zа-я0-9\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _extract_after_wake(self, text: str) -> Optional[str]:
        """
        Режим wake: ждать кодовое слово, вернуть команду после него.
        Если в той же фразе только wake — вернуть пустую строку (слушать следующую).
        Если wake нет — None (игнор).
        """
        mode = (getattr(config, "VOICE_INPUT_MODE", "push") or "push").lower()
        if mode not in ("wake", "always", "hotword", "keyword"):
            return text  # push / continuous without wake: вся фраза

        wake = self._normalize_wake(
            getattr(config, "WAKE_WORD", None) or "лисичка"
        )
        if not wake:
            return text

        norm = self._normalize_wake(text)
        if wake not in norm:
            logger.debug(f"Wake: пропуск (нет «{wake}»): {text[:60]}")
            return None

        # всё после первого вхождения wake
        idx = norm.find(wake)
        after = norm[idx + len(wake):].strip()
        # убрать ведущие «,»/«пожалуйста»
        after = re.sub(r"^(пожалуйста|плиз|hey|,|\.|:)+\s*", "", after)
        if not after:
            logger.info(f"Wake «{wake}» — жду команду...")
            return ""  # активированы, ждём следующую фразу
        logger.info(f"Wake «{wake}» → команда: {after[:80]}")
        return after

    async def listen_continuous_async(self, callback: Optional[Callable] = None):
        """
        Непрерывное прослушивание.
        VOICE_INPUT_MODE=wake → реагирует только после кодового слова.
        """
        self.is_listening = True
        self.callback = callback or self.callback
        armed = False  # после wake без команды — следующая фраза целиком

        mode = (getattr(config, "VOICE_INPUT_MODE", "push") or "push").lower()
        wake = getattr(config, "WAKE_WORD", "лисичка")
        logger.info(
            f"Continuous listen: mode={mode}, wake={wake!r}"
        )

        while self.is_listening:
            # не слушать собственный TTS (эхо → ложные wake)
            try:
                if self.is_speaking():
                    await asyncio.sleep(0.35)
                    continue
            except Exception:
                pass
            if not self.microphone:
                logger.warning("Continuous listen: микрофон недоступен")
                await asyncio.sleep(2.0)
                continue
            text = await self.listen_async(timeout=5, phrase_time_limit=12)
            if not text:
                await asyncio.sleep(0.15)
                continue

            if armed:
                payload = text.strip()
                armed = False
            else:
                payload = self._extract_after_wake(text)
                if payload is None:
                    await asyncio.sleep(0.1)
                    continue
                if payload == "":
                    armed = True
                    await asyncio.sleep(0.1)
                    continue

            if payload and self.callback:
                try:
                    if asyncio.iscoroutinefunction(self.callback):
                        await self.callback(payload)
                    else:
                        self.callback(payload)
                except Exception as e:
                    logger.error(f"Ошибка колбэка: {e}")
            await asyncio.sleep(0.2)

    async def start_listening_async(self, callback: Optional[Callable] = None):
        if self._listener_task and not self._listener_task.done():
            logger.warning("Прослушивание уже запущено")
            return

        self._listener_task = asyncio.create_task(
            self.listen_continuous_async(callback)
        )
        logger.info("Непрерывное прослушивание запущено")

    async def stop_listening_async(self):
        self.is_listening = False
        self.is_recording = False

        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

        self._listener_task = None
        logger.info("Прослушивание остановлено")

    # ===== СИНТЕЗ РЕЧИ (TTS) =====

    def _get_tts_engine(self) -> str:
        return (getattr(config, "VOICE_SYNTHESIS_ENGINE", "edge-tts") or "edge-tts").lower()

    async def speak_async(self, text: str):
        if not getattr(config, "ENABLE_VOICE_OUTPUT", False):
            return
        if not text or not text.strip():
            return

        clean_text = self._clean_text_for_tts(text)
        if not clean_text:
            return

        await self.stop_speaking_async()
        self._tts_stop.clear()
        asyncio.create_task(self._speak_internal_async(clean_text))

    async def _speak_internal_async(self, text: str):
        engine = self._get_tts_engine()
        temp_path = None

        try:
            async with voice_semaphore:
                if engine == "pyttsx3":
                    await self._speak_pyttsx3_async(text)
                    return

                # silero / edge / openai / custom → файл → pygame
                suffix = ".wav" if engine in ("silero", "silero-tts") else ".mp3"
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=suffix
                ) as tmp_file:
                    temp_path = tmp_file.name

                ok = False
                if engine in ("silero", "silero-tts"):
                    ok = await self._generate_silero_tts(text, temp_path)
                elif engine == "edge-tts":
                    ok = await self._generate_edge_tts(text, temp_path)
                elif engine in ("openai", "custom"):
                    ok = await self._generate_openai_compatible_tts(text, temp_path)
                else:
                    # неизвестный — silero, затем edge, затем pyttsx3
                    ok = await self._generate_silero_tts(text, temp_path)
                    if not ok:
                        ok = await self._generate_edge_tts(text, temp_path)

                if self._tts_stop.is_set():
                    return

                if ok and temp_path and os.path.exists(temp_path):
                    await self._play_audio_async(temp_path)
                else:
                    logger.warning(f"TTS {engine} не удался → fallback pyttsx3")
                    await self._speak_pyttsx3_async(text)

        except asyncio.CancelledError:
            logger.debug("Синтез отменён")
        except Exception as e:
            if not self._tts_stop.is_set():
                logger.error(f"Ошибка синтеза ({engine}): {e}", exc_info=True)
                await self._speak_pyttsx3_async(text)
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass


    # ----- Silero TTS (офлайн) -----

    _SILERO_SPEAKERS = frozenset({
        "xenia", "kseniya", "baya", "aidar", "eugene",
    })

    def _resolve_silero_speaker(self) -> str:
        raw = (self._silero_speaker or self.voice or "xenia").strip().lower()
        # VOICE_NAME мог быть edge-именем — маппим на silero
        if raw not in self._SILERO_SPEAKERS:
            if "kseni" in raw:
                return "kseniya"
            if "baya" in raw:
                return "baya"
            if "aidar" in raw or "male" in raw or "dmitry" in raw:
                return "aidar"
            # по умолчанию молодая женская
            return "xenia"
        return raw

    def preload_silero_async(self) -> None:
        """Фоновая загрузка Silero — GUI не блокируется."""
        if getattr(self, "_silero_model", None) is not None:
            return
        if getattr(self, "_silero_loading", False):
            return
        self._silero_loading = True

        def _job():
            try:
                self._ensure_silero_model()
                logger.info("Silero: фоновая предзагрузка завершена")
            except Exception as e:
                self._silero_load_error = str(e)
                logger.error(f"Silero preload: {e}")
            finally:
                self._silero_loading = False

        threading.Thread(target=_job, name="silero-preload", daemon=True).start()

    def _ensure_silero_model(self):

        """Ленивая загрузка. Первый раз может скачать модель (нужен интернет один раз)."""
        if self._silero_model is not None:
            return self._silero_model
        with self._silero_lock:
            if self._silero_model is not None:
                return self._silero_model
            try:
                import torch
            except ImportError as e:
                raise RuntimeError("Нужен torch: pip install torch") from e

            logger.info("Silero TTS: загрузка модели (первый раз может занять время)...")
            device = torch.device("cpu")
            # v3_1_ru — актуальная русская мультиспикер
            model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-models",
                model="silero_tts",
                language="ru",
                speaker="v3_1_ru",
                trust_repo=True,
            )
            model.to(device)
            self._silero_model = model
            logger.info("Silero TTS: модель готова (офлайн)")
            return model

    def _generate_silero_sync(self, text: str, output_path: str) -> bool:
        try:
            import torch
            import numpy as np
            import wave

            model = self._ensure_silero_model()
            speaker = self._resolve_silero_speaker()
            sample_rate = int(self._silero_sample_rate or 48000)
            if sample_rate not in (8000, 24000, 48000):
                sample_rate = 48000

            # put_accent/put_yo улучшают русское произношение
            audio = model.apply_tts(
                text=text,
                speaker=speaker,
                sample_rate=sample_rate,
                put_accent=True,
                put_yo=True,
            )

            if audio is None:
                return False

            if hasattr(audio, "detach"):
                audio_np = audio.detach().cpu().numpy()
            else:
                audio_np = np.asarray(audio, dtype=np.float32)
            audio_np = np.asarray(audio_np, dtype=np.float32).reshape(-1)

            # лёгкая коррекция «скорости» через простой resampling (грубо)
            # rate −50..+50 → растяжение/сжатие
            if self.rate and abs(self.rate) >= 5:
                factor = 1.0 - (self.rate / 200.0)  # +20 → чуть быстрее
                factor = max(0.7, min(1.3, factor))
                n = max(1, int(len(audio_np) * factor))
                x_old = np.linspace(0.0, 1.0, len(audio_np))
                x_new = np.linspace(0.0, 1.0, n)
                audio_np = np.interp(x_new, x_old, audio_np).astype(np.float32)

            audio_np = np.clip(audio_np, -1.0, 1.0)
            pcm = (audio_np * 32767.0).astype(np.int16)

            with wave.open(output_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm.tobytes())

            return os.path.exists(output_path) and os.path.getsize(output_path) > 100
        except Exception as e:
            msg = str(e)
            if "omegaconf" in msg.lower():
                logger.error("Silero: установи omegaconf → pip install omegaconf")
            else:
                logger.error(f"Silero TTS ошибка: {e}", exc_info=True)
            return False

    async def _generate_silero_tts(self, text: str, output_path: str) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._generate_silero_sync, text, output_path
        )

    async def _generate_edge_tts(self, text: str, output_path: str) -> bool:
        if not HAS_EDGE_TTS:
            logger.warning("edge-tts не установлен")
            return False
        try:
            rate_str = f"+{self.rate}%" if self.rate >= 0 else f"{self.rate}%"
            communicate = edge_tts.Communicate(text, self.voice, rate=rate_str)
            await communicate.save(output_path)
            return True
        except Exception as e:
            logger.warning(f"edge-tts ошибка: {e}")
            try:
                communicate = edge_tts.Communicate(text, self.voice)
                await communicate.save(output_path)
                return True
            except Exception as e2:
                logger.error(f"edge-tts повторная ошибка: {e2}")
                return False

    async def _generate_openai_compatible_tts(
        self, text: str, output_path: str
    ) -> bool:
        """
        OpenAI-совместимый endpoint:
          POST {VOICE_TTS_API_URL}/audio/speech
          body: { "model": "...", "input": "...", "voice": "..." }
          response: audio bytes (mp3/wav)
        Работает и для openai.com, и для локальных/прокси (LM Studio, LocalAI и т.п.).
        """
        import aiohttp

        base = (getattr(config, "VOICE_TTS_API_URL", "") or "").rstrip("/")
        api_key = getattr(config, "VOICE_TTS_API_KEY", "") or ""
        model = getattr(config, "VOICE_TTS_MODEL", "tts-1") or "tts-1"
        voice = self.voice or "alloy"

        if not base:
            logger.error("VOICE_TTS_API_URL не задан")
            return False

        url = f"{base}/audio/speech"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # speed: edge rate −50..+50 → openai 0.25..4.0
        speed = 1.0 + (self.rate / 100.0)
        speed = max(0.25, min(4.0, speed))

        payload = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": "mp3",
            "speed": speed,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"TTS API {resp.status}: {body[:300]}")
                        return False
                    data = await resp.read()
                    if not data or len(data) < 100:
                        logger.error("TTS API вернул пустой ответ")
                        return False
                    with open(output_path, "wb") as f:
                        f.write(data)
                    return True
        except Exception as e:
            logger.error(f"TTS API ошибка: {e}", exc_info=True)
            return False

    async def _speak_pyttsx3_async(self, text: str):
        """Локальный синтез через pyttsx3 (Windows SAPI / espeak)."""
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._speak_pyttsx3_sync, text)
        except Exception as e:
            logger.error(f"pyttsx3 async ошибка: {e}")

    def _speak_pyttsx3_sync(self, text: str):
        try:
            import pyttsx3

            engine = pyttsx3.init()
            # Скорость: pyttsx3 rate ~150 = норма, наш rate −50..+50
            try:
                base_rate = engine.getProperty("rate") or 150
                engine.setProperty("rate", int(base_rate + self.rate))
            except Exception:
                pass
            try:
                engine.setProperty("volume", max(0.0, min(1.0, self.volume)))
            except Exception:
                pass

            # Попытка выбрать голос по имени/языку
            if self.voice:
                try:
                    for v in engine.getProperty("voices") or []:
                        vid = (getattr(v, "id", "") or "").lower()
                        vname = (getattr(v, "name", "") or "").lower()
                        if (
                            self.voice.lower() in vid
                            or self.voice.lower() in vname
                            or "russian" in vname
                            or "ru" in vid
                        ):
                            engine.setProperty("voice", v.id)
                            break
                except Exception:
                    pass

            engine.say(text)
            engine.runAndWait()
            try:
                engine.stop()
            except Exception:
                pass
        except ImportError:
            logger.error("pyttsx3 не установлен: pip install pyttsx3")
        except Exception as e:
            logger.error(f"pyttsx3 ошибка: {e}")

    async def _play_audio_async(self, file_path: str):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._play_audio_sync, file_path)

    def _play_audio_sync(self, file_path: str):
        try:
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.set_volume(self.volume)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy():
                if self._tts_stop.is_set():
                    pygame.mixer.music.stop()
                    break
                time.sleep(0.08)
        except Exception as e:
            logger.error(f"Ошибка воспроизведения: {e}")

    async def stop_speaking_async(self):
        self._tts_stop.set()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._stop_audio_sync)

    def _stop_audio_sync(self):
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass

    async def toggle_pause_async(self) -> str:
        if self._tts_paused:
            await self.resume_async()
            return "resume"

        try:
            if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                pygame.mixer.music.pause()
                self._tts_paused = True
                return "pause"
        except Exception:
            pass
        return "idle"

    async def resume_async(self):
        try:
            if pygame.mixer.get_init() and self._tts_paused:
                pygame.mixer.music.unpause()
                self._tts_paused = False
        except Exception:
            pass

    def is_speaking(self) -> bool:
        try:
            return bool(pygame.mixer.get_init() and pygame.mixer.music.get_busy())
        except Exception:
            return False

    # ===== СИНХРОННЫЕ ОБЁРТКИ =====

    def speak(self, text: str):
        if not text or not text.strip():
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.speak_async(text))
            else:
                asyncio.run(self.speak_async(text))
        except Exception:
            asyncio.create_task(self.speak_async(text))

    def stop_speaking(self):
        self._tts_stop.set()
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass

    def listen_once(self) -> Optional[str]:
        return self._listen_sync(timeout=5, phrase_time_limit=10)

    def is_recording_now(self) -> bool:
        return self.is_recording

    def get_microphones(self) -> List[Dict]:
        try:
            devices = []
            for i, name in enumerate(sr.Microphone.list_microphone_names()):
                devices.append({"index": i, "name": name})
            return devices
        except Exception as e:
            logger.error(f"Ошибка сканирования микрофонов: {e}")
            return []

    def set_voice_params(
        self,
        voice: Optional[str] = None,
        rate: Optional[int] = None,
        volume: Optional[float] = None,
    ):
        if voice:
            self.voice = voice
        if rate is not None:
            self.rate = rate
        if volume is not None:
            self.volume = max(0.0, min(1.0, volume))

    async def test_microphone_async(self) -> bool:
        text = await self.listen_async(timeout=3, phrase_time_limit=5)
        return text is not None

    async def test_speaker_async(
        self, text: str = "Привет! Я твоя виртуальная лисичка!"
    ):
        # Временно включить вывод для теста
        old = getattr(config, "ENABLE_VOICE_OUTPUT", False)
        config.ENABLE_VOICE_OUTPUT = True
        try:
            await self.speak_async(text)
            # Дать время начать воспроизведение
            await asyncio.sleep(0.5)
        finally:
            config.ENABLE_VOICE_OUTPUT = old

    def test_microphone(self) -> bool:
        text = self._listen_sync(timeout=3, phrase_time_limit=5)
        return text is not None

    def test_speaker(self, text: str = "Привет! Я твоя виртуальная лисичка!"):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.test_speaker_async(text))
            else:
                asyncio.run(self.test_speaker_async(text))
        except Exception as e:
            logger.error(f"test_speaker: {e}")
            # sync fallback
            self._speak_pyttsx3_sync(text)
        return True

    def _clean_text_for_tts(self, text: str) -> Optional[str]:
        if not text:
            return None

        text = re.sub(r"\[ANIM:\w+\]", "", text)
        text = re.sub(r"\[.*?\]", "", text)

        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"
            "\U0001F300-\U0001F5FF"
            "\U0001F680-\U0001F6FF"
            "\U0001F700-\U0001F77F"
            "\U0001F780-\U0001F7FF"
            "\U0001F800-\U0001F8FF"
            "\U0001F900-\U0001F9FF"
            "\U0001FA00-\U0001FA6F"
            "\U0001FA70-\U0001FAFF"
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "]+",
            flags=re.UNICODE,
        )
        text = emoji_pattern.sub("", text)
        text = re.sub(r"[^\w\s.,!?\-—:;]", "", text)
        text = re.sub(r"\s+", " ", text).strip()

        return text if len(text) > 2 else None

    def close(self):
        self.is_listening = False
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
                pygame.mixer.quit()
        except Exception:
            pass
        logger.info("VoiceController закрыт")
