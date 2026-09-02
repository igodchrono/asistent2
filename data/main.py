# main.py — с health-check при старте
# Замените свой main.py этим файлом (или вставьте блок health-check).

import sys
import os
import asyncio

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if sys.platform == "win32":
    try:
        os.system("chcp 65001 >nul 2>&1")
    except Exception:
        pass

from PyQt5 import QtWidgets, QtCore, QtGui
from qasync import QEventLoop

import config
from settings_manager import apply_to_config

applied = apply_to_config(config)

try:
    import character_manager as _persona
    _persona.migrate_legacy_files()
    _docs = _persona.apply_to_config()
    print(f"🎭 Persona: character={getattr(config, 'ACTIVE_CHARACTER', '?')}, user={getattr(config, 'ACTIVE_USER', '?')}")
    print(f"🎭 RAG_DOCS: {_docs}")
except Exception as _pe:
    print(f"⚠️ persona: {_pe}")

try:
    from config import print_banner
    print_banner()
except Exception as _be:
    print(f"⚠️ banner: {_be}")

# Явно логируем голосовой режим ПОСЛЕ применения settings.json
_mode = (getattr(config, "VOICE_INPUT_MODE", "push") or "push")
_wake = getattr(config, "WAKE_WORD", "лисичка")
print(f"🔧 После settings.json: VOICE_INPUT_MODE={_mode!r}, WAKE_WORD={_wake!r}")
if applied:
    print(f"🔧 Применено ключей: {len(applied)} (есть VOICE_INPUT_MODE: {'VOICE_INPUT_MODE' in applied})")
else:
    print("🔧 settings.json пуст или не применён — используются defaults из config.py")

# Модульный промпт (делает config.SYSTEM_PROMPT короче)
try:
    from prompt_builder import apply_modular_prompt_to_config
    apply_modular_prompt_to_config()
except Exception as e:
    print(f"⚠️ prompt_builder: {e}")

async def main():
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("ИИ Ассистент — Лисичка")

    font = QtGui.QFont()
    for family in ("Segoe UI", "Noto Sans", "DejaVu Sans", "Arial", "Sans Serif"):
        font.setFamily(family)
        if QtGui.QFontInfo(font).family():
            break
    font.setPointSize(11)
    app.setFont(font)

    from splash import BootSplash
    boot = BootSplash(app)
    boot.say("ядро и окна", 15)

    from assistant_core import LMAssistant
    from gui import AssistantWindow
    from lifecycle_manager import LifecycleManager

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    print("=" * 70)
    print("🦊 ЗАПУСК ИИ АССИСТЕНТА — ЛИСИЧКА")
    print("=" * 70)

    boot.say("проверка окружения", 30)
    try:
        from health_check import run_health_check
        health = run_health_check(verbose=True)
        if not health.get("ok"):
            print("⚠️ Продолжаем запуск несмотря на проблемы...\n")
    except Exception as e:
        print(f"⚠️ Health-check не выполнен: {e}\n")

    boot.say("ассистент", 50)
    assistant = LMAssistant()
    boot.say("сервер ИИ", 70)
    try:
        from llm_server import ping, api_base
        ok = ping(1.2)
        boot.say("сервер онлайн" if ok else "сервер выкл — работаем без модели", 80)
        print(f"🔌 LLM {api_base()}: {'онлайн' if ok else 'офлайн — GUI всё равно, болтовня после включения сервера'}")
    except Exception as _le:
        print(f"🔌 LLM статус неизвестен: {_le}")
    # Silero: фоновая загрузка, GUI не ждёт
    try:
        eng = (getattr(config, "VOICE_SYNTHESIS_ENGINE", "") or "").lower()
        if (
            getattr(config, "ENABLE_VOICE_OUTPUT", False)
            and eng in ("silero", "silero-tts", "silero_tts")
            and hasattr(assistant, "voice")
            and hasattr(assistant.voice, "preload_silero_async")
        ):
            assistant.voice.preload_silero_async()
            print("🔊 Silero: фоновая предзагрузка запущена")
        elif not getattr(config, "ENABLE_VOICE_OUTPUT", False):
            print("🔊 Silero: пропущен (VOICE_OUTPUT выключен)")
    except Exception as _se:
        print(f"⚠️ Silero preload: {_se}")

    # Подключаем умный селектор анимаций
    try:
        from animation_selector import AnimationSelector
        assistant.anim_selector = AnimationSelector(analyzer=getattr(assistant, "analyzer", None))
        assistant.anim_selector.context = getattr(assistant, "context", None)
        print("🎬 AnimationSelector подключён")
    except Exception as e:
        print(f"⚠️ AnimationSelector: {e}")

    boot.say("интерфейс", 90)
    window = AssistantWindow(assistant)
    window.show()
    boot.finish(window)

    if config.ENABLE_VOICE_INPUT:
        mode = (getattr(config, "VOICE_INPUT_MODE", "push") or "push").lower()
        if mode in ("wake", "always", "hotword", "keyword"):
            try:
                asyncio.create_task(assistant.voice.start_listening_async())
                wake = getattr(config, "WAKE_WORD", "лисичка")
                print(f"🎤 Режим wake: слушаю кодовое слово «{wake}»")
            except RuntimeError as e:
                print(f"⚠️ Ошибка активации голоса: {e}")
        else:
            print("🎤 Режим push: говорите через кнопку 🎤")

    print("🔄 Инициализация LifecycleManager...")
    lifecycle = LifecycleManager(assistant.executor)
    lifecycle.set_assistant(assistant)
    current_loop = asyncio.get_running_loop()
    lifecycle.set_loop(current_loop)
    lifecycle.start()
    assistant._lifecycle = lifecycle

    print("🔄 LifecycleManager запущен (авто-сообщения при простое)")
    print(f"   📊 Интервал: {config.GREETING_INTERVAL_MIN}-{config.GREETING_INTERVAL_MAX} сек")
    print(f"   🤖 Использовать LLM: {getattr(config, 'GREETING_USE_LLM', False)}")
    print(f"   🔞 Шанс NSFW: {getattr(config, 'GREETING_NSFW_CHANCE', 0) * 100:.0f}%")

    print("=" * 70)
    print("✅ АССИСТЕНТ ГОТОВ К РАБОТЕ!")
    print("=" * 70)

    # Закрытие окна → выход из loop
    def _on_about_to_quit():
        print("🔄 Qt aboutToQuit — останавливаем фоновые службы...")
        try:
            if hasattr(assistant, "_lifecycle") and assistant._lifecycle:
                assistant._lifecycle.stop()
        except Exception:
            pass

    app.aboutToQuit.connect(_on_about_to_quit)

    try:
        with loop:
            loop.run_forever()
    except KeyboardInterrupt:
        print("\n👋 Получен сигнал прерывания...")
    finally:
        print("🔄 Остановка ассистента...")
        try:
            if hasattr(assistant, "_lifecycle") and assistant._lifecycle:
                assistant._lifecycle.stop()
        except Exception as e:
            print(f"⚠️ lifecycle: {e}")
        try:
            if hasattr(assistant, "shutdown"):
                assistant.shutdown()
            elif hasattr(assistant, "shutdown_async"):
                try:
                    asyncio.get_running_loop()
                    await assistant.shutdown_async()
                except RuntimeError:
                    print("⚠️ shutdown: нет цикла — синхронный stop уже должен быть в closeEvent")
        except Exception as e:
            print(f"⚠️ shutdown: {e}")
        try:
            # принудительно закрыть Qt
            app.quit()
        except Exception:
            pass
        print("✅ Ассистент остановлен")
        # sys уже импортирован на уровне модуля — не делать import sys здесь
        # (иначе UnboundLocalError на sys.argv в начале main)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Завершение работы по запросу пользователя")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        input("Нажмите Enter для выхода...")
    finally:
        # Гарантия: не оставлять python.exe с залоченным apps.db
        try:
            print("[DEBUG] process exit", flush=True)
        except Exception:
            pass
